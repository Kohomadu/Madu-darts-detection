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
    cfg = FusionConfig(agree_mm=15.0)
    close = {0: (10.0, 100.0), 1: (12.0, 103.0), 2: (9.0, 98.0)}
    fused = fuse_points(close, config=cfg)
    assert fused is not None and fused.method == UNANIMOUS and fused.used_slots == (0, 1, 2)
    assert abs(fused.x_mm - 31 / 3) < 1e-9 and abs(fused.y_mm - 301 / 3) < 1e-9

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
