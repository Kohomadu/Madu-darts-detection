"""Auto-suggest a camera's Board-plane bind from one frame (Autodarts "magic wand").

Pipeline
--------
1. HSV masks for the scoring-band colours. ``red`` means the warm band colour
   (classic red *or* Target-style orange); ``green`` is the cool band colour.
2. Morphological closing merges the 20 wedges of each band into an annulus;
   contours-with-holes are scored against WDF area ratios so a lit surround /
   number ring is not mistaken for the double.
3. Walk each band around the bull and read warm/cool colour; every transition
   is a sector wire → 20 wire points on double + treble with known Board-mm
   positions (up to a multiple of 18°).
4. Pick the warm-banded wedge closest to screen-up as the suggested **20**
   (20's double/treble are the warm colour on every standard Board), then
   RANSAC-fit the homography. The operator corrects remaining ambiguity with
   rotate-20.

Only the ideas from open peers are reused; no third-party code is copied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from madu_darts.board import DOUBLE_INNER_MM, DOUBLE_OUTER_MM, TREBLE_INNER_MM, TREBLE_OUTER_MM
from madu_darts.calibration.homography import (
    fit_homography,
    polar_mm,
    reprojection_rms_mm,
    rings_from_homography,
    wire_angles_deg,
)
from madu_darts.calibration.model import (
    PASS_RMS_MM,
    SECTORS,
    WARN_MIN_COVERAGE,
    WARN_MIN_INLIERS,
    WARN_RMS_MM,
    CamCalibration,
    Ellipse,
    FitStatus,
    far_double_status,
)
from madu_darts.calibration.refine import FitQuality, RefineParams, apply_quality, refine_homography
from madu_darts.calibration.residuals import residual_field_from_correspondences, summarize_residuals

_DOUBLE_MID_MM = (DOUBLE_INNER_MM + DOUBLE_OUTER_MM) / 2.0  # 166.0
_TREBLE_MID_MM = (TREBLE_INNER_MM + TREBLE_OUTER_MM) / 2.0  # 103.4

# Expected area ratios (circle areas scale with r²).
_RATIO_DOUBLE_INNER = (DOUBLE_INNER_MM / DOUBLE_OUTER_MM) ** 2  # ~0.908
_RATIO_TREBLE_OUTER = (TREBLE_OUTER_MM / DOUBLE_OUTER_MM) ** 2  # ~0.399
_RATIO_TREBLE_HOLE = (TREBLE_INNER_MM / TREBLE_OUTER_MM) ** 2  # ~0.856

NONE, RED, GREEN, GAP = 0, 1, 2, 3  # RED == warm band (red or orange)


class AutoFitError(ValueError):
    """Auto-fit could not bind this frame to the Board plane; ``reason`` explains why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AutoFitParams:
    """Tunable knobs; defaults cover classic red/green and Target-style orange/green."""

    # Warm band (red…orange). Live Target Board peaks around H=6–13.
    red_hue_max: int = 20
    red_hue_wrap_min: int = 170
    green_hue_min: int = 35
    green_hue_max: int = 95
    min_saturation: int = 50
    min_value: int = 40
    close_kernel_px: int = 15
    min_band_area_px: float = 2000.0
    min_bull_area_px: float = 80.0
    ratio_tolerance: float = 0.20
    ring_samples: int = 1440
    min_run_deg: float = 2.0
    max_wire_match_deg: float = 12.0
    ransac_threshold_mm: float = 3.0
    min_inliers: int = 28
    #: Ticket 15: edge-refine the colour-seeded H (disable for pure colour tests).
    refine: bool = True
    refine_iters: int = 3


@dataclass(frozen=True)
class DetectedRings:
    """Ring ellipses measured directly from the colour masks (pre-homography)."""

    bull: tuple[float, float]
    double_outer: Ellipse
    double_inner: Ellipse
    treble_outer: Ellipse
    treble_inner: Ellipse


@dataclass(frozen=True)
class WirePoints:
    """Sector-wire crossings on both bands, ordered clockwise from the suggested 20."""

    double_px: np.ndarray
    """``(20, 2)`` image points on the double band; index 0 is the wire at board 9°."""
    treble_px: np.ndarray
    """``(20, 2)`` image points on the treble band, same order."""
    screen_angles_deg: np.ndarray
    """``(20,)`` screen angles of the wires around the bull (image coords, v down)."""

    @property
    def double_mm(self) -> np.ndarray:
        return np.asarray([polar_mm(_DOUBLE_MID_MM, a) for a in wire_angles_deg()])

    @property
    def treble_mm(self) -> np.ndarray:
        return np.asarray([polar_mm(_TREBLE_MID_MM, a) for a in wire_angles_deg()])


# --- step 1: colour masks ---


def colour_masks(image: np.ndarray, params: AutoFitParams | None = None) -> tuple[np.ndarray, np.ndarray]:
    """``(warm, green)`` uint8 masks (0/255) of the scoring-band colours.

    ``warm`` covers classic red and Target-style orange doubles/trebles/bulls.
    """
    import cv2

    p = params or AutoFitParams()
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vivid = (s >= p.min_saturation) & (v >= p.min_value)
    warm = vivid & ((h <= p.red_hue_max) | (h >= p.red_hue_wrap_min))
    green = vivid & (h >= p.green_hue_min) & (h <= p.green_hue_max)
    return warm.astype(np.uint8) * 255, green.astype(np.uint8) * 255


# --- step 2: rings from closed band mask ---


@dataclass(frozen=True)
class _Annulus:
    outer_idx: int
    hole_idx: int
    outer_area: float
    hole_area: float

    @property
    def ratio(self) -> float:
        return self.hole_area / self.outer_area if self.outer_area > 0 else 0.0


def _ellipse_of(contour: np.ndarray) -> Ellipse:
    import cv2

    if len(contour) < 5:
        raise AutoFitError("ring contour too small to fit an ellipse")
    return Ellipse.from_cv(cv2.fitEllipse(contour))


def _within(ratio: float, expected: float, tolerance: float) -> bool:
    return abs(ratio - expected) <= tolerance * expected


def _relative_error(value: float, expected: float) -> float:
    return abs(value - expected) / expected if expected else float("inf")


def _annuli_from_hierarchy(contours: list, hier: np.ndarray, min_area: float) -> list[_Annulus]:
    import cv2

    out: list[_Annulus] = []
    for i, contour in enumerate(contours):
        if hier[i][3] >= 0:  # not a top-level contour
            continue
        outer_area = cv2.contourArea(contour)
        if outer_area < min_area:
            continue
        child = hier[i][2]
        best: tuple[float, int] | None = None
        while child >= 0:
            area = cv2.contourArea(contours[child])
            if best is None or area > best[0]:
                best = (area, child)
            child = hier[child][0]
        if best is None or best[0] < min_area * 0.2:
            continue
        out.append(_Annulus(outer_idx=i, hole_idx=best[1], outer_area=outer_area, hole_area=best[0]))
    return out


def _scaled_ellipse(outer: Ellipse, radius_mm: float, reference_mm: float = DOUBLE_OUTER_MM) -> Ellipse:
    """Concentric ellipse sharing centre/angle, scaled by WDF radius ratio."""
    scale = radius_mm / reference_mm
    return Ellipse(
        cx=outer.cx,
        cy=outer.cy,
        width=outer.width * scale,
        height=outer.height * scale,
        angle=outer.angle,
    )


def _bull_from_closed_contours(
    contours: list,
    hierarchy: np.ndarray,
    near: tuple[float, float],
    *,
    min_area: float,
    max_area: float,
    max_dist_px: float,
) -> tuple[float, float] | None:
    """Bull is the small filled top-level blob nearest ``near`` after band wedges have been closed."""
    import cv2

    best: tuple[float, tuple[float, float]] | None = None
    for i, contour in enumerate(contours):
        if hierarchy[i][3] >= 0:
            continue  # only top-level
        if hierarchy[i][2] >= 0:
            continue  # annuli have holes; bull is a filled disk
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            continue
        centre = (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])
        dist = math.hypot(centre[0] - near[0], centre[1] - near[1])
        if dist > max_dist_px:
            continue
        if best is None or dist < best[0]:
            best = (dist, centre)
    return None if best is None else best[1]


def _bull_inside_ellipse(ellipse: Ellipse, bull: tuple[float, float], max_norm: float = 0.45) -> bool:
    """True when ``bull`` lies well inside ``ellipse`` (normalised ellipse radius)."""
    theta = math.radians(ellipse.angle)
    ct, st = math.cos(theta), math.sin(theta)
    dx, dy = bull[0] - ellipse.cx, bull[1] - ellipse.cy
    x = dx * ct + dy * st
    y = -dx * st + dy * ct
    a, b = ellipse.width / 2.0, ellipse.height / 2.0
    if a <= 1 or b <= 1:
        return False
    return (x / a) ** 2 + (y / b) ** 2 <= max_norm**2


def _rings_from_outer_ellipse(outer: Ellipse, bull: tuple[float, float] | None = None) -> DetectedRings:
    """Outer ellipse + WDF-scaled rings. Treble is concentric here on purpose:

    A provisional H that labels outer-ellipse samples with screen angles is
    wrong under tilt (screen angle ≠ board angle). Edge refinement after the
    colour seed (ticket 15) is what places the treble correctly.
    """
    origin = bull if bull is not None else (outer.cx, outer.cy)
    if bull is not None and not _bull_inside_ellipse(outer, bull, max_norm=0.75):
        raise AutoFitError("outer envelope does not surround the bull; ring detection inconsistent")
    return DetectedRings(
        bull=origin,
        double_outer=outer,
        double_inner=_scaled_ellipse(outer, DOUBLE_INNER_MM),
        treble_outer=_scaled_ellipse(outer, TREBLE_OUTER_MM),
        treble_inner=_scaled_ellipse(outer, TREBLE_INNER_MM),
    )


def _rings_from_double_annulus(
    contours: list,
    hierarchy: np.ndarray,
    double: _Annulus,
    min_bull_area: float,
) -> DetectedRings:
    """Double annulus from colour; treble rings scaled from WDF radii (weak-green Boards)."""
    double_outer = _ellipse_of(contours[double.outer_idx])
    double_inner = _ellipse_of(contours[double.hole_idx])
    bull = _bull_from_closed_contours(
        contours,
        hierarchy,
        (double_outer.cx, double_outer.cy),
        min_area=min_bull_area,
        max_area=double.outer_area * 0.2,
        max_dist_px=0.35 * max(double_outer.width, double_outer.height),
    )
    origin = bull if bull is not None else (double_outer.cx, double_outer.cy)
    if bull is not None and not _bull_inside_ellipse(double_outer, bull):
        origin = (double_outer.cx, double_outer.cy)
    return DetectedRings(
        bull=origin,
        double_outer=double_outer,
        double_inner=double_inner,
        treble_outer=_scaled_ellipse(double_outer, TREBLE_OUTER_MM),
        treble_inner=_scaled_ellipse(double_outer, TREBLE_INNER_MM),
    )


def _best_annulus_pair(
    contours: list,
    hierarchy: np.ndarray,
    annuli: list[_Annulus],
    tolerance: float,
    min_bull_area: float,
) -> DetectedRings | None:
    """Pick double+treble by WDF outer-area ratio; hole ratios are soft (morphology warps them)."""
    if not annuli:
        return None
    best: tuple[float, _Annulus, _Annulus] | None = None
    for double in annuli:
        for treble in annuli:
            if treble.outer_idx == double.outer_idx:
                continue
            if treble.outer_area >= double.outer_area * 0.9:
                continue
            if double.ratio < 0.55 or treble.ratio < 0.55:
                continue  # reject filled blobs / tiny holes
            area_err = _relative_error(treble.outer_area / double.outer_area, _RATIO_TREBLE_OUTER)
            # Soft preference for WDF-like hole ratios, but area pairing dominates.
            hole_err = 0.25 * (
                _relative_error(double.ratio, _RATIO_DOUBLE_INNER) + _relative_error(treble.ratio, _RATIO_TREBLE_HOLE)
            )
            score = area_err + hole_err
            if best is None or score < best[0]:
                best = (score, double, treble)
    if best is not None and best[0] <= tolerance * 2.5:
        _, double, treble = best
        double_outer = _ellipse_of(contours[double.outer_idx])
        # Ray origin must be the projected bull, not the ellipse centre — under
        # perspective those differ, and wires are radial only from the true origin.
        bull = _bull_from_closed_contours(
            contours,
            hierarchy,
            (double_outer.cx, double_outer.cy),
            min_area=min_bull_area,
            max_area=treble.outer_area * 0.5,
            max_dist_px=0.35 * max(double_outer.width, double_outer.height),
        )
        origin = bull if bull is not None else (double_outer.cx, double_outer.cy)
        return DetectedRings(
            bull=origin,
            double_outer=double_outer,
            double_inner=_ellipse_of(contours[double.hole_idx]),
            treble_outer=_ellipse_of(contours[treble.outer_idx]),
            treble_inner=_ellipse_of(contours[treble.hole_idx]),
        )

    # Weak green: accept a double-like annulus alone and scale treble.
    # Prefer hole ratios near the double (~0.91); allow down to ~0.75 when that
    # annulus is clearly the largest high-ratio band (orange Boards under LEDs).
    preferred = [
        a
        for a in annuli
        if a.ratio >= 0.88 and _relative_error(a.ratio, _RATIO_DOUBLE_INNER) < tolerance * 3.0
    ]
    if preferred:
        return _rings_from_double_annulus(
            contours, hierarchy, max(preferred, key=lambda a: a.outer_area), min_bull_area
        )
    loose = [a for a in annuli if a.ratio >= 0.75]
    if loose:
        largest = max(loose, key=lambda a: a.outer_area)
        huge = max(annuli, key=lambda a: a.outer_area)
        # Only fall back to a lone high-ratio annulus when nothing much larger exists
        # (otherwise the high-ratio band is usually the treble inside a merged double).
        if largest.outer_area >= 0.35 * huge.outer_area:
            return _rings_from_double_annulus(contours, hierarchy, largest, min_bull_area)
    return None


def _outer_ellipse_from_mask(bands: np.ndarray) -> Ellipse:
    """Fit the outer double from the colour-mask envelope (fallback when annuli are messy)."""
    import cv2

    # Light close so fragmented wedges touch, then take the largest external contour.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    closed = cv2.morphologyEx(bands, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise AutoFitError("no coloured envelope to fit an outer ellipse")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 2000 or len(contour) < 5:
        raise AutoFitError("coloured envelope too small for ellipse fit")
    return _ellipse_of(contour)


def detect_rings(image: np.ndarray, params: AutoFitParams | None = None) -> DetectedRings:
    """Locate the double/treble bands and bull by colour; raise ``AutoFitError`` if unsure.

    Tries several close kernels and picks a double/treble annulus pair by WDF
    area ratio. If colour fragments (weak green under LED, orange Board) never
    form clean annuli, falls back to fitting the outer envelope and scaling the
    remaining rings from WDF radii.
    """
    import cv2

    p = params or AutoFitParams()
    warm, green = colour_masks(image, p)
    bands = cv2.bitwise_or(warm, green)
    if int(bands.sum()) < p.min_band_area_px * 255:
        raise AutoFitError("coloured regions too small; Board too far or masks too strict")

    frame_h, frame_w = image.shape[:2]

    def _band_coverage(rings: DetectedRings) -> float:
        """Fraction of double-band midpoints that still land on scoring colours."""
        angles = np.arange(0.0, 360.0, 5.0)
        origin = rings.bull
        try:
            mid = (
                ray_ellipse_intersections(rings.double_outer, origin, angles)
                + ray_ellipse_intersections(rings.double_inner, origin, angles)
            ) / 2.0
        except AutoFitError:
            return 0.0
        u = np.rint(mid[:, 0]).astype(int)
        v = np.rint(mid[:, 1]).astype(int)
        inside = (u >= 0) & (u < frame_w) & (v >= 0) & (v < frame_h)
        if not np.any(inside):
            return 0.0
        return float(np.mean(bands[v[inside], u[inside]] > 0))

    def _plausible(rings: DetectedRings) -> bool:
        e = rings.double_outer
        # Steep side cams project the double to a tall ellipse that can exceed the
        # frame height slightly; only reject clearly-impossible fits (2x frame).
        if e.width > frame_w * 2.0 or e.height > frame_h * 2.0:
            return False
        if e.width < 40 or e.height < 40:
            return False
        # Half-visible boards leave large arcs of the double band on empty pixels.
        if _band_coverage(rings) < 0.40:
            return False
        return True

    kernels = sorted({p.close_kernel_px, 9, 11, 15, 19, 23})
    best_pair: DetectedRings | None = None
    best_score = float("inf")
    for k in kernels:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        closed = cv2.morphologyEx(bands, cv2.MORPH_CLOSE, kernel)
        contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if hierarchy is None or not contours:
            continue
        hier = hierarchy[0]
        annuli = _annuli_from_hierarchy(contours, hier, p.min_band_area_px)
        pair = _best_annulus_pair(contours, hier, annuli, p.ratio_tolerance, p.min_bull_area_px)
        if pair is None or not _plausible(pair):
            continue
        # Lower score = tighter treble/double area match; prefer a real bull blob.
        score = _relative_error(
            (pair.treble_outer.width * pair.treble_outer.height)
            / (pair.double_outer.width * pair.double_outer.height),
            _RATIO_TREBLE_OUTER,
        )
        if abs(pair.bull[0] - pair.double_outer.cx) < 1 and abs(pair.bull[1] - pair.double_outer.cy) < 1:
            score += 0.05  # ellipse-centre fallback is slightly worse under tilt
        # WDF-scaled treble (double-only path) matches the ratio exactly — penalise so a
        # real double+treble annulus pair still wins when both are visible.
        if (
            abs(pair.treble_outer.cx - pair.double_outer.cx) < 1.0
            and abs(pair.treble_outer.cy - pair.double_outer.cy) < 1.0
            and abs(pair.treble_outer.angle - pair.double_outer.angle) < 1.0
        ):
            score += 0.25
        if score < best_score:
            best_score = score
            best_pair = pair

    if best_pair is not None:
        return best_pair

    # Fallback: outer envelope + WDF-scaled rings (handles weak green / orange Boards).
    geometry_rejected = False
    try:
        outer = _outer_ellipse_from_mask(bands)
        if outer.width > frame_w * 2.0 or outer.height > frame_h * 2.0:
            geometry_rejected = True
            raise AutoFitError("outer envelope exceeds the frame")
        # One light close so the bull stays a separate filled blob if visible.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        closed = cv2.morphologyEx(bands, cv2.MORPH_CLOSE, kernel)
        contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        bull = None
        if hierarchy is not None and contours:
            bull = _bull_from_closed_contours(
                contours,
                hierarchy[0],
                (outer.cx, outer.cy),
                min_area=p.min_bull_area_px,
                max_area=0.15 * math.pi * (outer.width / 2.0) * (outer.height / 2.0),
                max_dist_px=0.35 * max(outer.width, outer.height),
            )
        rings = _rings_from_outer_ellipse(outer, bull)
        if not _plausible(rings):
            geometry_rejected = True
            raise AutoFitError("outer envelope implausible for this frame")
        return rings
    except AutoFitError:
        pass

    # Classic red/green masks (stricter) — recovers synthetic/noisy frames when the
    # orange-wide defaults merge the surround into one oversized blob. Do not use
    # when the wide mask already found a plausible-sized board (half-visible case).
    if (p.red_hue_max > 12 or p.min_saturation < 70) and (
        geometry_rejected or best_pair is None
    ):
        # If annulus pairing produced candidates that failed only coverage, skip classic.
        if best_pair is None or geometry_rejected:
            classic = AutoFitParams(
                red_hue_max=10,
                red_hue_wrap_min=p.red_hue_wrap_min,
                green_hue_min=p.green_hue_min,
                green_hue_max=min(p.green_hue_max, 90),
                min_saturation=80,
                min_value=50,
                close_kernel_px=9,
                min_band_area_px=max(p.min_band_area_px, 3000.0),
                min_bull_area_px=max(p.min_bull_area_px, 150.0),
                ratio_tolerance=max(p.ratio_tolerance, 0.25),
                ring_samples=p.ring_samples,
                min_run_deg=p.min_run_deg,
                max_wire_match_deg=p.max_wire_match_deg,
                ransac_threshold_mm=p.ransac_threshold_mm,
                min_inliers=p.min_inliers,
            )
            return detect_rings(image, classic)

    raise AutoFitError("could not form double/treble annuli from scoring-band colours")


# --- step 3: wires as colour transitions around each band ---


def ray_ellipse_intersections(ellipse: Ellipse, origin: tuple[float, float], angles_deg: np.ndarray) -> np.ndarray:
    """``(N, 2)`` points where rays from ``origin`` at screen angles hit the ellipse.

    Screen angle is ``atan2(v - oy, u - ox)`` in image coords (v down), so
    increasing angle is clockwise on screen. Origin must lie inside the ellipse.
    """
    ox, oy = origin
    theta = math.radians(ellipse.angle)
    ct, st = math.cos(theta), math.sin(theta)
    a, b = ellipse.width / 2.0, ellipse.height / 2.0
    if a <= 0 or b <= 0:
        raise AutoFitError("degenerate ring ellipse")

    phi = np.radians(np.asarray(angles_deg, dtype=np.float64))
    dx, dy = np.cos(phi), np.sin(phi)
    # Into the ellipse's own frame.
    ox_e, oy_e = ox - ellipse.cx, oy - ellipse.cy
    x0 = ox_e * ct + oy_e * st
    y0 = -ox_e * st + oy_e * ct
    x1 = dx * ct + dy * st
    y1 = -dx * st + dy * ct

    qa = x1**2 / a**2 + y1**2 / b**2
    qb = 2.0 * (x0 * x1 / a**2 + y0 * y1 / b**2)
    qc = x0**2 / a**2 + y0**2 / b**2 - 1.0
    if qc >= 0:
        raise AutoFitError("bull lies outside a fitted ring; ring detection inconsistent")
    disc = qb**2 - 4.0 * qa * qc
    s = (-qb + np.sqrt(disc)) / (2.0 * qa)  # positive root (origin inside)
    return np.column_stack([ox + s * dx, oy + s * dy])


def _classify(red: np.ndarray, green: np.ndarray, points: np.ndarray) -> np.ndarray:
    h, w = red.shape
    u = np.rint(points[:, 0]).astype(int)
    v = np.rint(points[:, 1]).astype(int)
    inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    labels = np.full(len(points), NONE, dtype=int)
    uu, vv = u[inside], v[inside]
    lab = np.where(red[vv, uu] > 0, RED, np.where(green[vv, uu] > 0, GREEN, NONE))
    labels[inside] = lab
    return labels


@dataclass(frozen=True)
class _Run:
    colour: int
    start: int  # sample index (inclusive)
    end: int  # sample index (inclusive), may wrap past n


def _colour_runs(labels: np.ndarray, min_run: int) -> list[_Run]:
    """Cyclic run-length encoding of coloured samples; short runs and NONE dropped,
    same-colour neighbours merged."""
    n = len(labels)
    # Rotate so we start at a NONE or a colour boundary to avoid splitting a run.
    start = 0
    for i in range(n):
        if labels[i] != labels[i - 1]:
            start = i
            break
    rolled = np.roll(labels, -start)

    runs: list[_Run] = []
    i = 0
    while i < n:
        j = i
        while j < n and rolled[j] == rolled[i]:
            j += 1
        if rolled[i] != NONE and (j - i) >= min_run:
            runs.append(_Run(int(rolled[i]), (i + start) % n, (j - 1 + start) % n))
        i = j

    # Merge cyclically adjacent same-colour runs (a wedge split by noise).
    merged: list[_Run] = []
    for run in runs:
        if merged and merged[-1].colour == run.colour:
            merged[-1] = _Run(run.colour, merged[-1].start, run.end)
        else:
            merged.append(run)
    if len(merged) > 1 and merged[0].colour == merged[-1].colour:
        merged[0] = _Run(merged[0].colour, merged[-1].start, merged[0].end)
        merged.pop()
    return merged


def _circular_mid(a_deg: float, b_deg: float) -> float:
    """Midpoint from ``a`` going clockwise (increasing) to ``b``."""
    span = (b_deg - a_deg) % 360.0
    return (a_deg + span / 2.0) % 360.0


def _circular_distance(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 360.0
    return min(d, 360.0 - d)


def _circular_smooth(signal: np.ndarray, sigma: float) -> np.ndarray:
    """1-D Gaussian smooth of a circular signal (OpenCV kernel, no SciPy)."""
    import cv2

    if sigma <= 0:
        return signal.astype(np.float64)
    pad = max(3, int(3 * sigma))
    y = np.r_[signal[-pad:], signal, signal[:pad]].astype(np.float64)
    radius = max(1, int(round(sigma * 2)))
    kernel = cv2.getGaussianKernel(2 * radius + 1, sigma).ravel()
    y = np.convolve(y, kernel, mode="same")
    return y[pad:-pad]


def _warm_fraction_around_double(
    warm: np.ndarray,
    green: np.ndarray,
    rings: DetectedRings,
    params: AutoFitParams,
) -> np.ndarray:
    """Fraction of warm hits across three radii in the double band (length ``ring_samples``)."""
    origin = rings.bull
    n = params.ring_samples
    angles = np.arange(n) * (360.0 / n)
    votes = np.zeros(n, dtype=np.float64)
    for scale in (0.3, 0.5, 0.7):
        pts = (1.0 - scale) * ray_ellipse_intersections(rings.double_inner, origin, angles) + scale * ray_ellipse_intersections(
            rings.double_outer, origin, angles
        )
        labels = _classify(warm, green, pts)
        votes += (labels == RED).astype(np.float64)
    return votes / 3.0


def _threshold_warm_runs(signal: np.ndarray, threshold: float, min_run: int) -> list[_Run]:
    """Warm (above threshold) runs on a circular 1-D signal."""
    binary = np.where(signal >= threshold, RED, GAP)
    n = len(binary)
    start = 0
    for i in range(n):
        if binary[i] != binary[i - 1]:
            start = i
            break
    rolled = np.roll(binary, -start)
    raw: list[_Run] = []
    i = 0
    while i < n:
        j = i
        while j < n and rolled[j] == rolled[i]:
            j += 1
        if rolled[i] == RED and (j - i) >= min_run:
            raw.append(_Run(RED, (i + start) % n, (j - 1 + start) % n))
        i = j
    if not raw:
        return []
    # Merge cyclically adjacent warm runs separated only by dropped gaps.
    merged: list[_Run] = [raw[0]]
    for run in raw[1:]:
        prev = merged[-1]
        gap = (run.start - prev.end - 1) % n
        if gap <= min_run:
            merged[-1] = _Run(RED, prev.start, run.end)
        else:
            merged.append(run)
    if len(merged) > 1:
        gap = (merged[0].start - merged[-1].end - 1) % n
        if gap <= min_run:
            merged[0] = _Run(RED, merged[-1].start, merged[0].end)
            merged.pop()
    return merged


def _ten_warm_runs(signal: np.ndarray) -> list[_Run]:
    """Search smooth/threshold/min-run for exactly ten warm wedges."""
    best: tuple[float, list[_Run]] | None = None
    for sigma in (2.0, 4.0, 6.0, 8.0):
        smooth = _circular_smooth(signal, sigma)
        if float(smooth.max()) <= 0:
            continue
        for thr in (0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6):
            for min_run in (4, 6, 8, 10, 12, 16, 20, 24):
                runs = _threshold_warm_runs(smooth, thr, min_run)
                err = abs(len(runs) - SECTORS // 2)
                score = err + 0.01 * abs(min_run - 12) + 0.001 * abs(sigma - 4.0)
                if best is None or score < best[0]:
                    best = (score, runs)
                if len(runs) == SECTORS // 2:
                    return runs
    n = 0 if best is None else len(best[1])
    raise AutoFitError(f"found {n} warm wedges on a band, expected {SECTORS // 2}")


def _wires_from_warm_runs(warm_runs: list[_Run], n_samples: int) -> np.ndarray:
    """Order 20 wire screen-angles clockwise from the warm wedge nearest screen-up."""
    if len(warm_runs) != SECTORS // 2:
        raise AutoFitError(f"found {len(warm_runs)} warm wedges on a band, expected {SECTORS // 2}")
    step = 360.0 / n_samples
    screen_up = 270.0
    centres = [_circular_mid(run.start * step, run.end * step) for run in warm_runs]
    start_i = min(range(len(warm_runs)), key=lambda i: _circular_distance(centres[i], screen_up))

    wire_raw: list[float] = []
    for run in warm_runs:
        wire_raw.append((run.start * step) % 360.0)
        wire_raw.append((run.end * step) % 360.0)
    if len(wire_raw) != SECTORS:
        raise AutoFitError(f"found {len(wire_raw)} warm-edge wires, expected {SECTORS}")
    start_angle = (warm_runs[start_i].end * step) % 360.0
    return np.asarray(sorted(wire_raw, key=lambda a: (a - start_angle) % 360.0), dtype=np.float64)


def _band_transitions(
    red: np.ndarray,
    green: np.ndarray,
    outer: Ellipse,
    inner: Ellipse,
    origin: tuple[float, float],
    params: AutoFitParams,
) -> tuple[np.ndarray, list[tuple[int, int]], list[float]]:
    """Wire screen angles on one band via alternating warm/green colour runs."""
    n = params.ring_samples
    angles = np.arange(n) * (360.0 / n)
    mid = (ray_ellipse_intersections(outer, origin, angles) + ray_ellipse_intersections(inner, origin, angles)) / 2.0
    labels = _classify(red, green, mid)
    min_run = max(1, int(round(params.min_run_deg / (360.0 / n))))
    runs = _colour_runs(labels, min_run)
    if len(runs) != SECTORS:
        raise AutoFitError(f"found {len(runs)} coloured wedges on a band, expected {SECTORS}")

    step = 360.0 / n
    transitions: list[float] = []
    colours: list[tuple[int, int]] = []
    centres: list[float] = []
    for k, run in enumerate(runs):
        nxt = runs[(k + 1) % SECTORS]
        transitions.append(_circular_mid(run.end * step, nxt.start * step))
        colours.append((run.colour, nxt.colour))
        centres.append(_circular_mid(run.start * step, run.end * step))
    return np.asarray(transitions), colours, centres


def _detect_wire_points_colour(
    image: np.ndarray,
    rings: DetectedRings,
    params: AutoFitParams,
) -> WirePoints:
    """Classic path: 20 alternating warm/green wedges on the double band.

    Treble wires prefer a matched colour run on the treble band; if that band is
    noisy (strong tilt / weak green), the double screen-angles are reused.
    """
    red, green = colour_masks(image, params)
    d_angles, d_colours, d_centres = _band_transitions(
        red, green, rings.double_outer, rings.double_inner, rings.bull, params
    )

    screen_up = 270.0
    candidates = [
        (_circular_distance(d_centres[k], screen_up), k)
        for k in range(SECTORS)
        if d_colours[k] == (RED, GREEN)
    ]
    if not candidates:
        raise AutoFitError("no warm->green wire transition found; band colours unreadable")
    _, start = min(candidates)
    order = [(start + k) % SECTORS for k in range(SECTORS)]
    wire_angles = d_angles[order]

    treble_angles = wire_angles
    try:
        t_angles, _, _ = _band_transitions(
            red, green, rings.treble_outer, rings.treble_inner, rings.bull, params
        )
        used: set[int] = set()
        treble_idx: list[int] = []
        for angle in wire_angles:
            best = min(
                ((_circular_distance(angle, t_angles[j]), j) for j in range(SECTORS) if j not in used),
                default=None,
            )
            if best is None or best[0] > params.max_wire_match_deg:
                raise AutoFitError("treble-band wires do not line up with double-band wires")
            used.add(best[1])
            treble_idx.append(best[1])
        treble_angles = t_angles[treble_idx]
    except AutoFitError:
        treble_angles = wire_angles

    d_pts = (
        ray_ellipse_intersections(rings.double_outer, rings.bull, wire_angles)
        + ray_ellipse_intersections(rings.double_inner, rings.bull, wire_angles)
    ) / 2.0
    t_pts = (
        ray_ellipse_intersections(rings.treble_outer, rings.bull, treble_angles)
        + ray_ellipse_intersections(rings.treble_inner, rings.bull, treble_angles)
    ) / 2.0
    return WirePoints(double_px=d_pts, treble_px=t_pts, screen_angles_deg=wire_angles)


def _detect_wire_points_warm(
    image: np.ndarray,
    rings: DetectedRings,
    params: AutoFitParams,
) -> WirePoints:
    """Fallback for weak green / orange Boards: smoothed warm fraction → 10 wedges → 20 wires."""
    warm, green = colour_masks(image, params)
    signal = _warm_fraction_around_double(warm, green, rings, params)
    warm_runs = _ten_warm_runs(signal)
    wire_angles = _wires_from_warm_runs(warm_runs, params.ring_samples)
    origin = rings.bull
    d_pts = (
        ray_ellipse_intersections(rings.double_outer, origin, wire_angles)
        + ray_ellipse_intersections(rings.double_inner, origin, wire_angles)
    ) / 2.0
    t_pts = (
        ray_ellipse_intersections(rings.treble_outer, origin, wire_angles)
        + ray_ellipse_intersections(rings.treble_inner, origin, wire_angles)
    ) / 2.0
    return WirePoints(double_px=d_pts, treble_px=t_pts, screen_angles_deg=wire_angles)


def detect_wire_points(
    image: np.ndarray,
    rings: DetectedRings,
    params: AutoFitParams | None = None,
) -> WirePoints:
    """Find the 20 sector wires and order them from the suggested 20.

    Prefers alternating warm/green colour runs (clean Boards). Falls back to a
    smoothed warm-fraction signal when green is weak (Target-style orange Boards).
    """
    p = params or AutoFitParams()
    soft = AutoFitParams(
        red_hue_max=max(p.red_hue_max, 25),
        red_hue_wrap_min=p.red_hue_wrap_min,
        green_hue_min=min(p.green_hue_min, 30),
        green_hue_max=max(p.green_hue_max, 100),
        min_saturation=max(20, p.min_saturation // 2),
        min_value=max(20, p.min_value // 2),
        close_kernel_px=p.close_kernel_px,
        min_band_area_px=p.min_band_area_px,
        min_bull_area_px=p.min_bull_area_px,
        ratio_tolerance=p.ratio_tolerance,
        ring_samples=p.ring_samples,
        min_run_deg=p.min_run_deg,
        max_wire_match_deg=max(p.max_wire_match_deg, 12.0),
        ransac_threshold_mm=p.ransac_threshold_mm,
        min_inliers=p.min_inliers,
    )
    errors: list[str] = []
    for attempt in (p, soft):
        try:
            return _detect_wire_points_colour(image, rings, attempt)
        except AutoFitError as exc:
            errors.append(exc.reason)
        try:
            return _detect_wire_points_warm(image, rings, attempt)
        except AutoFitError as exc:
            errors.append(exc.reason)
    raise AutoFitError(errors[-1] if errors else "wire detection failed")


# --- step 4: homography ---


_WIRE_OFFSET_DEG = 9.0
_SECTOR_STEP_DEG = 18.0


def _edge_seed_needs_polish(seed_edge: FitQuality | None, homography: np.ndarray) -> bool:
    """True when measured ring/wire edges say the colour H is soft (esp. far double).

    Colour Auto can look "healthy" on mid-bed wire points while the concentric
    rings sit inside the real wires on the foreshortened half. Edge re-score
    catches that so we still run ``refine_homography``.
    """
    if seed_edge is None or seed_edge.n_points <= 0:
        return False
    if seed_edge.n_inliers < WARN_MIN_INLIERS or seed_edge.coverage < WARN_MIN_COVERAGE:
        return True
    if math.isfinite(seed_edge.rms_mm) and seed_edge.rms_mm > WARN_RMS_MM:
        return True
    if seed_edge.points_px is None or seed_edge.points_mm is None:
        return False
    field = residual_field_from_correspondences(
        homography,
        seed_edge.points_px,
        seed_edge.points_mm,
        seed_edge.inlier_mask,
    )
    if field is None:
        return False
    far = summarize_residuals(field, homography, 0).get("farDouble")
    status = far_double_status(far)
    return status in (FitStatus.WARN, FitStatus.FAIL)


def _wire_mm_for_label_offset(offset: int) -> tuple[np.ndarray, np.ndarray]:
    """Board-mm wire targets with sector labels rotated by ``offset`` (0 = suggested 20)."""
    angles = [
        (_WIRE_OFFSET_DEG + _SECTOR_STEP_DEG * ((k + offset) % SECTORS)) % 360.0 for k in range(SECTORS)
    ]
    double_mm = np.asarray([polar_mm(_DOUBLE_MID_MM, a) for a in angles], dtype=np.float64)
    treble_mm = np.asarray([polar_mm(_TREBLE_MID_MM, a) for a in angles], dtype=np.float64)
    return double_mm, treble_mm


def suggest(image: np.ndarray, slot: int = 0, params: AutoFitParams | None = None) -> CamCalibration:
    """Auto-suggest a Board-plane bind for one frame (``rotate_offset`` starts at 0).

    Raises ``AutoFitError`` when the frame cannot be bound; the Calibration view
    then shows status ``none`` for the cam.
    """
    p = params or AutoFitParams()
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise AutoFitError("expected a BGR image")

    rings = detect_rings(image, p)
    wires = detect_wire_points(image, rings, p)

    if p.min_inliers > 2 * SECTORS:
        raise AutoFitError(f"only 0 of {2 * SECTORS} wire points fit the Board plane")

    # Prefer the colour-suggested labelling (offset 0). Only then try other
    # cyclic labelings — needed when noise / weak green picks the wrong 20.
    best: tuple[float, float, np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None
    for offset in range(SECTORS):
        double_mm, treble_mm = _wire_mm_for_label_offset(offset)
        candidates = (
            (np.vstack([wires.double_px, wires.treble_px]), np.vstack([double_mm, treble_mm])),
            (wires.double_px, double_mm),
        )
        for px, mm in candidates:
            min_needed = (
                p.min_inliers if len(px) == 2 * SECTORS else min(p.min_inliers, max(12, (SECTORS * 3) // 4))
            )
            if min_needed > len(px):
                continue
            for thr in (p.ransac_threshold_mm, p.ransac_threshold_mm * 1.75):
                homography, inliers = fit_homography(px, mm, ransac_threshold_mm=thr)
                n_in = int(inliers.sum())
                if n_in < min_needed:
                    continue
                rms = reprojection_rms_mm(homography, 0, px[inliers], mm[inliers])
                # Strongly prefer offset 0 so a clean suggested-20 wins over a rotated alias.
                score = n_in * 1000 - rms - (0 if offset == 0 else 5000) - (0 if thr == p.ransac_threshold_mm else 50)
                if best is None or score > best[0]:
                    best = (score, rms, homography, inliers, px, mm)
                break
        if offset == 0 and best is not None:
            break  # colour suggestion already binds the Board plane

    if best is None:
        # Last resort for noisy / weak-green frames: looser RANSAC on the double band.
        loose_thr = max(p.ransac_threshold_mm * 2.5, 7.5)
        loose_need = 10
        for offset in range(SECTORS):
            double_mm, _ = _wire_mm_for_label_offset(offset)
            homography, inliers = fit_homography(
                wires.double_px, double_mm, ransac_threshold_mm=loose_thr
            )
            n_in = int(inliers.sum())
            if n_in < loose_need:
                continue
            rms = reprojection_rms_mm(homography, 0, wires.double_px[inliers], double_mm[inliers])
            score = n_in * 1000 - rms - (0 if offset == 0 else 5000)
            if best is None or score > best[0]:
                best = (score, rms, homography, inliers, wires.double_px, double_mm)
        if best is None:
            raise AutoFitError(f"only 0 of {2 * SECTORS} wire points fit the Board plane")

    _, rms, homography, inliers, px, mm = best
    cal = CamCalibration(
        slot=slot,
        homography=homography,
        rotate_offset=0,
        rings=rings_from_homography(homography),
        rms_mm=rms,
        n_inliers=int(inliers.sum()),
        n_points=int(len(px)),
    )

    if not p.refine:
        return cal

    # Ticket 15 + spider polish: edge-refine when the colour seed is weak *or*
    # when edge re-score shows a soft far double / thin coverage. Healthy
    # colour binds (cam1/2, clean synthetic) with tight far-double stay on the
    # colour H and are only re-scored for the badge.
    from madu_darts.calibration.refine import evaluate_fit, measure_board_edges

    from madu_darts.calibration.mount import DEFAULT_MOUNT_ANGLES_DEG

    refine_params = RefineParams(
        max_iters=p.refine_iters,
        ransac_threshold_mm=min(p.ransac_threshold_mm, 2.5),
        min_inliers=max(24, p.min_inliers),
        mount_angle_deg=DEFAULT_MOUNT_ANGLES_DEG.get(int(slot)),
    )
    seed_px, seed_mm = measure_board_edges(image, homography, refine_params)
    seed_edge = (
        evaluate_fit(homography, seed_px, seed_mm, ransac_threshold_mm=refine_params.ransac_threshold_mm)
        if len(seed_px)
        else None
    )

    colour_inliers = cal.n_inliers or 0
    colour_weak = colour_inliers < 28 or (cal.rms_mm is not None and cal.rms_mm > PASS_RMS_MM)
    if not colour_weak and not _edge_seed_needs_polish(seed_edge, homography):
        return apply_quality(cal, seed_edge) if seed_edge and seed_edge.n_inliers else cal

    refined_h, quality = refine_homography(image, homography, refine_params)
    if quality.n_inliers < 16:
        return apply_quality(cal, seed_edge) if seed_edge and seed_edge.n_inliers else cal
    # Take refinement when it clearly binds more of the Board than the soft seed.
    if seed_edge and quality.n_inliers < seed_edge.n_inliers and quality.rms_mm > seed_edge.rms_mm:
        return apply_quality(
            CamCalibration(slot=slot, homography=homography, rotate_offset=0, rms_mm=seed_edge.rms_mm),
            seed_edge,
        )
    return apply_quality(
        CamCalibration(slot=slot, homography=refined_h, rotate_offset=0, rms_mm=quality.rms_mm),
        quality,
    )


def suggest_best(
    images: list[np.ndarray],
    slot: int = 0,
    params: AutoFitParams | None = None,
) -> CamCalibration:
    """Run ``suggest`` on several frames; keep the best by coverage then RMS.

    Multi-frame Auto (ticket 15): a single noisy frame no longer decides the bind.
    """
    if not images:
        raise AutoFitError("no frames to auto-fit")
    best: CamCalibration | None = None
    best_score = float("-inf")
    last_error: str | None = None
    for image in images:
        try:
            cal = suggest(image, slot=slot, params=params)
        except AutoFitError as exc:
            last_error = exc.reason
            continue
        coverage = cal.coverage if cal.coverage is not None else 0.0
        n_in = cal.n_inliers or 0
        rms = cal.rms_mm if cal.rms_mm is not None else 99.0
        score = n_in * 1000 + coverage * 100 - rms
        if score > best_score:
            best_score = score
            best = cal
    if best is None:
        raise AutoFitError(last_error or "no frame bound the Board plane")
    return best
