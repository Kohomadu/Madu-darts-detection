"""Per-cam classical tip localization from a settled change.

Ring-mounted cams look across the Board face, so a stuck dart projects as a
line whose flight end is *away* from the Board (image-up) and whose tip is the
extreme point along the dart axis toward image-down. ``tip_direction`` lets a
differently mounted cam flip that prior.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from madu_darts.hits.config import TipConfig


@dataclass(frozen=True)
class TipCandidate:
    slot: int
    tip_px: tuple[float, float]
    flight_px: tuple[float, float]
    axis_dir: tuple[float, float]
    length_px: float
    inlier_fraction: float
    elongation: float
    area_px: int
    confidence: float

    def to_api(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "tipPx": [round(self.tip_px[0], 2), round(self.tip_px[1], 2)],
            "lengthPx": round(self.length_px, 1),
            "inlierFraction": round(self.inlier_fraction, 3),
            "elongation": round(self.elongation, 2),
            "areaPx": self.area_px,
            "confidence": round(self.confidence, 3),
        }


def _gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def dart_change_mask(background: np.ndarray, frame: np.ndarray, config: TipConfig) -> np.ndarray:
    """Full-res uint8 0/255 mask of pixels that changed since ``background``."""
    diff = cv2.absdiff(_gray(frame), _gray(background))
    k = max(1, int(config.kernel))
    if k > 1:
        if k % 2 == 0:
            k += 1
        diff = cv2.GaussianBlur(diff, (k, k), 0)
    _, mask = cv2.threshold(diff, int(config.threshold), 255, cv2.THRESH_BINARY)
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, element)


def locate_tip(
    background: np.ndarray,
    frame: np.ndarray,
    bbox_px: tuple[int, int, int, int],
    *,
    slot: int = 0,
    config: TipConfig | None = None,
    tip_direction: tuple[float, float] = (0.0, 1.0),
) -> TipCandidate | None:
    """Find the dart tip inside ``bbox_px`` (x, y, w, h at full resolution).

    Returns ``None`` when the change does not look like a single dart.
    """
    cfg = config or TipConfig()
    height, width = frame.shape[:2]
    x, y, w, h = bbox_px
    pad = int(cfg.roi_pad_px)
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    if (x1 - x0) > cfg.max_frame_fraction * width and (y1 - y0) > cfg.max_frame_fraction * height:
        return None

    mask = dart_change_mask(background, frame, cfg)
    roi = np.zeros_like(mask)
    roi[y0:y1, x0:x1] = 255
    mask = cv2.bitwise_and(mask, roi)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max())
    keep = [i + 1 for i, a in enumerate(areas) if a >= max(cfg.min_component_px, cfg.component_rel * largest)]
    ys, xs = np.nonzero(np.isin(labels, keep))
    if len(xs) < cfg.min_points:
        return None
    pts = np.column_stack([xs, ys]).astype(np.float32)

    vx, vy, px0, py0 = cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    direction = np.array([vx, vy], dtype=np.float64)
    origin = np.array([px0, py0], dtype=np.float64)
    prior = np.asarray(tip_direction, dtype=np.float64)
    if float(direction @ prior) < 0:
        direction = -direction

    along = (pts - origin) @ direction
    across = np.abs((pts - origin) @ np.array([-direction[1], direction[0]]))
    inliers = across < cfg.axis_inlier_px
    if int(inliers.sum()) < max(10, cfg.min_points // 2):
        return None

    along_in = along[inliers]
    pts_in = pts[inliers]
    length = float(along_in.max() - along_in.min())
    if length < cfg.min_length_px:
        return None

    cov = np.cov(pts.T)
    eigvals = np.linalg.eigvalsh(cov)
    elongation = float(eigvals[1] / max(eigvals[0], 1e-6))
    if elongation < cfg.min_elongation:
        return None

    top = np.argsort(-along_in)[: max(1, cfg.tip_top_k)]
    tip = pts_in[top].mean(axis=0)
    flight = pts_in[int(np.argmin(along_in))]
    inlier_fraction = float(inliers.mean())
    confidence = min(1.0, inlier_fraction) * min(1.0, length / 80.0) * (1.0 if elongation >= 4.0 else 0.6)

    return TipCandidate(
        slot=slot,
        tip_px=(float(tip[0]), float(tip[1])),
        flight_px=(float(flight[0]), float(flight[1])),
        axis_dir=(float(direction[0]), float(direction[1])),
        length_px=length,
        inlier_fraction=inlier_fraction,
        elongation=elongation,
        area_px=largest,
        confidence=float(confidence),
    )


__all__ = ["TipCandidate", "dart_change_mask", "locate_tip"]
