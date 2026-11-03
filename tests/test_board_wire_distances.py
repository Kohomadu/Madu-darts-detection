"""Wire distances and Segment-disagreement classes (ticket 33)."""

from __future__ import annotations

import math

import pytest

from madu_darts.board.geometry import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    classify_segment_disagreement,
    distance_to_nearest_ring_wire_mm,
    distance_to_nearest_sector_wire_mm,
    point_mm_to_segment,
)


def _polar(radius_mm: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return radius_mm * math.sin(rad), radius_mm * math.cos(rad)


def test_point_just_inside_double_is_closer_to_ring_than_sector() -> None:
    # Sector-20 centre, mid-double: 4 mm to either ring wire, ~26.7 mm to a sector wire.
    x, y = _polar((DOUBLE_INNER_MM + DOUBLE_OUTER_MM) / 2.0, 0.0)
    assert point_mm_to_segment(x, y).name == "D20"
    ring = distance_to_nearest_ring_wire_mm(x, y)
    sector = distance_to_nearest_sector_wire_mm(x, y)
    assert ring == pytest.approx(4.0, abs=0.05)
    assert sector > 20.0
    assert ring < sector


def test_point_just_across_outer_double_wire() -> None:
    x, y = _polar(DOUBLE_OUTER_MM + 0.5, 0.0)
    assert point_mm_to_segment(x, y).name == "MISS"
    assert distance_to_nearest_ring_wire_mm(x, y) == pytest.approx(0.5, abs=0.05)


def test_point_one_sector_over_near_wire_is_neighbour_class() -> None:
    # Just clockwise of the 20/1 wire (at 9°), still near the outer-single mid-radius.
    x, y = _polar(130.0, 9.5)
    assert point_mm_to_segment(x, y).name == "S1"
    ring = distance_to_nearest_ring_wire_mm(x, y)
    sector = distance_to_nearest_sector_wire_mm(x, y)
    assert sector < ring
    assert (
        classify_segment_disagreement("S20", "S1", x, y) == "neighbour"
    )


def test_ring_miss_when_wrong_bed_near_double_wire() -> None:
    # Just outside the inner double wire → single; truth was the double.
    x, y = _polar(DOUBLE_INNER_MM - 0.4, 0.0)
    assert point_mm_to_segment(x, y).name == "S20"
    assert classify_segment_disagreement("D20", "S20", x, y) == "ring_miss"


def test_bull_disagreement_is_bull_class() -> None:
    x, y = _polar(10.0, 0.0)
    assert classify_segment_disagreement("25", "S20", x, y) == "bull"


def test_agree_returns_agree() -> None:
    x, y = _polar(166.0, 0.0)
    assert classify_segment_disagreement("D20", "D20", x, y) == "agree"
