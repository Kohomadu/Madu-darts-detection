"""Tip localization + multi-view fusion → Hit (classical, Autodarts-shaped)."""

from madu_darts.hits.config import FusionConfig, TipConfig
from madu_darts.hits.detector import HitDetector
from madu_darts.hits.fusion import MAJORITY, SINGLE, UNANIMOUS, FusedPoint, fuse_points, on_board
from madu_darts.hits.hit import Hit, SlotVote, autodarts_segment_fields, autodarts_segment_name
from madu_darts.hits.recheck import RECHECK_METHOD, locate_tips_vs_empty, recheck_hits
from madu_darts.hits.tip import TipCandidate, dart_change_mask, locate_tip

__all__ = [
    "MAJORITY",
    "RECHECK_METHOD",
    "SINGLE",
    "UNANIMOUS",
    "FusedPoint",
    "FusionConfig",
    "Hit",
    "HitDetector",
    "SlotVote",
    "TipCandidate",
    "TipConfig",
    "autodarts_segment_fields",
    "autodarts_segment_name",
    "dart_change_mask",
    "fuse_points",
    "locate_tip",
    "locate_tips_vs_empty",
    "on_board",
    "recheck_hits",
]
