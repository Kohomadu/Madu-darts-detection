"""Calibration model: status thresholds, rotate-20 wrapping, ellipse/ring shapes."""

from __future__ import annotations

import math

import numpy as np
import pytest

from madu_darts.calibration import (
    PASS_RMS_MM,
    WARN_RMS_MM,
    CamCalibration,
    Ellipse,
    FitStatus,
    RingFit,
    status_for_rms,
)


@pytest.mark.parametrize(
    ("rms", "expected"),
    [
        (None, FitStatus.NONE),
        (0.0, FitStatus.PASS),
        (PASS_RMS_MM, FitStatus.PASS),
        (PASS_RMS_MM + 0.01, FitStatus.WARN),
        (WARN_RMS_MM, FitStatus.WARN),
        (WARN_RMS_MM + 0.01, FitStatus.FAIL),
        (math.inf, FitStatus.FAIL),
        (math.nan, FitStatus.FAIL),
    ],
)
def test_status_for_rms_thresholds(rms: float | None, expected: FitStatus) -> None:
    assert status_for_rms(rms) is expected


def test_cam_calibration_without_fit_is_none_status() -> None:
    cal = CamCalibration(slot=0)
    assert not cal.has_fit
    assert cal.status is FitStatus.NONE


def test_cam_calibration_with_fit_but_unknown_rms_is_warn() -> None:
    cal = CamCalibration(slot=0, homography=np.eye(3))
    assert cal.has_fit
    assert cal.status is FitStatus.WARN


def test_cam_calibration_status_follows_rms() -> None:
    assert CamCalibration(slot=0, homography=np.eye(3), rms_mm=1.0).status is FitStatus.PASS
    assert CamCalibration(slot=0, homography=np.eye(3), rms_mm=2.0).status is FitStatus.WARN
    assert CamCalibration(slot=0, homography=np.eye(3), rms_mm=9.0).status is FitStatus.FAIL


def test_cam_calibration_rejects_non_3x3_homography() -> None:
    with pytest.raises(ValueError):
        CamCalibration(slot=0, homography=np.eye(2))


def test_rotate_offset_normalizes_mod_20() -> None:
    assert CamCalibration(slot=0, rotate_offset=20).rotate_offset == 0
    assert CamCalibration(slot=0, rotate_offset=-1).rotate_offset == 19
    assert CamCalibration(slot=0, rotate_offset=23).rotate_offset == 3


def test_rotate_left_right_wrap_and_preserve_fit() -> None:
    h = np.diag([0.5, -0.5, 1.0])
    cal = CamCalibration(slot=1, homography=h, rotate_offset=19, rms_mm=0.4)

    left = cal.rotate_left()
    assert left.rotate_offset == 0
    assert left.rotate_right().rotate_offset == 19
    assert CamCalibration(slot=1, rotate_offset=0).rotate_right().rotate_offset == 19

    assert left.slot == 1
    assert left.rms_mm == 0.4
    np.testing.assert_array_equal(left.homography, h)


def test_ellipse_points_lie_on_axis_aligned_circle() -> None:
    e = Ellipse(cx=100.0, cy=50.0, width=40.0, height=40.0, angle=0.0)
    pts = e.points(36)
    assert pts.shape == (36, 2)
    radii = np.linalg.norm(pts - np.array([100.0, 50.0]), axis=1)
    np.testing.assert_allclose(radii, 20.0, atol=1e-9)


def test_ellipse_points_respect_rotation() -> None:
    # Major axis 100 along +x rotated 90° -> extremes should be along y.
    e = Ellipse(cx=0.0, cy=0.0, width=100.0, height=20.0, angle=90.0)
    pts = e.points(360)
    assert pytest.approx(np.abs(pts[:, 1]).max(), abs=1e-6) == 50.0
    assert pytest.approx(np.abs(pts[:, 0]).max(), abs=1e-6) == 10.0


def test_ellipse_from_cv_and_autodarts_shape() -> None:
    e = Ellipse.from_cv(((10.0, 20.0), (30.0, 40.0), 15.0))
    assert e == Ellipse(10.0, 20.0, 30.0, 40.0, 15.0)
    assert e.to_autodarts() == {"angle": 15.0, "x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0}


def test_ring_fit_to_autodarts_has_bull_rings_and_points() -> None:
    e = Ellipse(640.0, 360.0, 300.0, 200.0, 0.0)
    rings = RingFit(bull=(640.0, 360.0), double_outer=e, double_inner=e, treble_outer=e, treble_inner=e)
    out = rings.to_autodarts(ring_points=20)
    assert out["bull"] == [640.0, 360.0]
    for key in ("doubleOuter", "doubleInner", "trebleOuter", "trebleInner"):
        assert set(out[key]) == {"angle", "x", "y", "width", "height"}
        assert len(out[f"{key}Points"]) == 20
        assert len(out[f"{key}Points"][0]) == 2
