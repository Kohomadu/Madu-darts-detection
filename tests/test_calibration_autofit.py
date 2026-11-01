"""Auto-fit on synthetic cameras: rings, wires, suggested 20, homography quality, failures."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from madu_darts.calibration.synthetic import POSES, SyntheticCamera, synthetic_camera

from madu_darts.board import DOUBLE_OUTER_MM, point_mm_to_segment
from madu_darts.calibration import (
    AutoFitError,
    AutoFitParams,
    Ellipse,
    FitStatus,
    board_mm_to_image,
    colour_masks,
    detect_rings,
    detect_wire_points,
    image_to_board_mm,
    ray_ellipse_intersections,
    rings_from_homography,
    suggest,
)

T20_MM = (0.0, 103.4)
GRID_MM = np.array(
    [(x, y) for x in range(-160, 161, 40) for y in range(-160, 161, 40) if x * x + y * y <= 165**2],
    dtype=np.float64,
)


def _grid_rms(cam: SyntheticCamera, homography: np.ndarray, offset: int) -> float:
    px = board_mm_to_image(cam.truth_homography, 0, GRID_MM)
    mm = image_to_board_mm(homography, offset, px)
    return float(np.sqrt(np.mean(np.sum((mm - GRID_MM) ** 2, axis=1))))


def _best_offset(cam: SyntheticCamera, homography: np.ndarray) -> tuple[int, float]:
    scored = [(_grid_rms(cam, homography, d), d) for d in range(20)]
    rms, offset = min(scored)
    return offset, rms


# --- building blocks ---


def test_colour_masks_pick_up_bull_and_bands() -> None:
    cam = synthetic_camera("fronto")
    red, green = colour_masks(cam.image)
    bull = cam.pixel_of_mm(0.0, 0.0)
    assert red[int(bull[1]), int(bull[0])] == 255
    ob = cam.pixel_of_mm(11.0, 0.0)  # outer bull ring
    assert green[int(ob[1]), int(ob[0])] == 255
    d20 = cam.pixel_of_mm(0.0, 166.0)  # red double of 20
    assert red[int(d20[1]), int(d20[0])] == 255
    s20 = cam.pixel_of_mm(0.0, 60.0)  # dark single bed: neither
    assert red[int(s20[1]), int(s20[0])] == 0 and green[int(s20[1]), int(s20[0])] == 0


def test_ray_ellipse_intersections_on_circle() -> None:
    circle = Ellipse(cx=100.0, cy=100.0, width=50.0, height=50.0, angle=0.0)
    pts = ray_ellipse_intersections(circle, (100.0, 100.0), np.array([0.0, 90.0, 270.0]))
    np.testing.assert_allclose(pts, [(125.0, 100.0), (100.0, 125.0), (100.0, 75.0)], atol=1e-9)


def test_ray_ellipse_intersections_from_off_centre_origin() -> None:
    e = Ellipse(cx=0.0, cy=0.0, width=200.0, height=100.0, angle=0.0)
    pts = ray_ellipse_intersections(e, (30.0, 10.0), np.array([0.0]))
    x, y = pts[0]
    assert y == pytest.approx(10.0)
    assert (x / 100.0) ** 2 + (y / 50.0) ** 2 == pytest.approx(1.0)


def test_ray_ellipse_intersections_rejects_origin_outside() -> None:
    e = Ellipse(cx=0.0, cy=0.0, width=20.0, height=20.0, angle=0.0)
    with pytest.raises(AutoFitError):
        ray_ellipse_intersections(e, (50.0, 0.0), np.array([0.0]))


@pytest.mark.parametrize("pose", sorted(POSES))
def test_detect_rings_matches_truth_projection(pose: str) -> None:
    cam = synthetic_camera(pose)
    found = detect_rings(cam.image)
    truth = rings_from_homography(cam.truth_homography)

    np.testing.assert_allclose(found.bull, cam.pixel_of_mm(0.0, 0.0), atol=1.5)
    for got, want in (
        (found.double_outer, truth.double_outer),
        (found.double_inner, truth.double_inner),
        (found.treble_outer, truth.treble_outer),
        (found.treble_inner, truth.treble_inner),
    ):
        assert (got.cx, got.cy) == pytest.approx((want.cx, want.cy), abs=2.0)
        assert max(got.width, got.height) == pytest.approx(max(want.width, want.height), rel=0.02)
        assert min(got.width, got.height) == pytest.approx(min(want.width, want.height), rel=0.02)


def test_detect_wire_points_orders_from_suggested_twenty() -> None:
    cam = synthetic_camera("fronto")
    rings = detect_rings(cam.image)
    wires = detect_wire_points(cam.image, rings)

    assert wires.double_px.shape == (20, 2) and wires.treble_px.shape == (20, 2)
    # Wire 0 sits at board 9°, i.e. 9° clockwise of screen-up (270° in image coords).
    assert wires.screen_angles_deg[0] == pytest.approx(279.0, abs=1.0)
    # Points lie on the band midlines.
    for k in (0, 5, 13):
        want_d = cam.pixel_of_mm(166.0 * np.sin(np.radians(9 + 18 * k)), 166.0 * np.cos(np.radians(9 + 18 * k)))
        np.testing.assert_allclose(wires.double_px[k], want_d, atol=1.5)
    np.testing.assert_allclose(wires.double_mm[0], (166.0 * np.sin(np.radians(9.0)), 166.0 * np.cos(np.radians(9.0))))


# --- suggest() end to end ---


@pytest.mark.parametrize("pose", sorted(POSES))
def test_suggest_upright_board_is_correct_without_rotation(pose: str) -> None:
    cam = synthetic_camera(pose, rotation_sectors=0)
    cal = suggest(cam.image, slot=1)

    assert cal.slot == 1
    assert cal.rotate_offset == 0
    assert cal.status is FitStatus.PASS
    assert cal.rms_mm is not None and cal.rms_mm < 1.0
    assert cal.rings is not None
    assert _grid_rms(cam, cal.homography, 0) < 0.5

    t20 = image_to_board_mm(cal.homography, cal.rotate_offset, cam.pixel_of_mm(*T20_MM))
    assert point_mm_to_segment(*t20).name == "T20"


@pytest.mark.parametrize("rotation_sectors", [2, 4, 10, 16])
@pytest.mark.parametrize("pose", ["fronto", "tilt_top", "tilt_right"])
def test_suggest_even_rotation_picks_red_wedge_nearest_up(pose: str, rotation_sectors: int) -> None:
    """With a red wedge at the top the suggestion is exact: offset needed == truth."""
    cam = synthetic_camera(pose, rotation_sectors=rotation_sectors)
    cal = suggest(cam.image)
    offset, rms = _best_offset(cam, cal.homography)
    assert offset == cam.correct_offset
    assert rms < 0.5

    corrected = cal.rotated(offset)
    t20 = image_to_board_mm(corrected.homography, corrected.rotate_offset, cam.pixel_of_mm(*T20_MM))
    assert point_mm_to_segment(*t20).name == "T20"


@pytest.mark.parametrize("rotation_sectors", [1, 5, 19])
@pytest.mark.parametrize("pose", ["fronto", "tilt_left"])
def test_suggest_odd_rotation_is_within_one_arrow_press(pose: str, rotation_sectors: int) -> None:
    """A green wedge at the top means two red wedges tie; operator fixes it with one rotate."""
    cam = synthetic_camera(pose, rotation_sectors=rotation_sectors)
    cal = suggest(cam.image)
    offset, rms = _best_offset(cam, cal.homography)
    assert rms < 0.5
    assert (offset - cam.correct_offset) % 20 in (1, 19)


def test_suggest_survives_sensor_noise_and_blur() -> None:
    cam = synthetic_camera("tilt_top", rotation_sectors=0)
    rng = np.random.default_rng(7)
    noisy = cv2.GaussianBlur(cam.image, (3, 3), 0).astype(np.int16)
    noisy += rng.normal(0.0, 8.0, size=noisy.shape).astype(np.int16)
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)

    cal = suggest(noisy)
    assert cal.status in (FitStatus.PASS, FitStatus.WARN)
    assert _grid_rms(cam, cal.homography, 0) < 1.5


def test_suggest_exports_autodarts_shaped_rings() -> None:
    cam = synthetic_camera("fronto")
    cal = suggest(cam.image)
    out = cal.rings.to_autodarts()
    assert set(out) >= {"bull", "doubleOuter", "doubleInner", "trebleOuter", "trebleInner", "doubleOuterPoints"}
    np.testing.assert_allclose(out["bull"], cam.pixel_of_mm(0.0, 0.0), atol=1.0)


# --- failure modes ---


def test_suggest_rejects_blank_frame() -> None:
    with pytest.raises(AutoFitError):
        suggest(np.zeros((720, 1280, 3), dtype=np.uint8))


def test_suggest_rejects_noise_frame() -> None:
    rng = np.random.default_rng(3)
    with pytest.raises(AutoFitError):
        suggest(rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8))


def test_suggest_rejects_non_bgr_input() -> None:
    with pytest.raises(AutoFitError):
        suggest(np.zeros((720, 1280), dtype=np.uint8))


def test_suggest_rejects_half_visible_board() -> None:
    cam = synthetic_camera("fronto")
    cropped = cam.image.copy()
    bull_u = int(cam.pixel_of_mm(0.0, 0.0)[0])
    cropped[:, :bull_u] = (28, 28, 28)
    with pytest.raises(AutoFitError):
        suggest(cropped)


def test_autofit_error_carries_reason() -> None:
    with pytest.raises(AutoFitError) as info:
        suggest(np.zeros((100, 100, 3), dtype=np.uint8))
    assert info.value.reason
    assert str(info.value) == info.value.reason


def test_params_can_make_fit_impossible() -> None:
    cam = synthetic_camera("fronto")
    strict = AutoFitParams(min_inliers=41)  # more than the 40 wire points
    with pytest.raises(AutoFitError):
        suggest(cam.image, params=strict)


def test_double_outer_ring_projects_close_to_detected_edge() -> None:
    """The fitted homography's projected outer double should sit on the rendered ring."""
    cam = synthetic_camera("tilt_left")
    cal = suggest(cam.image)
    for angle in (0.0, 45.0, 123.0, 200.0, 310.0):
        mm = (DOUBLE_OUTER_MM * np.sin(np.radians(angle)), DOUBLE_OUTER_MM * np.cos(np.radians(angle)))
        projected = board_mm_to_image(cal.homography, 0, mm)
        np.testing.assert_allclose(projected, cam.pixel_of_mm(*mm), atol=1.5)
