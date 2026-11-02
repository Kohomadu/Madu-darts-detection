"""WDF Board geometry: polar radii, clockwise sector clock, point_mm → Segment.

Radii from WDF Playing & Tournament Rules (rev 20), as cited in
`.scratch/detection-tool/research-three-cam-approaches.md` § Segment mapping.

Board plane: origin at bull centre, +y toward sector 20 (top), +x to the right
(toward the centre of sector 6). Angle is measured clockwise from +y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- WDF radii (mm), centre → inside edge of wire / ring ---
# Bull diameters → radii; treble/double outer edges given; bands 8 mm wide.
INNER_BULL_RADIUS_MM = 6.35  # diameter 12.7
OUTER_BULL_RADIUS_MM = 15.9  # "25" ring diameter 31.8
TREBLE_OUTER_MM = 107.4
TREBLE_INNER_MM = TREBLE_OUTER_MM - 8.0  # 99.4
DOUBLE_OUTER_MM = 170.0
DOUBLE_INNER_MM = DOUBLE_OUTER_MM - 8.0  # 162.0

# Clockwise from top (sector 20).
SECTOR_CLOCKWISE: tuple[int, ...] = (
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

_SECTOR_HALF_WIDTH_DEG = 9.0  # 18° wedges; wires sit at ±9° from sector centres


@dataclass(frozen=True)
class Segment:
    """A named scoring region on the Board (glossary: Segment).

    ``name`` is the Madu label (`T20`, `D16`, `S5`, `IB`, `OB`, `MISS`).
    ``number`` / ``multiplier`` / ``bed`` mirror Autodarts throw segment shape
    for interoperability tests.
    """

    name: str
    number: int
    multiplier: int
    bed: str

    @property
    def value(self) -> int:
        return self.number * self.multiplier


def _sector_number(x_mm: float, y_mm: float) -> int:
    """Clockwise sector number from board-plane mm (bulls ignored)."""
    # atan2(x, y): 0 at +y (sector 20), increasing clockwise toward +x.
    angle_deg = math.degrees(math.atan2(x_mm, y_mm))
    if angle_deg < 0:
        angle_deg += 360.0
    # +9° so wires land on integer boundaries; wire belongs to the
    # clockwise-next sector (half-open wedges).
    index = int((angle_deg + _SECTOR_HALF_WIDTH_DEG) / 18.0) % 20
    return SECTOR_CLOCKWISE[index]


def segment_name_to_mm(name: str) -> tuple[float, float]:
    """Representative Board-mm point for a Madu / Autodarts segment label (manual override)."""
    key = name.strip()
    upper = key.upper()
    if upper in ("IB", "BULL", "50"):
        return (0.0, 0.0)
    if upper in ("OB", "25"):
        return (0.0, (INNER_BULL_RADIUS_MM + OUTER_BULL_RADIUS_MM) / 2.0)
    if upper in ("MISS", "M"):
        return (0.0, DOUBLE_OUTER_MM + 10.0)

    bed = upper[0]
    rest = upper[1:]
    if bed == "M" and rest.isdigit():
        number = int(rest)
        angle = _sector_centre_deg(number)
        rad = math.radians(angle)
        r = DOUBLE_OUTER_MM + 8.0
        return (r * math.sin(rad), r * math.cos(rad))
    if bed in ("T", "D", "S") and rest.isdigit():
        number = int(rest)
    else:
        raise ValueError(f"unknown segment name {name!r}")

    angle = _sector_centre_deg(number)
    rad = math.radians(angle)
    if bed == "T":
        r = (TREBLE_INNER_MM + TREBLE_OUTER_MM) / 2.0
    elif bed == "D":
        r = (DOUBLE_INNER_MM + DOUBLE_OUTER_MM) / 2.0
    else:  # single — prefer outer single mid
        r = (TREBLE_OUTER_MM + DOUBLE_INNER_MM) / 2.0
    return (r * math.sin(rad), r * math.cos(rad))


def _sector_centre_deg(number: int) -> float:
    try:
        index = SECTOR_CLOCKWISE.index(int(number))
    except ValueError as exc:
        raise ValueError(f"unknown sector number {number}") from exc
    return float(index * 18.0)


def point_mm_to_segment(x_mm: float, y_mm: float) -> Segment:
    """Map a board-plane tip position in millimetres to a Segment.

    Ring edges: outer wire of a ring is inclusive of that ring; inner wire of
    treble/double is exclusive (scores as the adjacent single). Bull outer
    edges are inclusive. Beyond the outer double wire is ``MISS``.
    """
    radius = math.hypot(x_mm, y_mm)

    if radius <= INNER_BULL_RADIUS_MM:
        return Segment(name="IB", number=25, multiplier=2, bed="DoubleBull")
    if radius <= OUTER_BULL_RADIUS_MM:
        return Segment(name="OB", number=25, multiplier=1, bed="SingleBull")
    if radius > DOUBLE_OUTER_MM:
        return Segment(name="MISS", number=0, multiplier=0, bed="Miss")

    number = _sector_number(x_mm, y_mm)

    if TREBLE_INNER_MM < radius <= TREBLE_OUTER_MM:
        return Segment(name=f"T{number}", number=number, multiplier=3, bed="Treble")
    if DOUBLE_INNER_MM < radius <= DOUBLE_OUTER_MM:
        return Segment(name=f"D{number}", number=number, multiplier=2, bed="Double")
    if radius <= TREBLE_INNER_MM:
        return Segment(name=f"S{number}", number=number, multiplier=1, bed="SingleInner")
    return Segment(name=f"S{number}", number=number, multiplier=1, bed="SingleOuter")
