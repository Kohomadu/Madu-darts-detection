"""Light radial lens model + joint fit with a Board-plane homography (ticket 22).

Observed image points are undistorted with ``(k1, k2)`` about a principal point,
then mapped with ``H`` into board millimetres. Homography-only is ``k1 = k2 = 0``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from madu_darts.calibration.homography import apply_homography, fit_homography


@dataclass(frozen=True)
class RadialParams:
    """Division model: ideal = centre + (obs - centre) / (1 + k1 r² + k2 r⁴)."""

    k1: float = 0.0
    k2: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    #: Normalises pixel radius so k1/k2 stay O(1); typically max(image width, height).
    scale: float = 1.0

    @property
    def is_identity(self) -> bool:
        return abs(self.k1) < 1e-12 and abs(self.k2) < 1e-12


def principal_from_points(points_px: ArrayLike, *, image_shape: tuple[int, int] | None = None) -> tuple[float, float, float]:
    """``(cx, cy, scale)`` from point cloud, falling back to image centre when given."""
    pts = np.asarray(points_px, dtype=np.float64).reshape(-1, 2)
    if image_shape is not None:
        h, w = int(image_shape[0]), int(image_shape[1])
        return w * 0.5, h * 0.5, float(max(w, h))
    if len(pts) == 0:
        return 0.0, 0.0, 1.0
    cx = float(np.mean(pts[:, 0]))
    cy = float(np.mean(pts[:, 1]))
    span = float(np.max(np.linalg.norm(pts - np.array([cx, cy]), axis=1)))
    return cx, cy, max(span, 1.0)


def undistort_points(points_px: ArrayLike, radial: RadialParams | None) -> np.ndarray:
    """Observed pixels → ideal (undistorted) pixels."""
    pts = np.asarray(points_px, dtype=np.float64)
    single = pts.ndim == 1
    pts = pts.reshape(-1, 2)
    if radial is None or radial.is_identity:
        out = pts.copy()
        return out[0] if single else out
    scale = max(float(radial.scale), 1e-6)
    dx = pts[:, 0] - radial.cx
    dy = pts[:, 1] - radial.cy
    # Iterate: obs = centre + ideal_delta * (1 + k1 r² + k2 r⁴)
    ix, iy = dx.copy(), dy.copy()
    for _ in range(8):
        r2 = (ix * ix + iy * iy) / (scale * scale)
        factor = 1.0 + radial.k1 * r2 + radial.k2 * r2 * r2
        factor = np.where(np.abs(factor) < 1e-8, 1e-8, factor)
        ix = dx / factor
        iy = dy / factor
    out = np.column_stack([radial.cx + ix, radial.cy + iy])
    return out[0] if single else out


def distort_points(points_px: ArrayLike, radial: RadialParams | None) -> np.ndarray:
    """Ideal pixels → observed (distorted) pixels."""
    pts = np.asarray(points_px, dtype=np.float64)
    single = pts.ndim == 1
    pts = pts.reshape(-1, 2)
    if radial is None or radial.is_identity:
        out = pts.copy()
        return out[0] if single else out
    scale = max(float(radial.scale), 1e-6)
    dx = pts[:, 0] - radial.cx
    dy = pts[:, 1] - radial.cy
    r2 = (dx * dx + dy * dy) / (scale * scale)
    factor = 1.0 + radial.k1 * r2 + radial.k2 * r2 * r2
    out = np.column_stack([radial.cx + dx * factor, radial.cy + dy * factor])
    return out[0] if single else out


def image_to_board_mm_radial(
    homography: ArrayLike,
    rotate_offset: int,
    points_px: ArrayLike,
    radial: RadialParams | None = None,
) -> np.ndarray:
    from madu_darts.calibration.homography import effective_homography

    ideal = undistort_points(points_px, radial)
    return apply_homography(effective_homography(homography, rotate_offset), ideal)


def board_mm_to_image_radial(
    homography: ArrayLike,
    rotate_offset: int,
    points_mm: ArrayLike,
    radial: RadialParams | None = None,
) -> np.ndarray:
    from madu_darts.calibration.homography import effective_homography

    ideal = apply_homography(np.linalg.inv(effective_homography(homography, rotate_offset)), points_mm)
    return distort_points(ideal, radial)


_K1_MIN, _K1_MAX = -0.45, 0.45
_K2_MIN, _K2_MAX = -0.25, 0.25


def _clamp_k(k1: float, k2: float) -> tuple[float, float]:
    return float(np.clip(k1, _K1_MIN, _K1_MAX)), float(np.clip(k2, _K2_MIN, _K2_MAX))


def _sample_errors(
    homography: np.ndarray, points_px: np.ndarray, points_mm: np.ndarray, radial: RadialParams
) -> np.ndarray:
    mapped = image_to_board_mm_radial(homography, 0, points_px, radial).reshape(-1, 2)
    target = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    return np.linalg.norm(mapped - target, axis=1)


def _rms_mm(homography: np.ndarray, points_px: np.ndarray, points_mm: np.ndarray, radial: RadialParams) -> float:
    err = _sample_errors(homography, points_px, points_mm, radial)
    return float(np.sqrt(np.mean(err**2))) if len(err) else float("inf")


def _objective_mm(
    homography: np.ndarray, points_px: np.ndarray, points_mm: np.ndarray, radial: RadialParams
) -> float:
    """RMS with far-double annulus samples up-weighted (ticket 22 success metric)."""
    from madu_darts.board import DOUBLE_INNER_MM, DOUBLE_OUTER_MM

    err = _sample_errors(homography, points_px, points_mm, radial)
    if len(err) == 0:
        return float("inf")
    rad = np.hypot(points_mm[:, 0], points_mm[:, 1])
    on_double = (rad >= DOUBLE_INNER_MM - 4.0) & (rad <= DOUBLE_OUTER_MM + 4.0)
    # Cheap foreshortening proxy: smallest |y| board samples ≈ far under tilt_top mounts.
    weights = np.ones(len(err), dtype=np.float64)
    if int(on_double.sum()) > 0:
        # Up-weight double samples; among them prefer the outer half of the cloud.
        weights[on_double] = 3.0
        yy = points_mm[on_double, 1]
        far_half = yy <= float(np.median(yy))
        idx = np.flatnonzero(on_double)
        weights[idx[far_half]] = 5.0
    return float(np.sqrt(np.average(err**2, weights=weights)))


def _fit_h_on_undistorted(
    points_px: np.ndarray,
    points_mm: np.ndarray,
    radial: RadialParams,
    *,
    ransac_threshold_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    ideal = undistort_points(points_px, radial)
    return fit_homography(ideal, points_mm, ransac_threshold_mm=ransac_threshold_mm)


def _polish_h(points_px: np.ndarray, points_mm: np.ndarray, radial: RadialParams, seed_h: np.ndarray) -> np.ndarray:
    try:
        import cv2

        ideal = undistort_points(points_px, radial).astype(np.float32)
        h_ls, _ = cv2.findHomography(ideal, points_mm.astype(np.float32), 0)
        if h_ls is not None:
            return np.asarray(h_ls, dtype=np.float64)
    except Exception:
        pass
    try:
        h_new, _ = _fit_h_on_undistorted(points_px, points_mm, radial, ransac_threshold_mm=5.0)
        return h_new
    except ValueError:
        return seed_h


def fit_joint_homography_radial(
    points_px: ArrayLike,
    points_mm: ArrayLike,
    *,
    seed_homography: ArrayLike | None = None,
    ransac_threshold_mm: float = 2.0,
    image_shape: tuple[int, int] | None = None,
    max_iters: int = 8,
) -> tuple[np.ndarray, RadialParams, np.ndarray]:
    """Joint ``H`` + ``(k1, k2)`` on correspondences.

    Returns ``(homography, radial, inlier_mask)`` where the mask is from the
    final undistorted RANSAC (or all-true when using a seed H polish only).
    """
    px = np.asarray(points_px, dtype=np.float64).reshape(-1, 2)
    mm = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    if len(px) < 8 or len(px) != len(mm):
        raise ValueError("need ≥8 matching correspondences")

    cx, cy, scale = principal_from_points(px, image_shape=image_shape)
    radial = RadialParams(k1=0.0, k2=0.0, cx=cx, cy=cy, scale=scale)

    if seed_homography is not None:
        h = np.asarray(seed_homography, dtype=np.float64).copy()
        inliers = np.ones(len(px), dtype=bool)
    else:
        h, inliers = fit_homography(px, mm, ransac_threshold_mm=ransac_threshold_mm)

    if int(inliers.sum()) < 8:
        return h, radial, inliers

    px_in = px[inliers]
    mm_in = mm[inliers]
    best_h = h
    best_radial = radial
    best_obj = _objective_mm(h, px_in, mm_in, radial)

    k1, k2 = 0.0, 0.0
    step = 0.12
    for _ in range(max_iters):
        radial = RadialParams(k1=k1, k2=k2, cx=cx, cy=cy, scale=scale)
        h_new = _polish_h(px_in, mm_in, radial, best_h)

        def obj(k1_v: float, k2_v: float) -> float:
            kk1, kk2 = _clamp_k(k1_v, k2_v)
            r = RadialParams(k1=kk1, k2=kk2, cx=cx, cy=cy, scale=scale)
            return _objective_mm(h_new, px_in, mm_in, r)

        # Coordinate descent on a shrinking neighbourhood (clamped).
        deltas = (-2.0 * step, -step, -0.5 * step, 0.0, 0.5 * step, step, 2.0 * step)
        best_local = (obj(k1, k2), k1, k2)
        for d1 in deltas:
            for d2 in deltas:
                cand = obj(k1 + d1, k2 + d2)
                if cand < best_local[0]:
                    ck1, ck2 = _clamp_k(k1 + d1, k2 + d2)
                    best_local = (cand, ck1, ck2)
        _, k1, k2 = best_local
        radial = RadialParams(k1=k1, k2=k2, cx=cx, cy=cy, scale=scale)
        h_new = _polish_h(px_in, mm_in, radial, h_new)
        score = _objective_mm(h_new, px_in, mm_in, radial)
        if score < best_obj - 1e-4:
            best_obj = score
            best_h = h_new
            best_radial = radial
            step = max(step * 0.7, 0.02)
        else:
            break

    mapped = image_to_board_mm_radial(best_h, 0, px, best_radial).reshape(-1, 2)
    err = np.linalg.norm(mapped - mm, axis=1)
    mask = err <= ransac_threshold_mm
    if int(mask.sum()) < 8:
        mask = inliers
    return best_h, best_radial, mask


def apply_lens_remap(image: np.ndarray, radial: RadialParams) -> np.ndarray:
    """Distort a synthetic image so a known ``radial`` model is ground truth."""
    import cv2

    h, w = image.shape[:2]
    # Remap: for each observed pixel, sample the ideal (undistorted) source.
    uu, vv = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    obs = np.column_stack([uu.ravel(), vv.ravel()])
    ideal = undistort_points(obs, radial).reshape(h, w, 2)
    map_x = ideal[:, :, 0].astype(np.float32)
    map_y = ideal[:, :, 1].astype(np.float32)
    return cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


__all__ = [
    "RadialParams",
    "apply_lens_remap",
    "board_mm_to_image_radial",
    "distort_points",
    "fit_joint_homography_radial",
    "image_to_board_mm_radial",
    "principal_from_points",
    "undistort_points",
]
