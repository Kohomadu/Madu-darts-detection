"""Per-sample wire and ring residuals for the Calibration overlay (ticket 19).

``FitQuality`` already scores a homography against measured edges. This module
keeps those correspondences, colours them, and summarises the far double
annulus — the foreshortened half of the double ring, where a soft cam
(typically cam0) drifts while the inlier-only RMS still looks acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from madu_darts.board import DOUBLE_INNER_MM, DOUBLE_OUTER_MM
from madu_darts.calibration.homography import board_mm_to_image, image_to_board_mm, polar_mm

# Double annulus is the inner/outer double wires, not the r=150 sector-wire
# samples (those sit in the outer single and dominate a >=150 gate).
DOUBLE_ANNULUS_MIN_MM = DOUBLE_INNER_MM - 4.0
DOUBLE_ANNULUS_MAX_MM = DOUBLE_OUTER_MM + 4.0
TREBLE_BAND_MIN_MM = 90.0
TREBLE_BAND_MAX_MM = 120.0
FAR_HALF_DEG = 90.0

# Green → yellow → orange → red. Cuts sit on the pass / warn RMS gates.
_GREEN = (70, 210, 70)
_YELLOW = (40, 220, 230)
_ORANGE = (20, 140, 255)
_RED = (40, 40, 230)
FAR_ARC_COLOUR = (220, 40, 220)  # magenta: the far double annulus


def residual_bgr(error_mm: float) -> tuple[int, int, int]:
    """BGR colour for one residual sample."""
    if error_mm <= 0.75:
        return _GREEN
    if error_mm <= 1.5:
        return _YELLOW
    if error_mm <= 3.0:
        return _ORANGE
    return _RED


@dataclass(frozen=True)
class ResidualField:
    """Measured edge samples in the *raw* board frame (rotate-20 not applied).

    ``points_px`` are where the edge was seen; ``points_mm`` are the WDF
    targets those edges were assigned to. ``error_mm`` is the Board-plane
    distance between the mapped pixel and that target.
    """

    points_px: np.ndarray
    points_mm: np.ndarray
    error_mm: np.ndarray
    radius_mm: np.ndarray
    angle_deg: np.ndarray
    inlier: np.ndarray


def residual_field_from_correspondences(
    homography: np.ndarray,
    points_px: np.ndarray,
    points_mm: np.ndarray,
    inlier_mask: np.ndarray | None = None,
) -> ResidualField | None:
    """Build a residual field for a homography and its measured correspondences."""
    px = np.asarray(points_px, dtype=np.float64).reshape(-1, 2)
    mm = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    if len(px) == 0 or len(px) != len(mm):
        return None
    mapped = image_to_board_mm(homography, 0, px).reshape(-1, 2)
    err = np.linalg.norm(mapped - mm, axis=1)
    radius = np.hypot(mm[:, 0], mm[:, 1])
    angle = np.degrees(np.arctan2(mm[:, 0], mm[:, 1])) % 360.0
    if inlier_mask is None or len(inlier_mask) != len(px):
        inlier = np.ones(len(px), dtype=bool)
    else:
        inlier = np.asarray(inlier_mask, dtype=bool).ravel()
    return ResidualField(
        points_px=px,
        points_mm=mm,
        error_mm=err,
        radius_mm=radius,
        angle_deg=angle,
        inlier=inlier,
    )


def foreshortened_angle_deg(
    homography: np.ndarray,
    rotate_offset: int,
    *,
    radius_mm: float = DOUBLE_OUTER_MM,
    n: int = 72,
) -> float:
    """Board angle (clockwise from +y, rotate-20 applied) of the compressed outer double.

    Under perspective the far side of the ring is the short side in the image.
    A fronto-parallel cam has no far side; the minimum is then just the first
    sample and the callout is nearly symmetric.
    """
    angles = np.linspace(0.0, 360.0, n, endpoint=False)
    rad = np.radians(angles)
    pts = np.column_stack([radius_mm * np.sin(rad), radius_mm * np.cos(rad)])
    try:
        pix = board_mm_to_image(homography, rotate_offset, pts)
        bull = board_mm_to_image(homography, rotate_offset, (0.0, 0.0))
    except ValueError:
        return 0.0
    dist = np.linalg.norm(pix - np.asarray(bull, dtype=np.float64).reshape(1, 2), axis=1)
    return float(angles[int(np.argmin(dist))])


def _effective_angles(raw_deg: np.ndarray, rotate_offset: int) -> np.ndarray:
    from madu_darts.calibration.model import SECTOR_STEP_DEG, SECTORS

    phi = SECTOR_STEP_DEG * (int(rotate_offset) % SECTORS)
    return (np.asarray(raw_deg, dtype=np.float64) + phi) % 360.0


def _ang_dist_deg(a: np.ndarray, b: float) -> np.ndarray:
    return (np.asarray(a, dtype=np.float64) - b + 180.0) % 360.0 - 180.0


def _band_stats(error_mm: np.ndarray, mask: np.ndarray) -> dict[str, Any] | None:
    n = int(np.count_nonzero(mask))
    if n == 0:
        return None
    err = error_mm[mask]
    return {
        "n": n,
        "rmsMm": round(float(np.sqrt(np.mean(err**2))), 3),
        "maxMm": round(float(np.max(err)), 3),
    }


def summarize_residuals(
    field: ResidualField,
    homography: np.ndarray,
    rotate_offset: int,
    *,
    far_angle_deg: float | None = None,
) -> dict[str, Any]:
    """Compact per-band residual summary for ``GET /api/calibration`` and the CLI.

    Band RMS here includes every measured sample, outliers included. The
    inlier-only ``rmsDoubleMm`` / ``rmsTrebleMm`` on the cam stay as the
    Accept diagnostic from ticket 15; this summary is what shows a rejected
    far-double cluster.
    """
    err = field.error_mm
    far = (
        foreshortened_angle_deg(homography, rotate_offset)
        if far_angle_deg is None
        else float(far_angle_deg) % 360.0
    )
    eff = _effective_angles(field.angle_deg, rotate_offset)
    on_far = np.abs(_ang_dist_deg(eff, far)) <= FAR_HALF_DEG
    on_double = (field.radius_mm >= DOUBLE_ANNULUS_MIN_MM) & (field.radius_mm <= DOUBLE_ANNULUS_MAX_MM)
    on_treble = (field.radius_mm >= TREBLE_BAND_MIN_MM) & (field.radius_mm <= TREBLE_BAND_MAX_MM)
    far_double = _band_stats(err, on_double & on_far)
    if far_double is not None:
        far_double = {**far_double, "angleDeg": round(far, 1)}
    max_mm = float(np.max(err)) if len(err) else None
    return {
        "maxMm": None if max_mm is None else round(max_mm, 3),
        "n": int(len(err)),
        "double": _band_stats(err, on_double),
        "treble": _band_stats(err, on_treble),
        "farDouble": far_double,
        "nearDouble": _band_stats(err, on_double & ~on_far),
        "farAngleDeg": round(far, 1),
    }


def far_annulus_polylines_mm(far_angle_deg: float, *, half_deg: float = FAR_HALF_DEG, n: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """Outer and inner double arcs (effective board mm) spanning the far half."""
    angles = np.linspace(far_angle_deg - half_deg, far_angle_deg + half_deg, n)
    outer = np.asarray([polar_mm(DOUBLE_OUTER_MM, float(a)) for a in angles], dtype=np.float64)
    inner = np.asarray([polar_mm(DOUBLE_INNER_MM, float(a)) for a in angles], dtype=np.float64)
    return outer, inner
