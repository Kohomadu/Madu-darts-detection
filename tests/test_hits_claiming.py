"""Hit-claiming seam: live claim_settled, resolve_manual Segment rules."""

from __future__ import annotations

from madu_darts.board import point_mm_to_segment
from madu_darts.hits import (
    MANUAL_METHOD,
    UNANIMOUS,
    FusionConfig,
    TipCandidate,
    claim_settled,
    resolve_manual,
)


def _tip(slot: int, confidence: float = 0.9) -> TipCandidate:
    return TipCandidate(
        slot=slot,
        tip_px=(100.0 + slot, 200.0),
        flight_px=(100.0, 40.0),
        axis_dir=(0.0, 1.0),
        length_px=80.0,
        inlier_fraction=0.9,
        elongation=8.0,
        area_px=2000,
        confidence=confidence,
    )


def test_claim_settled_assigns_segment_and_unanimous_method() -> None:
    # Tight T20 cluster across three cams.
    points = {0: (0.0, 103.4), 1: (0.5, 103.0), 2: (-0.4, 103.6)}
    cands = {s: _tip(s) for s in points}
    hit = claim_settled(points, cands, fusion_config=FusionConfig(), t_mono=1.5)
    assert hit is not None
    assert hit.segment.name == point_mm_to_segment(0.0, 103.4).name
    assert hit.method == UNANIMOUS
    assert hit.t_mono == 1.5
    assert len(hit.slot_votes) == 3
    assert all(v.used for v in hit.slot_votes)


def test_resolve_manual_from_segment_name_and_board_mm() -> None:
    by_name = resolve_manual(segment_name="T20", t_mono=2.0)
    assert by_name.method == MANUAL_METHOD
    assert by_name.confidence == 1.0
    assert by_name.segment.name == "T20"
    assert by_name.slot_votes == ()

    prior = by_name
    by_mm = resolve_manual(x_mm=-3.56, y_mm=102.51, previous=prior, t_mono=3.0)
    assert by_mm.method == MANUAL_METHOD
    assert by_mm.segment.name == point_mm_to_segment(-3.56, 102.51).name
    assert by_mm.slot_votes == prior.slot_votes
