"""Autodarts normalised ``coordsX/Y`` ↔ Board-plane millimetres."""

from __future__ import annotations

import math

from madu_darts.record.meta import COORDS_NORM_RADIUS_MM


def autodarts_coords_to_mm(
    coords_x: float,
    coords_y: float,
    *,
    radius_mm: float = COORDS_NORM_RADIUS_MM,
) -> tuple[float, float]:
    """Convert Autodarts normalised board coords to mm (origin bull, +y→20)."""
    return float(coords_x) * radius_mm, float(coords_y) * radius_mm


def mm_to_autodarts_coords(
    x_mm: float,
    y_mm: float,
    *,
    radius_mm: float = COORDS_NORM_RADIUS_MM,
) -> tuple[float, float]:
    return float(x_mm) / radius_mm, float(y_mm) / radius_mm


def mm_error(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance on the Board plane (mm)."""
    return math.hypot(ax - bx, ay - by)
