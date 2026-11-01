"""OpenCV capture handle: resolution/FPS + settle-then-lock exposure/WB.

Autodarts locks image controls once the Board is lit so motion/detection stay
stable. We do the same without shipping a full UVC panel yet:

1. Enable auto-exposure / auto-WB.
2. Grab a few frames so the driver can settle under the LED ring.
3. Read the settled absolute exposure (and WB temperature when available).
4. Switch to manual and write those values back.

Just flipping ``CAP_PROP_AUTO_EXPOSURE`` to manual without step 2–4 leaves many
V4L2 cams near-black (the Board symptom we hit on first live run).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from madu_darts.cameras.config import CameraConfig
from madu_darts.cameras.devices import CameraDevice

log = logging.getLogger(__name__)

# OpenCV / V4L2 conventions (float props; DirectShow often mirrors these).
_AUTO_EXPOSURE_ON = (0.75, 3.0)  # aperture-priority / auto
_AUTO_EXPOSURE_OFF = (0.25, 1.0)  # manual


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
    """Open a device, set MJPG/res/FPS when possible, settle-then-lock exposure/WB."""

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
    """Settle under auto, then lock exposure/WB when requested."""
    if config.lock_exposure or config.lock_white_balance:
        _enable_auto(cap, cv2, exposure=config.lock_exposure, white_balance=config.lock_white_balance)
        _warmup(cap, config.settle_frames)

    if config.lock_exposure:
        _lock_exposure(cap, cv2, absolute=config.exposure)
    if config.lock_white_balance:
        _lock_white_balance(cap, cv2, temperature=config.white_balance_temperature)


def _set_any(cap: Any, prop: int, values: tuple[float, ...]) -> bool:
    for value in values:
        try:
            if cap.set(prop, value):
                return True
        except Exception:
            continue
    return False


def _enable_auto(cap: Any, cv2: Any, *, exposure: bool, white_balance: bool) -> None:
    if exposure:
        if not _set_any(cap, cv2.CAP_PROP_AUTO_EXPOSURE, _AUTO_EXPOSURE_ON):
            log.debug("could not enable auto-exposure before settle")
    if white_balance:
        try:
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        except Exception:
            log.debug("could not enable auto white-balance before settle")


def _warmup(cap: Any, frames: int) -> None:
    """Grab frames so auto-exposure / auto-WB can converge under the LED ring."""
    for _ in range(max(0, frames)):
        try:
            cap.read()
        except Exception:
            break


def _lock_exposure(cap: Any, cv2: Any, *, absolute: float | None) -> None:
    """Disable auto-exposure and pin the settled (or configured) absolute value."""
    try:
        settled = float(cap.get(cv2.CAP_PROP_EXPOSURE))
    except Exception:
        settled = float("nan")

    target = absolute if absolute is not None else settled
    _set_any(cap, cv2.CAP_PROP_AUTO_EXPOSURE, _AUTO_EXPOSURE_OFF)

    if target == target:  # not NaN
        try:
            if not cap.set(cv2.CAP_PROP_EXPOSURE, float(target)):
                log.debug("exposure lock write rejected (value=%s)", target)
        except Exception:
            log.debug("exposure lock write failed (value=%s)", target, exc_info=True)
    else:
        log.debug("exposure lock skipped write: no settled value available")


def _lock_white_balance(cap: Any, cv2: Any, *, temperature: float | None) -> None:
    """Disable auto-WB and pin the settled (or configured) colour temperature."""
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
            if not cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(target)):
                log.debug("WB temperature lock write rejected (value=%s)", target)
        except Exception:
            log.debug("WB temperature lock write failed (value=%s)", target, exc_info=True)
