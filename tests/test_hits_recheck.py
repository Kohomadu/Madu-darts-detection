"""Vision Recheck (ticket 17) + manual Hit override helpers (ticket 18)."""

from __future__ import annotations

import math

import numpy as np

from madu_darts.board import point_mm_to_segment, segment_name_to_mm
from madu_darts.calibration.homography import apply_homography
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits import (
    RECHECK_METHOD,
    FusionConfig,
    Hit,
    TipConfig,
    locate_tips_vs_empty,
    recheck_hits,
    resolve_manual,
)
from madu_darts.hits.recheck import _merge_keeping_strong_priors, _should_keep_previous
from madu_darts.hits.tip import TipCandidate
from madu_darts.hits.hit import SlotVote
from madu_darts.turn import TurnEvent, TurnStatus
from tests.test_hits_tip_fusion import draw_dart
from tests.test_turn_controller import CAMS, Sim, T20, S6, S11


def _board_point(slot: int, px: tuple[float, float]) -> np.ndarray:
    return apply_homography(CAMS[slot].truth_homography, px)


def _fake_tip(*, slot: int = 0, confidence: float = 0.5, elongation: float = 8.0) -> TipCandidate:
    return TipCandidate(
        slot=slot,
        tip_px=(100.0, 100.0),
        flight_px=(100.0, 40.0),
        axis_dir=(0.0, 1.0),
        length_px=60.0,
        inlier_fraction=0.8,
        elongation=elongation,
        area_px=2000,
        confidence=confidence,
    )


def _fake_hit(
    x_mm: float,
    y_mm: float,
    *,
    method: str = "UnanimousCam",
    confidence: float = 0.9,
    used_cams: tuple[int, ...] = (0, 1),
) -> Hit:
    votes = tuple(
        SlotVote(
            slot=s,
            tip=_fake_tip(slot=s, confidence=confidence),
            x_mm=x_mm,
            y_mm=y_mm,
            used=True,
        )
        for s in used_cams
    )
    return Hit(
        x_mm=x_mm,
        y_mm=y_mm,
        segment=point_mm_to_segment(x_mm, y_mm),
        method=method,
        confidence=confidence,
        t_mono=0.0,
        slot_votes=votes,
        spread_mm=1.0,
    )


def test_locate_tips_vs_empty_finds_three_darts() -> None:
    cam = CAMS[0]
    targets = [T20, S11, S6]
    frame = cam.image
    for t in targets:
        frame = draw_dart(frame, cam.pixel_of_mm(*t), angle_deg=5.0)
    tips = locate_tips_vs_empty(cam.image, frame, max_darts=3, slot=0, config=TipConfig())
    assert len(tips) == 3
    recovered = []
    for tip in tips:
        mm = apply_homography(cam.truth_homography, tip.tip_px)
        recovered.append(point_mm_to_segment(float(mm[0]), float(mm[1])).name)
    assert set(recovered) == {point_mm_to_segment(*t).name for t in targets}


def test_recheck_restores_wrong_first_hit() -> None:
    """Three stuck darts; first Hit deliberately wrong → Recheck restores Segments."""
    targets = [T20, S11, S6]
    empty = {s: c.image for s, c in CAMS.items()}
    stuck = {}
    for slot, cam in CAMS.items():
        img = cam.image
        for t in targets:
            img = draw_dart(img, cam.pixel_of_mm(*t), angle_deg=5.0)
        stuck[slot] = img

    # Wrong first Hit (claim D16 near where nothing is); keep last two roughly right.
    wrong = [
        _fake_hit(-135.0, -98.0),  # D16 — wrong
        _fake_hit(*S11),
        _fake_hit(*S6),
    ]
    assert wrong[0].segment.name == "D16"

    corrected = recheck_hits(
        stuck,
        empty,
        tuple(wrong),
        _board_point,
        tip_config=TipConfig(),
        fusion_config=FusionConfig(),
        fit_ok={0: True, 1: True, 2: True},
        t_mono=1.0,
    )
    assert len(corrected) == 3
    names = [h.segment.name for h in corrected]
    assert "T20" in names
    assert "D16" not in names
    assert set(names) == {point_mm_to_segment(*t).name for t in targets}
    assert any(h.method == RECHECK_METHOD or h.method.startswith("Cam") or h.method == "UnanimousCam" for h in corrected)


def test_replace_hits_emits_recheck_and_keeps_cardinality() -> None:
    sim = Sim()
    sim.throw([T20])
    assert len(sim.ctrl.hits) == 1
    frames = sim.frames([T20, S11])
    new = [_fake_hit(*T20, method=RECHECK_METHOD), _fake_hit(*S11, method=RECHECK_METHOD)]
    tr = sim.ctrl.replace_hits(new, frames, sim.t + 0.1)
    assert tr.event == TurnEvent.RECHECK
    assert tr.status == TurnStatus.THROW
    assert len(sim.ctrl.hits) == 2
    assert [h.segment.name for h in sim.ctrl.hits] == [
        point_mm_to_segment(*T20).name,
        point_mm_to_segment(*S11).name,
    ]


def test_override_hit_sets_manual_method() -> None:
    sim = Sim()
    sim.throw([T20])
    prior = sim.ctrl.hits[0]
    hit = resolve_manual(segment_name="D20", previous=prior, t_mono=sim.t)
    tr = sim.ctrl.override_hit(0, hit, sim.t + 0.1)
    assert tr.event == TurnEvent.OVERRIDE
    assert sim.ctrl.hits[0].method == "Manual"
    assert sim.ctrl.hits[0].segment.name == "D20"
    assert sim.ctrl.hits[0].autodarts_segment_name == "D20"
    assert sim.ctrl.hits[0].slot_votes == prior.slot_votes


def test_recheck_tip_fork_deleted() -> None:
    """Recheck must not own a second tip-from-component-points implementation."""
    from pathlib import Path

    import madu_darts.hits.recheck as recheck_mod
    import madu_darts.hits.tip as tip_mod

    assert not hasattr(recheck_mod, "_tip_from_component_points")
    assert not hasattr(recheck_mod, "tip_from_component_points")
    assert hasattr(tip_mod, "tip_from_component_points")
    source = Path(recheck_mod.__file__).read_text(encoding="utf-8")
    assert "cv2.fitLine" not in source
    assert "locate_tips_vs_empty" in source


def test_segment_name_to_mm_roundtrip_beds() -> None:
    for name in ("T20", "D16", "S11", "Bull", "25", "IB", "OB"):
        x, y = segment_name_to_mm(name)
        seg = point_mm_to_segment(x, y)
        if name in ("Bull", "IB"):
            assert seg.name == "IB"
        elif name in ("25", "OB"):
            assert seg.name == "OB"
        else:
            assert seg.name == name
        assert math.hypot(x, y) < 180.0 or name.startswith("M")


def test_recheck_keeps_prior_over_miss_stub() -> None:
    """Board visit #6: BestCam Miss (flight stub) must not overwrite an on-Board Hit."""
    prior = _fake_hit(-91.07, -31.23, method="Cam+1", confidence=0.414)  # S8
    assert prior.segment.bed != "Miss"
    stub = _fake_hit(-117.41, -138.88, method="BestCam", confidence=0.247, used_cams=(0,))  # M7
    assert stub.segment.bed == "Miss"
    assert _should_keep_previous(prior, stub)
    merged = _merge_keeping_strong_priors([stub], (prior,))
    assert merged[0] is prior


def test_recheck_keeps_prior_over_far_weak_bestcam() -> None:
    """Mid-board garbage BestCam far from T1 must not replace it."""
    prior = _fake_hit(37.78, 96.95, method="UnanimousCam", confidence=0.532, used_cams=(0, 1, 2))
    junk = _fake_hit(3.29, 65.04, method="BestCam", confidence=0.225, used_cams=(1,))
    assert _should_keep_previous(prior, junk)
    merged = _merge_keeping_strong_priors([junk], (prior,))
    assert merged[0].segment.name == prior.segment.name


def test_recheck_allows_nearby_bed_correction() -> None:
    """S8 → T8 at the same tip (cam0) with decent conf should replace the prior."""
    prior = _fake_hit(-91.07, -31.23, method="Cam+1", confidence=0.414)
    better = _fake_hit(-95.17, -33.89, method="BestCam", confidence=0.523, used_cams=(0,))
    assert prior.segment.name == "S8"
    assert better.segment.name == "T8"
    assert not _should_keep_previous(prior, better)
    merged = _merge_keeping_strong_priors([better], (prior,))
    assert merged[0].segment.name == "T8"


def test_recheck_allows_far_correction_when_multi_cam() -> None:
    """Wrong D16 prior can still be replaced by a strong multi-cam T20 far away."""
    prior = _fake_hit(-135.0, -98.0, method="BestCam", confidence=0.9, used_cams=(0,))
    corrected = _fake_hit(*T20, method=RECHECK_METHOD, confidence=0.55, used_cams=(0, 1, 2))
    assert not _should_keep_previous(prior, corrected)
