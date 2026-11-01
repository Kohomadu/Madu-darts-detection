"""Camera stand-in for ``madu-darts serve --synthetic``: three rendered Board views."""

from __future__ import annotations

import time

from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.cameras import CameraDevice, CamFrame, CamStats, IngestConfig

# Pose + rotation per slot, roughly mimicking three cams spread around the Board.
SYNTHETIC_VIEWS = {0: ("tilt_top", 0), 1: ("tilt_left", 7), 2: ("tilt_right", 13)}


class SyntheticIngest:
    """Duck-types ``CameraIngest`` with fixed synthetic frames (no hardware)."""

    def __init__(self, config: IngestConfig) -> None:
        self._config = config
        self._open = False
        self._frames: dict[int, CamFrame] = {}
        self._fps = float(config.capture.fps)
        self._last_read = 0.0

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
            image = synthetic_camera(pose, rotation_sectors=rotation).image
            if slot.rotate_180:
                image = image[::-1, ::-1].copy()
            self._frames[slot.slot] = CamFrame(slot=slot.slot, location=slot.location, image=image)
        self._open = True

    def close(self) -> None:
        self._open = False
        self._frames.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def read(self) -> dict[int, CamFrame]:
        if not self._open:
            raise RuntimeError("SyntheticIngest is not open")
        # Pace like a real camera so the frame pump does not spin.
        wait = (1.0 / self._fps) - (time.monotonic() - self._last_read)
        if wait > 0:
            time.sleep(wait)
        self._last_read = time.monotonic()
        return dict(self._frames)

    def stats(self) -> list[CamStats]:
        c = self._config.capture
        return [
            CamStats(slot=s.slot, location=s.location, is_opened=self._open, width=c.width, height=c.height, fps=self._fps)
            for s in self._config.slots
        ]
