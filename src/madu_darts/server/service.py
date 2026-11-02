"""Detection service: camera ingest + frame pump + Calibration session for one process run.

Startup (ADR 0002): open the three cams, pull first frames, auto-suggest every
cam, then wait for the operator to rotate-20 / Accept in the Calibration view.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from madu_darts.calibration import AutoFitParams, CalibrationSession
from madu_darts.cameras import CameraIngest, CamFrame, IngestConfig
from madu_darts.motion import BoardModel, MotionConfig, MotionGate, SettledChange

log = logging.getLogger(__name__)

IngestFactory = Callable[[IngestConfig], CameraIngest]
FrameListener = Callable[[float, dict[int, CamFrame]], None]


@dataclass(frozen=True)
class ServiceConfig:
    ingest: IngestConfig = field(default_factory=IngestConfig)
    autofit: AutoFitParams | None = None
    motion: MotionConfig = field(default_factory=MotionConfig)
    first_frame_timeout_s: float = 3.0
    stream_fps: float = 10.0
    jpeg_quality: int = 80


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
        self.session = session or CalibrationSession(slots, params=self._config.autofit)
        self.board_model = BoardModel(slots)
        self.motion_gate = MotionGate(self.board_model, self._config.motion, slots=slots)
        self._ingest: CameraIngest | None = None
        self._pump: FramePump | None = None
        self._lock = threading.RLock()
        self.camera_error: str | None = None

    # --- lifecycle ---

    @property
    def config(self) -> ServiceConfig:
        return self._config

    def start(self) -> None:
        if self.reopen_cameras():
            self.recalibrate()

    def stop(self) -> None:
        with self._lock:
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
        if not self.session.accepted:
            return
        images = {slot: frame.image for slot, frame in frames.items()}
        self.motion_gate.process_frames(images, t_mono)

    # --- frames ---

    def latest_frames(self) -> dict[int, np.ndarray]:
        pump = self._pump
        if pump is None:
            return {}
        return {slot: frame.image for slot, frame in pump.latest().items()}

    def frame(self, slot: int) -> np.ndarray | None:
        return self.latest_frames().get(slot)

    # --- motion / settle ---

    def arm_motion_from_latest(self) -> None:
        """Capture empty-Board references and enable the motion gate (post-Accept)."""
        frames = self.latest_frames()
        if not frames:
            log.warning("arm_motion_from_latest: no frames yet")
            return
        self.board_model.capture_all(frames)
        self.motion_gate.reset()
        self.motion_gate.set_enabled(True)

    def on_calibration_accepted(self) -> None:
        self.session.require_accepted()
        self.arm_motion_from_latest()

    def on_calibration_reset(self) -> None:
        self.motion_gate.set_enabled(False)
        self.motion_gate.reset()
        self.board_model.reset()

    def sync_motion_with_calibration(self) -> None:
        """Enable the gate only while Calibration is Accepted; park it otherwise."""
        if self.session.accepted:
            if not self.motion_gate.enabled:
                self.arm_motion_from_latest()
        else:
            self.on_calibration_reset()

    def motion_state(self) -> dict[str, Any]:
        snap = self.motion_gate.snapshot()
        snap["enabled"] = bool(snap["enabled"] and self.session.accepted)
        return snap

    def drain_settled(self) -> list[SettledChange]:
        return self.motion_gate.drain_events()

    def api_config(self) -> dict[str, Any]:
        """Madu ``GET /api/config`` — motion knobs + cam summary."""
        return {
            "motion": self._config.motion.to_api(),
            "cam": {
                "fps": self._config.ingest.capture.fps,
                "width": self._config.ingest.capture.width,
                "height": self._config.ingest.capture.height,
            },
        }

    # --- calibration ---

    def recalibrate(self, slot: int | None = None) -> dict[str, Any]:
        frames = self.latest_frames()
        if slot is None:
            self.session.suggest_all(frames)
        else:
            image = frames.get(slot)
            if image is None:
                self.session.clear(slot, "no frame from camera")
            else:
                self.session.suggest(slot, image)
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
