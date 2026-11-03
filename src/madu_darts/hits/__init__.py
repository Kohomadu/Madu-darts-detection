"""Hit claiming: tips + multi-view fusion → Hit (classical, Autodarts-shaped).

External seam: ``claim_settled`` (live), ``recheck_hits`` (Recheck), ``resolve_manual``
(override). ``HitDetector`` is the live settle-window adapter. Tip and fuse helpers
remain importable for tests/migration but are internal seams of claiming.
"""

from madu_darts.hits.claiming import MANUAL_METHOD, claim_settled, hit_from_fusion, resolve_manual
from madu_darts.hits.config import FusionConfig, TipConfig
from madu_darts.hits.detector import HitDetector
from madu_darts.hits.fusion import (
    MAJORITY,
    SINGLE,
    UNANIMOUS,
    FusedPoint,
    fuse_points,
    occluded_slots,
    on_board,
)
from madu_darts.hits.hit import Hit, SlotVote, autodarts_segment_fields, autodarts_segment_name
from madu_darts.hits.recheck import (
    RECHECK_KEEP_PRIOR_JUMP_MM,
    RECHECK_METHOD,
    RECHECK_MIN_ELONGATION,
    RECHECK_MIN_TIP_CONFIDENCE,
    recheck_hits,
)
from madu_darts.hits.tip import (
    TipCandidate,
    dart_change_mask,
    locate_tip,
    locate_tips_vs_empty,
    tip_from_component_points,
)

__all__ = [
    # Claiming seam
    "MANUAL_METHOD",
    "RECHECK_METHOD",
    "Hit",
    "HitDetector",
    "SlotVote",
    "FusionConfig",
    "TipConfig",
    "claim_settled",
    "hit_from_fusion",
    "recheck_hits",
    "resolve_manual",
    # Autodarts projection (ADR 0004)
    "autodarts_segment_fields",
    "autodarts_segment_name",
    # Internal seams (tests / migration)
    "MAJORITY",
    "RECHECK_KEEP_PRIOR_JUMP_MM",
    "RECHECK_MIN_ELONGATION",
    "RECHECK_MIN_TIP_CONFIDENCE",
    "SINGLE",
    "UNANIMOUS",
    "FusedPoint",
    "TipCandidate",
    "dart_change_mask",
    "fuse_points",
    "locate_tip",
    "locate_tips_vs_empty",
    "occluded_slots",
    "on_board",
    "tip_from_component_points",
]
