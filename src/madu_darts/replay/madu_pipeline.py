"""Real Madu pipeline over a Recording: frames → motion/settle → tip → fusion → Hit.

Camera bind for a recording
---------------------------
Recordings carry Autodarts' ellipses, not a Madu homography, so replay binds
each cam the way the live product does: ``calibration.suggest`` on an
empty-Board frame (first visit whose frame fits). The rotate-20 step the
operator performs by eye is replaced by ``resolve_rotate_offsets`` which picks,
per cam, the offset under which Autodarts' labelled tips project onto changed
pixels. Offsets can be pinned explicitly (``rotate_offsets``) to skip that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from madu_darts.calibration import AutoFitError, CamCalibration, board_mm_to_image, image_to_board_mm, suggest
from madu_darts.hits import FusionConfig, HitDetector, TipConfig, dart_change_mask
from madu_darts.motion import BoardModel, MotionConfig, MotionGate
from madu_darts.record.meta import VisitMeta, load_visit_meta
from madu_darts.replay.coords import autodarts_coords_to_mm
from madu_darts.replay.pipeline import HitHypothesis
from madu_darts.turn import TurnConfig, TurnController, TurnEvent, TurnStatus, TurnTransition

log = logging.getLogger(__name__)

SLOTS: tuple[int, ...] = (0, 1, 2)
#: Frame period used when padding frozen frames (recording cams ran ~30 fps).
_PAD_DT = 1.0 / 30.0


@dataclass
class VisitTrace:
    """Turn status/event sequence Madu produced for one recorded visit vs Autodarts' labels."""

    visit_index: int
    autodarts_status: str | None
    autodarts_event: str | None
    autodarts_num_throws: int
    transitions: list[TurnTransition] = field(default_factory=list)
    #: Status / event / throws right after the last dart window (what Autodarts reported at close).
    status_at_close: TurnStatus | None = None
    event_at_close: TurnEvent | None = None
    num_hits_at_close: int = 0
    #: Takeout simulated on the following empty-Board frames: did the strip empty?
    takeout_cleared: bool | None = None

    @property
    def throws_match(self) -> bool:
        return self.num_hits_at_close == self.autodarts_num_throws

    @property
    def status_match(self) -> bool:
        return (
            self.status_at_close is not None
            and self.event_at_close is not None
            and self.status_at_close.value == self.autodarts_status
            and self.event_at_close.value == self.autodarts_event
        )

    @property
    def ok(self) -> bool:
        return self.throws_match and self.status_match and bool(self.takeout_cleared)

    def sequence(self) -> str:
        parts = []
        for tr in self.transitions:
            if tr.event == TurnEvent.THROW_DETECTED:
                parts.append(f"{tr.status.value}/{tr.event.value}({tr.num_hits})")
            else:
                parts.append(f"{tr.status.value}/{tr.event.value}")
        return " → ".join(parts)


def _frame_time(path: str) -> float:
    # …/d00_015_t9354.250.jpg → 9354.250
    stem = Path(path).stem
    return float(stem.split("_t", 1)[1])


def _read(path: Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(path)
    return image


def _visits(recording: Path) -> list[tuple[Path, VisitMeta]]:
    out = []
    for visit in sorted(Path(recording).glob("visit-*")):
        meta_path = visit / "meta.json"
        if meta_path.is_file():
            out.append((visit, load_visit_meta(meta_path)))
    return out


def bind_recording_cameras(recording: Path, slots: tuple[int, ...] = SLOTS) -> dict[int, CamCalibration]:
    """Autofit each cam on the first empty-Board frame that binds."""
    cals: dict[int, CamCalibration] = {}
    for slot in slots:
        last_error: str | None = None
        for visit, meta in _visits(recording):
            if not meta.darts:
                continue
            paths = meta.darts[0].get("frames", {}).get(str(slot), [])
            if not paths:
                continue
            try:
                cals[slot] = suggest(_read(visit / paths[0]), slot, None)
                break
            except AutoFitError as exc:
                last_error = exc.reason
        if slot not in cals:
            raise AutoFitError(f"cam {slot}: no frame in recording binds ({last_error})")
    return cals


def resolve_rotate_offsets(
    recording: Path,
    cals: dict[int, CamCalibration],
    *,
    tip_config: TipConfig | None = None,
    max_darts: int | None = None,
) -> dict[int, int]:
    """Rotate-20 per cam: offset whose projected Autodarts tips land on changed pixels."""
    cfg = tip_config or TipConfig()
    offsets: dict[int, int] = {}
    for slot, cal in cals.items():
        scores = np.zeros(20, dtype=np.float64)
        seen = 0
        for visit, meta in _visits(recording):
            if not meta.darts:
                continue
            background = None
            for dart in meta.darts:
                paths = dart.get("frames", {}).get(str(slot), [])
                throw = dart.get("throw") or {}
                if not paths or "coordsX" not in throw:
                    continue
                frame = _read(visit / paths[-1])
                if background is None:
                    background = _read(visit / paths[0])
                mask = dart_change_mask(background, frame, cfg)
                ys, xs = np.nonzero(mask)
                if len(xs):
                    x_mm, y_mm = autodarts_coords_to_mm(float(throw["coordsX"]), float(throw["coordsY"]))
                    for offset in range(20):
                        px = board_mm_to_image(cal.homography, offset, (x_mm, y_mm), cal.radial())
                        scores[offset] += min(200.0, float(np.min(np.hypot(xs - px[0], ys - px[1]))))
                    seen += 1
                background = frame
                if max_darts is not None and seen >= max_darts:
                    break
            if max_darts is not None and seen >= max_darts:
                break
        offsets[slot] = int(np.argmin(scores)) if seen else 0
        log.info("cam %s rotate offset %s (mean px to change %.1f over %d darts)", slot, offsets[slot], scores[offsets[slot]] / max(seen, 1), seen)
    return offsets


@dataclass
class RecordingBind:
    cals: dict[int, CamCalibration]
    offsets: dict[int, int]

    def board_point(self, slot: int, point_px: tuple[float, float]) -> np.ndarray:
        cal = self.cals[slot]
        return image_to_board_mm(cal.homography, self.offsets[slot], point_px, cal.radial())


class MaduPipeline:
    """``Pipeline`` implementation running the real detection chain per dart window.

    Each visit runs through a fresh ``TurnController`` (gate → tips → fusion →
    Hit commit). Recordings end at Autodarts' detection time and hold no takeout
    frames, so the takeout is exercised on the *next* visit's empty-Board frames
    (real frames, real lighting), which the controller must clear to ``throw``.
    """

    def __init__(
        self,
        *,
        motion_config: MotionConfig | None = None,
        tip_config: TipConfig | None = None,
        fusion_config: FusionConfig | None = None,
        turn_config: TurnConfig | None = None,
        rotate_offsets: dict[int, int] | None = None,
        slots: tuple[int, ...] = SLOTS,
    ) -> None:
        self.motion_config = motion_config or MotionConfig()
        self.tip_config = tip_config or TipConfig()
        self.fusion_config = fusion_config or FusionConfig()
        self.turn_config = turn_config or TurnConfig(standby_minutes=0.0)
        self._pinned_offsets = rotate_offsets
        self._slots = slots
        self._binds: dict[Path, RecordingBind] = {}
        self.last_hits: list = []
        self.visit_traces: list[VisitTrace] = []

    def bind(self, recording: Path) -> RecordingBind:
        root = Path(recording).resolve()
        bind = self._binds.get(root)
        if bind is None:
            cals = bind_recording_cameras(root, self._slots)
            offsets = dict(self._pinned_offsets) if self._pinned_offsets else resolve_rotate_offsets(root, cals, tip_config=self.tip_config)
            bind = RecordingBind(cals=cals, offsets=offsets)
            self._binds[root] = bind
        return bind

    def _empty_frames(self, visit_dir: Path, meta: VisitMeta) -> dict[int, np.ndarray]:
        """First frame of the first dart window: the Board before anything landed."""
        refs: dict[int, np.ndarray] = {}
        if not meta.darts:
            return refs
        for slot in self._slots:
            paths = meta.darts[0].get("frames", {}).get(str(slot), [])
            if paths:
                refs[slot] = _read(visit_dir / paths[0])
        return refs

    def _next_visit_empty_frames(self, visit_dir: Path, meta: VisitMeta) -> dict[int, np.ndarray]:
        visits = _visits(visit_dir.parent)
        for i, (path, m) in enumerate(visits):
            if path.resolve() == visit_dir.resolve() and i + 1 < len(visits):
                frames = self._empty_frames(visits[i + 1][0], visits[i + 1][1])
                if frames:
                    return frames
        return self._empty_frames(visit_dir, meta)  # last visit: its own pre-dart Board

    def detect_visit(self, visit_dir: Path, meta: VisitMeta) -> list[HitHypothesis]:
        visit_dir = Path(visit_dir)
        bind = self.bind(visit_dir.parent)
        board = BoardModel(self._slots)
        gate = MotionGate(board, self.motion_config, slots=self._slots)
        detector = HitDetector(
            bind.board_point,
            board,
            slots=self._slots,
            motion_scale=self.motion_config.scale,
            tip_config=self.tip_config,
            fusion_config=self.fusion_config,
        )
        ctrl = TurnController(board, gate, detector, config=self.turn_config, slots=self._slots)
        trace = VisitTrace(
            visit_index=meta.visit_index,
            autodarts_status=meta.autodarts_status,
            autodarts_event=meta.autodarts_event,
            autodarts_num_throws=len(meta.throws),
        )
        hyps: list[HitHypothesis] = []
        self.last_hits = []
        if not meta.darts:
            self.visit_traces.append(trace)
            return hyps

        refs = self._empty_frames(visit_dir, meta)
        first_t = min(_frame_time(p) for d in meta.darts for ps in d.get("frames", {}).values() for p in ps)
        trace.transitions += [ctrl.start(refs, first_t - _PAD_DT)]
        last_t = first_t
        last_frames = refs

        for dart in meta.darts:
            by_t: dict[float, dict[int, np.ndarray]] = {}
            for cam, paths in dart.get("frames", {}).items():
                for path in paths:
                    by_t.setdefault(_frame_time(path), {})[int(cam)] = _read(visit_dir / path)
            if not by_t:
                hyps.append(HitHypothesis(segment_name="", x_mm=float("nan"), y_mm=float("nan")))
                continue
            last_t = max(by_t)
            last_frames = by_t[last_t]
            n_before = len(ctrl.hits)
            for t in sorted(by_t):
                trace.transitions += ctrl.process(by_t[t], t)
            trace.transitions += ctrl.flush(last_frames, last_t)
            new_hits = ctrl.hits[n_before:]
            if not new_hits:
                hyps.append(HitHypothesis(segment_name="", x_mm=float("nan"), y_mm=float("nan")))
                continue
            hit = new_hits[-1]
            self.last_hits.append(hit)
            hyps.append(
                HitHypothesis(
                    segment_name=hit.autodarts_segment_name,
                    x_mm=hit.x_mm,
                    y_mm=hit.y_mm,
                    number=hit.segment.number,
                    multiplier=hit.segment.multiplier,
                    bed=hit.segment.bed,
                    method=hit.method,
                )
            )

        trace.status_at_close = ctrl.status
        trace.event_at_close = ctrl.event
        trace.num_hits_at_close = len(ctrl.hits)

        # Takeout: the recording jumps to the next visit's empty Board (no hand frames).
        empty_after = self._next_visit_empty_frames(visit_dir, meta)
        t = last_t
        pad = self.motion_config.stable_num_frames + self.turn_config.quiet_frames + 4
        for _ in range(pad):
            t += _PAD_DT
            trace.transitions += ctrl.process(empty_after, t)
            if ctrl.event == TurnEvent.TAKEOUT_FINISHED:
                break
        trace.takeout_cleared = ctrl.event == TurnEvent.TAKEOUT_FINISHED and not ctrl.hits
        self.visit_traces.append(trace)
        return hyps


def format_turn_table(traces: list[VisitTrace]) -> str:
    """Per-visit Autodarts status/event/throws at close vs Madu's Turn sequence."""
    if not traces:
        return "(no visits)"
    header = f"{'V':>2}  {'AD status/event':<26} {'AD':>2} {'Madu':>4}  ok  Madu Turn sequence"
    lines = [header, "-" * len(header)]
    for tr in traces:
        ad = f"{tr.autodarts_status or '?'}/{tr.autodarts_event or '?'}"
        lines.append(
            f"{tr.visit_index:2d}  {ad:<26} {tr.autodarts_num_throws:2d} {tr.num_hits_at_close:4d}  "
            f"{'Y' if tr.ok else 'N'}   {tr.sequence()}"
        )
    ok = sum(1 for tr in traces if tr.ok)
    lines.append("-" * len(header))
    lines.append(
        f"visits matching Autodarts status/event + throws, then clearing on takeout: {ok}/{len(traces)}"
    )
    return "\n".join(lines)


__all__ = [
    "MaduPipeline",
    "RecordingBind",
    "VisitTrace",
    "bind_recording_cameras",
    "format_turn_table",
    "resolve_rotate_offsets",
]
