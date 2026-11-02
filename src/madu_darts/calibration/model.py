"""Calibration data model: fitted rings, per-cam Board-plane bind, pass/fail status.

Conventions
-----------
* Image space: OpenCV pixels, ``u`` right, ``v`` down.
* Board space: millimetres, origin at bull, ``+y`` toward sector 20, ``+x``
  right (see ``madu_darts.board.geometry``).
* ``CamCalibration.homography`` maps image px -> *raw* board mm, where the
  sector clock is only known up to a multiple of 18° (auto-fit cannot tell
  which wedge is 20). ``rotate_offset`` resolves that: the effective mapping
  rotates raw mm clockwise by ``18° * rotate_offset`` (see ``homography.py``).
  This is the Autodarts **rotate-20** control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from madu_darts.calibration.residuals import ResidualField

import numpy as np

SECTORS = 20
SECTOR_STEP_DEG = 360.0 / SECTORS  # 18°

# Reprojection RMS (mm) thresholds for the warped-board pass/fail badge.
PASS_RMS_MM = 1.5
WARN_RMS_MM = 3.0
# Ticket 15: a low inlier-only RMS is not enough — enough real edges must bind.
# Coverage is inliers/measured-peaks (false peaks from glare lower it); absolute
# inlier count is the stronger signal that both bands are actually observed.
PASS_MIN_COVERAGE = 0.45
PASS_MIN_INLIERS = 100
WARN_MIN_COVERAGE = 0.30
WARN_MIN_INLIERS = 40


class FitStatus(str, Enum):
    """Per-cam Calibration quality shown in the Calibration view."""

    NONE = "none"  # no Board-plane bind yet (auto-fit failed / not run)
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


def status_for_rms(
    rms_mm: float | None,
    *,
    n_inliers: int | None = None,
    n_points: int | None = None,
) -> FitStatus:
    """Classify fit quality from RMS and (optional) edge-inlier coverage.

    Without coverage stats this falls back to the legacy RMS-only thresholds so
    older callers / synthetic tests keep working. With coverage (ticket 15), a
    cam only **pass**es when RMS is low *and* enough measured edges are inliers
    — stopping a soft cam0 (15/40 colour wires) from looking almost-green.
    """
    if rms_mm is None:
        return FitStatus.NONE
    if not math.isfinite(rms_mm):
        return FitStatus.FAIL

    coverage: float | None = None
    if n_inliers is not None and n_points is not None and n_points > 0:
        coverage = n_inliers / n_points

    if coverage is None:
        if rms_mm <= PASS_RMS_MM:
            return FitStatus.PASS
        if rms_mm <= WARN_RMS_MM:
            return FitStatus.WARN
        return FitStatus.FAIL

    n_in = int(n_inliers or 0)
    if (
        rms_mm <= PASS_RMS_MM
        and coverage >= PASS_MIN_COVERAGE
        and n_in >= PASS_MIN_INLIERS
    ):
        return FitStatus.PASS
    if rms_mm <= WARN_RMS_MM and (coverage >= WARN_MIN_COVERAGE or n_in >= WARN_MIN_INLIERS):
        return FitStatus.WARN
    if rms_mm <= WARN_RMS_MM:
        # Bound the Board loosely but coverage is thin → still warn (Acceptable).
        return FitStatus.WARN
    return FitStatus.FAIL


class CalibrationNotAccepted(RuntimeError):
    """Board-plane mapping requested before the operator Accepted Calibration.

    ADR 0002: no Accept -> no Hits.
    """


@dataclass(frozen=True)
class Ellipse:
    """Image-space ellipse in OpenCV ``fitEllipse`` / ``RotatedRect`` convention.

    ``width``/``height`` are full axis lengths; ``angle`` is degrees.
    """

    cx: float
    cy: float
    width: float
    height: float
    angle: float

    @classmethod
    def from_cv(cls, rotated_rect: Any) -> Ellipse:
        (cx, cy), (width, height), angle = rotated_rect
        return cls(float(cx), float(cy), float(width), float(height), float(angle))

    def to_autodarts(self) -> dict[str, float]:
        """Shape of one ring in Autodarts ``/api/config/calibration/ellipses``."""
        return {
            "angle": self.angle,
            "x": self.cx,
            "y": self.cy,
            "width": self.width,
            "height": self.height,
        }

    def points(self, n: int = 20) -> np.ndarray:
        """``(n, 2)`` points sampled around the ellipse."""
        t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        a = math.radians(self.angle)
        ca, sa = math.cos(a), math.sin(a)
        rx, ry = self.width / 2.0, self.height / 2.0
        x = self.cx + rx * np.cos(t) * ca - ry * np.sin(t) * sa
        y = self.cy + rx * np.cos(t) * sa + ry * np.sin(t) * ca
        return np.column_stack([x, y])


@dataclass(frozen=True)
class RingFit:
    """Fitted Board rings in image space for one cam (Autodarts ellipses analogue)."""

    bull: tuple[float, float]
    double_outer: Ellipse
    double_inner: Ellipse
    treble_outer: Ellipse
    treble_inner: Ellipse

    def to_autodarts(self, ring_points: int = 20) -> dict[str, Any]:
        """Autodarts-shaped dict: ``bull``, ``<ring>`` ellipses, ``<ring>Points``."""
        out: dict[str, Any] = {"bull": [self.bull[0], self.bull[1]]}
        for key, ellipse in (
            ("doubleOuter", self.double_outer),
            ("doubleInner", self.double_inner),
            ("trebleOuter", self.treble_outer),
            ("trebleInner", self.treble_inner),
        ):
            out[key] = ellipse.to_autodarts()
            out[f"{key}Points"] = ellipse.points(ring_points).tolist()
        return out


@dataclass(frozen=True, eq=False)
class CamCalibration:
    """One camera's bind to the Board plane plus operator rotate-20 state."""

    slot: int
    homography: np.ndarray | None = None
    """3x3, image px -> raw board mm (sector clock unresolved)."""
    rotate_offset: int = 0
    """Sectors of clockwise rotation applied to raw mm; wraps mod 20."""
    rings: RingFit | None = None
    rms_mm: float | None = None
    """Reprojection RMS of the fit points, mm."""
    n_inliers: int | None = None
    """Edge correspondences within the RANSAC threshold after refinement."""
    n_points: int | None = None
    """Total measured ring/wire edge correspondences used for quality."""
    rms_double_mm: float | None = None
    """Inlier RMS on the double band alone (diagnostic)."""
    rms_treble_mm: float | None = None
    """Inlier RMS on the treble band alone (diagnostic)."""
    residuals: ResidualField | None = None
    """Measured wire/ring residuals for the Calibration overlay (ticket 19)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rotate_offset", int(self.rotate_offset) % SECTORS)
        if self.homography is not None:
            h = np.asarray(self.homography, dtype=np.float64)
            if h.shape != (3, 3):
                raise ValueError(f"homography must be 3x3, got {h.shape}")
            object.__setattr__(self, "homography", h)

    @property
    def has_fit(self) -> bool:
        return self.homography is not None

    @property
    def coverage(self) -> float | None:
        if self.n_inliers is None or self.n_points is None or self.n_points <= 0:
            return None
        return self.n_inliers / self.n_points

    @property
    def status(self) -> FitStatus:
        """``NONE`` without a fit; a fit with unknown RMS is ``WARN`` (operator judges)."""
        if self.homography is None:
            return FitStatus.NONE
        if self.rms_mm is None:
            return FitStatus.WARN
        return status_for_rms(self.rms_mm, n_inliers=self.n_inliers, n_points=self.n_points)

    def rotated(self, delta_sectors: int) -> CamCalibration:
        return replace(self, rotate_offset=(self.rotate_offset + delta_sectors) % SECTORS)

    def rotate_left(self) -> CamCalibration:
        """Move the 20 highlight one sector counter-clockwise in the image."""
        return self.rotated(+1)

    def rotate_right(self) -> CamCalibration:
        """Move the 20 highlight one sector clockwise in the image."""
        return self.rotated(-1)
