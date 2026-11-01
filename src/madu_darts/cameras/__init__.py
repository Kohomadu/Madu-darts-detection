"""Three-cam USB ingest for the detection tool."""

from madu_darts.cameras.config import (
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_LOCATIONS,
    DEFAULT_WIDTH,
    CameraConfig,
    CameraSlot,
    IngestConfig,
    default_board_slots,
)
from madu_darts.cameras.devices import CameraDevice, match_devices_by_location, normalize_location
from madu_darts.cameras.ingest import CamFrame, CameraIngest, CamStats

__all__ = [
    "DEFAULT_FPS",
    "DEFAULT_HEIGHT",
    "DEFAULT_LOCATIONS",
    "DEFAULT_WIDTH",
    "CamFrame",
    "CamStats",
    "CameraConfig",
    "CameraDevice",
    "CameraIngest",
    "CameraSlot",
    "IngestConfig",
    "default_board_slots",
    "match_devices_by_location",
    "normalize_location",
]
