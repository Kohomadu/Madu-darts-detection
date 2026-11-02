"""Motion gate public types: phase, debug state, settled-change events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class MotionPhase(str, Enum):
    IDLE = "idle"
    MOTION = "motion"
    SETTLING = "settling"
    STABLE = "stable"


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    w: int
    h: int

    def to_api(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class CamMotionState:
    """Per-cam Vision-like debug fields (Autodarts ``motion_state`` flavour)."""

    slot: int
    phase: MotionPhase = MotionPhase.IDLE
    is_moving: bool = False
    is_stable: bool = True
    is_takeout: bool = False
    changed_pixels: int = 0
    motion_pixels: int = 0
    frame_counts: dict[str, int] = field(
        default_factory=lambda: {"motion": 0, "stable": 0, "takeout": 0}
    )
    bbox: BoundingBox | None = None

    def to_api(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "phase": self.phase.value,
            "isMoving": self.is_moving,
            "isStable": self.is_stable,
            "isTakeout": self.is_takeout,
            "changedPixels": self.changed_pixels,
            "motionPixels": self.motion_pixels,
            "frameCounts": dict(self.frame_counts),
            "bbox": None if self.bbox is None else self.bbox.to_api(),
        }


@dataclass
class SettledChange:
    """One settled change on one cam — tip localizer (09) consumes these."""

    slot: int
    t_mono: float
    changed_pixels: int
    bbox: BoundingBox
    #: Diff mask at motion scale (uint8 0/255); ROI for tip search.
    mask: np.ndarray
    kind: str = "dart"  # "dart" | suppressed kinds never emitted

    def to_api(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "tMono": self.t_mono,
            "changedPixels": self.changed_pixels,
            "bbox": self.bbox.to_api(),
            "kind": self.kind,
            "maskShape": list(self.mask.shape),
        }


__all__ = ["BoundingBox", "CamMotionState", "MotionPhase", "SettledChange"]
