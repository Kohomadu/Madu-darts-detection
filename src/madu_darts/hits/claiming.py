"""Hit claiming: one external seam for live settle, Recheck, and Manual override.

Tip localization and fusion stay as internal seams; callers learn this module
(and ``Hit`` / configs) rather than reassembling tip → fuse → Segment.
"""

from __future__ import annotations

from madu_darts.board.geometry import point_mm_to_segment, segment_name_to_mm
from madu_darts.hits.config import FusionConfig
from madu_darts.hits.fusion import FusedPoint, fuse_points
from madu_darts.hits.hit import Hit, SlotVote
from madu_darts.hits.tip import TipCandidate

MANUAL_METHOD = "Manual"


def hit_from_fusion(
    fused: FusedPoint,
    candidates: dict[int, TipCandidate],
    points_mm: dict[int, tuple[float, float]],
    *,
    t_mono: float,
    method: str | None = None,
    confidence_scale_if_not_unanimous: float = 1.0,
) -> Hit:
    """Assign Segment and build a Hit from a fused Board-plane point + per-cam tips."""
    votes = tuple(
        SlotVote(
            slot=s,
            tip=candidates[s],
            x_mm=points_mm[s][0],
            y_mm=points_mm[s][1],
            used=s in fused.used_slots,
        )
        for s in sorted(candidates)
    )
    used_conf = [candidates[s].confidence for s in fused.used_slots if s in candidates]
    confidence = float(sum(used_conf) / len(used_conf)) if used_conf else 0.0
    resolved_method = method if method is not None else fused.method
    if fused.method != "UnanimousCam" and confidence_scale_if_not_unanimous != 1.0:
        confidence *= float(confidence_scale_if_not_unanimous)
    segment = point_mm_to_segment(fused.x_mm, fused.y_mm)
    return Hit(
        x_mm=fused.x_mm,
        y_mm=fused.y_mm,
        segment=segment,
        method=resolved_method,
        confidence=confidence,
        t_mono=float(t_mono),
        slot_votes=votes,
        spread_mm=fused.spread_mm,
        occluded_slots=fused.occluded_slots,
    )


def claim_settled(
    points_mm: dict[int, tuple[float, float]],
    candidates: dict[int, TipCandidate],
    *,
    fusion_config: FusionConfig | None = None,
    fit_ok: dict[int, bool] | None = None,
    occluded: frozenset[int] | set[int] | None = None,
    t_mono: float = 0.0,
) -> Hit | None:
    """Live entry after settle-window tip collect: fuse → Segment → Hit (at most one)."""
    if not points_mm or not candidates:
        return None
    fusion = fusion_config or FusionConfig()
    fused = fuse_points(
        points_mm,
        {s: c.confidence for s, c in candidates.items()},
        fusion,
        fit_ok=fit_ok,
        occluded=occluded,
    )
    if fused is None:
        return None
    return hit_from_fusion(
        fused,
        candidates,
        points_mm,
        t_mono=t_mono,
        confidence_scale_if_not_unanimous=0.8,
    )


def resolve_manual(
    *,
    x_mm: float | None = None,
    y_mm: float | None = None,
    segment_name: str | None = None,
    previous: Hit | None = None,
    t_mono: float = 0.0,
) -> Hit:
    """Override entry: Board-mm or segmentName → Manual Hit (no tip find).

    Preserves ``previous.slot_votes`` when provided so history still shows cam votes.
    """
    if x_mm is not None and y_mm is not None:
        resolved_x, resolved_y = float(x_mm), float(y_mm)
    elif segment_name:
        resolved_x, resolved_y = segment_name_to_mm(str(segment_name))
    else:
        raise ValueError("resolve_manual needs segment_name or x_mm+y_mm")
    segment = point_mm_to_segment(resolved_x, resolved_y)
    return Hit(
        x_mm=resolved_x,
        y_mm=resolved_y,
        segment=segment,
        method=MANUAL_METHOD,
        confidence=1.0,
        t_mono=float(t_mono),
        slot_votes=previous.slot_votes if previous is not None else (),
        spread_mm=0.0,
    )


__all__ = [
    "MANUAL_METHOD",
    "claim_settled",
    "hit_from_fusion",
    "resolve_manual",
]
