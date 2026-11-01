"""Calibration view drawings: spiderweb + 20 highlight on the feed, warped Board check.

Both functions return new images and never modify their input. They work with
``opencv-python-headless`` (pure drawing, no windows).
"""

from __future__ import annotations

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
    effective_homography,
    polar_mm,
    ring_points_mm,
    wire_angles_deg,
)
from madu_darts.calibration.model import SECTOR_STEP_DEG, CamCalibration, FitStatus

RING_RADII_MM = (
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
)

WEB_COLOUR = (255, 230, 60)  # BGR cyan-ish spiderweb
TWENTY_COLOUR = (40, 40, 230)  # red highlight (Autodarts "20" mark)
TWENTY_ALPHA = 0.45
IDEAL_RING_COLOUR = (60, 255, 60)
STATUS_COLOURS = {
    FitStatus.NONE: (90, 90, 90),
    FitStatus.PASS: (60, 200, 60),
    FitStatus.WARN: (30, 200, 240),
    FitStatus.FAIL: (40, 40, 230),
}

WARPED_SIZE_PX = 400
WARPED_MARGIN_MM = 20.0


def _to_int_pts(points: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(points, dtype=np.float64)).astype(np.int32).reshape(-1, 1, 2)


def _twenty_wedge_mm(r_in: float = OUTER_BULL_RADIUS_MM, r_out: float = DOUBLE_OUTER_MM, steps: int = 12) -> np.ndarray:
    """Polygon (mm) covering sector 20 from the outer bull to the outer double."""
    half = SECTOR_STEP_DEG / 2.0
    outer = [polar_mm(r_out, -half + SECTOR_STEP_DEG * i / steps) for i in range(steps + 1)]
    inner = [polar_mm(r_in, half - SECTOR_STEP_DEG * i / steps) for i in range(steps + 1)]
    return np.asarray(outer + inner, dtype=np.float64)


def _status_text(cal: CamCalibration) -> str:
    if cal.rms_mm is None:
        return cal.status.value.upper()
    return f"{cal.status.value.upper()}  {cal.rms_mm:.2f} mm"


def _put_badge(image: np.ndarray, text: str, colour: tuple[int, int, int]) -> None:
    import cv2

    cv2.rectangle(image, (8, 8), (8 + 11 * len(text) + 12, 36), (20, 20, 20), -1)
    cv2.putText(image, text, (14, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA)


def draw_spiderweb(image: np.ndarray, cal: CamCalibration, *, highlight_twenty: bool = True) -> np.ndarray:
    """Project rings + wires onto the feed and tint sector 20 red (operator rotate-20 aid)."""
    import cv2

    out = np.ascontiguousarray(image).copy()
    if not cal.has_fit:
        _put_badge(out, "NO FIT", STATUS_COLOURS[FitStatus.NONE])
        return out

    h, k = cal.homography, cal.rotate_offset

    if highlight_twenty:
        wedge_px = board_mm_to_image(h, k, _twenty_wedge_mm())
        layer = out.copy()
        cv2.fillPoly(layer, [_to_int_pts(wedge_px)], TWENTY_COLOUR, lineType=cv2.LINE_AA)
        cv2.addWeighted(layer, TWENTY_ALPHA, out, 1.0 - TWENTY_ALPHA, 0.0, dst=out)

    for radius in RING_RADII_MM:
        ring_px = board_mm_to_image(h, k, ring_points_mm(radius, n=90))
        cv2.polylines(out, [_to_int_pts(ring_px)], True, WEB_COLOUR, 1, lineType=cv2.LINE_AA)

    for angle in wire_angles_deg():
        p0 = board_mm_to_image(h, k, polar_mm(OUTER_BULL_RADIUS_MM, angle))
        p1 = board_mm_to_image(h, k, polar_mm(DOUBLE_OUTER_MM, angle))
        cv2.line(out, tuple(np.round(p0).astype(int)), tuple(np.round(p1).astype(int)), WEB_COLOUR, 1, lineType=cv2.LINE_AA)

    _put_badge(out, _status_text(cal), STATUS_COLOURS[cal.status])
    return out


def canonical_mm_to_px(size_px: int = WARPED_SIZE_PX, margin_mm: float = WARPED_MARGIN_MM) -> np.ndarray:
    """3x3 board mm (+y up) -> warped-image px, Board centred, outer double + margin fills the square."""
    half_mm = DOUBLE_OUTER_MM + margin_mm
    px_per_mm = size_px / (2.0 * half_mm)
    c = (size_px - 1) / 2.0
    return np.array([[px_per_mm, 0.0, c], [0.0, -px_per_mm, c], [0.0, 0.0, 1.0]], dtype=np.float64)


def draw_warped_board(
    image: np.ndarray,
    cal: CamCalibration,
    *,
    size_px: int = WARPED_SIZE_PX,
    margin_mm: float = WARPED_MARGIN_MM,
) -> np.ndarray:
    """Warp the feed onto the Board plane and draw the ideal rings/wires over it.

    If Calibration is right, the drawn geometry sits exactly on the physical
    wires (Autodarts Vision "Calibration" tab). Misalignment is immediately
    visible, which is the pass/fail check before Accept.
    """
    import cv2

    if not cal.has_fit:
        out = np.full((size_px, size_px, 3), 24, dtype=np.uint8)
        _put_badge(out, "NO FIT", STATUS_COLOURS[FitStatus.NONE])
        return out

    mm_to_px = canonical_mm_to_px(size_px, margin_mm)
    matrix = mm_to_px @ effective_homography(cal.homography, cal.rotate_offset)
    out = cv2.warpPerspective(np.ascontiguousarray(image), matrix, (size_px, size_px), flags=cv2.INTER_LINEAR)

    def px(point_mm: tuple[float, float] | np.ndarray) -> np.ndarray:
        p = mm_to_px @ np.array([point_mm[0], point_mm[1], 1.0])
        return p[:2] / p[2]

    # Same red tint as the feed so the operator can check it covers the physical 20.
    wedge_px = np.asarray([px(p) for p in _twenty_wedge_mm()])
    layer = out.copy()
    cv2.fillPoly(layer, [_to_int_pts(wedge_px)], TWENTY_COLOUR, lineType=cv2.LINE_AA)
    cv2.addWeighted(layer, TWENTY_ALPHA, out, 1.0 - TWENTY_ALPHA, 0.0, dst=out)

    centre = tuple(np.round(px((0.0, 0.0))).astype(int))
    px_per_mm = mm_to_px[0, 0]
    for radius in RING_RADII_MM:
        cv2.circle(out, centre, int(round(radius * px_per_mm)), IDEAL_RING_COLOUR, 1, lineType=cv2.LINE_AA)
    for angle in wire_angles_deg():
        p0 = px(polar_mm(OUTER_BULL_RADIUS_MM, angle))
        p1 = px(polar_mm(DOUBLE_OUTER_MM, angle))
        cv2.line(out, tuple(np.round(p0).astype(int)), tuple(np.round(p1).astype(int)), IDEAL_RING_COLOUR, 1, lineType=cv2.LINE_AA)

    label = px(polar_mm(DOUBLE_OUTER_MM + margin_mm * 0.5, 0.0))
    cv2.putText(out, "20", (int(label[0]) - 10, int(label[1]) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TWENTY_COLOUR, 2, cv2.LINE_AA)
    _put_badge(out, _status_text(cal), STATUS_COLOURS[cal.status])
    return out


def draw_calibration_tile(image: np.ndarray, cal: CamCalibration, *, pip_fraction: float = 0.38) -> np.ndarray:
    """Spiderweb feed with the warped-Board check inset bottom-right (one stream per cam).

    Browsers allow ~6 connections per host; compositing keeps the Calibration
    view at one MJPEG stream per camera so control requests are never starved.
    """
    import cv2

    out = draw_spiderweb(image, cal)
    h, w = out.shape[:2]
    size = max(64, int(round(min(h, w) * pip_fraction)))
    pip = draw_warped_board(image, cal, size_px=size)
    y0, x0 = h - size - 8, w - size - 8
    if y0 < 0 or x0 < 0:
        return out
    out[y0 : y0 + size, x0 : x0 + size] = pip
    cv2.rectangle(out, (x0 - 1, y0 - 1), (x0 + size, y0 + size), WEB_COLOUR, 1)
    return out
