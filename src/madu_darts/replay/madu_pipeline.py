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
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from madu_darts.calibration import AutoFitError, CamCalibration, board_mm_to_image, image_to_board_mm, suggest
from madu_darts.hits import FusionConfig, HitDetector, TipConfig, dart_change_mask
from madu_darts.motion import BoardModel, MotionConfig, MotionGate
from madu_darts.record.meta import VisitMeta, load_visit_meta
from madu_darts.replay.coords import autodarts_coords_to_mm
from madu_darts.replay.pipeline import HitHypothesis

log = logging.getLogger(__name__)

SLOTS: tuple[int, ...] = (0, 1, 2)


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
                        px = board_mm_to_image(cal.homography, offset, (x_mm, y_mm))
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
        return image_to_board_mm(cal.homography, self.offsets[slot], point_px)


class MaduPipeline:
    """``Pipeline`` implementation running the real detection chain per dart window."""

    def __init__(
        self,
        *,
        motion_config: MotionConfig | None = None,
        tip_config: TipConfig | None = None,
        fusion_config: FusionConfig | None = None,
        rotate_offsets: dict[int, int] | None = None,
        slots: tuple[int, ...] = SLOTS,
    ) -> None:
        self.motion_config = motion_config or MotionConfig()
        self.tip_config = tip_config or TipConfig()
        self.fusion_config = fusion_config or FusionConfig()
        self._pinned_offsets = rotate_offsets
        self._slots = slots
        self._binds: dict[Path, RecordingBind] = {}
        self.last_hits: list = []

    def bind(self, recording: Path) -> RecordingBind:
        root = Path(recording).resolve()
        bind = self._binds.get(root)
        if bind is None:
            cals = bind_recording_cameras(root, self._slots)
            offsets = dict(self._pinned_offsets) if self._pinned_offsets else resolve_rotate_offsets(root, cals, tip_config=self.tip_config)
            bind = RecordingBind(cals=cals, offsets=offsets)
            self._binds[root] = bind
        return bind

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
        gate.set_enabled(True)
        hyps: list[HitHypothesis] = []
        self.last_hits = []
        if not meta.darts:
            return hyps

        refs = {}
        for slot in self._slots:
            paths = meta.darts[0].get("frames", {}).get(str(slot), [])
            if paths:
                refs[slot] = _read(visit_dir / paths[0])
        board.capture_all(refs)

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
            for t in sorted(by_t):
                for event in gate.process_frames(by_t[t], t):
                    detector.offer(event, by_t[t][event.slot])
            for event in gate.flush():
                detector.offer(event, last_frames.get(event.slot, by_t[max(by_t)][event.slot]))
            hit = detector.poll(last_t, force=True, latest_frames=last_frames)
            gate.reset()
            gate.set_enabled(True)
            if hit is None:
                hyps.append(HitHypothesis(segment_name="", x_mm=float("nan"), y_mm=float("nan")))
                continue
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
        return hyps


__all__ = ["MaduPipeline", "RecordingBind", "bind_recording_cameras", "resolve_rotate_offsets"]
