"""OpenCV capture handle: resolution/FPS + optional settle-then-lock exposure/WB.

Autodarts locks image controls once the Board is lit so motion/detection stay
stable. On these UVC cams, reading ``CAP_PROP_EXPOSURE`` during auto and writing
it back in manual mode often pins a near-black shutter — so locking is **opt-in**
and aborted when a post-lock frame is still too dark (auto stays on).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from madu_darts.cameras.config import CameraConfig
from madu_darts.cameras.devices import CameraDevice

log = logging.getLogger(__name__)

# Prefer V4L2-native enums first; OpenCV's 0.75/0.25 floats are a second try.
_AUTO_EXPOSURE_ON = (3.0, 0.75)
_AUTO_EXPOSURE_OFF = (1.0, 0.25)


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
    """Open a device, set MJPG/res/FPS when possible, optionally settle-then-lock."""

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

        apply_image_controls(cap, cv2, config)

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or config.width)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or config.height)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or config.fps)

        return OpenCvCaptureHandle(
            _cap=cap,
            _width=width,
            _height=height,
            _fps=fps,
        )


def apply_image_controls(cap: Any, cv2: Any, config: CameraConfig) -> None:
    """Optionally settle under auto, lock, then undo the lock if the frame stays dark."""
    if not (config.lock_exposure or config.lock_white_balance):
        # Still nudge auto on so freshly opened UVC nodes aren't stuck in manual black.
        _enable_auto(cap, cv2, exposure=True, white_balance=True)
        _warmup(cap, min(8, config.settle_frames))
        return

    _enable_auto(cap, cv2, exposure=config.lock_exposure, white_balance=config.lock_white_balance)
    _warmup(cap, config.settle_frames)

    if config.lock_exposure:
        _lock_exposure(cap, cv2, absolute=config.exposure)
    if config.lock_white_balance:
        _lock_white_balance(cap, cv2, temperature=config.white_balance_temperature)

    mean = _frame_mean(cap)
    if mean is not None and mean < config.min_lock_mean:
        log.warning(
            "post-lock frame mean %.1f < %.1f; leaving auto-exposure/WB on",
            mean,
            config.min_lock_mean,
        )
        _enable_auto(cap, cv2, exposure=config.lock_exposure, white_balance=config.lock_white_balance)
        _warmup(cap, min(8, config.settle_frames))


def _set_any(cap: Any, prop: int, values: tuple[float, ...]) -> bool:
    for value in values:
        try:
            if cap.set(prop, value):
                return True
        except Exception:
            continue
    # Some drivers return False even when the value stuck; try a last write anyway.
    try:
        cap.set(prop, values[-1])
    except Exception:
        pass
    return False


def _enable_auto(cap: Any, cv2: Any, *, exposure: bool, white_balance: bool) -> None:
    if exposure:
        _set_any(cap, cv2.CAP_PROP_AUTO_EXPOSURE, _AUTO_EXPOSURE_ON)
    if white_balance:
        try:
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        except Exception:
            log.debug("could not enable auto white-balance")


def _warmup(cap: Any, frames: int) -> None:
    for _ in range(max(0, frames)):
        try:
            cap.read()
        except Exception:
            break


def _frame_mean(cap: Any) -> float | None:
    try:
        ok, frame = cap.read()
    except Exception:
        return None
    if not ok or frame is None:
        return None
    try:
        import numpy as np

        return float(np.mean(frame))
    except Exception:
        return None


def _lock_exposure(cap: Any, cv2: Any, *, absolute: float | None) -> None:
    try:
        settled = float(cap.get(cv2.CAP_PROP_EXPOSURE))
    except Exception:
        settled = float("nan")

    target = absolute if absolute is not None else settled
    _set_any(cap, cv2.CAP_PROP_AUTO_EXPOSURE, _AUTO_EXPOSURE_OFF)

    if target == target:  # not NaN
        try:
            cap.set(cv2.CAP_PROP_EXPOSURE, float(target))
        except Exception:
            log.debug("exposure lock write failed (value=%s)", target, exc_info=True)


def _lock_white_balance(cap: Any, cv2: Any, *, temperature: float | None) -> None:
    try:
        settled = float(cap.get(cv2.CAP_PROP_WB_TEMPERATURE))
    except Exception:
        settled = float("nan")

    target = temperature if temperature is not None else settled
    try:
        cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    except Exception:
        log.debug("could not disable auto white-balance")

    if target == target and target > 0:
        try:
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(target))
        except Exception:
            log.debug("WB temperature lock write failed (value=%s)", target, exc_info=True)
