"""The Hit object (glossary) and its Autodarts-shaped throw projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from madu_darts.board.geometry import DOUBLE_OUTER_MM, Segment, _sector_number, point_mm_to_segment
from madu_darts.hits.tip import TipCandidate

# Autodarts ``coordsX/Y`` = Board mm ÷ outer-double radius (same as record.meta.COORDS_NORM_RADIUS_MM;
# imported from geometry to avoid a record → server → hits import cycle).
COORDS_NORM_RADIUS_MM = float(DOUBLE_OUTER_MM)

# Autodarts 2.1 bed vocabulary (observed in recordings): Single (25), SingleInner,
# SingleOuter, Double, Triple, Outside. Inner bull assumed "Bull"/"Double".
_BED_TO_AUTODARTS = {
    "SingleInner": "SingleInner",
    "SingleOuter": "SingleOuter",
    "Double": "Double",
    "Treble": "Triple",
    "SingleBull": "Single",
    "DoubleBull": "Double",
    "Miss": "Outside",
}


def autodarts_segment_fields(segment: Segment, x_mm: float, y_mm: float) -> dict[str, Any]:
    """``{segmentName, segmentNumber, multiplier, bed}`` the way Autodarts labels them."""
    if segment.name == "OB":
        return {"segmentName": "25", "segmentNumber": 25, "multiplier": 1, "bed": "Single"}
    if segment.name == "IB":
        return {"segmentName": "Bull", "segmentNumber": 25, "multiplier": 2, "bed": "Double"}
    if segment.name == "MISS":
        number = _sector_number(x_mm, y_mm)
        return {"segmentName": f"M{number}", "segmentNumber": number, "multiplier": 0, "bed": "Outside"}
    return {
        "segmentName": segment.name,
        "segmentNumber": segment.number,
        "multiplier": segment.multiplier,
        "bed": _BED_TO_AUTODARTS.get(segment.bed, segment.bed),
    }


def autodarts_segment_name(x_mm: float, y_mm: float) -> str:
    return str(autodarts_segment_fields(point_mm_to_segment(x_mm, y_mm), x_mm, y_mm)["segmentName"])


@dataclass(frozen=True)
class SlotVote:
    slot: int
    tip: TipCandidate
    x_mm: float
    y_mm: float
    used: bool

    def to_api(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "xMm": round(self.x_mm, 2),
            "yMm": round(self.y_mm, 2),
            "used": self.used,
            "tip": self.tip.to_api(),
        }


@dataclass(frozen=True)
class Hit:
    """One dart stuck in the Board with its Segment (glossary: Hit)."""

    x_mm: float
    y_mm: float
    segment: Segment
    method: str
    confidence: float
    t_mono: float
    slot_votes: tuple[SlotVote, ...] = field(default_factory=tuple)
    spread_mm: float = 0.0

    @property
    def coords(self) -> tuple[float, float]:
        """Autodarts-normalised Board coords (mm ÷ outer-double radius)."""
        return (self.x_mm / COORDS_NORM_RADIUS_MM, self.y_mm / COORDS_NORM_RADIUS_MM)

    @property
    def autodarts_segment_name(self) -> str:
        return str(autodarts_segment_fields(self.segment, self.x_mm, self.y_mm)["segmentName"])

    def to_autodarts_throw(self) -> dict[str, Any]:
        """Flat 2.1 ``throws[]`` element (ADR 0004)."""
        cx, cy = self.coords
        fields = autodarts_segment_fields(self.segment, self.x_mm, self.y_mm)
        return {
            "bed": fields["bed"],
            "bouncer": False,
            "coordsX": cx,
            "coordsY": cy,
            "failed": False,
            "method": self.method,
            "multiplier": fields["multiplier"],
            "segmentName": fields["segmentName"],
            "segmentNumber": fields["segmentNumber"],
        }

    def to_api(self) -> dict[str, Any]:
        out = self.to_autodarts_throw()
        out.update(
            {
                "madu": {
                    "segment": self.segment.name,
                    "xMm": round(self.x_mm, 2),
                    "yMm": round(self.y_mm, 2),
                    "confidence": round(self.confidence, 3),
                    "spreadMm": round(self.spread_mm, 2),
                    "tMono": self.t_mono,
                    "votes": [v.to_api() for v in self.slot_votes],
                }
            }
        )
        return out


__all__ = ["Hit", "SlotVote", "autodarts_segment_fields", "autodarts_segment_name"]
