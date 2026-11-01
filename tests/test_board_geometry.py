"""Polar edge cases for point_mm → Segment (WDF radii + sector clock)."""

from __future__ import annotations

import math

import pytest

from madu_darts.board import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    SECTOR_CLOCKWISE,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
    point_mm_to_segment,
)


def _polar(radius_mm: float, angle_deg_clockwise_from_top: float) -> tuple[float, float]:
    """Board plane: +y = top (20), +x = right; angle clockwise from +y."""
    rad = math.radians(angle_deg_clockwise_from_top)
    return radius_mm * math.sin(rad), radius_mm * math.cos(rad)


# --- WDF constants ---


def test_wdf_radii_match_research_citations() -> None:
    assert INNER_BULL_RADIUS_MM == 6.35
    assert OUTER_BULL_RADIUS_MM == 15.9
    assert TREBLE_OUTER_MM == 107.4
    assert TREBLE_INNER_MM == pytest.approx(99.4)
    assert DOUBLE_OUTER_MM == 170.0
    assert DOUBLE_INNER_MM == pytest.approx(162.0)


def test_sector_clock_is_standard_clockwise_from_20() -> None:
    assert SECTOR_CLOCKWISE == (
        20,
        1,
        18,
        4,
        13,
        6,
        10,
        15,
        2,
        17,
        3,
        19,
        7,
        16,
        8,
        11,
        14,
        9,
        12,
        5,
    )


# --- Bulls & miss ---


def test_centre_is_inner_bull() -> None:
    seg = point_mm_to_segment(0.0, 0.0)
    assert seg.name == "IB"
    assert seg.number == 25
    assert seg.multiplier == 2
    assert seg.bed == "DoubleBull"
    assert seg.value == 50


def test_inner_bull_outer_wire_inclusive() -> None:
    seg = point_mm_to_segment(0.0, INNER_BULL_RADIUS_MM)
    assert seg.name == "IB"
    assert seg.value == 50


def test_just_outside_inner_bull_is_outer_bull() -> None:
    seg = point_mm_to_segment(0.0, INNER_BULL_RADIUS_MM + 1e-9)
    assert seg.name == "OB"
    assert seg.number == 25
    assert seg.multiplier == 1
    assert seg.bed == "SingleBull"
    assert seg.value == 25


def test_outer_bull_outer_wire_inclusive() -> None:
    seg = point_mm_to_segment(0.0, OUTER_BULL_RADIUS_MM)
    assert seg.name == "OB"
    assert seg.value == 25


def test_just_outside_outer_bull_is_single_inner() -> None:
    seg = point_mm_to_segment(0.0, OUTER_BULL_RADIUS_MM + 1e-9)
    assert seg.name == "S20"
    assert seg.bed == "SingleInner"
    assert seg.multiplier == 1


def test_beyond_double_outer_is_miss() -> None:
    seg = point_mm_to_segment(0.0, DOUBLE_OUTER_MM + 1e-9)
    assert seg.name == "MISS"
    assert seg.number == 0
    assert seg.multiplier == 0
    assert seg.bed == "Miss"
    assert seg.value == 0


# --- Treble / double ring wires ---


def test_treble_inner_wire_exclusive_scores_single() -> None:
    seg = point_mm_to_segment(0.0, TREBLE_INNER_MM)
    assert seg.name == "S20"
    assert seg.bed == "SingleInner"


def test_just_inside_treble_is_treble() -> None:
    seg = point_mm_to_segment(0.0, TREBLE_INNER_MM + 1e-9)
    assert seg.name == "T20"
    assert seg.multiplier == 3
    assert seg.bed == "Treble"
    assert seg.value == 60


def test_treble_outer_wire_inclusive() -> None:
    seg = point_mm_to_segment(0.0, TREBLE_OUTER_MM)
    assert seg.name == "T20"
    assert seg.bed == "Treble"


def test_just_outside_treble_is_single_outer() -> None:
    seg = point_mm_to_segment(0.0, TREBLE_OUTER_MM + 1e-9)
    assert seg.name == "S20"
    assert seg.bed == "SingleOuter"


def test_double_inner_wire_exclusive_scores_single_outer() -> None:
    seg = point_mm_to_segment(0.0, DOUBLE_INNER_MM)
    assert seg.name == "S20"
    assert seg.bed == "SingleOuter"


def test_just_inside_double_is_double() -> None:
    seg = point_mm_to_segment(0.0, DOUBLE_INNER_MM + 1e-9)
    assert seg.name == "D20"
    assert seg.multiplier == 2
    assert seg.bed == "Double"
    assert seg.value == 40


def test_double_outer_wire_inclusive() -> None:
    seg = point_mm_to_segment(0.0, DOUBLE_OUTER_MM)
    assert seg.name == "D20"
    assert seg.bed == "Double"


# --- Sector centres (every number at single-inner radius) ---


@pytest.mark.parametrize(
    "index,number",
    list(enumerate(SECTOR_CLOCKWISE)),
)
def test_sector_centre_maps_to_clock_number(index: int, number: int) -> None:
    angle = index * 18.0  # centre of wedge
    x, y = _polar(50.0, angle)
    seg = point_mm_to_segment(x, y)
    assert seg.name == f"S{number}"
    assert seg.number == number
    assert seg.bed == "SingleInner"


# --- Sector wires (clockwise-next owns the wire) ---


def test_wire_between_20_and_1_belongs_to_1() -> None:
    # Wire at +9° from top.
    x, y = _polar(50.0, 9.0)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "S1"


def test_just_before_wire_between_20_and_1_is_20() -> None:
    x, y = _polar(50.0, 9.0 - 1e-6)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "S20"


def test_wire_between_5_and_20_belongs_to_20() -> None:
    # Last wire wraps: 20 starts at 351° (= -9°).
    x, y = _polar(50.0, 351.0)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "S20"


def test_just_before_wrap_wire_is_5() -> None:
    x, y = _polar(50.0, 351.0 - 1e-6)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "S5"


# --- Named beds at non-20 sectors ---


def test_d16_at_sector_centre() -> None:
    # 16 is index 13 → 13 * 18° = 234°.
    x, y = _polar((DOUBLE_INNER_MM + DOUBLE_OUTER_MM) / 2, 13 * 18.0)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "D16"
    assert seg.number == 16
    assert seg.multiplier == 2
    assert seg.bed == "Double"
    assert seg.value == 32


def test_t5_at_sector_centre() -> None:
    # 5 is last index → 19 * 18° = 342°.
    x, y = _polar((TREBLE_INNER_MM + TREBLE_OUTER_MM) / 2, 19 * 18.0)
    seg = point_mm_to_segment(x, y)
    assert seg.name == "T5"
    assert seg.value == 15


def test_autodarts_sample_s2_coords_shape() -> None:
    """Normalized Autodarts coords for S2, scaled to mm (outer double = 1.0)."""
    # From board-1.0.7-three-darts capture: S2 at (0.296, -0.458).
    x = 0.2955363475119883 * DOUBLE_OUTER_MM
    y = -0.45832545657511614 * DOUBLE_OUTER_MM
    seg = point_mm_to_segment(x, y)
    assert seg.name == "S2"
    assert seg.bed == "SingleInner"
    assert seg.multiplier == 1
