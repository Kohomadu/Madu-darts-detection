"""Tip localization on synthetic darts + fusion rules + Autodarts-shaped Hit fields."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from madu_darts.board import point_mm_to_segment
from madu_darts.calibration.homography import apply_homography
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits import (
    MAJORITY,
    SINGLE,
    UNANIMOUS,
    FusionConfig,
    Hit,
    TipConfig,
    autodarts_segment_fields,
    fuse_points,
    locate_tip,
    occluded_slots,
)

WHITE = (255, 255, 255)


def draw_dart(image: np.ndarray, tip_px: np.ndarray, *, length_px: float = 110.0, angle_deg: float = 0.0) -> np.ndarray:
    """Shaft from the tip toward image-up (flight away from the Board) + a flight blob."""
    out = image.copy()
    a = math.radians(angle_deg)
    direction = np.array([math.sin(a), -math.cos(a)])  # image-up with optional lean
    end = tip_px + direction * length_px
    cv2.line(out, tuple(np.round(tip_px).astype(int)), tuple(np.round(end).astype(int)), WHITE, 3, cv2.LINE_AA)
    flight = end + direction * 14.0
    cv2.ellipse(out, tuple(np.round(flight).astype(int)), (10, 18), angle_deg, 0, 360, WHITE, -1, cv2.LINE_AA)
    return out


def bbox_of_change(background: np.ndarray, frame: np.ndarray) -> tuple[int, int, int, int]:
    diff = cv2.absdiff(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.cvtColor(background, cv2.COLOR_BGR2GRAY))
    ys, xs = np.nonzero(diff > 16)
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


@pytest.mark.parametrize("pose", ["fronto", "tilt_left", "tilt_right"])
@pytest.mark.parametrize("target_mm", [(0.0, 103.4), (-60.0, 20.0), (120.0, -95.0)])
def test_locate_tip_recovers_tip_within_mm(pose: str, target_mm: tuple[float, float]) -> None:
    cam = synthetic_camera(pose)
    tip_px = cam.pixel_of_mm(*target_mm)
    frame = draw_dart(cam.image, tip_px, angle_deg=8.0)
    bbox = bbox_of_change(cam.image, frame)

    cand = locate_tip(cam.image, frame, bbox, slot=0, config=TipConfig())
    assert cand is not None
    assert math.hypot(cand.tip_px[0] - tip_px[0], cand.tip_px[1] - tip_px[1]) <= 4.0
    mm = apply_homography(cam.truth_homography, cand.tip_px)
    assert math.hypot(mm[0] - target_mm[0], mm[1] - target_mm[1]) <= 4.0
    assert point_mm_to_segment(*mm).name == point_mm_to_segment(*target_mm).name
    assert cand.length_px > 80 and cand.elongation > 4 and 0 < cand.confidence <= 1


def test_locate_tip_rejects_no_change_and_hand_like_blob() -> None:
    cam = synthetic_camera("fronto")
    assert locate_tip(cam.image, cam.image, (600, 300, 40, 40)) is None

    hand = cam.image.copy()
    cv2.circle(hand, (640, 360), 90, WHITE, -1)  # round blob: no dart axis
    assert locate_tip(cam.image, hand, bbox_of_change(cam.image, hand)) is None


def test_fuse_unanimous_majority_single() -> None:
    cfg = FusionConfig(agree_mm=15.0, mount_angles_deg={})
    close = {0: (10.0, 100.0), 1: (12.0, 103.0), 2: (9.0, 101.0)}
    fused = fuse_points(close, config=cfg)
    assert fused is not None and fused.method == UNANIMOUS and fused.used_slots == (0, 1, 2)
    assert abs(fused.x_mm - 31 / 3) < 1e-9 and abs(fused.y_mm - 304 / 3) < 1e-9

    outlier = {0: (10.0, 100.0), 1: (12.0, 103.0), 2: (90.0, -40.0)}
    fused = fuse_points(outlier, config=cfg)
    assert fused is not None and fused.method == MAJORITY and fused.used_slots == (0, 1) and fused.dropped_slots == (2,)

    scattered = {0: (10.0, 100.0), 1: (60.0, 10.0), 2: (-80.0, -40.0)}
    fused = fuse_points(scattered, {0: 0.2, 1: 0.9, 2: 0.5}, config=cfg)
    assert fused is not None and fused.method == SINGLE and fused.used_slots == (1,)

    two = {0: (10.0, 100.0), 2: (12.0, 103.0)}
    fused = fuse_points(two, config=cfg)
    assert fused is not None and fused.method == MAJORITY

    assert fuse_points({0: (1.0, 1.0)}, config=FusionConfig(min_cams=2)) is None
    one = fuse_points({1: (1.0, 1.0)}, config=cfg)
    assert one is not None and one.method == SINGLE and one.spread_mm == 0.0


def test_fuse_prefers_inside_double_when_cams_straddle_outer_wire() -> None:
    """Live 2026-11-02 V15/V17: mean just outside 170 called M; one cam alone was D."""
    cfg = FusionConfig(agree_mm=15.0)
    # V15 dart3: cam1 D6 (r≈168), cam0 M (r≈175) — spatial agree, bed disagree.
    v15 = {0: (172.87, -27.44), 1: (166.37, -21.58)}
    fused = fuse_points(v15, {0: 0.35, 1: 0.60}, config=cfg)
    assert fused is not None
    assert fused.used_slots == (1,)
    assert math.hypot(fused.x_mm, fused.y_mm) <= 170.0
    assert point_mm_to_segment(fused.x_mm, fused.y_mm).name == "D6"
    # V17 dart1: cam0 D18 (r≈170), cam1 just outside — prefer inside.
    v17 = {0: (105.42, 132.99), 1: (108.70, 132.88)}
    fused = fuse_points(v17, {0: 0.36, 1: 0.72}, config=cfg)
    assert fused is not None
    assert 0 in fused.used_slots and 1 not in fused.used_slots
    assert point_mm_to_segment(fused.x_mm, fused.y_mm).name == "D18"


def test_fuse_prefers_on_treble_when_cams_straddle_treble_wire() -> None:
    """Ticket 25: mean slides inside treble-inner → S; keep the on-treble cam(s)."""
    cfg = FusionConfig(agree_mm=15.0)
    # Cam0 on T20 mid-bed; cams 1+2 just inside treble-inner (Single) within agree_mm.
    # Scoring faces (ticket 21): treble ≈ 97.9–105.9; mid ≈ 101.9.
    points = {0: (0.0, 101.9), 1: (0.0, 94.0), 2: (1.0, 93.5)}
    mean_y = (101.9 + 94.0 + 93.5) / 3.0
    assert point_mm_to_segment(0.0, mean_y).bed != "Treble"
    fused = fuse_points(points, {0: 0.5, 1: 0.7, 2: 0.65}, config=cfg)
    assert fused is not None
    assert fused.used_slots == (0,)
    assert point_mm_to_segment(fused.x_mm, fused.y_mm).name == "T20"
    # Two on-treble vs one inside → Cam+1 on the treble pair.
    pair = {0: (0.0, 101.9), 1: (1.0, 103.0), 2: (0.0, 94.0)}
    fused2 = fuse_points(pair, config=cfg)
    assert fused2 is not None and fused2.used_slots == (0, 1)
    assert point_mm_to_segment(fused2.x_mm, fused2.y_mm).name == "T20"


def test_fuse_drops_warn_cam_when_two_pass_cams_agree() -> None:
    """Ticket 15: soft Calibration must not veto a tight Cam+1 pair."""
    cfg = FusionConfig(agree_mm=15.0, prefer_pass_cams=True)
    # Cams 1+2 agree on T20; cam0 (warn) pulls into the outer single (not a treble-wire straddle).
    points = {0: (8.0, 120.0), 1: (0.0, 103.0), 2: (1.0, 104.0)}
    fused = fuse_points(points, config=cfg, fit_ok={0: False, 1: True, 2: True})
    assert fused is not None
    assert fused.method == MAJORITY
    assert fused.used_slots == (1, 2)
    assert fused.dropped_slots == (0,)
    # When all three are healthy and agree → UnanimousCam unchanged.
    tight = {0: (0.0, 103.0), 1: (1.0, 104.0), 2: (-1.0, 102.5)}
    uni = fuse_points(tight, config=cfg, fit_ok={0: True, 1: True, 2: True})
    assert uni is not None and uni.method == UNANIMOUS and uni.used_slots == (0, 1, 2)
    # Without fit_ok, a soft third cam that still spatially agrees is kept (no treble straddle).
    loose_pts = {0: (2.0, 105.0), 1: (0.0, 103.0), 2: (1.0, 104.0)}
    loose = fuse_points(loose_pts, config=cfg, fit_ok=None)
    assert loose is not None and 0 in loose.used_slots and loose.method == UNANIMOUS


def test_fuse_rejects_off_board_arm_tips() -> None:
    """Ticket 14: tips at r ≫ double-outer must not become BestCam Hits."""
    cfg = FusionConfig(agree_mm=15.0, max_hit_radius_mm=200.0)
    # Live V3/V4 style: single-cam points hundreds of mm out.
    assert fuse_points({0: (-550.0, 4.9)}, config=cfg) is None
    assert fuse_points({0: (-391.0, -155.0), 1: (-640.0, -375.0), 2: (-431.0, -241.0)}, config=cfg) is None
    # One on-Board tip among off-Board junk → BestCam on the good cam only.
    mixed = {0: (-500.0, 0.0), 1: (0.0, 103.4), 2: (400.0, 200.0)}
    fused = fuse_points(mixed, {0: 0.9, 1: 0.5, 2: 0.8}, config=cfg)
    assert fused is not None and fused.used_slots == (1,) and fused.method == SINGLE
    assert math.hypot(fused.x_mm, fused.y_mm) <= 200.0
    # Just outside the double (real miss) still allowed.
    near = fuse_points({0: (-23.8, 173.4)}, config=cfg)
    assert near is not None and math.hypot(near.x_mm, near.y_mm) < 200.0


def test_fuse_drops_occluded_cam_when_peers_remain() -> None:
    """Ticket 24: cam locked on dart 1 must not pull dart 2 across a sector wire."""
    from madu_darts.calibration.homography import polar_mm

    cfg = FusionConfig(agree_mm=15.0)
    # Cam 0 still on the S20 side of the 20|1 wire; cams 1+2 see the new dart on S1.
    # Within agree_mm the classical mean flips to T20; dropping cam 0 keeps T1.
    points = {0: polar_mm(100.0, 5.0), 1: polar_mm(100.0, 10.0), 2: polar_mm(100.0, 11.0)}
    classical = fuse_points(points, {0: 0.95, 1: 0.5, 2: 0.5}, config=cfg)
    assert classical is not None
    assert point_mm_to_segment(classical.x_mm, classical.y_mm).name == "T20"
    fused = fuse_points(points, {0: 0.95, 1: 0.5, 2: 0.5}, config=cfg, occluded={0})
    assert fused is not None
    assert 0 not in fused.used_slots
    assert fused.occluded_slots == (0,)
    assert point_mm_to_segment(fused.x_mm, fused.y_mm).name == "T1"
    # All cams "occluded" (clustered real darts) → keep classical pool.
    all_near = {0: (0.0, 103.0), 1: (1.0, 104.0), 2: (-1.0, 102.5)}
    kept = fuse_points(all_near, config=cfg, occluded={0, 1, 2})
    assert kept is not None and kept.method == UNANIMOUS and kept.used_slots == (0, 1, 2)


def test_fuse_soft_tie_weights_near_mount_cam() -> None:
    """Soft multi-cam spread: weight toward the cam whose mount faces the tip."""
    from madu_darts.calibration.homography import polar_mm

    # Tip near sector 20 (cam0 mount). Soft spread across cams (still within agree_mm).
    points = {
        0: polar_mm(103.0, 0.0),
        1: polar_mm(103.0, 4.0),
        2: polar_mm(103.0, -4.0),
    }
    plain = fuse_points(points, config=FusionConfig(agree_mm=20.0, mount_angles_deg={}, soft_tie_spread_mm=0.5))
    weighted = fuse_points(
        points,
        config=FusionConfig(
            agree_mm=20.0,
            mount_angles_deg={0: 0.0, 1: 234.0, 2: 126.0},
            soft_tie_spread_mm=0.5,
        ),
    )
    assert plain is not None and weighted is not None
    assert plain.method == UNANIMOUS and weighted.method == UNANIMOUS
    # Near-weighted centre should sit closer to cam0's tip than the plain mean.
    assert abs(weighted.x_mm - points[0][0]) + abs(weighted.y_mm - points[0][1]) < abs(
        plain.x_mm - points[0][0]
    ) + abs(plain.y_mm - points[0][1])


def test_occluded_slots_from_footprint_and_prior_tip() -> None:
    tips_px = {0: (100.0, 200.0), 1: (500.0, 400.0), 2: (510.0, 405.0)}
    tips_mm = {0: (-36.0, -97.0), 1: (0.0, 103.4), 2: (1.0, 102.0)}
    # Prior dart footprint only on cam 0; tip sits inside it.
    footprints = [{0: (80, 180, 40, 40), 1: (10, 10, 20, 20)}]
    marked = occluded_slots(
        tips_px,
        tips_mm,
        prior_footprints=footprints,
        prior_tips_mm=[(-36.0, -97.0)],
        bbox_pad_px=8.0,
        tip_radius_mm=8.0,
    )
    assert 0 in marked
    assert 1 not in marked and 2 not in marked

    # Board-mm rule alone: cam 0 on prior tip, peers on a new tip → cam 0 occluded.
    marked_mm = occluded_slots(
        {0: (0.0, 0.0), 1: (0.0, 0.0), 2: (0.0, 0.0)},
        tips_mm,
        prior_footprints=[],
        prior_tips_mm=[(-36.0, -97.0)],
        tip_radius_mm=8.0,
    )
    assert marked_mm == frozenset({0})


def test_autodarts_segment_fields_match_live_vocabulary() -> None:
    # From the 07 recording: ('25','Single',25,1), ('T19','Triple',19,3), ('M20','Outside',20,0), ('D13','Double',13,2)
    ob = autodarts_segment_fields(point_mm_to_segment(-10.0, -6.0), -10.0, -6.0)
    assert ob == {"segmentName": "25", "segmentNumber": 25, "multiplier": 1, "bed": "Single"}
    t19 = autodarts_segment_fields(point_mm_to_segment(-36.0, -97.0), -36.0, -97.0)
    assert t19 == {"segmentName": "T19", "segmentNumber": 19, "multiplier": 3, "bed": "Triple"}
    miss = autodarts_segment_fields(point_mm_to_segment(-23.8, 173.4), -23.8, 173.4)
    assert miss == {"segmentName": "M20", "segmentNumber": 20, "multiplier": 0, "bed": "Outside"}
    d13 = autodarts_segment_fields(point_mm_to_segment(154.3, 63.6), 154.3, 63.6)
    assert d13 == {"segmentName": "D13", "segmentNumber": 13, "multiplier": 2, "bed": "Double"}
    s1_outer = autodarts_segment_fields(point_mm_to_segment(22.2, 91.3), 22.2, 91.3)
    assert s1_outer["bed"] == "SingleInner" and s1_outer["segmentName"] == "S1"


def test_hit_projects_to_autodarts_throw_shape() -> None:
    hit = Hit(x_mm=-3.56, y_mm=102.51, segment=point_mm_to_segment(-3.56, 102.51), method=UNANIMOUS, confidence=0.7, t_mono=1.0)
    throw = hit.to_autodarts_throw()
    assert set(throw) == {"bed", "bouncer", "coordsX", "coordsY", "failed", "method", "multiplier", "segmentName", "segmentNumber"}
    assert throw["segmentName"] == "T20" and throw["bed"] == "Triple" and throw["multiplier"] == 3
    assert throw["coordsX"] == pytest.approx(-3.56 / 170.0) and throw["coordsY"] == pytest.approx(102.51 / 170.0)
    assert throw["bouncer"] is False and throw["failed"] is False and throw["method"] == "UnanimousCam"
    assert hit.to_api()["madu"]["segment"] == "T20"
