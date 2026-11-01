"""Three-cam ingest: open by USB location, read frames for Calibration view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from madu_darts.cameras.capture import CaptureFactory, CaptureHandle, OpenCvCaptureFactory
from madu_darts.cameras.config import IngestConfig
from madu_darts.cameras.devices import CameraDevice, match_devices_by_location
from madu_darts.cameras.enumerate import DeviceEnumerator, default_enumerator


@dataclass(frozen=True)
class CamFrame:
    """One frame from a Board camera slot."""

    slot: int
    location: str
    image: Any
    """BGR ndarray (OpenCV)."""


@dataclass(frozen=True)
class CamStats:
    slot: int
    location: str
    is_opened: bool
    width: int
    height: int
    fps: float


class CameraIngest:
    """Capture three USB streams identified by USB location.

    Feeds the Calibration view. Does not run Calibration itself (ticket 04).
    """

    def __init__(
        self,
        config: IngestConfig | None = None,
        *,
        enumerator: DeviceEnumerator | None = None,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        self._config = config or IngestConfig()
        self._enumerator = enumerator or default_enumerator()
        self._capture_factory = capture_factory or OpenCvCaptureFactory()
        self._handles: dict[int, CaptureHandle] = {}
        self._devices: dict[int, CameraDevice] = {}
        self._locations: dict[int, str] = {}

    @property
    def is_open(self) -> bool:
        return bool(self._handles) and all(h.is_opened() for h in self._handles.values())

    def list_devices(self) -> list[CameraDevice]:
        return self._enumerator.list_devices()

    def matched_devices(self) -> dict[int, CameraDevice]:
        """Slot -> device bound at ``open()`` (empty when closed)."""
        return dict(self._devices)

    def open(self) -> None:
        if self._handles:
            raise RuntimeError("CameraIngest already open; call close() first")

        locations = [slot.location for slot in self._config.slots]
        devices = self.list_devices()
        matched = match_devices_by_location(
            devices,
            locations,
            index_overrides=self._config.location_index_overrides,
        )

        opened: dict[int, CaptureHandle] = {}
        try:
            for slot in self._config.slots:
                device = matched[slot.location]
                handle = self._capture_factory.open(device, self._config.capture)
                opened[slot.slot] = handle
                self._devices[slot.slot] = device
                self._locations[slot.slot] = slot.location
        except Exception:
            for handle in opened.values():
                handle.release()
            self._devices.clear()
            self._locations.clear()
            raise

        self._handles = opened

    def close(self) -> None:
        for handle in self._handles.values():
            handle.release()
        self._handles.clear()
        self._devices.clear()
        self._locations.clear()

    def read(self) -> dict[int, CamFrame]:
        """Grab one frame per open slot. Missing/failed reads are omitted."""
        if not self._handles:
            raise RuntimeError("CameraIngest is not open")

        rotate = {s.slot: s.rotate_180 for s in self._config.slots}
        frames: dict[int, CamFrame] = {}
        for slot, handle in self._handles.items():
            ok, image = handle.read()
            if not ok or image is None:
                continue
            if rotate.get(slot):
                image = _rotate_180(image)
            frames[slot] = CamFrame(
                slot=slot,
                location=self._locations[slot],
                image=image,
            )
        return frames

    def stats(self) -> list[CamStats]:
        result: list[CamStats] = []
        for slot in sorted(self._handles):
            handle = self._handles[slot]
            result.append(
                CamStats(
                    slot=slot,
                    location=self._locations[slot],
                    is_opened=handle.is_opened(),
                    width=handle.width,
                    height=handle.height,
                    fps=handle.fps,
                )
            )
        return result

    def __enter__(self) -> CameraIngest:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _rotate_180(image: Any) -> Any:
    try:
        import cv2

        return cv2.rotate(image, cv2.ROTATE_180)
    except Exception:
        import numpy as np

        arr = np.asarray(image)
        return arr[::-1, ::-1].copy()
