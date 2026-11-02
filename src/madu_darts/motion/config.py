"""Motion / settle knobs (Autodarts-shaped defaults from live ``/api/config``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MotionConfig:
    """Per-process motion gate settings.

    Defaults match Autodarts 2.1.0 ``motion`` / observed Vision behaviour:
    downscale ``scale`` 4 → 320×180 from 1280×720, blur/morph ``kernel`` 3,
    pixel ``threshold`` 16, ``stable_num_frames`` 3 before settle commit.
    """

    scale: float = 4.0
    kernel: int = 3
    threshold: int = 16
    stable_num_frames: int = 3
    #: Changed pixels (at motion scale) required to enter / stay in motion.
    min_changed_pixels: int = 40
    #: Background-diff pixels above this → takeout-like (suppress settle).
    takeout_min_changed_pixels: int = 2500
    #: Consecutive motion frames with a large change before takeout classify.
    takeout_min_motion_frames: int = 12

    def to_api(self) -> dict[str, Any]:
        """CamelCase fragment for ``GET /api/config`` (Autodarts-shaped)."""
        return {
            "kernel": self.kernel,
            "scale": self.scale,
            "stableNumFrames": self.stable_num_frames,
            "threshold": self.threshold,
            "minChangedPixels": self.min_changed_pixels,
            "takeoutMinChangedPixels": self.takeout_min_changed_pixels,
            "takeoutMinMotionFrames": self.takeout_min_motion_frames,
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["MotionConfig"]
