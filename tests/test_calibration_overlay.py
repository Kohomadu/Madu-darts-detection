"""Spiderweb + 20 highlight on the feed; warped Board with ideal rings (pass/fail view)."""

from __future__ import annotations

import numpy as np
import pytest
from madu_darts.calibration.synthetic import synthetic_camera

from madu_darts.calibration import (
    CamCalibration,
    canonical_mm_to_px,
    draw_spiderweb,
    draw_warped_board,
    polar_mm,
)


def _px(image: np.ndarray, point: np.ndarray) -> np.ndarray:
    return image[int(round(point[1])), int(round(point[0]))].astype(int)


def _redness(bgr: np.ndarray) -> int:
    return int(bgr[2]) - int(max(bgr[0], bgr[1]))


# --- spiderweb ---


def test_spiderweb_returns_copy_with_same_shape() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    before = cam.image.copy()
    out = draw_spiderweb(cam.image, cal)
    assert out.shape == cam.image.shape and out.dtype == np.uint8
    assert out is not cam.image
    np.testing.assert_array_equal(cam.image, before)


def test_spiderweb_highlights_sector_twenty_only() -> None:
    cam = synthetic_camera("tilt_top")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    out = draw_spiderweb(cam.image, cal)

    s20 = cam.pixel_of_mm(0.0, 60.0)  # dark single bed of 20 -> tinted red
    assert _redness(_px(out, s20)) > _redness(_px(cam.image, s20)) + 40

    s3 = cam.pixel_of_mm(*polar_mm(60.0, 180.0))  # sector 3 at the bottom: untouched bed
    np.testing.assert_array_equal(_px(out, s3), _px(cam.image, s3))


def test_spiderweb_highlight_follows_rotate_left() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    rotated = cal.rotate_left()
    out = draw_spiderweb(cam.image, rotated)

    s20 = cam.pixel_of_mm(0.0, 60.0)
    s1 = cam.pixel_of_mm(*polar_mm(60.0, 18.0))  # physical sector 1 (clockwise neighbour)
    # Highlight moved counter-clockwise on screen: physical 20 is clean, physical 19 is tinted.
    s19 = cam.pixel_of_mm(*polar_mm(60.0, -18.0))
    np.testing.assert_array_equal(_px(out, s20), _px(cam.image, s20))
    np.testing.assert_array_equal(_px(out, s1), _px(cam.image, s1))
    assert _redness(_px(out, s19)) > _redness(_px(cam.image, s19)) + 40


def test_spiderweb_can_skip_highlight() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    out = draw_spiderweb(cam.image, cal, highlight_twenty=False)
    s20 = cam.pixel_of_mm(0.0, 60.0)
    np.testing.assert_array_equal(_px(out, s20), _px(cam.image, s20))


def test_spiderweb_draws_web_lines_on_wires() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    out = draw_spiderweb(cam.image, cal, highlight_twenty=False)
    on_ring = cam.pixel_of_mm(*polar_mm(168.5, 123.0))  # outer double scoring face, sector 10 area
    changed = np.abs(_px(out, on_ring) - _px(cam.image, on_ring)).max()
    assert changed > 30


def test_spiderweb_without_fit_only_adds_badge() -> None:
    cam = synthetic_camera("fronto")
    out = draw_spiderweb(cam.image, CamCalibration(slot=2))
    assert out.shape == cam.image.shape
    # Badge in the top-left corner, rest of the frame untouched.
    np.testing.assert_array_equal(out[100:, :], cam.image[100:, :])
    assert not np.array_equal(out[:40, :120], cam.image[:40, :120])


# --- warped board ---


def test_canonical_mm_to_px_centres_board() -> None:
    m = canonical_mm_to_px(400, 20.0)
    centre = m @ np.array([0.0, 0.0, 1.0])
    np.testing.assert_allclose(centre[:2] / centre[2], (199.5, 199.5))
    top = m @ np.array([0.0, 188.5, 1.0])  # outer double scoring face + margin -> top edge
    assert top[1] / top[2] == pytest.approx(-0.5, abs=1e-9)


def test_warped_board_with_truth_is_upright_and_scaled() -> None:
    cam = synthetic_camera("tilt_left", rotation_sectors=3)
    cal = CamCalibration(slot=0, homography=cam.raw_homography, rotate_offset=cam.correct_offset, rms_mm=0.2)
    out = draw_warped_board(cam.image, cal, size_px=400)
    assert out.shape == (400, 400, 3)

    m = canonical_mm_to_px(400)

    def at(x_mm: float, y_mm: float) -> np.ndarray:
        p = m @ np.array([x_mm, y_mm, 1.0])
        return _px(out, p[:2] / p[2])

    # Bull red in the middle; physical 20 (dark bed, red-tinted) at the top; sector 1 light to its right.
    assert _redness(at(0.0, 0.0)) > 60
    top_bed = at(0.0, 60.0)
    assert max(top_bed[0], top_bed[1]) < 80 and _redness(top_bed) > 40
    assert at(*polar_mm(60.0, 18.0)).min() > 150
    # Red double of 20 at the top after rotation is corrected.
    assert _redness(at(0.0, 166.0)) > 60


def test_warped_board_with_wrong_offset_shows_misaligned_sector() -> None:
    cam = synthetic_camera("fronto", rotation_sectors=3)
    wrong = CamCalibration(slot=0, homography=cam.raw_homography, rotate_offset=(cam.correct_offset + 1) % 20)
    out = draw_warped_board(cam.image, wrong, size_px=400)
    m = canonical_mm_to_px(400)
    p = m @ np.array([0.0, 60.0, 1.0])
    # The light bed of sector 5 lands under the 20 tint: visibly wrong to the operator.
    bed = _px(out, p[:2] / p[2])
    assert min(bed[0], bed[1]) > 90 and _redness(bed) > 40


def test_calibration_tile_composites_warped_inset_bottom_right() -> None:
    from madu_darts.calibration import draw_calibration_tile

    cam = synthetic_camera("tilt_top")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.3)
    tile = draw_calibration_tile(cam.image, cal)
    assert tile.shape == cam.image.shape
    size = int(round(720 * 0.38))
    inset = tile[720 - size - 8 : 720 - 8, 1280 - size - 8 : 1280 - 8]
    centre = inset[size // 2, size // 2]
    assert _redness(centre) > 60  # warped bull sits in the inset's middle
    # Top-left of the frame is still the live feed (badge + backdrop), not the inset.
    np.testing.assert_array_equal(tile[100:300, 0:100], cam.image[100:300, 0:100])


def test_warped_board_without_fit_is_placeholder() -> None:
    out = draw_warped_board(np.zeros((720, 1280, 3), dtype=np.uint8), CamCalibration(slot=1), size_px=320)
    assert out.shape == (320, 320, 3)
    assert out[300, 300].tolist() == [24, 24, 24]
