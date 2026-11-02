"""Camera stand-in for ``madu-darts serve --synthetic``: three rendered Board views.

With ``script=True`` (``--synthetic-throws``) the views play a looping visit —
three darts land, a hand sweeps through, the Board empties — so the Detection
view and the ``/api/events`` stream can be exercised without hardware.
"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

from madu_darts.calibration.synthetic import SyntheticCamera, synthetic_camera
from madu_darts.cameras import CameraDevice, CamFrame, CamStats, IngestConfig

# Pose + rotation per slot, roughly mimicking three cams spread around the Board.
SYNTHETIC_VIEWS = {0: ("tilt_top", 0), 1: ("tilt_left", 7), 2: ("tilt_right", 13)}

#: Scripted visit: (time in loop, Board mm) per dart; hand sweep + empty afterwards.
SCRIPT_DARTS: tuple[tuple[float, tuple[float, float]], ...] = ((3.0, (0.0, 103.4)), (6.0, (-130.0, 0.0)), (9.0, (-135.0, -98.0)))
SCRIPT_HAND = (11.5, 12.7)
SCRIPT_PERIOD_S = 16.0

_WHITE = (235, 235, 235)


def _draw_dart(image: np.ndarray, tip_px: np.ndarray, *, length_px: float = 110.0, angle_deg: float = 0.0) -> np.ndarray:
    out = image.copy()
    a = math.radians(angle_deg)
    direction = np.array([math.sin(a), -math.cos(a)])
    end = tip_px + direction * length_px
    cv2.line(out, tuple(np.round(tip_px).astype(int)), tuple(np.round(end).astype(int)), _WHITE, 3, cv2.LINE_AA)
    flight = end + direction * 14.0
    cv2.ellipse(out, tuple(np.round(flight).astype(int)), (10, 18), angle_deg, 0, 360, _WHITE, -1, cv2.LINE_AA)
    return out


class SyntheticIngest:
    """Duck-types ``CameraIngest`` with fixed (or scripted) synthetic frames (no hardware)."""

    def __init__(self, config: IngestConfig, *, script: bool = False) -> None:
        self._config = config
        self._open = False
        self._frames: dict[int, CamFrame] = {}
        self._cams: dict[int, SyntheticCamera] = {}
        self._fps = float(config.capture.fps)
        self._last_read = 0.0
        self._script = script
        self._t0 = time.monotonic()

    def list_devices(self) -> list[CameraDevice]:
        return [
            CameraDevice(index=i, name="Synthetic Board camera", location=s.location, path=f"synthetic://{s.location}")
            for i, s in enumerate(self._config.slots)
        ]

    def matched_devices(self) -> dict[int, CameraDevice]:
        return {s.slot: d for s, d in zip(self._config.slots, self.list_devices())} if self._open else {}

    def open(self) -> None:
        for slot in self._config.slots:
            pose, rotation = SYNTHETIC_VIEWS.get(slot.slot, ("fronto", 0))
            cam = synthetic_camera(pose, rotation_sectors=rotation)
            self._cams[slot.slot] = cam
            image = cam.image
            if slot.rotate_180:
                image = image[::-1, ::-1].copy()
            self._frames[slot.slot] = CamFrame(slot=slot.slot, location=slot.location, image=image)
        self._open = True
        self._t0 = time.monotonic()

    def close(self) -> None:
        self._open = False
        self._frames.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def _scripted(self, now: float) -> dict[int, CamFrame]:
        t = (now - self._t0) % SCRIPT_PERIOD_S
        hand_t0, hand_t1 = SCRIPT_HAND
        out: dict[int, CamFrame] = {}
        for slot in self._config.slots:
            cam = self._cams[slot.slot]
            image = cam.image
            if t < hand_t1:
                for i, (t_dart, mm) in enumerate(SCRIPT_DARTS):
                    if t >= t_dart:
                        image = _draw_dart(image, cam.pixel_of_mm(*mm), angle_deg=5.0 - 4.0 * i)
            if hand_t0 <= t < hand_t1:
                image = image.copy()
                cx = int(200 + 900 * (t - hand_t0) / (hand_t1 - hand_t0))
                cv2.circle(image, (cx, 360), 150, (60, 40, 30), -1)
            if slot.rotate_180:
                image = image[::-1, ::-1].copy()
            out[slot.slot] = CamFrame(slot=slot.slot, location=slot.location, image=image)
        return out

    def read(self) -> dict[int, CamFrame]:
        if not self._open:
            raise RuntimeError("SyntheticIngest is not open")
        # Pace like a real camera so the frame pump does not spin.
        wait = (1.0 / self._fps) - (time.monotonic() - self._last_read)
        if wait > 0:
            time.sleep(wait)
        self._last_read = time.monotonic()
        if self._script:
            return self._scripted(self._last_read)
        return dict(self._frames)

    def stats(self) -> list[CamStats]:
        c = self._config.capture
        return [
            CamStats(slot=s.slot, location=s.location, is_opened=self._open, width=c.width, height=c.height, fps=self._fps)
            for s in self._config.slots
        ]
