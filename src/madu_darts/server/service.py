"""Detection service: camera ingest + frame pump + Calibration session for one process run.

Startup (ADR 0002): open the three cams, pull first frames, auto-suggest every
cam, then wait for the operator to rotate-20 / Accept in the Calibration view.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from madu_darts.calibration import AutoFitParams, CalibrationSession
from madu_darts.calibration.bind_store import DEFAULT_BIND_STORE
from madu_darts.calibration.mount import DEFAULT_OFFSET_STORE, DEFAULT_ROTATE_OFFSETS
from madu_darts.cameras import CameraIngest, CamFrame, IngestConfig
from madu_darts.hits import FusionConfig, Hit, HitDetector, TipConfig
from madu_darts.motion import BoardModel, MotionConfig, MotionGate, SettledChange
from madu_darts.server.live_store import LiveStore
from madu_darts.turn import TurnConfig, TurnController, TurnEvent, TurnStatus, TurnTransition

log = logging.getLogger(__name__)

IngestFactory = Callable[[IngestConfig], CameraIngest]
FrameListener = Callable[[float, dict[int, CamFrame]], None]


@dataclass(frozen=True)
class ServiceConfig:
    ingest: IngestConfig = field(default_factory=IngestConfig)
    autofit: AutoFitParams | None = None
    motion: MotionConfig = field(default_factory=MotionConfig)
    tip: TipConfig = field(default_factory=TipConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    turn: TurnConfig = field(default_factory=TurnConfig)
    first_frame_timeout_s: float = 3.0
    stream_fps: float = 10.0
    jpeg_quality: int = 80
    #: Published ``/api/state`` snapshots kept for late WS subscribers to catch up on.
    state_log: int = 256
    #: Sealed visits kept in ``GET /api/history`` (survives takeout).
    max_history: int = 50
    #: On-disk frame packs under ``captures/live/`` (auto on 3rd Hit + ``POST /api/capture``).
    max_captures: int = 30
    capture_root: str | None = None
    #: After autofit, apply these rotate-20 offsets (Board ring mounts). ``None`` → ticket 13 defaults.
    rotate_offsets: dict[int, int] | None = None
    #: Persist last Accepted offsets here (re-applied on next suggest). ``None`` disables.
    offset_store: str | None = str(DEFAULT_OFFSET_STORE)
    #: Persist Accepted full binds (H + rotate-20). ``None`` disables.
    bind_store: str | None = str(DEFAULT_BIND_STORE)


class FramePump(threading.Thread):
    """Background reader keeping the latest frame per slot."""

    def __init__(
        self,
        ingest: CameraIngest,
        fps: float,
        *,
        on_frames: FrameListener | None = None,
    ) -> None:
        super().__init__(name="madu-frame-pump", daemon=True)
        self._ingest = ingest
        self._interval = 1.0 / max(fps, 1.0)
        self._lock = threading.Lock()
        self._latest: dict[int, CamFrame] = {}
        self._stop_event = threading.Event()
        self._count = 0
        self._started_at = time.monotonic()
        self._on_frames = on_frames
        self.error: str | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                frames = self._ingest.read()
            except Exception as exc:  # camera unplugged etc.
                self.error = str(exc)
                log.warning("frame pump read failed: %s", exc)
                self._stop_event.wait(self._interval)
                continue
            if frames:
                with self._lock:
                    self._latest.update(frames)
                    self._count += 1
                if self._on_frames is not None:
                    try:
                        self._on_frames(time.monotonic(), frames)
                    except Exception as exc:
                        log.warning("frame listener failed: %s", exc)
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(0.0, self._interval - elapsed))

    def latest(self) -> dict[int, CamFrame]:
        with self._lock:
            return dict(self._latest)

    @property
    def measured_fps(self) -> float:
        elapsed = time.monotonic() - self._started_at
        return self._count / elapsed if elapsed > 0 else 0.0

    def stop(self) -> None:
        self._stop_event.set()


class DetectionService:
    """Owns ingest, frame pump and the Calibration session; the web app talks to this."""

    def __init__(
        self,
        config: ServiceConfig | None = None,
        *,
        ingest_factory: IngestFactory | None = None,
        session: CalibrationSession | None = None,
    ) -> None:
        self._config = config or ServiceConfig()
        self._ingest_factory: IngestFactory = ingest_factory or (lambda cfg: CameraIngest(cfg))
        slots = tuple(s.slot for s in self._config.ingest.slots)
        offsets = self._config.rotate_offsets if self._config.rotate_offsets is not None else dict(DEFAULT_ROTATE_OFFSETS)
        self.session = session or CalibrationSession(
            slots,
            params=self._config.autofit,
            default_rotate_offsets=offsets,
            offset_store=self._config.offset_store,
            bind_store=self._config.bind_store,
        )
        self.board_model = BoardModel(slots)
        self.motion_gate = MotionGate(self.board_model, self._config.motion, slots=slots)
        from madu_darts.calibration.model import FitStatus

        self.hit_detector = HitDetector(
            self.session.board_point,
            self.board_model,
            slots=slots,
            motion_scale=self._config.motion.scale,
            tip_config=self._config.tip,
            fusion_config=self._config.fusion,
            fit_ok=lambda: {
                s: self.session.get(s).status is FitStatus.PASS for s in self.session.slots
            },
        )
        #: Calibration residual dots (ticket 19); default on so far-double soft spots show (ticket 34).
        self._show_residuals = True
        #: Detection tip / fused-Hit overlay on cam streams (ticket 30); off by default.
        self._show_hit_debug = False
        self.live = LiveStore(
            root=None if self._config.capture_root is None else Path(self._config.capture_root),
            max_visits=self._config.max_history,
            max_captures=self._config.max_captures,
            jpeg_quality=self._config.jpeg_quality,
        )
        self.turn = TurnController(
            self.board_model,
            self.motion_gate,
            self.hit_detector,
            config=self._config.turn,
            slots=slots,
            on_transition=self._on_turn_transition,
        )
        self._ingest: CameraIngest | None = None
        self._pump: FramePump | None = None
        self._lock = threading.RLock()
        self.camera_error: str | None = None
        # Autodarts-shaped state stream (ADR 0004): every change appends a full snapshot.
        self._state_cv = threading.Condition()
        self._state_seq = 0
        self._state_log: deque[tuple[int, dict[str, Any]]] = deque(maxlen=self._config.state_log)

    # --- lifecycle ---

    @property
    def config(self) -> ServiceConfig:
        return self._config

    def start(self) -> None:
        if self.reopen_cameras():
            if self.session.load_saved_binds():
                packs = self._calibration_frame_packs(n=1)
                frames = {s: imgs[0] for s, imgs in packs.items() if imgs}
                self.session.rescore(frames)
                # Auto only unbound slots (mounts moved / first-time cams).
                unbound = [s for s in self.session.slots if not self.session.is_bound(s)]
                if unbound:
                    self.recalibrate()
                elif not self.session.accepted:
                    self.on_calibration_reset()
            else:
                self.recalibrate()

    @property
    def show_residuals(self) -> bool:
        return self._show_residuals

    def set_show_residuals(self, value: bool) -> None:
        self._show_residuals = bool(value)

    @property
    def show_hit_debug(self) -> bool:
        return self._show_hit_debug

    def set_show_hit_debug(self, value: bool) -> None:
        self._show_hit_debug = bool(value)

    def committed_hits(self) -> list[Any]:
        """Hits currently on the Turn (for cam tip overlays)."""
        return list(self.turn.hits)

    def stop(self) -> None:
        with self._lock:
            if self.turn.running:
                self.turn.stop(time.monotonic())
            self.motion_gate.set_enabled(False)
            if self._pump is not None:
                self._pump.stop()
                self._pump.join(timeout=2.0)
                self._pump = None
            if self._ingest is not None:
                try:
                    self._ingest.close()
                except Exception as exc:
                    log.warning("ingest close failed: %s", exc)
                self._ingest = None

    def reopen_cameras(self) -> bool:
        """(Re)open the cams from the current config; returns True when frames are flowing."""
        was_accepted = self.session.accepted
        self.stop()
        with self._lock:
            try:
                ingest = self._ingest_factory(self._config.ingest)
                ingest.open()
            except Exception as exc:
                self.camera_error = str(exc)
                log.error("camera open failed: %s", exc)
                return False
            self._ingest = ingest
            self.camera_error = None
            pump = FramePump(
                ingest,
                fps=float(self._config.ingest.capture.fps),
                on_frames=self._on_pump_frames,
            )
            pump.start()
            self._pump = pump

        deadline = time.monotonic() + self._config.first_frame_timeout_s
        wanted = set(self.session.slots)
        while time.monotonic() < deadline:
            if wanted <= set(pump.latest()):
                if was_accepted and self.session.accepted:
                    self.arm_motion_from_latest()
                return True
            time.sleep(0.02)
        if not pump.latest():
            self.camera_error = pump.error or "cameras opened but delivered no frames"
            return False
        if was_accepted and self.session.accepted:
            self.arm_motion_from_latest()
        return True

    def _on_pump_frames(self, t_mono: float, frames: dict[int, CamFrame]) -> None:
        if not self.session.accepted or not self.turn.running:
            return
        images = {slot: frame.image for slot, frame in frames.items()}
        for tr in self.turn.process(images, t_mono):
            log.info("turn: %s / %s (%d throws)", tr.status.value, tr.event.value, tr.num_hits)

    # --- frames ---

    def latest_frames(self) -> dict[int, np.ndarray]:
        pump = self._pump
        if pump is None:
            return {}
        return {slot: frame.image for slot, frame in pump.latest().items()}

    def frame(self, slot: int) -> np.ndarray | None:
        return self.latest_frames().get(slot)

    # --- motion / settle ---

    def arm_motion_from_latest(self) -> bool:
        """Start the Turn controller on the latest frames as the empty Board (post-Accept / Start)."""
        frames = self.latest_frames()
        if not frames:
            log.warning("arm_motion_from_latest: no frames yet")
            return False
        self.turn.start(frames, time.monotonic())
        return True

    def on_calibration_accepted(self) -> None:
        self.session.require_accepted()
        self.arm_motion_from_latest()

    def on_calibration_reset(self) -> None:
        now = time.monotonic()
        if self.turn.running:
            self.turn.stop(now)
        self.turn.reset(None, now)
        self.motion_gate.set_enabled(False)
        self.motion_gate.reset()
        self.hit_detector.reset()
        self.board_model.reset()

    # --- Turn (ticket 10): start / stop / reset + Autodarts-shaped state ---

    def _on_turn_transition(self, tr: TurnTransition) -> None:
        """Publish WS state, track visit history, auto-capture on the 3rd Hit."""
        hits = self.turn.hits
        self.live.note_transition(tr, hits)
        if (
            tr.event == TurnEvent.THROW_DETECTED
            and tr.status == TurnStatus.TAKEOUT
            and tr.num_hits >= self._config.turn.max_hits
            and self.live.open_capture_id() is None
        ):
            try:
                pack = self.capture_now(reason="auto-third")
                self.live.attach_capture(str(pack["id"]))
            except Exception as exc:
                log.warning("auto-capture failed: %s", exc)
        if tr.event in (TurnEvent.TAKEOUT_FINISHED, TurnEvent.RESET, TurnEvent.STARTED):
            # Hits are already cleared on the controller; finalize from the open-visit snapshot.
            self.live.finalize(t_mono=tr.t_mono, reason=tr.event.value)
        self.publish_state()

    def start_detection(self) -> dict[str, Any]:
        """``PUT /api/start``: requires Accepted Calibration; Board taken as empty now."""
        self.session.require_accepted()
        if not self.arm_motion_from_latest():
            raise RuntimeError("no camera frames to start detection on")
        return self.turn_state()

    def stop_detection(self) -> dict[str, Any]:
        """``PUT /api/stop``: park detection, keep Calibration and the visible Hits."""
        if self.turn.running:
            self.turn.stop(time.monotonic())
        return self.turn_state()

    def reset_turn(self) -> dict[str, Any]:
        """``POST /api/reset``: clear the Turn (zero-dart false takeout recovery), keep Calibration."""
        frames = self.latest_frames() if self.session.accepted else None
        self.turn.reset(frames or None, time.monotonic())
        return self.turn_state()

    def recheck(self) -> dict[str, Any]:
        """``POST /api/recheck``: mid-Turn classical re-detect vs empty refs (ticket 17)."""
        from madu_darts.calibration.model import FitStatus
        from madu_darts.hits import recheck_hits

        self.session.require_accepted()
        if not self.turn.running:
            raise RuntimeError("detection not running")
        previous = self.turn.hits
        if not previous:
            raise RuntimeError("no Hits to recheck")
        frames = self.latest_frames()
        empty = self.turn.empty_refs()
        if not frames or not empty:
            raise RuntimeError("no frames / empty refs for recheck")
        # Board must still show darts vs empty (operator mid-Turn).
        if self.turn._board_empty(frames):  # noqa: SLF001 — intentional reuse of empty gate
            raise RuntimeError("Board looks empty; nothing to recheck")
        fit_ok = {s: self.session.get(s).status is FitStatus.PASS for s in self.session.slots}
        t = time.monotonic()
        new_hits = recheck_hits(
            frames,
            empty,
            previous,
            self.session.board_point,
            tip_config=self._config.tip,
            fusion_config=self._config.fusion,
            fit_ok=fit_ok,
            t_mono=t,
        )
        self.turn.replace_hits(new_hits, frames, t)
        try:
            pack = self.capture_now(reason="recheck")
            self.live.attach_capture(str(pack["id"]))
        except Exception as exc:
            log.warning("recheck capture failed: %s", exc)
        return self.api_state()

    def override_hit(self, index: int, body: dict[str, Any]) -> dict[str, Any]:
        """``PATCH /api/state/hits/{index}``: manual Segment / Board-mm correction (ticket 18)."""
        from madu_darts.hits import resolve_manual

        hits = self.turn.hits
        if not hits:
            raise RuntimeError("no Hits to override")
        if index < 0 or index >= len(hits):
            raise IndexError(f"hit index {index} out of range")
        t = time.monotonic()
        if "xMm" in body and "yMm" in body:
            hit = resolve_manual(
                x_mm=float(body["xMm"]),
                y_mm=float(body["yMm"]),
                previous=hits[index],
                t_mono=t,
            )
        elif "segmentName" in body and body["segmentName"]:
            hit = resolve_manual(
                segment_name=str(body["segmentName"]),
                previous=hits[index],
                t_mono=t,
            )
        else:
            raise ValueError("body needs segmentName or xMm+yMm")
        self.turn.override_hit(index, hit, t)
        return self.api_state()

    def hits(self) -> list[Hit]:
        return list(self.turn.hits)

    def clear_hits(self) -> None:
        self.reset_turn()

    def turn_state(self) -> dict[str, Any]:
        return self.turn.snapshot().to_api()

    def hits_state(self) -> dict[str, Any]:
        return self.turn_state()

    def sync_motion_with_calibration(self) -> None:
        """Run the Turn controller only while Calibration is Accepted; park it otherwise."""
        if self.session.accepted:
            if not self.turn.running:
                self.arm_motion_from_latest()
        else:
            self.on_calibration_reset()

    def motion_state(self) -> dict[str, Any]:
        snap = self.motion_gate.snapshot()
        snap["enabled"] = bool(snap["enabled"] and self.session.accepted)
        return snap

    def drain_settled(self) -> list[SettledChange]:
        return self.motion_gate.drain_events()

    # --- Autodarts-shaped state + change stream (ticket 11, ADR 0004) ---

    def api_state(self) -> dict[str, Any]:
        """``GET /api/state``: Autodarts 2.1 core + Madu ``calibration`` / ``cameras`` / ``madu`` blocks."""
        snap = self.turn.snapshot()
        state = snap.to_autodarts_state()
        calibration = self.session.snapshot()
        state["calibration"] = calibration
        state["cameras"] = {"open": self._ingest is not None and self._ingest.is_open, "error": self.camera_error}
        state["madu"] = {
            "numThrows": len(snap.hits),
            "standby": snap.standby,
            "pending": snap.pending,
            "bounceOuts": [b.to_api() for b in snap.bounce_outs],
            "ignoredChanges": snap.ignored_changes,
            "hits": [h.to_api() for h in snap.hits],
            "calibrationAccepted": bool(calibration["accepted"]),
            "version": snap.version,
            "historyCount": self.live.history_count,
            "lastVisitId": self.live.last_visit_id,
            "captureId": self.live.open_capture_id(),
            **self.turn.empty_debug(self.latest_frames()),
        }
        return state

    def history_state(self) -> dict[str, Any]:
        return self.live.history()

    def clear_history(self) -> dict[str, Any]:
        self.live.clear_history()
        self.publish_state()
        return self.live.history()

    def capture_now(self, *, reason: str = "manual") -> dict[str, Any]:
        """Freeze latest cam frames + ``/api/state`` into ``captures/live/{id}/``."""
        frames = self.latest_frames()
        if not frames:
            raise RuntimeError("no camera frames to capture")
        pack = self.live.capture(frames, self.api_state(), reason=reason)
        if self.turn.hits and self.live.open_capture_id() is None:
            self.live.attach_capture(str(pack["id"]))
            self.publish_state()
        return pack

    def publish_state(self) -> int:
        """Append the current ``/api/state`` to the log and wake WS subscribers; returns its seq."""
        state = self.api_state()
        with self._state_cv:
            if self._state_log and self._state_log[-1][1] == state:
                return self._state_seq  # nothing changed (e.g. transition + explicit publish)
            self._state_seq += 1
            self._state_log.append((self._state_seq, state))
            self._state_cv.notify_all()
            return self._state_seq

    @property
    def state_seq(self) -> int:
        with self._state_cv:
            return self._state_seq

    def states_since(self, after_seq: int) -> list[tuple[int, dict[str, Any]]]:
        with self._state_cv:
            return [(seq, st) for seq, st in self._state_log if seq > after_seq]

    def wait_for_states(self, after_seq: int, timeout_s: float) -> list[tuple[int, dict[str, Any]]]:
        """Block (worker thread) until a state newer than ``after_seq`` exists or ``timeout_s`` passes."""
        with self._state_cv:
            if self._state_seq <= after_seq:
                self._state_cv.wait(timeout=max(0.0, timeout_s))
            return [(seq, st) for seq, st in self._state_log if seq > after_seq]

    def api_config(self) -> dict[str, Any]:
        """Madu ``GET /api/config`` — motion knobs + cam summary."""
        return {
            "motion": self._config.motion.to_api(),
            "detection": self._config.tip.to_api(),
            "fusion": self._config.fusion.to_api(),
            "turn": self._config.turn.to_api(),
            "cam": {
                "fps": self._config.ingest.capture.fps,
                "width": self._config.ingest.capture.width,
                "height": self._config.ingest.capture.height,
            },
        }

    # --- calibration ---

    def _calibration_frame_packs(self, *, n: int = 5, gap_s: float = 0.05) -> dict[int, list[np.ndarray]]:
        """Grab ``n`` latest-frame snapshots a few dozen ms apart for multi-frame Auto."""
        packs: dict[int, list[np.ndarray]] = {s: [] for s in self.session.slots}
        for i in range(max(1, n)):
            if i:
                time.sleep(gap_s)
            for slot, image in self.latest_frames().items():
                packs.setdefault(slot, []).append(image.copy())
        return {s: imgs for s, imgs in packs.items() if imgs}

    def recalibrate(self, slot: int | None = None, *, force: bool = False) -> dict[str, Any]:
        packs = self._calibration_frame_packs()
        if slot is None:
            self.session.suggest_all(packs, force=force)
        else:
            images = packs.get(slot)
            if not images:
                if force or not self.session.is_bound(slot):
                    self.session.clear(slot, "no frame from camera")
            else:
                self.session.suggest(slot, images, force=force)
        # Any calibration change revokes Accept (session) — park the detector.
        if not self.session.accepted:
            self.on_calibration_reset()
        return self.session.snapshot()

    # --- cameras ---

    def cam_config(self) -> dict[str, Any]:
        cfg = self._config.ingest
        devices: dict[int, Any] = {}
        ingest = self._ingest
        if ingest is not None:
            for slot, device in ingest.matched_devices().items():
                devices[slot] = {"index": device.index, "name": device.name, "path": device.path}
        return {
            "width": cfg.capture.width,
            "height": cfg.capture.height,
            "fps": cfg.capture.fps,
            "lockExposure": cfg.capture.lock_exposure,
            "lockWhiteBalance": cfg.capture.lock_white_balance,
            "slots": [
                {
                    "slot": s.slot,
                    "location": s.location,
                    "rotate180": s.rotate_180,
                    "device": devices.get(s.slot),
                }
                for s in cfg.slots
            ],
            "indexOverrides": dict(cfg.location_index_overrides),
            "camerasOpen": ingest is not None and ingest.is_open,
            "error": self.camera_error,
        }

    def update_cam_config(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        rotate_180: dict[int, bool] | None = None,
    ) -> dict[str, Any]:
        """Apply device settings, reopen cams, and re-run auto-suggest (settings change geometry)."""
        cfg = self._config.ingest
        capture = replace(
            cfg.capture,
            width=width if width is not None else cfg.capture.width,
            height=height if height is not None else cfg.capture.height,
            fps=fps if fps is not None else cfg.capture.fps,
        )
        slots = tuple(
            replace(s, rotate_180=rotate_180.get(s.slot, s.rotate_180)) if rotate_180 else s for s in cfg.slots
        )
        with self._lock:
            self._config = replace(self._config, ingest=replace(cfg, capture=capture, slots=slots))
        if self.reopen_cameras():
            self.recalibrate()
        return self.cam_config()

    def devices(self) -> list[dict[str, Any]]:
        ingest = self._ingest
        if ingest is None:
            try:
                ingest = self._ingest_factory(self._config.ingest)
            except Exception:
                return []
        try:
            return [
                {"index": d.index, "name": d.name, "location": d.location, "path": d.path}
                for d in ingest.list_devices()
            ]
        except Exception as exc:
            log.warning("device enumeration failed: %s", exc)
            return []

    def stats(self) -> dict[str, Any]:
        ingest, pump = self._ingest, self._pump
        cams = []
        if ingest is not None and ingest.is_open:
            cams = [
                {
                    "slot": s.slot,
                    "location": s.location,
                    "isOpened": s.is_opened,
                    "width": s.width,
                    "height": s.height,
                    "fps": s.fps,
                }
                for s in ingest.stats()
            ]
        return {
            "cams": cams,
            "pumpFps": round(pump.measured_fps, 1) if pump else 0.0,
            "pumpError": pump.error if pump else None,
            "error": self.camera_error,
        }


__all__ = ["DetectionService", "FramePump", "ServiceConfig"]
