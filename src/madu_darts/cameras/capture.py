"""OpenCV capture handle: resolution/FPS + best-effort exposure/WB lock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from madu_darts.cameras.config import CameraConfig
from madu_darts.cameras.devices import CameraDevice


class CaptureHandle(Protocol):
    def is_opened(self) -> bool: ...

    def read(self) -> tuple[bool, Any]:
        """Return ``(ok, frame)``; frame is BGR ndarray when ok."""

    def release(self) -> None: ...

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    @property
    def fps(self) -> float: ...


class CaptureFactory(Protocol):
    def open(self, device: CameraDevice, config: CameraConfig) -> CaptureHandle: ...


@dataclass
class OpenCvCaptureHandle:
    """Thin wrapper around ``cv2.VideoCapture`` after format/controls applied."""

    _cap: Any
    _width: int
    _height: int
    _fps: float

    def is_opened(self) -> bool:
        return bool(self._cap.isOpened())

    def read(self) -> tuple[bool, Any]:
        return self._cap.read()

    def release(self) -> None:
        self._cap.release()

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def fps(self) -> float:
        return self._fps


class OpenCvCaptureFactory:
    """Open a device, set MJPG/res/FPS when possible, lock exposure/WB."""

    def __init__(self, api_preference: int | None = None) -> None:
        self._api_preference = api_preference

    def open(self, device: CameraDevice, config: CameraConfig) -> CaptureHandle:
        import cv2

        if self._api_preference is None:
            cap = cv2.VideoCapture(device.index)
        else:
            cap = cv2.VideoCapture(device.index, self._api_preference)

        if not cap.isOpened():
            raise RuntimeError(f"failed to open camera index {device.index}")

        # Prefer MJPEG at Autodarts defaults when the driver offers it.
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
        cap.set(cv2.CAP_PROP_FPS, config.fps)

        if config.lock_exposure:
            _lock_exposure(cap, cv2)
        if config.lock_white_balance:
            _lock_white_balance(cap, cv2)

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or config.width)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or config.height)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or config.fps)

        return OpenCvCaptureHandle(
            _cap=cap,
            _width=width,
            _height=height,
            _fps=fps,
        )


def _lock_exposure(cap: Any, cv2: Any) -> None:
    """Best-effort: disable auto-exposure. V4L2 and DirectShow differ."""
    # V4L2: 1 = manual; DirectShow often uses 0.25 = manual.
    for value in (1.0, 0.25, 0.0):
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value)
        except Exception:
            pass


def _lock_white_balance(cap: Any, cv2: Any) -> None:
    try:
        cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    except Exception:
        pass
