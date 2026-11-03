"""Edge-based Board-plane refinement of a colour-seeded homography (ticket 15).

The colour autofit seeds a homography from ~40 double/treble wire midpoints.
Under LED glare / weak green that seed can bind only one band, or put the
treble ellipse in the wrong place under perspective. This module re-measures
ring and wire edges in the image against WDF geometry and refits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from madu_darts.board import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
)
from madu_darts.calibration.homography import (
    board_mm_to_image,
    fit_homography,
    image_to_board_mm,
    polar_mm,
    reprojection_rms_mm,
    rings_from_homography,
)
from madu_darts.calibration.model import SECTORS, CamCalibration

# Scoring-band midlines + both bull edges + both sides of each thin ring.
_RING_RADII_MM: tuple[float, ...] = (
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
)

_WIRE_SAMPLE_RADII_MM: tuple[float, ...] = (55.0, 80.0, 130.0, 150.0)


@dataclass(frozen=True)
class FitQuality:
    """How well a homography binds the measured Board edges."""

    rms_mm: float
    n_inliers: int
    n_points: int
    rms_double_mm: float | None = None
    rms_treble_mm: float | None = None
    points_px: np.ndarray | None = None
    points_mm: np.ndarray | None = None
    inlier_mask: np.ndarray | None = None
    radial_k1: float = 0.0
    radial_k2: float = 0.0
    principal_px: tuple[float, float] | None = None
    radial_scale: float = 1.0
    #: Homography-only H kept when a joint radial fit won (ticket 22).
    homography_only: np.ndarray | None = None

    @property
    def coverage(self) -> float:
        return self.n_inliers / self.n_points if self.n_points else 0.0

    def radial(self):
        from madu_darts.calibration.distortion import RadialParams

        if abs(self.radial_k1) < 1e-12 and abs(self.radial_k2) < 1e-12:
            return None
        cx, cy = self.principal_px if self.principal_px is not None else (0.0, 0.0)
        return RadialParams(
            k1=float(self.radial_k1),
            k2=float(self.radial_k2),
            cx=float(cx),
            cy=float(cy),
            scale=float(self.radial_scale) if self.radial_scale > 0 else 1.0,
        )


@dataclass(frozen=True)
class RefineParams:
    ring_angles: int = 72
    #: Wide radial scan so a soft colour seed (wrong treble ellipse) still finds real edges.
    ring_scan_min_mm: float = 70.0
    ring_scan_max_mm: float = 185.0
    ring_step_mm: float = 0.5
    #: Max |measured − WDF| board-mm when assigning a peak to a ring.
    ring_assign_mm: float = 10.0
    min_edge_strength: float = 5.0
    wire_search_deg: float = 4.0
    wire_step_deg: float = 0.25
    ransac_threshold_mm: float = 2.0
    min_inliers: int = 40
    max_iters: int = 3
    min_improvement_mm: float = 0.05
    #: Mild near-hemisphere up-weight during LS polish (1.0 = off). Far samples stay.
    near_weight: float = 1.5
    #: Board mount angle (deg clockwise from +y); ``None`` disables near weighting.
    mount_angle_deg: float | None = None
    #: Ticket 22: after H-only refine, try joint ``(k1, k2)`` + H on the same edges.
    fit_radial: bool = True


def _gray(image: np.ndarray) -> np.ndarray:
    import cv2

    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _sample_bilinear(gray: np.ndarray, u: float, v: float) -> float | None:
    h, w = gray.shape[:2]
    if u < 1.0 or v < 1.0 or u >= w - 2 or v >= h - 2:
        return None
    x0, y0 = int(math.floor(u)), int(math.floor(v))
    dx, dy = u - x0, v - y0
    p00 = float(gray[y0, x0])
    p10 = float(gray[y0, x0 + 1])
    p01 = float(gray[y0 + 1, x0])
    p11 = float(gray[y0 + 1, x0 + 1])
    return (1 - dx) * (1 - dy) * p00 + dx * (1 - dy) * p10 + (1 - dx) * dy * p01 + dx * dy * p11


def _radial_profile(
    gray: np.ndarray,
    homography: np.ndarray,
    angle_deg: float,
    radii_mm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Intensity samples along one Board-plane ray; returns ``(valid_mask, values)``."""
    vals = np.zeros(len(radii_mm), dtype=np.float64)
    valid = np.zeros(len(radii_mm), dtype=bool)
    for i, r in enumerate(radii_mm):
        px = board_mm_to_image(homography, 0, polar_mm(float(r), angle_deg))
        sample = _sample_bilinear(gray, float(px[0]), float(px[1]))
        if sample is not None:
            vals[i] = sample
            valid[i] = True
    return valid, vals


def _local_edge_peaks(
    radii_mm: np.ndarray,
    values: np.ndarray,
    valid: np.ndarray,
    *,
    min_strength: float,
) -> list[tuple[float, float]]:
    """``(radius_mm, strength)`` peaks of |dI/dr| along a sampled ray."""
    deriv = np.zeros(len(radii_mm), dtype=np.float64)
    for i in range(1, len(radii_mm) - 1):
        if valid[i - 1] and valid[i + 1]:
            deriv[i] = abs(values[i + 1] - values[i - 1])
    peaks: list[tuple[float, float]] = []
    for i in range(2, len(radii_mm) - 2):
        if not valid[i] or deriv[i] < min_strength:
            continue
        if deriv[i] >= deriv[i - 1] and deriv[i] >= deriv[i + 1]:
            peaks.append((float(radii_mm[i]), float(deriv[i])))
    return peaks


def _near_scoring_colour(
    bands: np.ndarray,
    u: float,
    v: float,
    radius_px: int = 5,
) -> bool:
    """True when a neighbourhood still has warm/green band pixels (rejects table/surround edges)."""
    h, w = bands.shape
    x, y = int(round(u)), int(round(v))
    x0, x1 = max(0, x - radius_px), min(w, x + radius_px + 1)
    y0, y1 = max(0, y - radius_px), min(h, y + radius_px + 1)
    if x1 <= x0 or y1 <= y0:
        return False
    return bool((bands[y0:y1, x0:x1] > 0).any())


def measure_ring_edges(
    image: np.ndarray,
    homography: np.ndarray,
    params: RefineParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """``(N,2)`` image px and Board-mm targets on WDF ring edges.

    Scans a wide radial window per angle and assigns each strong peak to the
    nearest WDF radius. That recovers treble edges even when the colour seed's
    treble ellipse was concentrically misplaced (ticket 15 cam0).
    """
    import cv2

    from madu_darts.calibration.autofit import colour_masks

    p = params or RefineParams()
    gray = _gray(image)
    warm, green = colour_masks(image)
    bands = cv2.bitwise_or(warm, green)
    px_list: list[tuple[float, float]] = []
    mm_list: list[tuple[float, float]] = []
    radii = np.arange(p.ring_scan_min_mm, p.ring_scan_max_mm + p.ring_step_mm * 0.5, p.ring_step_mm)
    step = 360.0 / p.ring_angles
    for k in range(p.ring_angles):
        angle = k * step
        valid, vals = _radial_profile(gray, homography, angle, radii)
        if int(valid.sum()) < 10:
            continue
        peaks = _local_edge_peaks(radii, vals, valid, min_strength=p.min_edge_strength)
        if not peaks:
            continue
        assigned: dict[float, tuple[float, float, float]] = {}
        for measured_r, strength in sorted(peaks, key=lambda t: -t[1]):
            target = min(_RING_RADII_MM, key=lambda r: abs(r - measured_r))
            if abs(target - measured_r) > p.ring_assign_mm:
                continue
            pix = board_mm_to_image(homography, 0, polar_mm(measured_r, angle))
            # Scoring rings are coloured; reject wood / surround chrome edges.
            if not _near_scoring_colour(bands, float(pix[0]), float(pix[1])):
                continue
            prev = assigned.get(target)
            if prev is None or strength > prev[1]:
                assigned[target] = (measured_r, strength, target)
        for measured_r, _strength, target in assigned.values():
            pix = board_mm_to_image(homography, 0, polar_mm(measured_r, angle))
            px_list.append((float(pix[0]), float(pix[1])))
            mm_list.append(polar_mm(target, angle))
    if not px_list:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.asarray(px_list, dtype=np.float64), np.asarray(mm_list, dtype=np.float64)


def measure_wire_edges(
    image: np.ndarray,
    homography: np.ndarray,
    params: RefineParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """``(N,2)`` image px and Board-mm targets on sector wires."""
    p = params or RefineParams()
    gray = _gray(image)
    px_list: list[tuple[float, float]] = []
    mm_list: list[tuple[float, float]] = []
    wire_angles = [9.0 + 18.0 * k for k in range(SECTORS)]
    for wire_a in wire_angles:
        angles = np.arange(
            wire_a - p.wire_search_deg,
            wire_a + p.wire_search_deg + p.wire_step_deg * 0.5,
            p.wire_step_deg,
        )
        for r in _WIRE_SAMPLE_RADII_MM:
            samples = []
            for a in angles:
                pix = board_mm_to_image(homography, 0, polar_mm(r, float(a)))
                val = _sample_bilinear(gray, float(pix[0]), float(pix[1]))
                samples.append(val)
            if any(v is None for v in samples):
                continue
            arr = np.asarray(samples, dtype=np.float64)
            # Wire = local intensity minimum (dark metal on bright sisal / coloured ring).
            i_min = int(np.argmin(arr))
            if arr[i_min] > float(np.median(arr)) - 8.0:
                continue  # not a clear dark crossing
            measured_a = float(angles[i_min])
            if abs(((measured_a - wire_a + 180.0) % 360.0) - 180.0) > p.wire_search_deg * 0.9:
                continue
            pix = board_mm_to_image(homography, 0, polar_mm(r, measured_a))
            px_list.append((float(pix[0]), float(pix[1])))
            mm_list.append(polar_mm(r, wire_a))
    if not px_list:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.asarray(px_list, dtype=np.float64), np.asarray(mm_list, dtype=np.float64)


def measure_board_edges(
    image: np.ndarray,
    homography: np.ndarray,
    params: RefineParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Combine ring + wire edge measurements for a seed homography."""
    r_px, r_mm = measure_ring_edges(image, homography, params)
    w_px, w_mm = measure_wire_edges(image, homography, params)
    if len(r_px) == 0 and len(w_px) == 0:
        return np.zeros((0, 2)), np.zeros((0, 2))
    if len(r_px) == 0:
        return w_px, w_mm
    if len(w_px) == 0:
        return r_px, r_mm
    return np.vstack([r_px, w_px]), np.vstack([r_mm, w_mm])


def evaluate_fit(
    homography: np.ndarray,
    points_px: np.ndarray,
    points_mm: np.ndarray,
    *,
    ransac_threshold_mm: float = 2.0,
    radial=None,
    homography_only: np.ndarray | None = None,
) -> FitQuality:
    """RMS / inlier stats for a fixed H against measured correspondences."""
    if len(points_px) == 0:
        return FitQuality(rms_mm=float("inf"), n_inliers=0, n_points=0)
    mapped = image_to_board_mm(homography, 0, points_px, radial).reshape(-1, 2)
    target = np.asarray(points_mm, dtype=np.float64).reshape(-1, 2)
    err = np.linalg.norm(mapped - target, axis=1)
    mask = err <= ransac_threshold_mm
    n_in = int(mask.sum())
    if n_in == 0:
        rms = float(np.sqrt(np.mean(err**2)))
    else:
        rms = float(np.sqrt(np.mean(err[mask] ** 2)))
    # Per-band: classify by target radius.
    rad = np.hypot(target[:, 0], target[:, 1])
    double_m = (rad >= 150.0) & mask
    treble_m = (rad >= 90.0) & (rad <= 120.0) & mask
    rms_d = float(np.sqrt(np.mean(err[double_m] ** 2))) if int(double_m.sum()) else None
    rms_t = float(np.sqrt(np.mean(err[treble_m] ** 2))) if int(treble_m.sum()) else None
    k1 = float(getattr(radial, "k1", 0.0) or 0.0) if radial is not None else 0.0
    k2 = float(getattr(radial, "k2", 0.0) or 0.0) if radial is not None else 0.0
    principal = None
    scale = 1.0
    if radial is not None:
        principal = (float(radial.cx), float(radial.cy))
        scale = float(radial.scale)
    return FitQuality(
        rms_mm=rms,
        n_inliers=n_in,
        n_points=len(points_px),
        rms_double_mm=rms_d,
        rms_treble_mm=rms_t,
        points_px=points_px,
        points_mm=points_mm,
        inlier_mask=mask,
        radial_k1=k1,
        radial_k2=k2,
        principal_px=principal,
        radial_scale=scale,
        homography_only=homography_only,
    )


def _far_double_rms(
    homography: np.ndarray,
    points_px: np.ndarray,
    points_mm: np.ndarray,
    *,
    radial=None,
) -> float:
    from madu_darts.calibration.residuals import residual_field_from_correspondences, summarize_residuals

    field = residual_field_from_correspondences(homography, points_px, points_mm, radial=radial)
    if field is None:
        return float("inf")
    far = summarize_residuals(field, homography, 0, radial=radial).get("farDouble")
    if far is None or far.get("rmsMm") is None:
        return float("inf")
    return float(far["rmsMm"])


def refine_homography(
    image: np.ndarray,
    seed: np.ndarray,
    params: RefineParams | None = None,
) -> tuple[np.ndarray, FitQuality]:
    """Iterate edge measurement → RANSAC refit starting from ``seed`` H.

    Returns the refined homography and quality against the *final* measurement
    set. If measurement/refit cannot improve the seed, the seed is kept and
    evaluated on whatever edges were found. When ``params.fit_radial`` is set,
    a joint ``(k1, k2)`` + H polish follows the H-only pass (ticket 22).
    """
    p = params or RefineParams()
    h = np.asarray(seed, dtype=np.float64).copy()
    best_h = h
    best_q = FitQuality(rms_mm=float("inf"), n_inliers=0, n_points=0)

    for _ in range(p.max_iters):
        px, mm = measure_board_edges(image, h, p)
        if len(px) < 8:
            break
        try:
            h_new, inliers = fit_homography(px, mm, ransac_threshold_mm=p.ransac_threshold_mm)
        except ValueError:
            break
        n_in = int(inliers.sum())
        if n_in < max(8, p.min_inliers // 4):
            # Still evaluate so the caller sees coverage of the seed.
            q = evaluate_fit(h, px, mm, ransac_threshold_mm=p.ransac_threshold_mm)
            if q.n_inliers > best_q.n_inliers or (
                q.n_inliers == best_q.n_inliers and q.rms_mm < best_q.rms_mm
            ):
                best_q = q
            break
        # Polish: least-squares on RANSAC inliers (OpenCV method 0).
        # Mild near-hemisphere up-weight: duplicate near inliers; never drop far ones.
        if n_in >= 8:
            try:
                import cv2

                px_in = px[inliers]
                mm_in = mm[inliers]
                if p.near_weight > 1.0 and p.mount_angle_deg is not None and len(mm_in):
                    tip_a = float(p.mount_angle_deg) % 360.0
                    ang = np.degrees(np.arctan2(mm_in[:, 0], mm_in[:, 1]))
                    ang = np.where(ang < 0.0, ang + 360.0, ang)
                    dist = np.minimum(np.abs(ang - tip_a) % 360.0, 360.0 - (np.abs(ang - tip_a) % 360.0))
                    near = dist <= 90.0
                    if int(near.sum()) > 0:
                        # Integer weight via stacking (OpenCV findHomography has no weights).
                        extra = max(1, int(round(p.near_weight)) - 1)
                        px_in = np.vstack([px_in] + [px_in[near]] * extra)
                        mm_in = np.vstack([mm_in] + [mm_in[near]] * extra)
                h_ls, _ = cv2.findHomography(
                    px_in.astype(np.float32),
                    mm_in.astype(np.float32),
                    0,
                )
                if h_ls is not None:
                    h_new = np.asarray(h_ls, dtype=np.float64)
            except Exception:
                pass
        q = evaluate_fit(h_new, px, mm, ransac_threshold_mm=p.ransac_threshold_mm)
        improved = q.n_inliers > best_q.n_inliers or (
            q.n_inliers >= best_q.n_inliers and q.rms_mm < best_q.rms_mm - p.min_improvement_mm
        )
        if not improved and best_q.n_points > 0:
            break
        best_h, best_q = h_new, q
        h = h_new

    if best_q.n_points == 0:
        # Last chance: measure once against the seed for a quality report.
        px, mm = measure_board_edges(image, best_h, p)
        if len(px):
            best_q = evaluate_fit(best_h, px, mm, ransac_threshold_mm=p.ransac_threshold_mm)

    if (
        p.fit_radial
        and best_q.points_px is not None
        and best_q.points_mm is not None
        and best_q.n_inliers >= 16
    ):
        from madu_darts.calibration.distortion import fit_joint_homography_radial

        px = best_q.points_px
        mm = best_q.points_mm
        h_only = best_h
        try:
            h_joint, radial, mask = fit_joint_homography_radial(
                px,
                mm,
                seed_homography=h_only,
                ransac_threshold_mm=p.ransac_threshold_mm,
                image_shape=image.shape[:2],
            )
        except ValueError:
            return best_h, best_q
        if radial.is_identity:
            return best_h, best_q
        far_only = _far_double_rms(h_only, px, mm)
        far_joint = _far_double_rms(h_joint, px, mm, radial=radial)
        # Keep joint when it helps the foreshortened double (ticket 22 success metric).
        if math.isfinite(far_joint) and far_joint < far_only - 0.02:
            best_h = h_joint
            best_q = evaluate_fit(
                h_joint,
                px,
                mm,
                ransac_threshold_mm=p.ransac_threshold_mm,
                radial=radial,
                homography_only=h_only,
            )
            from dataclasses import replace

            best_q = replace(best_q, inlier_mask=mask if best_q.inlier_mask is None else best_q.inlier_mask)
    return best_h, best_q


def apply_quality(cal: CamCalibration, quality: FitQuality) -> CamCalibration:
    """Copy fit-quality fields onto a ``CamCalibration`` (rings refreshed from H)."""
    from dataclasses import replace

    if cal.homography is None:
        return cal
    from madu_darts.calibration.residuals import residual_field_from_correspondences

    radial = quality.radial()
    rings = rings_from_homography(cal.homography, radial=radial)
    residuals = None
    if quality.points_px is not None and quality.points_mm is not None and len(quality.points_px):
        residuals = residual_field_from_correspondences(
            cal.homography,
            quality.points_px,
            quality.points_mm,
            quality.inlier_mask,
            radial=radial,
        )
    return replace(
        cal,
        rings=rings,
        rms_mm=quality.rms_mm if math.isfinite(quality.rms_mm) else cal.rms_mm,
        n_inliers=quality.n_inliers,
        n_points=quality.n_points,
        rms_double_mm=quality.rms_double_mm,
        rms_treble_mm=quality.rms_treble_mm,
        residuals=residuals,
        radial_k1=quality.radial_k1,
        radial_k2=quality.radial_k2,
        principal_px=quality.principal_px,
        radial_scale=quality.radial_scale,
        homography_only=quality.homography_only,
    )


__all__ = [
    "FitQuality",
    "RefineParams",
    "apply_quality",
    "evaluate_fit",
    "measure_board_edges",
    "measure_ring_edges",
    "measure_wire_edges",
    "refine_homography",
]
