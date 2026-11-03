"""Per-cam classical tip localization from a settled change.

Ring-mounted cams look across the Board face, so a stuck dart projects as a
line whose flight end is *away* from the Board (image-up) and whose tip is the
extreme point along the dart axis toward image-down. ``tip_direction`` lets a
differently mounted cam flip that prior.

Live settle (bbox ROI) and Recheck (full-frame multi-blob vs empty refs) are
adapters over one tip-from-component-points core; Recheck strictness is
parameters (``min_elongation`` / ``min_confidence``), not a second implementation.
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


def tip_from_component_points(
    pts: np.ndarray,
    *,
    slot: int,
    area_px: int,
    config: TipConfig,
    tip_direction: tuple[float, float] = (0.0, 1.0),
    min_elongation: float | None = None,
    min_confidence: float | None = None,
) -> TipCandidate | None:
    """Axis-fit + tip for one connected component's pixel coordinates.

    ``min_elongation`` / ``min_confidence`` override ``TipConfig`` floors when set
    (Recheck passes stricter values; live uses TipConfig defaults).
    """
    if len(pts) < config.min_points:
        return None
    pts_f = pts.astype(np.float32)
    vx, vy, px0, py0 = cv2.fitLine(pts_f, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    direction = np.array([vx, vy], dtype=np.float64)
    origin = np.array([px0, py0], dtype=np.float64)
    prior = np.asarray(tip_direction, dtype=np.float64)
    if float(direction @ prior) < 0:
        direction = -direction

    along = (pts_f - origin) @ direction
    across = np.abs((pts_f - origin) @ np.array([-direction[1], direction[0]]))
    inliers = across < config.axis_inlier_px
    if int(inliers.sum()) < max(10, config.min_points // 2):
        return None

    along_in = along[inliers]
    pts_in = pts_f[inliers]
    length = float(along_in.max() - along_in.min())
    if length < config.min_length_px:
        return None

    cov = np.cov(pts_f.T)
    eigvals = np.linalg.eigvalsh(cov)
    elongation = float(eigvals[1] / max(eigvals[0], 1e-6))
    elong_floor = float(min_elongation if min_elongation is not None else config.min_elongation)
    if elongation < elong_floor:
        return None

    top = np.argsort(-along_in)[: max(1, config.tip_top_k)]
    tip = pts_in[top].mean(axis=0)
    flight = pts_in[int(np.argmin(along_in))]
    inlier_fraction = float(inliers.mean())
    confidence = min(1.0, inlier_fraction) * min(1.0, length / 80.0) * (1.0 if elongation >= 4.0 else 0.6)
    conf_floor = float(min_confidence if min_confidence is not None else 0.0)
    if confidence < conf_floor:
        return None

    return TipCandidate(
        slot=slot,
        tip_px=(float(tip[0]), float(tip[1])),
        flight_px=(float(flight[0]), float(flight[1])),
        axis_dir=(float(direction[0]), float(direction[1])),
        length_px=length,
        inlier_fraction=inlier_fraction,
        elongation=elongation,
        area_px=int(area_px),
        confidence=float(confidence),
    )


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
    pts = np.column_stack([xs, ys])
    return tip_from_component_points(
        pts,
        slot=slot,
        area_px=largest,
        config=cfg,
        tip_direction=tip_direction,
    )


def locate_tips_vs_empty(
    background: np.ndarray,
    frame: np.ndarray,
    *,
    max_darts: int,
    slot: int = 0,
    config: TipConfig | None = None,
    tip_direction: tuple[float, float] = (0.0, 1.0),
    min_elongation: float | None = None,
    min_confidence: float | None = None,
) -> list[TipCandidate]:
    """Up to ``max_darts`` tip candidates from change vs an empty-Board reference.

    Recheck passes stricter ``min_elongation`` / ``min_confidence``; live callers
    can omit them to use TipConfig defaults only.
    """
    cfg = config or TipConfig()
    max_darts = max(1, int(max_darts))
    height, width = frame.shape[:2]
    mask = dart_change_mask(background, frame, cfg)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return []
    comps: list[tuple[int, int]] = []  # (area, label)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < cfg.min_component_px:
            continue
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if w > cfg.max_frame_fraction * width and h > cfg.max_frame_fraction * height:
            continue  # hand / full-frame thrash
        comps.append((area, label))
    comps.sort(reverse=True)
    elong_floor = max(cfg.min_elongation, float(min_elongation)) if min_elongation is not None else None
    out: list[TipCandidate] = []
    for area, label in comps[: max_darts * 3]:  # spare rejects after strict elong/conf gates
        ys, xs = np.nonzero(labels == label)
        if len(xs) < cfg.min_points:
            continue
        pts = np.column_stack([xs, ys])
        cand = tip_from_component_points(
            pts,
            slot=slot,
            area_px=area,
            config=cfg,
            tip_direction=tip_direction,
            min_elongation=elong_floor,
            min_confidence=min_confidence,
        )
        if cand is not None:
            out.append(cand)
        if len(out) >= max_darts:
            break
    return out


__all__ = [
    "TipCandidate",
    "dart_change_mask",
    "locate_tip",
    "locate_tips_vs_empty",
    "tip_from_component_points",
]
