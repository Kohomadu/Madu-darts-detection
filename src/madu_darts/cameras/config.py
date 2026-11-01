"""Camera ingest configuration (Autodarts-shaped defaults)."""

from __future__ import annotations

from dataclasses import dataclass, field

# Autodarts live board defaults — research-autodarts-behaviour.md §2.1 / checklist §1.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30

# This Board's USB locations (Linux bus) for cams 0/1/2.
DEFAULT_LOCATIONS: tuple[str, str, str] = ("7.2", "7.3", "7.4")


@dataclass(frozen=True)
class CameraSlot:
    """One fixed Board camera: slot index + preferred USB location."""

    slot: int
    location: str
    rotate_180: bool = False


@dataclass(frozen=True)
class CameraConfig:
    """Shared capture settings for all three cams."""

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    lock_exposure: bool = True
    lock_white_balance: bool = True


def default_board_slots(
    locations: tuple[str, str, str] = DEFAULT_LOCATIONS,
) -> tuple[CameraSlot, CameraSlot, CameraSlot]:
    """Three slots bound to USB locations (this Board: 7.2 / 7.3 / 7.4)."""
    return (
        CameraSlot(slot=0, location=locations[0]),
        CameraSlot(slot=1, location=locations[1]),
        CameraSlot(slot=2, location=locations[2]),
    )


@dataclass(frozen=True)
class IngestConfig:
    """Full ingest setup: slots + shared capture knobs."""

    slots: tuple[CameraSlot, ...] = field(default_factory=default_board_slots)
    capture: CameraConfig = field(default_factory=CameraConfig)
    # Optional location → OpenCV index map when USB path enumeration is unavailable
    # (typical Windows-dev fallback). Prefer real location matching on the Board.
    location_index_overrides: dict[str, int] = field(default_factory=dict)
