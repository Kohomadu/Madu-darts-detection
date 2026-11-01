"""Auto-suggest a camera's Board-plane bind from one frame (Autodarts "magic wand").

Pipeline
--------
1. HSV masks for the red and green scoring bands (doubles, trebles, bulls).
2. Morphological closing merges the 20 wedges of each band into an annulus;
   ``findContours`` with holes yields double-outer/inner and treble-outer/inner
   ellipses plus the bull disc.
3. Walk each band around the bull and read the red/green colour; every colour
   transition is a sector wire. That gives 20 wire points on the double band and
   20 on the treble band with known Board-mm positions (up to a multiple of 18°).
4. Pick the red-banded wedge closest to screen-up as the suggested **20**
   (20's double and treble are red on every standard Board), then RANSAC-fit the
   homography image px -> raw Board mm. The operator corrects the remaining
   ambiguity with rotate-20.

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
from madu_darts.calibration.model import SECTORS, CamCalibration, Ellipse

_DOUBLE_MID_MM = (DOUBLE_INNER_MM + DOUBLE_OUTER_MM) / 2.0  # 166.0
_TREBLE_MID_MM = (TREBLE_INNER_MM + TREBLE_OUTER_MM) / 2.0  # 103.4

# Expected area ratios relative to the double-outer disc (circle areas scale with r²).
_RATIO_DOUBLE_INNER = (DOUBLE_INNER_MM / DOUBLE_OUTER_MM) ** 2
_RATIO_TREBLE_OUTER = (TREBLE_OUTER_MM / DOUBLE_OUTER_MM) ** 2
_RATIO_TREBLE_INNER = (TREBLE_INNER_MM / DOUBLE_OUTER_MM) ** 2

NONE, RED, GREEN = 0, 1, 2


class AutoFitError(ValueError):
    """Auto-fit could not bind this frame to the Board plane; ``reason`` explains why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AutoFitParams:
    """Tunable knobs; defaults target a lit bristle Board at 1280x720."""

    red_hue_max: int = 10
    red_hue_wrap_min: int = 170
    green_hue_min: int = 35
    green_hue_max: int = 90
    min_saturation: int = 80
    min_value: int = 50
    close_kernel_px: int = 9
    min_band_area_px: float = 3000.0
    min_bull_area_px: float = 150.0
    ratio_tolerance: float = 0.25
    ring_samples: int = 1440
    min_run_deg: float = 2.0
    max_wire_match_deg: float = 6.0
    ransac_threshold_mm: float = 3.0
    min_inliers: int = 28


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
    """``(red, green)`` uint8 masks (0/255) of the scoring-band colours."""
    import cv2

    p = params or AutoFitParams()
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vivid = (s >= p.min_saturation) & (v >= p.min_value)
    red = vivid & ((h <= p.red_hue_max) | (h >= p.red_hue_wrap_min))
    green = vivid & (h >= p.green_hue_min) & (h <= p.green_hue_max)
    return red.astype(np.uint8) * 255, green.astype(np.uint8) * 255


# --- step 2: rings from closed band mask ---


def _ellipse_of(contour: np.ndarray) -> Ellipse:
    import cv2

    if len(contour) < 5:
        raise AutoFitError("ring contour too small to fit an ellipse")
    return Ellipse.from_cv(cv2.fitEllipse(contour))


def _within(ratio: float, expected: float, tolerance: float) -> bool:
    return abs(ratio - expected) <= tolerance * expected


def detect_rings(image: np.ndarray, params: AutoFitParams | None = None) -> DetectedRings:
    """Locate the double/treble bands and bull by colour; raise ``AutoFitError`` if unsure."""
    import cv2

    p = params or AutoFitParams()
    red, green = colour_masks(image, p)
    bands = cv2.bitwise_or(red, green)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (p.close_kernel_px, p.close_kernel_px))
    closed = cv2.morphologyEx(bands, cv2.MORPH_CLOSE, kernel)

    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None or len(contours) < 3:
        raise AutoFitError("fewer than three coloured regions found (no Board in view?)")
    hier = hierarchy[0]

    top = [(cv2.contourArea(c), i) for i, c in enumerate(contours) if hier[i][3] < 0]
    top.sort(reverse=True)
    if len(top) < 3:
        raise AutoFitError("need double band, treble band and bull as separate regions")
    (area_d, idx_d), (area_t, idx_t), (area_b, idx_b) = top[:3]

    if area_t < p.min_band_area_px or area_b < p.min_bull_area_px:
        raise AutoFitError("coloured regions too small; Board too far or masks too strict")

    def largest_hole(parent: int) -> np.ndarray:
        child = hier[parent][2]
        best: tuple[float, int] | None = None
        while child >= 0:
            area = cv2.contourArea(contours[child])
            if best is None or area > best[0]:
                best = (area, child)
            child = hier[child][0]
        if best is None:
            raise AutoFitError("band has no inner boundary (wedges not merged into an annulus)")
        return contours[best[1]]

    hole_d = largest_hole(idx_d)
    hole_t = largest_hole(idx_t)
    area_hd = cv2.contourArea(hole_d)
    area_ht = cv2.contourArea(hole_t)

    # Disc areas (band outer contour encloses band + hole).
    checks = (
        (area_hd / area_d, _RATIO_DOUBLE_INNER, "double inner/outer"),
        (area_t / area_d, _RATIO_TREBLE_OUTER, "treble outer/double outer"),
        (area_ht / area_d, _RATIO_TREBLE_INNER, "treble inner/double outer"),
    )
    for ratio, expected, label in checks:
        if not _within(ratio, expected, p.ratio_tolerance):
            raise AutoFitError(f"ring size ratio {label} = {ratio:.3f}, expected ~{expected:.3f}")
    bull_ratio = area_b / area_d
    if not (0.3 * (15.9 / 170.0) ** 2 <= bull_ratio <= 3.0 * (15.9 / 170.0) ** 2):
        raise AutoFitError(f"bull size ratio {bull_ratio:.4f} implausible")

    moments = cv2.moments(contours[idx_b])
    if moments["m00"] <= 0:
        raise AutoFitError("bull region has no area")
    bull = (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])

    return DetectedRings(
        bull=bull,
        double_outer=_ellipse_of(contours[idx_d]),
        double_inner=_ellipse_of(hole_d),
        treble_outer=_ellipse_of(contours[idx_t]),
        treble_inner=_ellipse_of(hole_t),
    )


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


def _band_transitions(
    red: np.ndarray,
    green: np.ndarray,
    outer: Ellipse,
    inner: Ellipse,
    origin: tuple[float, float],
    params: AutoFitParams,
) -> tuple[np.ndarray, list[tuple[int, int]], list[float]]:
    """Wire screen angles on one band.

    Returns ``(transition_angles_deg, (colour_before, colour_after) per transition,
    wedge_centre_angles_deg)`` where wedge ``k`` lies counter-clockwise of
    transition ``k`` (between transition ``k-1`` and ``k``).
    """
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
        # Transition between this run's end and the next run's start (clockwise).
        transitions.append(_circular_mid(run.end * step, nxt.start * step))
        colours.append((run.colour, nxt.colour))
        centres.append(_circular_mid(run.start * step, run.end * step))
    return np.asarray(transitions), colours, centres


def _circular_distance(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 360.0
    return min(d, 360.0 - d)


def detect_wire_points(
    image: np.ndarray,
    rings: DetectedRings,
    params: AutoFitParams | None = None,
) -> WirePoints:
    """Find the 20 sector wires on both bands and order them from the suggested 20."""
    p = params or AutoFitParams()
    red, green = colour_masks(image, p)

    d_angles, d_colours, d_centres = _band_transitions(red, green, rings.double_outer, rings.double_inner, rings.bull, p)
    t_angles, _, _ = _band_transitions(red, green, rings.treble_outer, rings.treble_inner, rings.bull, p)

    # Wire 0 (board 9°) has sector 20 counter-clockwise of it: red wedge before, green after.
    screen_up = 270.0  # (0, -1) in image coords
    candidates = [
        (_circular_distance(d_centres[k], screen_up), k)
        for k in range(SECTORS)
        if d_colours[k] == (RED, GREEN)
    ]
    if not candidates:
        raise AutoFitError("no red->green wire transition found; band colours unreadable")
    _, start = min(candidates)
    order = [(start + k) % SECTORS for k in range(SECTORS)]
    wire_angles = d_angles[order]

    # Match treble transitions to the same wires (they share screen angle around the bull).
    used: set[int] = set()
    treble_idx: list[int] = []
    for angle in wire_angles:
        best = min(
            ((_circular_distance(angle, t_angles[j]), j) for j in range(SECTORS) if j not in used),
            default=None,
        )
        if best is None or best[0] > p.max_wire_match_deg:
            raise AutoFitError("treble-band wires do not line up with double-band wires")
        used.add(best[1])
        treble_idx.append(best[1])

    d_pts = (
        ray_ellipse_intersections(rings.double_outer, rings.bull, wire_angles)
        + ray_ellipse_intersections(rings.double_inner, rings.bull, wire_angles)
    ) / 2.0
    t_matched = t_angles[treble_idx]
    t_pts = (
        ray_ellipse_intersections(rings.treble_outer, rings.bull, t_matched)
        + ray_ellipse_intersections(rings.treble_inner, rings.bull, t_matched)
    ) / 2.0
    return WirePoints(double_px=d_pts, treble_px=t_pts, screen_angles_deg=wire_angles)


# --- step 4: homography ---


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

    px = np.vstack([wires.double_px, wires.treble_px])
    mm = np.vstack([wires.double_mm, wires.treble_mm])
    homography, inliers = fit_homography(px, mm, ransac_threshold_mm=p.ransac_threshold_mm)
    if int(inliers.sum()) < p.min_inliers:
        raise AutoFitError(f"only {int(inliers.sum())} of {len(px)} wire points fit the Board plane")

    rms = reprojection_rms_mm(homography, 0, px[inliers], mm[inliers])
    return CamCalibration(
        slot=slot,
        homography=homography,
        rotate_offset=0,
        rings=rings_from_homography(homography),
        rms_mm=rms,
    )
