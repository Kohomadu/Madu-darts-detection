"""Residual overlay: far-double callout and per-sample colours (ticket 19)."""

from __future__ import annotations

import numpy as np

from madu_darts.calibration import CamCalibration, draw_spiderweb, draw_warped_board, suggest
from madu_darts.calibration.homography import polar_mm
from madu_darts.calibration.refine import RefineParams, evaluate_fit, measure_board_edges
from madu_darts.calibration.residuals import (
    FAR_ARC_COLOUR,
    foreshortened_angle_deg,
    residual_bgr,
    residual_field_from_correspondences,
    summarize_residuals,
)
from madu_darts.calibration.session import CalibrationSession
from madu_darts.calibration.synthetic import synthetic_camera


def _px(image: np.ndarray, point: np.ndarray) -> np.ndarray:
    return image[int(round(float(point[1]))), int(round(float(point[0])))].astype(int)


def _warmth(bgr: np.ndarray) -> int:
    """Red channel minus green. Positive when the residual dot is in the red/orange band."""
    return int(bgr[2]) - int(bgr[1])


def test_foreshortened_angle_is_the_short_side_of_a_tilted_cam() -> None:
    cam = synthetic_camera("tilt_top")
    far = foreshortened_angle_deg(cam.truth_homography, 0)
    # tilt_top compresses the top of the canonical image, which is sector 20 (+y).
    assert min(far, 360.0 - far) < 25.0
    near = (far + 180.0) % 360.0
    bull = cam.pixel_of_mm(0.0, 0.0)
    far_px = cam.pixel_of_mm(*polar_mm(170.0, far))
    near_px = cam.pixel_of_mm(*polar_mm(170.0, near))
    far_d = float(np.linalg.norm(far_px - bull))
    near_d = float(np.linalg.norm(near_px - bull))
    assert far_d < near_d - 20.0


def test_summary_splits_far_and_near_double() -> None:
    cam = synthetic_camera("fronto")
    samples = (
        (0.0, 170.0, 5.0),
        (20.0, 162.0, 4.0),
        (180.0, 170.0, 0.4),
        (0.0, 107.0, 1.2),
    )
    px, mm = [], []
    for angle, radius, err in samples:
        mm.append(polar_mm(radius, angle))
        px.append(cam.pixel_of_mm(*polar_mm(radius + err, angle)))
    field = residual_field_from_correspondences(cam.truth_homography, np.asarray(px), np.asarray(mm))
    assert field is not None
    summary = summarize_residuals(field, cam.truth_homography, 0, far_angle_deg=0.0)
    assert summary["farDouble"]["maxMm"] == summary["maxMm"]
    assert summary["farDouble"]["maxMm"] > summary["nearDouble"]["maxMm"] + 3.0
    assert summary["farDouble"]["n"] == 2
    assert summary["nearDouble"]["n"] == 1
    assert summary["treble"]["n"] == 1
    assert summary["farDouble"]["angleDeg"] == 0.0


def test_soft_far_double_on_tilted_board_is_the_weak_band() -> None:
    """Known soft cam: double annulus bulged on the foreshortened side only."""
    cam = synthetic_camera("tilt_top", far_double_bias_mm=6.0, far_angle_deg=0.0)
    px, mm = measure_board_edges(cam.image, cam.truth_homography, RefineParams(ring_angles=36))
    quality = evaluate_fit(cam.truth_homography, px, mm)
    field = residual_field_from_correspondences(
        cam.truth_homography, quality.points_px, quality.points_mm, quality.inlier_mask
    )
    assert field is not None
    summary = summarize_residuals(field, cam.truth_homography, 0)
    assert summary["farDouble"] is not None and summary["nearDouble"] is not None
    assert summary["farDouble"]["n"] >= 4
    assert summary["farDouble"]["rmsMm"] > summary["nearDouble"]["rmsMm"] + 1.5
    assert summary["farDouble"]["maxMm"] > summary["nearDouble"]["maxMm"]

    cal = suggest(cam.image, slot=0)
    assert cal.residuals is not None and cal.homography is not None
    fitted = summarize_residuals(cal.residuals, cal.homography, cal.rotate_offset)
    assert fitted["farDouble"]["maxMm"] > fitted["nearDouble"]["maxMm"]
    assert fitted["maxMm"] >= fitted["farDouble"]["maxMm"] - 1e-6


def test_overlay_paints_soft_samples_warm_and_calls_out_far_annulus() -> None:
    cam = synthetic_camera("fronto")
    soft_mm = polar_mm(175.0, 180.0)
    tight_mm = polar_mm(107.3, 90.0)
    field = residual_field_from_correspondences(
        cam.truth_homography,
        np.vstack([cam.pixel_of_mm(*soft_mm), cam.pixel_of_mm(*tight_mm)]),
        np.vstack([polar_mm(170.0, 180.0), polar_mm(107.0, 90.0)]),
        np.array([False, True]),
    )
    assert field is not None
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.4, residuals=field)
    before = cam.image.copy()
    out = draw_spiderweb(cam.image, cal, highlight_twenty=False, show_residuals=True)
    np.testing.assert_array_equal(cam.image, before)

    soft_px = _px(out, cam.pixel_of_mm(*soft_mm))
    tight_px = _px(out, cam.pixel_of_mm(*tight_mm))
    assert _warmth(soft_px) > 40
    assert int(tight_px[1]) > int(tight_px[2])  # green dominates the tight sample
    assert tuple(int(c) for c in residual_bgr(5.0)) == (40, 40, 230)

    # Magenta far-arc ink exists and is not the cyan spiderweb.
    magenta = np.all(np.abs(out.astype(int) - np.array(FAR_ARC_COLOUR)) <= 30, axis=2)
    assert int(magenta.sum()) > 20

    warped = draw_warped_board(cam.image, cal, size_px=400, show_residuals=True)
    assert warped.shape == (400, 400, 3)
    warped_magenta = np.all(np.abs(warped.astype(int) - np.array(FAR_ARC_COLOUR)) <= 40, axis=2)
    assert int(warped_magenta.sum()) > 10


def test_calibration_snapshot_exposes_far_double_summary() -> None:
    cam = synthetic_camera("tilt_top", far_double_bias_mm=6.0, far_angle_deg=0.0)
    session = CalibrationSession(slots=(0,))
    session.suggest(0, cam.image)
    snap = session.snapshot()["cams"]["0"]
    assert snap["maxResidualMm"] is not None
    assert snap["farDouble"]["maxMm"] >= snap["nearDouble"]["maxMm"]
    assert snap["farDouble"]["n"] > 0
    assert "angleDeg" in snap["farDouble"]
