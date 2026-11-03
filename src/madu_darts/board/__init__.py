"""Board geometry: WDF radii, sector clock, and Segment assignment."""

from madu_darts.board.geometry import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    RING_WIRE_RADII_MM,
    SECTOR_CLOCKWISE,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
    Segment,
    classify_segment_disagreement,
    distance_to_nearest_ring_wire_mm,
    distance_to_nearest_sector_wire_mm,
    nearest_ring_wire_mm,
    point_mm_to_segment,
    ring_side_of_point,
    segment_name_to_mm,
)

__all__ = [
    "DOUBLE_INNER_MM",
    "DOUBLE_OUTER_MM",
    "INNER_BULL_RADIUS_MM",
    "OUTER_BULL_RADIUS_MM",
    "RING_WIRE_RADII_MM",
    "SECTOR_CLOCKWISE",
    "TREBLE_INNER_MM",
    "TREBLE_OUTER_MM",
    "Segment",
    "classify_segment_disagreement",
    "distance_to_nearest_ring_wire_mm",
    "distance_to_nearest_sector_wire_mm",
    "nearest_ring_wire_mm",
    "point_mm_to_segment",
    "ring_side_of_point",
    "segment_name_to_mm",
]
