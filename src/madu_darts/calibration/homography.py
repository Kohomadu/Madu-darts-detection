"""Image <-> Board-plane mapping with rotate-20, fitting, and ring projection.

See ``model.py`` for the coordinate conventions. All public functions accept
points as ``(2,)`` or ``(N, 2)`` array-likes and return the same rank.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike

from madu_darts.board import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
)
from madu_darts.calibration.model import SECTOR_STEP_DEG, SECTORS, Ellipse, RingFit

_WIRE_OFFSET_DEG = SECTOR_STEP_DEG / 2.0  # wires sit at ±9° from sector centres


def rotation_mm(offset_sectors: int) -> np.ndarray:
    """3x3 clockwise rotation of board mm by ``18° * offset`` (board frame, +y up)."""
    phi = math.radians(SECTOR_STEP_DEG * (int(offset_sectors) % SECTORS))
    c, s = math.cos(phi), math.sin(phi)
    # Clockwise with +y up: (0, 1) -> (sin, cos).
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def effective_homography(homography: ArrayLike, rotate_offset: int) -> np.ndarray:
    """Image px -> board mm with the operator's rotate-20 applied."""
    h = np.asarray(homography, dtype=np.float64)
    if h.shape != (3, 3):
        raise ValueError(f"homography must be 3x3, got {h.shape}")
    return rotation_mm(rotate_offset) @ h


def apply_homography(matrix: ArrayLike, points: ArrayLike) -> np.ndarray:
    """Apply a 3x3 projective map to ``(2,)`` or ``(N, 2)`` points."""
    m = np.asarray(matrix, dtype=np.float64)
    pts = np.asarray(points, dtype=np.float64)
    single = pts.ndim == 1
    pts = pts.reshape(-1, 2)
    hom = np.hstack([pts, np.ones((len(pts), 1))])
    out = hom @ m.T
    w = out[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise ValueError("point maps to infinity under this homography")
    result = out[:, :2] / w
    return result[0] if single else result


def image_to_board_mm(
    homography: ArrayLike,
    rotate_offset: int,
    points_px: ArrayLike,
    radial: "RadialParams | None" = None,
) -> np.ndarray:
    """Observed image px → Board mm. Optional ``radial`` undistorts before ``H`` (ticket 22)."""
    from madu_darts.calibration.distortion import undistort_points

    ideal = undistort_points(points_px, radial) if radial is not None else points_px
    return apply_homography(effective_homography(homography, rotate_offset), ideal)


def board_mm_to_image(
    homography: ArrayLike,
    rotate_offset: int,
    points_mm: ArrayLike,
    radial: "RadialParams | None" = None,
) -> np.ndarray:
    """Board mm → observed image px. Optional ``radial`` distorts after ``H⁻¹`` (ticket 22)."""
    from madu_darts.calibration.distortion import distort_points

    ideal = apply_homography(np.linalg.inv(effective_homography(homography, rotate_offset)), points_mm)
    return distort_points(ideal, radial) if radial is not None else ideal


def polar_mm(radius_mm: float, angle_deg_clockwise_from_top: float) -> tuple[float, float]:
    """Board mm from polar coordinates (angle clockwise from +y / sector 20)."""
    rad = math.radians(angle_deg_clockwise_from_top)
    return radius_mm * math.sin(rad), radius_mm * math.cos(rad)


def ring_points_mm(radius_mm: float, n: int = 72, start_deg: float = 0.0) -> np.ndarray:
    """``(n, 2)`` points on a Board circle, clockwise from +y."""
    angles = np.radians(start_deg + np.arange(n) * (360.0 / n))
    return np.column_stack([radius_mm * np.sin(angles), radius_mm * np.cos(angles)])


def wire_angles_deg() -> tuple[float, ...]:
    """The 20 sector-wire angles, clockwise from +y: 9°, 27°, ..."""
    return tuple(_WIRE_OFFSET_DEG + SECTOR_STEP_DEG * k for k in range(SECTORS))


def wire_ring_intersections_mm(radii_mm: tuple[float, ...] = (DOUBLE_OUTER_MM, TREBLE_OUTER_MM)) -> np.ndarray:
    """Board-mm points where sector wires cross the given rings (``len(radii) * 20``)."""
    pts = [polar_mm(r, a) for r in radii_mm for a in wire_angles_deg()]
    return np.asarray(pts, dtype=np.float64)


def fit_homography(
    points_px: ArrayLike,
    points_mm: ArrayLike,
    *,
    ransac_threshold_mm: float = 3.0,
) -> tuple[np.ndarray, np.ndarray]:
    """RANSAC homography image px -> board mm. Returns ``(H, inlier_mask)``."""
    import cv2

    src = np.asarray(points_px, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    if len(src) != len(dst):
        raise ValueError("points_px and points_mm must have the same length")
    if len(src) < 4:
        raise ValueError("need at least 4 correspondences")

    h, mask = cv2.findHomography(
        src.astype(np.float32),
        dst.astype(np.float32),
        cv2.RANSAC,
        ransac_threshold_mm,
    )
    if h is None:
        raise ValueError("homography estimation failed")
    inliers = np.asarray(mask, dtype=bool).ravel() if mask is not None else np.ones(len(src), dtype=bool)
    return np.asarray(h, dtype=np.float64), inliers


def reprojection_rms_mm(
    homography: ArrayLike,
    rotate_offset: int,
    points_px: ArrayLike,
    points_mm: ArrayLike,
) -> float:
    """RMS distance (mm) between mapped image points and their Board-mm targets."""
    mapped = image_to_board_mm(homography, rotate_offset, points_px).reshape(-1, 2)
    target = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    if mapped.shape != target.shape:
        raise ValueError("point sets differ in length")
    if len(mapped) == 0:
        raise ValueError("no points")
    err = np.linalg.norm(mapped - target, axis=1)
    return float(np.sqrt(np.mean(err**2)))


def rings_from_homography(homography: ArrayLike, n: int = 72, radial=None) -> RingFit:
    """Project the WDF rings into the image and fit ellipses (rotation-invariant)."""
    import cv2

    def ring(radius: float) -> Ellipse:
        pts = board_mm_to_image(homography, 0, ring_points_mm(radius, n), radial)
        return Ellipse.from_cv(cv2.fitEllipse(pts.astype(np.float32)))

    bull = board_mm_to_image(homography, 0, (0.0, 0.0), radial)
    return RingFit(
        bull=(float(bull[0]), float(bull[1])),
        double_outer=ring(DOUBLE_OUTER_MM),
        double_inner=ring(DOUBLE_INNER_MM),
        treble_outer=ring(TREBLE_OUTER_MM),
        treble_inner=ring(TREBLE_INNER_MM),
    )
