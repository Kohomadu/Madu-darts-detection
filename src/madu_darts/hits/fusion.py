"""Multi-view fusion of per-cam Board-plane tips (Autodarts ``method`` vocabulary)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from madu_darts.hits.config import FusionConfig

# Observed on live Autodarts 2.1 ``throws[].method``.
UNANIMOUS = "UnanimousCam"
MAJORITY = "Cam+1"
SINGLE = "BestCam"


@dataclass(frozen=True)
class FusedPoint:
    x_mm: float
    y_mm: float
    method: str
    used_slots: tuple[int, ...]
    dropped_slots: tuple[int, ...]
    spread_mm: float

    @property
    def board_mm(self) -> tuple[float, float]:
        return (self.x_mm, self.y_mm)


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def fuse_points(
    points_mm: dict[int, tuple[float, float]],
    confidences: dict[int, float] | None = None,
    config: FusionConfig | None = None,
) -> FusedPoint | None:
    """Mean of agreeing cams with outlier rejection.

    * all cams within ``agree_mm`` → ``UnanimousCam``
    * best agreeing pair (others dropped) → ``Cam+1``
    * no agreement / one cam → ``BestCam`` (highest confidence)

    The plain mean beats confidence weighting on the 07 recording, so
    ``confidences`` only break ties when a single cam must be chosen.
    """
    cfg = config or FusionConfig()
    slots = sorted(points_mm)
    if len(slots) < max(1, cfg.min_cams):
        return None
    pts = {s: np.asarray(points_mm[s], dtype=np.float64) for s in slots}
    conf = confidences or {}

    def best_single() -> list[int]:
        return [max(slots, key=lambda s: conf.get(s, 0.0))]

    if len(slots) == 1:
        used, method = slots, SINGLE
    else:
        pairs = {(a, b): _dist(pts[a], pts[b]) for a, b in combinations(slots, 2)}
        if max(pairs.values()) <= cfg.agree_mm:
            used, method = slots, UNANIMOUS if len(slots) >= 3 else MAJORITY
        else:
            (a, b), d = min(pairs.items(), key=lambda kv: kv[1])
            if d <= cfg.agree_mm:
                used, method = [a, b], MAJORITY
            else:
                used, method = best_single(), SINGLE

    stack = np.vstack([pts[s] for s in used])
    centre = stack.mean(axis=0)
    spread = float(np.max(np.linalg.norm(stack - centre, axis=1))) if len(used) > 1 else 0.0
    dropped = tuple(s for s in slots if s not in used)
    return FusedPoint(
        x_mm=float(centre[0]),
        y_mm=float(centre[1]),
        method=method,
        used_slots=tuple(used),
        dropped_slots=dropped,
        spread_mm=spread,
    )


__all__ = ["MAJORITY", "SINGLE", "UNANIMOUS", "FusedPoint", "fuse_points"]
