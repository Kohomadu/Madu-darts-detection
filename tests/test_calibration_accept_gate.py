"""Accept quality gate v2 — soft far double cannot Accept (ticket 23)."""

from __future__ import annotations

import numpy as np
import pytest

from madu_darts.calibration import (
    ACCEPT_FAR_DOUBLE_MAX_MM,
    ACCEPT_FAR_DOUBLE_RMS_MM,
    AcceptBlocked,
    AcceptGateParams,
    CalibrationSession,
    CamCalibration,
    FitStatus,
    accept_block_reasons,
    far_double_status,
    suggest,
)
from madu_darts.calibration.homography import polar_mm
from madu_darts.calibration.residuals import residual_field_from_correspondences
from madu_darts.calibration.synthetic import synthetic_camera


def _field_with_far_errors(cam, *, far_err: float, near_err: float = 0.4):
    samples = (
        (0.0, 170.0, far_err),
        (20.0, 162.0, far_err),
        (180.0, 170.0, near_err),
        (200.0, 162.0, near_err),
        (90.0, 107.0, 0.5),
    )
    px, mm = [], []
    for angle, radius, err in samples:
        mm.append(polar_mm(radius, angle))
        px.append(cam.pixel_of_mm(*polar_mm(radius + err, angle)))
    return residual_field_from_correspondences(cam.truth_homography, np.asarray(px), np.asarray(mm))


def test_far_double_status_thresholds() -> None:
    assert far_double_status(None) is None
    assert far_double_status({"rmsMm": 1.0, "maxMm": 2.0}) is FitStatus.PASS
    assert far_double_status({"rmsMm": 3.5, "maxMm": 4.0}) is FitStatus.WARN
    assert far_double_status({"rmsMm": 5.4, "maxMm": 6.0}) is FitStatus.FAIL
    assert far_double_status({"rmsMm": 2.0, "maxMm": 8.5}) is FitStatus.FAIL


def test_soft_far_double_demotes_pass_badge_and_blocks_accept() -> None:
    """Live cam0-style: inlier RMS looks PASS, foreshortened double is soft."""
    cam = synthetic_camera("fronto")
    field = _field_with_far_errors(cam, far_err=5.5)
    cal = CamCalibration(
        slot=0,
        homography=cam.truth_homography,
        rms_mm=1.2,
        n_inliers=200,
        n_points=300,
        residuals=field,
    )
    assert cal.status is FitStatus.FAIL
    reasons = accept_block_reasons(cal)
    assert reasons and "far double" in reasons[0]
    assert "soft foreshortened double" in reasons[0]


def test_cam1_class_far_double_warns_but_still_acceptable() -> None:
    cam = synthetic_camera("fronto")
    field = _field_with_far_errors(cam, far_err=3.5)
    cal = CamCalibration(
        slot=1,
        homography=cam.truth_homography,
        rms_mm=1.2,
        n_inliers=200,
        n_points=300,
        residuals=field,
    )
    assert cal.status is FitStatus.WARN
    assert accept_block_reasons(cal) == []


def test_session_blocks_soft_far_double_even_with_green_rms() -> None:
    cam = synthetic_camera("fronto")
    soft = CamCalibration(
        slot=0,
        homography=cam.truth_homography,
        rms_mm=1.0,
        n_inliers=200,
        n_points=300,
        residuals=_field_with_far_errors(cam, far_err=5.5),
    )
    good = CamCalibration(slot=1, homography=np.eye(3), rms_mm=0.5)
    session = CalibrationSession(
        slots=(0, 1),
        suggester=lambda image, slot, params: soft if slot == 0 else good,
    )
    session.suggest_all({0: cam.image, 1: cam.image})
    assert not session.can_accept()
    assert any("far double" in b for b in session.blockers())
    with pytest.raises(AcceptBlocked) as info:
        session.accept()
    assert any("far double" in b for b in info.value.blockers)


def test_healthy_synthetic_board_still_accepts() -> None:
    cams = {s: synthetic_camera(pose) for s, pose in enumerate(("tilt_top", "tilt_left", "tilt_right"))}
    session = CalibrationSession()
    session.suggest_all({s: cam.image for s, cam in cams.items()})
    assert session.can_accept(), session.blockers()
    session.accept()
    assert session.accepted


def test_soft_far_double_synthetic_autofit_raises_far_stats() -> None:
    """Bulged far double still shows up in residual summary after Auto (gate input)."""
    cam = synthetic_camera("tilt_top", far_double_bias_mm=6.0, far_angle_deg=0.0)
    cal = suggest(cam.image, slot=0)
    assert cal.residuals is not None and cal.homography is not None
    from madu_darts.calibration.residuals import summarize_residuals

    summary = summarize_residuals(cal.residuals, cal.homography, cal.rotate_offset)
    assert summary["farDouble"]["maxMm"] > summary["nearDouble"]["maxMm"]
    # Homography absorbs some of the bulge; crafted soft fields cover the Accept block.
    assert summary["farDouble"]["rmsMm"] > summary["nearDouble"]["rmsMm"]


def test_accept_gate_params_are_tunable() -> None:
    cam = synthetic_camera("fronto")
    field = _field_with_far_errors(cam, far_err=3.5)
    cal = CamCalibration(
        slot=0,
        homography=cam.truth_homography,
        rms_mm=1.0,
        n_inliers=200,
        n_points=300,
        residuals=field,
    )
    loose = AcceptGateParams(far_double_rms_mm=6.0, far_double_max_mm=10.0)
    tight = AcceptGateParams(far_double_rms_mm=2.0, far_double_max_mm=3.0)
    assert accept_block_reasons(cal, params=loose) == []
    assert accept_block_reasons(cal, params=tight)
    assert ACCEPT_FAR_DOUBLE_RMS_MM == 4.0
    assert ACCEPT_FAR_DOUBLE_MAX_MM == 7.0


def test_suggest_exports_live_like_blocker_copy() -> None:
    """Live empty Board numbers: soft cam0-class far RMS must name the band."""
    cam = synthetic_camera("fronto")
    cal = suggest(cam.image, slot=0)
    # Healthy synthetic must not invent a soft-far blocker.
    assert accept_block_reasons(cal) == []
