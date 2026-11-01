"""Image <-> Board mm mapping, RANSAC fit, ring projection, and rotate-20 on synthetic cams."""

from __future__ import annotations

import numpy as np
import pytest
from madu_darts.calibration.synthetic import CANON_MM_PER_PX, POSES, render_board, synthetic_camera

from madu_darts.board import DOUBLE_OUTER_MM, TREBLE_OUTER_MM, point_mm_to_segment
from madu_darts.calibration import (
    CamCalibration,
    FitStatus,
    apply_homography,
    board_mm_to_image,
    effective_homography,
    fit_homography,
    image_to_board_mm,
    polar_mm,
    reprojection_rms_mm,
    ring_points_mm,
    rings_from_homography,
    rotation_mm,
    wire_angles_deg,
    wire_ring_intersections_mm,
)

T20_MM = (0.0, (99.4 + 107.4) / 2.0)  # centre of the treble-20 bed


# --- rotation / basic algebra ---


def test_rotation_zero_and_full_turn_are_identity() -> None:
    np.testing.assert_allclose(rotation_mm(0), np.eye(3), atol=1e-12)
    np.testing.assert_allclose(rotation_mm(20), np.eye(3), atol=1e-12)


def test_rotation_is_clockwise_with_y_up() -> None:
    # 5 sectors = 90° clockwise: top (20) -> right (6).
    out = apply_homography(rotation_mm(5), (0.0, 1.0))
    np.testing.assert_allclose(out, (1.0, 0.0), atol=1e-12)


def test_apply_homography_preserves_rank() -> None:
    assert apply_homography(np.eye(3), (1.0, 2.0)).shape == (2,)
    assert apply_homography(np.eye(3), [(1.0, 2.0), (3.0, 4.0)]).shape == (2, 2)


def test_apply_homography_rejects_points_at_infinity() -> None:
    h = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    with pytest.raises(ValueError):
        apply_homography(h, (0.0, 1.0))


def test_effective_homography_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        effective_homography(np.eye(2), 0)


def test_wire_angles_and_ring_points() -> None:
    angles = wire_angles_deg()
    assert len(angles) == 20
    assert angles[0] == 9.0 and angles[-1] == pytest.approx(351.0)
    ring = ring_points_mm(170.0, n=4)
    np.testing.assert_allclose(ring, [(0, 170), (170, 0), (0, -170), (-170, 0)], atol=1e-9)
    assert wire_ring_intersections_mm().shape == (40, 2)
    np.testing.assert_allclose(polar_mm(10.0, 90.0), (10.0, 0.0), atol=1e-12)


# --- round trips on synthetic cameras ---


@pytest.mark.parametrize("pose", sorted(POSES))
def test_image_board_round_trip(pose: str) -> None:
    cam = synthetic_camera(pose)
    rng = np.random.default_rng(1)
    mm = rng.uniform(-170.0, 170.0, size=(50, 2))
    px = board_mm_to_image(cam.truth_homography, 0, mm)
    back = image_to_board_mm(cam.truth_homography, 0, px)
    np.testing.assert_allclose(back, mm, atol=1e-6)


@pytest.mark.parametrize("pose", sorted(POSES))
def test_fit_homography_recovers_truth_from_wire_ring_points(pose: str) -> None:
    cam = synthetic_camera(pose)
    mm = wire_ring_intersections_mm()
    px = board_mm_to_image(cam.truth_homography, 0, mm)

    h, inliers = fit_homography(px, mm)
    assert inliers.all()
    assert reprojection_rms_mm(h, 0, px, mm) < 1e-3


def test_fit_homography_ransac_rejects_outliers() -> None:
    cam = synthetic_camera("tilt_top")
    mm = wire_ring_intersections_mm()
    px = board_mm_to_image(cam.truth_homography, 0, mm)
    px_noisy = px.copy()
    px_noisy[[3, 17, 29]] += (60.0, -45.0)  # gross mis-detections

    h, inliers = fit_homography(px_noisy, mm, ransac_threshold_mm=2.0)
    assert not inliers[[3, 17, 29]].any()
    assert inliers.sum() == len(mm) - 3
    assert reprojection_rms_mm(h, 0, px[inliers], mm[inliers]) < 1e-2


def test_fit_homography_input_validation() -> None:
    with pytest.raises(ValueError):
        fit_homography([(0, 0), (1, 0), (1, 1)], [(0, 0), (1, 0), (1, 1)])
    with pytest.raises(ValueError):
        fit_homography([(0, 0), (1, 0), (1, 1), (0, 1)], [(0, 0), (1, 0), (1, 1)])


def test_reprojection_rms_matches_known_perturbation() -> None:
    h = np.diag([1.0, 1.0, 1.0])
    px = np.array([(0.0, 0.0), (10.0, 0.0)])
    mm = px + np.array([(3.0, 4.0), (0.0, 0.0)])  # errors 5 and 0 -> RMS sqrt(12.5)
    assert reprojection_rms_mm(h, 0, px, mm) == pytest.approx(np.sqrt(12.5))


def test_rings_from_homography_fronto_are_circles_at_bull() -> None:
    cam = synthetic_camera("fronto")
    rings = rings_from_homography(cam.truth_homography)

    bull_px = cam.pixel_of_mm(0.0, 0.0)
    np.testing.assert_allclose(rings.bull, bull_px, atol=1e-6)

    # Fronto pose is a pure scale: canonical 800 px -> 640 px wide.
    scale_px_per_mm = (640.0 / 799.0) / CANON_MM_PER_PX
    for ellipse, radius in (
        (rings.double_outer, DOUBLE_OUTER_MM),
        (rings.treble_outer, TREBLE_OUTER_MM),
    ):
        np.testing.assert_allclose((ellipse.cx, ellipse.cy), bull_px, atol=0.05)
        assert ellipse.width == pytest.approx(2 * radius * scale_px_per_mm, rel=1e-3)
        assert ellipse.height == pytest.approx(2 * radius * scale_px_per_mm, rel=1e-3)


def test_rings_from_homography_tilted_are_eccentric_but_concentric_ordered() -> None:
    cam = synthetic_camera("tilt_top")
    rings = rings_from_homography(cam.truth_homography)
    assert abs(rings.double_outer.width - rings.double_outer.height) > 10.0
    assert max(rings.double_outer.width, rings.double_outer.height) > max(
        rings.double_inner.width, rings.double_inner.height
    )
    assert max(rings.treble_outer.width, rings.treble_outer.height) > max(
        rings.treble_inner.width, rings.treble_inner.height
    )


# --- rotate-20 semantics (Autodarts arrows) ---


@pytest.mark.parametrize("rotation_sectors", [0, 1, 3, 7, 10, 19])
@pytest.mark.parametrize("pose", ["fronto", "tilt_left"])
def test_correct_offset_maps_physical_t20_to_t20(pose: str, rotation_sectors: int) -> None:
    cam = synthetic_camera(pose, rotation_sectors=rotation_sectors)
    t20_px = cam.pixel_of_mm(*T20_MM)

    cal = CamCalibration(slot=0, homography=cam.raw_homography, rotate_offset=cam.correct_offset, rms_mm=0.1)
    mm = image_to_board_mm(cal.homography, cal.rotate_offset, t20_px)
    np.testing.assert_allclose(mm, T20_MM, atol=1e-6)
    assert point_mm_to_segment(*mm).name == "T20"
    assert cal.status is FitStatus.PASS


def test_rotate_left_moves_label_to_next_clockwise_sector() -> None:
    """After rotate-left, the physical 20 wedge is read one sector clockwise (as 1)."""
    cam = synthetic_camera("fronto", rotation_sectors=4)
    t20_px = cam.pixel_of_mm(*T20_MM)
    cal = CamCalibration(slot=0, homography=cam.raw_homography, rotate_offset=cam.correct_offset)

    assert point_mm_to_segment(*image_to_board_mm(cal.homography, cal.rotate_offset, t20_px)).name == "T20"

    left = cal.rotate_left()
    assert point_mm_to_segment(*image_to_board_mm(left.homography, left.rotate_offset, t20_px)).name == "T1"

    right = cal.rotate_right()
    assert point_mm_to_segment(*image_to_board_mm(right.homography, right.rotate_offset, t20_px)).name == "T5"


def test_rotate_left_moves_twenty_highlight_counter_clockwise_in_image() -> None:
    """The 20 wedge drawn via the inverse map must move CCW on screen on rotate-left."""
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.raw_homography, rotate_offset=0)
    bull = cam.pixel_of_mm(0.0, 0.0)

    def highlight_angle(c: CamCalibration) -> float:
        p = board_mm_to_image(c.homography, c.rotate_offset, T20_MM) - bull
        # Image y is down; convert to math angle (CCW positive) in degrees.
        return float(np.degrees(np.arctan2(-p[1], p[0])))

    before = highlight_angle(cal)
    after = highlight_angle(cal.rotate_left())
    delta = (after - before + 180.0) % 360.0 - 180.0
    assert delta == pytest.approx(18.0, abs=1e-6)


def test_wrong_offset_fails_segment_but_round_trip_still_consistent() -> None:
    cam = synthetic_camera("tilt_right", rotation_sectors=2)
    d20_px = cam.pixel_of_mm(*polar_mm(166.0, 0.0))  # physical D20 bed

    good = CamCalibration(slot=2, homography=cam.raw_homography, rotate_offset=cam.correct_offset)
    bad = good.rotated(1)
    assert point_mm_to_segment(*image_to_board_mm(good.homography, good.rotate_offset, d20_px)).name == "D20"
    assert point_mm_to_segment(*image_to_board_mm(bad.homography, bad.rotate_offset, d20_px)).name == "D1"


# --- renderer sanity (reused by auto-fit tests later) ---


def test_render_board_has_expected_colours_at_bull_and_sectors() -> None:
    img = render_board()
    assert img.shape == (800, 800, 3)
    c = (800 - 1) / 2.0
    bull = img[int(round(c)), int(round(c))]
    assert bull[2] > 150 and bull[1] < 100  # red inner bull (BGR)

    # Sector 20 single bed is dark; sector 1 (clockwise neighbour) is light.
    s20 = img[int(round(c - 60.0 / CANON_MM_PER_PX)), int(round(c))]
    x1, y1 = polar_mm(60.0, 18.0)
    s1 = img[int(round(c - y1 / CANON_MM_PER_PX)), int(round(c + x1 / CANON_MM_PER_PX))]
    assert s20.max() < 60
    assert s1.min() > 150


def test_synthetic_camera_frame_shape_and_board_visible() -> None:
    cam = synthetic_camera("tilt_left", rotation_sectors=5)
    assert cam.image.shape == (720, 1280, 3)
    bull = cam.pixel_of_mm(0.0, 0.0)
    assert 0 <= bull[0] < 1280 and 0 <= bull[1] < 720
    px = cam.image[int(round(bull[1])), int(round(bull[0]))]
    assert px[2] > 120  # red bull survives warp
