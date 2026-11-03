"""Ticket 34: nudge clears quality; Accept blocked until rescore."""

from __future__ import annotations

import numpy as np
import pytest

from madu_darts.calibration import (
    AcceptBlocked,
    CalibrationSession,
    CamCalibration,
    accept_block_reasons,
    suggest,
)
from madu_darts.calibration.synthetic import synthetic_camera


def test_nudge_blocks_accept_until_rescore() -> None:
    cam = synthetic_camera("fronto")
    cal = suggest(cam.image, slot=0)
    assert cal.has_fit and cal.residuals is not None and cal.rms_mm is not None
    session = CalibrationSession(slots=(0,))
    session._cals[0] = cal  # noqa: SLF001 — seed a real autofit
    session._auto_seeds[0] = cal  # noqa: SLF001
    assert session.can_accept()

    session.nudge_pan(0, 4.0, -2.0)
    nudged = session.get(0)
    assert nudged.residuals is None and nudged.rms_mm is None
    reasons = accept_block_reasons(nudged)
    assert reasons and "nudge" in reasons[0].lower()
    assert not session.can_accept()
    with pytest.raises(AcceptBlocked):
        session.accept()

    session.rescore({0: cam.image})
    assert session.get(0).residuals is not None
    assert session.get(0).rms_mm is not None
    assert session.can_accept()
    session.accept()
    assert session.accepted


def test_healthy_synthetic_fit_still_accepts() -> None:
    cam = synthetic_camera("fronto")
    cal = suggest(cam.image, slot=0)
    session = CalibrationSession(slots=(0,))
    session._cals[0] = cal  # noqa: SLF001
    assert session.can_accept()
    session.accept()
    assert session.accepted


def test_overlay_badge_prefers_far_double_rms() -> None:
    from madu_darts.calibration.overlay import _status_text
    from madu_darts.calibration.homography import polar_mm
    from madu_darts.calibration.residuals import residual_field_from_correspondences

    cam = synthetic_camera("fronto")
    # Soft far double so far RMS differs from a green inlier rms_mm.
    samples = ((0.0, 170.0, 4.0), (20.0, 162.0, 4.0), (180.0, 170.0, 0.3))
    px, mm = [], []
    for angle, radius, err in samples:
        mm.append(polar_mm(radius, angle))
        px.append(cam.pixel_of_mm(*polar_mm(radius + err, angle)))
    field = residual_field_from_correspondences(
        cam.truth_homography, np.asarray(px), np.asarray(mm)
    )
    cal = CamCalibration(
        slot=0,
        homography=cam.truth_homography,
        rms_mm=1.0,
        n_inliers=200,
        n_points=300,
        residuals=field,
    )
    text = _status_text(cal)
    assert "far dbl" in text
    assert "4." in text or "3." in text  # far RMS around the injected error
