"""WDF Board geometry: polar radii, clockwise sector clock, point_mm → Segment.

Radii from WDF Playing & Tournament Rules (rev 20), as cited in
`.scratch/detection-tool/research-three-cam-approaches.md` § Segment mapping.

Board plane: origin at bull centre, +y toward sector 20 (top), +x to the right
(toward the centre of sector 6). Angle is measured clockwise from +y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- WDF radii (mm) ---
# Bulls: inside diameters → radii (WDF 4.01).
INNER_BULL_RADIUS_MM = 6.35  # diameter 12.7
OUTER_BULL_RADIUS_MM = 15.9  # "25" ring diameter 31.8
# Double / treble: WDF publishes outside edge of the outer wire and an
# inside-to-inside bed of 8.0 mm. Segment boundaries and the spider use the
# *scoring faces* (inner faces of those wires), not outside-edge − 8.
# Ticket 21 / research-spider-calibration-accuracy.md.
BED_WIDTH_MM = 8.0
WIRE_THICKNESS_MM = 1.5  # named stock; WDF allows 1.27–1.85 (±0.2)
DOUBLE_OUTER_OUTSIDE_MM = 170.0  # WDF outside edge; Autodarts coords ÷ this
TREBLE_OUTER_OUTSIDE_MM = 107.4
DOUBLE_OUTER_MM = DOUBLE_OUTER_OUTSIDE_MM - WIRE_THICKNESS_MM  # 168.5 scoring face
DOUBLE_INNER_MM = DOUBLE_OUTER_MM - BED_WIDTH_MM  # 160.5
TREBLE_OUTER_MM = TREBLE_OUTER_OUTSIDE_MM - WIRE_THICKNESS_MM  # 105.9
TREBLE_INNER_MM = TREBLE_OUTER_MM - BED_WIDTH_MM  # 97.9

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

# Physical ring wires (mm from bull). Used for miss classification, not bed assignment.
RING_WIRE_RADII_MM: tuple[float, ...] = (
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
)


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
        return (0.0, DOUBLE_OUTER_OUTSIDE_MM + 10.0)

    bed = upper[0]
    rest = upper[1:]
    if bed == "M" and rest.isdigit():
        number = int(rest)
        angle = _sector_centre_deg(number)
        rad = math.radians(angle)
        r = DOUBLE_OUTER_OUTSIDE_MM + BED_WIDTH_MM
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

    Treble/double bounds are scoring faces (inner faces of the ring wires):
    outer face inclusive of that ring; inner face exclusive (adjacent single).
    Bull outer edges are inclusive. Beyond the outer double *outside* edge
    (WDF 170 mm) is ``MISS`` so the physical wire stock itself is still Board.
    """
    radius = math.hypot(x_mm, y_mm)

    if radius <= INNER_BULL_RADIUS_MM:
        return Segment(name="IB", number=25, multiplier=2, bed="DoubleBull")
    if radius <= OUTER_BULL_RADIUS_MM:
        return Segment(name="OB", number=25, multiplier=1, bed="SingleBull")
    if radius > DOUBLE_OUTER_OUTSIDE_MM:
        return Segment(name="MISS", number=0, multiplier=0, bed="Miss")

    number = _sector_number(x_mm, y_mm)

    if TREBLE_INNER_MM < radius <= TREBLE_OUTER_MM:
        return Segment(name=f"T{number}", number=number, multiplier=3, bed="Treble")
    # Outer treble wire stock (scoring face → WDF outside edge).
    if TREBLE_OUTER_MM < radius <= TREBLE_OUTER_OUTSIDE_MM:
        return Segment(name=f"T{number}", number=number, multiplier=3, bed="Treble")
    if DOUBLE_INNER_MM < radius <= DOUBLE_OUTER_MM:
        return Segment(name=f"D{number}", number=number, multiplier=2, bed="Double")
    # Outer double wire stock (scoring face → WDF outside edge).
    if DOUBLE_OUTER_MM < radius <= DOUBLE_OUTER_OUTSIDE_MM:
        return Segment(name=f"D{number}", number=number, multiplier=2, bed="Double")
    if radius <= TREBLE_INNER_MM:
        return Segment(name=f"S{number}", number=number, multiplier=1, bed="SingleInner")
    return Segment(name=f"S{number}", number=number, multiplier=1, bed="SingleOuter")


def distance_to_nearest_ring_wire_mm(x_mm: float, y_mm: float) -> float:
    """Radial distance from ``(x, y)`` to the nearest ring wire (mm)."""
    radius = math.hypot(x_mm, y_mm)
    return min(abs(radius - wire) for wire in RING_WIRE_RADII_MM)


def nearest_ring_wire_mm(x_mm: float, y_mm: float) -> float:
    """Radius (mm) of the ring wire nearest to ``(x, y)``."""
    radius = math.hypot(x_mm, y_mm)
    return min(RING_WIRE_RADII_MM, key=lambda wire: abs(radius - wire))


def ring_side_of_point(x_mm: float, y_mm: float) -> dict[str, float | str]:
    """Which side of the nearest ring wire a tip sits on (Detection overlay)."""
    radius = math.hypot(x_mm, y_mm)
    wire = nearest_ring_wire_mm(x_mm, y_mm)
    dist = abs(radius - wire)
    if dist < 1e-6:
        side = "on"
    elif radius < wire:
        side = "inside"
    else:
        side = "outside"
    return {"wireMm": float(wire), "side": side, "distMm": float(dist)}


def distance_to_nearest_sector_wire_mm(x_mm: float, y_mm: float) -> float:
    """Arc distance from ``(x, y)`` to the nearest sector wire (mm)."""
    radius = math.hypot(x_mm, y_mm)
    if radius < 1e-9:
        return 0.0
    angle_deg = math.degrees(math.atan2(x_mm, y_mm))
    if angle_deg < 0.0:
        angle_deg += 360.0
    # Wires at 9° + 18°·k. Offset from the previous wire is ``(angle + 9) % 18``.
    from_wire = (angle_deg + _SECTOR_HALF_WIDTH_DEG) % 18.0
    d_deg = min(from_wire, 18.0 - from_wire)
    return radius * math.radians(d_deg)


def _is_bull_label(segment: str) -> bool:
    name = segment.strip().upper()
    return name in ("25", "BULL", "IB", "OB", "50")


def classify_segment_disagreement(
    autodarts_segment: str,
    madu_segment: str,
    x_mm: float,
    y_mm: float,
) -> str:
    """Class for a Segment pair at board-mm tip ``(x, y)``.

    Returns ``agree``, ``bull``, ``ring_miss``, or ``neighbour``. A wrong
    Segment closer to a ring wire than to a sector wire is a ring miss; the
    opposite is a neighbour. Bull disagreements are their own class.
    """
    ad = autodarts_segment.strip()
    madu = madu_segment.strip()
    if ad and madu and ad == madu:
        return "agree"
    if _is_bull_label(ad) or _is_bull_label(madu):
        return "bull"
    ring = distance_to_nearest_ring_wire_mm(x_mm, y_mm)
    sector = distance_to_nearest_sector_wire_mm(x_mm, y_mm)
    if ring <= sector:
        return "ring_miss"
    return "neighbour"
