"""Vision Recheck (ticket 17) + manual Hit override helpers (ticket 18)."""

from __future__ import annotations

import math

import numpy as np

from madu_darts.board import point_mm_to_segment, segment_name_to_mm
from madu_darts.calibration.homography import apply_homography
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits import RECHECK_METHOD, FusionConfig, Hit, TipConfig, locate_tips_vs_empty, recheck_hits
from madu_darts.turn import TurnEvent, TurnStatus
from tests.test_hits_tip_fusion import draw_dart
from tests.test_turn_controller import CAMS, Sim, T20, S6, S11


def _board_point(slot: int, px: tuple[float, float]) -> np.ndarray:
    return apply_homography(CAMS[slot].truth_homography, px)


def _fake_hit(x_mm: float, y_mm: float, *, method: str = "UnanimousCam") -> Hit:
    return Hit(
        x_mm=x_mm,
        y_mm=y_mm,
        segment=point_mm_to_segment(x_mm, y_mm),
        method=method,
        confidence=0.9,
        t_mono=0.0,
        slot_votes=(),
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
    x_mm, y_mm = segment_name_to_mm("D20")
    hit = Hit(
        x_mm=x_mm,
        y_mm=y_mm,
        segment=point_mm_to_segment(x_mm, y_mm),
        method="Manual",
        confidence=1.0,
        t_mono=sim.t,
    )
    tr = sim.ctrl.override_hit(0, hit, sim.t + 0.1)
    assert tr.event == TurnEvent.OVERRIDE
    assert sim.ctrl.hits[0].method == "Manual"
    assert sim.ctrl.hits[0].segment.name == "D20"
    assert sim.ctrl.hits[0].autodarts_segment_name == "D20"


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
