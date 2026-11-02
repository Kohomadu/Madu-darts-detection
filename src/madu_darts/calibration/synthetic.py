"""Synthetic Board renderer + simulated camera poses with ground-truth homographies.

Renders an ideal WDF Board (sector shading, red/green rings, wires) into a
canonical square image, then warps it with a known perspective transform to a
1280x720 "camera" frame. Tests use the truth homographies to validate the
Calibration math without hardware; ``madu-darts serve --synthetic`` uses it as
a camera stand-in for UI development away from the Board.

Rotation convention: ``rotation_sectors = k`` draws the Board rotated ``k``
sectors (``18° * k``) clockwise, so sector 20 is no longer at the top. The raw
(unrotated) homography then needs ``rotate_offset = (-k) % 20`` to be correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from madu_darts.board import (
    DOUBLE_INNER_MM,
    DOUBLE_OUTER_MM,
    INNER_BULL_RADIUS_MM,
    OUTER_BULL_RADIUS_MM,
    SECTOR_CLOCKWISE,
    TREBLE_INNER_MM,
    TREBLE_OUTER_MM,
)
from madu_darts.calibration.homography import rotation_mm
from madu_darts.calibration.model import SECTOR_STEP_DEG

CANON_SIZE_PX = 800
CANON_MM_PER_PX = 0.5  # 400 mm field of view; Board diameter ~340 mm + catch ring margin
CAM_SIZE = (1280, 720)

# BGR palette approximating a bristle Board under an LED ring.
_BACKDROP = (28, 28, 28)
_CATCH_RING = (12, 12, 12)
_SECTOR_DARK = (22, 22, 22)
_SECTOR_LIGHT = (205, 222, 238)
_RED = (40, 40, 200)
_GREEN = (70, 160, 40)
_WIRE = (175, 175, 175)
CATCH_RING_RADIUS_MM = 200.0


def canonical_px_to_mm(size_px: int = CANON_SIZE_PX, mm_per_px: float = CANON_MM_PER_PX) -> np.ndarray:
    """3x3 map canonical px -> board mm (+y up) for the rendered (possibly rotated) content."""
    c = (size_px - 1) / 2.0
    s = mm_per_px
    return np.array([[s, 0.0, -s * c], [0.0, -s, s * c], [0.0, 0.0, 1.0]], dtype=np.float64)


def _mm_to_canon_px(x_mm: float, y_mm: float, size_px: int, mm_per_px: float) -> tuple[float, float]:
    c = (size_px - 1) / 2.0
    return c + x_mm / mm_per_px, c - y_mm / mm_per_px


def _polar(radius_mm: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return radius_mm * math.sin(rad), radius_mm * math.cos(rad)


def _biased_radius(radius_mm: float, angle_deg: float, far_angle_deg: float, bias_mm: float) -> float:
    """Push a double-band radius outward toward ``far_angle_deg`` (0 on the near half)."""
    if bias_mm == 0.0 or radius_mm < DOUBLE_INNER_MM - 0.1:
        return radius_mm
    delta = ((angle_deg - far_angle_deg + 180.0) % 360.0) - 180.0
    weight = math.cos(math.radians(delta))
    if weight <= 0.0:
        return radius_mm
    return radius_mm + bias_mm * weight


def render_board(
    size_px: int = CANON_SIZE_PX,
    mm_per_px: float = CANON_MM_PER_PX,
    rotation_sectors: int = 0,
    *,
    far_double_bias_mm: float = 0.0,
    far_angle_deg: float = 0.0,
) -> np.ndarray:
    """BGR image of an ideal Board; sector 20 is at the top when ``rotation_sectors == 0``.

    ``far_double_bias_mm`` shifts the double annulus outward around
    ``far_angle_deg`` (clockwise from the top of this image). The rest of the
    Board stays on the WDF radii, so a homography cannot absorb the error —
    used to golden-check the residual overlay on a known soft far double.
    """
    rot_deg = SECTOR_STEP_DEG * rotation_sectors
    img = np.full((size_px, size_px, 3), _BACKDROP, dtype=np.uint8)

    def px(x_mm: float, y_mm: float) -> tuple[float, float]:
        return _mm_to_canon_px(x_mm, y_mm, size_px, mm_per_px)

    def wedge(
        r_in: float,
        r_out: float,
        a0: float,
        a1: float,
        color: tuple[int, int, int],
        *,
        bias_radii: bool = False,
    ) -> None:
        steps = 16 if bias_radii else 12

        def rad(radius: float, angle: float) -> float:
            if not bias_radii:
                return radius
            return _biased_radius(radius, angle, far_angle_deg, far_double_bias_mm)

        outer = [px(*_polar(rad(r_out, a0 + (a1 - a0) * i / steps), a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]
        inner = [px(*_polar(rad(r_in, a1 - (a1 - a0) * i / steps), a1 - (a1 - a0) * i / steps)) for i in range(steps + 1)]
        pts = np.array(outer + inner, dtype=np.float64)
        shift = 4
        cv2.fillPoly(img, [np.round(pts * (1 << shift)).astype(np.int32)], color, lineType=cv2.LINE_AA, shift=shift)

    def circle(radius_mm: float, color: tuple[int, int, int], thickness: int = -1) -> None:
        cx, cy = px(0.0, 0.0)
        cv2.circle(img, (int(round(cx)), int(round(cy))), int(round(radius_mm / mm_per_px)), color, thickness, lineType=cv2.LINE_AA)

    circle(CATCH_RING_RADIUS_MM, _CATCH_RING)

    for index, _number in enumerate(SECTOR_CLOCKWISE):
        centre = SECTOR_STEP_DEG * index + rot_deg
        a0, a1 = centre - SECTOR_STEP_DEG / 2.0, centre + SECTOR_STEP_DEG / 2.0
        dark = index % 2 == 0  # 20 is dark on a standard Board
        single = _SECTOR_DARK if dark else _SECTOR_LIGHT
        band = _RED if dark else _GREEN
        wedge(OUTER_BULL_RADIUS_MM, TREBLE_INNER_MM, a0, a1, single)
        wedge(TREBLE_INNER_MM, TREBLE_OUTER_MM, a0, a1, band)
        wedge(TREBLE_OUTER_MM, DOUBLE_INNER_MM, a0, a1, single)
        wedge(DOUBLE_INNER_MM, DOUBLE_OUTER_MM, a0, a1, band, bias_radii=far_double_bias_mm != 0.0)

    circle(OUTER_BULL_RADIUS_MM, _GREEN)
    circle(INNER_BULL_RADIUS_MM, _RED)

    # Wires: ring circles + sector spokes from outer bull to outer double.
    ring_radii = (OUTER_BULL_RADIUS_MM, TREBLE_INNER_MM, TREBLE_OUTER_MM, DOUBLE_INNER_MM, DOUBLE_OUTER_MM)
    if far_double_bias_mm == 0.0:
        for radius in ring_radii:
            circle(radius, _WIRE, thickness=1)
    else:
        for radius in (OUTER_BULL_RADIUS_MM, TREBLE_INNER_MM, TREBLE_OUTER_MM):
            circle(radius, _WIRE, thickness=1)
        for radius in (DOUBLE_INNER_MM, DOUBLE_OUTER_MM):
            pts = [
                px(*_polar(_biased_radius(radius, a, far_angle_deg, far_double_bias_mm), a))
                for a in np.linspace(0.0, 360.0, 181, endpoint=False)
            ]
            cv2.polylines(img, [np.round(np.asarray(pts)).astype(np.int32)], True, _WIRE, 1, lineType=cv2.LINE_AA)
    for k in range(len(SECTOR_CLOCKWISE)):
        angle = SECTOR_STEP_DEG / 2.0 + SECTOR_STEP_DEG * k + rot_deg
        p0 = px(*_polar(OUTER_BULL_RADIUS_MM, angle))
        p1 = px(*_polar(DOUBLE_OUTER_MM, angle))
        cv2.line(img, (int(round(p0[0])), int(round(p0[1]))), (int(round(p1[0])), int(round(p1[1]))), _WIRE, 1, lineType=cv2.LINE_AA)

    return img


# Destination quads (TL, TR, BR, BL) in the 1280x720 camera frame for the canonical square.
POSES: dict[str, tuple[tuple[float, float], ...]] = {
    "fronto": ((320.0, 40.0), (960.0, 40.0), (960.0, 680.0), (320.0, 680.0)),
    "tilt_top": ((400.0, 80.0), (880.0, 80.0), (1180.0, 700.0), (100.0, 700.0)),
    "tilt_left": ((200.0, 150.0), (1100.0, 20.0), (1100.0, 700.0), (200.0, 570.0)),
    "tilt_right": ((180.0, 20.0), (1080.0, 150.0), (1080.0, 570.0), (180.0, 700.0)),
}


def perspective_for_pose(pose: str, size_px: int = CANON_SIZE_PX) -> np.ndarray:
    """3x3 canonical px -> camera px for a named pose."""
    s = float(size_px - 1)
    src = np.array([(0.0, 0.0), (s, 0.0), (s, s), (0.0, s)], dtype=np.float32)
    dst = np.array(POSES[pose], dtype=np.float32)
    return np.asarray(cv2.getPerspectiveTransform(src, dst), dtype=np.float64)


@dataclass(frozen=True)
class SyntheticCamera:
    pose: str
    rotation_sectors: int
    image: np.ndarray
    """BGR 1280x720 camera frame."""
    perspective: np.ndarray
    """Canonical px -> camera px."""
    raw_homography: np.ndarray
    """Camera px -> mm of the *drawn* (rotated) content; what auto-fit should recover."""
    truth_homography: np.ndarray
    """Camera px -> true Board mm (20 up)."""

    @property
    def correct_offset(self) -> int:
        return (-self.rotation_sectors) % len(SECTOR_CLOCKWISE)

    def pixel_of_mm(self, x_mm: float, y_mm: float) -> np.ndarray:
        """True camera pixel of a Board-mm point."""
        p = np.linalg.inv(self.truth_homography) @ np.array([x_mm, y_mm, 1.0])
        return p[:2] / p[2]


def synthetic_camera(
    pose: str = "fronto",
    rotation_sectors: int = 0,
    size_px: int = CANON_SIZE_PX,
    mm_per_px: float = CANON_MM_PER_PX,
    *,
    far_double_bias_mm: float = 0.0,
    far_angle_deg: float = 0.0,
) -> SyntheticCamera:
    canon = render_board(
        size_px,
        mm_per_px,
        rotation_sectors,
        far_double_bias_mm=far_double_bias_mm,
        far_angle_deg=far_angle_deg,
    )
    perspective = perspective_for_pose(pose, size_px)
    image = cv2.warpPerspective(canon, perspective, CAM_SIZE, flags=cv2.INTER_LINEAR, borderValue=_BACKDROP)
    raw = canonical_px_to_mm(size_px, mm_per_px) @ np.linalg.inv(perspective)
    truth = rotation_mm(-rotation_sectors) @ raw
    return SyntheticCamera(
        pose=pose,
        rotation_sectors=rotation_sectors,
        image=image,
        perspective=perspective,
        raw_homography=raw,
        truth_homography=truth,
    )
