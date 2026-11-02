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


def _radius_mm(xy: tuple[float, float] | np.ndarray) -> float:
    p = np.asarray(xy, dtype=np.float64).reshape(2)
    return float(np.hypot(p[0], p[1]))


def on_board(xy: tuple[float, float] | np.ndarray, max_radius_mm: float) -> bool:
    """True when the Board-plane tip is inside the hit gate radius (ticket 14)."""
    return _radius_mm(xy) <= float(max_radius_mm)


def fuse_points(
    points_mm: dict[int, tuple[float, float]],
    confidences: dict[int, float] | None = None,
    config: FusionConfig | None = None,
    *,
    fit_ok: dict[int, bool] | None = None,
) -> FusedPoint | None:
    """Mean of agreeing cams with outlier rejection.

    * all cams within ``agree_mm`` → ``UnanimousCam``
    * best agreeing pair (others dropped) → ``Cam+1``
    * no agreement / one cam → ``BestCam`` (highest confidence)

    Tips outside ``max_hit_radius_mm`` are dropped before fusion (arm/body FOV
    motion). The plain mean beats confidence weighting on the 07 recording, so
    ``confidences`` only break ties when a single cam must be chosen.

    Ticket 15: when ``prefer_pass_cams`` and ``fit_ok`` mark a cam as weak, that
    vote is dropped whenever two healthy cams already agree within ``agree_mm``.
    ``UnanimousCam`` is reserved for three healthy agreeing cams.
    """
    cfg = config or FusionConfig()
    max_r = float(cfg.max_hit_radius_mm)
    in_board = {s: xy for s, xy in points_mm.items() if on_board(xy, max_r)}
    off_board = tuple(sorted(s for s in points_mm if s not in in_board))
    slots = sorted(in_board)
    if len(slots) < max(1, cfg.min_cams):
        return None
    pts = {s: np.asarray(in_board[s], dtype=np.float64) for s in slots}
    conf = confidences or {}
    # Missing fit_ok → treat every cam as healthy (legacy / replay without quality).
    healthy = {s: True if fit_ok is None else bool(fit_ok.get(s, True)) for s in slots}

    def best_single(candidates: list[int]) -> list[int]:
        return [max(candidates, key=lambda s: (healthy[s], conf.get(s, 0.0)))]

    def agreeing(group: list[int]) -> bool:
        if len(group) < 2:
            return False
        return max(_dist(pts[a], pts[b]) for a, b in combinations(group, 2)) <= cfg.agree_mm

    # Ticket 15: drop a weak cam when two+ pass cams already agree.
    pool = slots
    if cfg.prefer_pass_cams and fit_ok is not None:
        good = [s for s in slots if healthy[s]]
        if agreeing(good):
            pool = good

    if len(pool) == 1:
        used, method = pool, SINGLE
    elif agreeing(pool):
        used, method = pool, UNANIMOUS if len(pool) >= 3 else MAJORITY
    else:
        pairs = {(a, b): _dist(pts[a], pts[b]) for a, b in combinations(pool, 2)}
        (a, b), d = min(pairs.items(), key=lambda kv: kv[1])
        if d <= cfg.agree_mm:
            used, method = [a, b], MAJORITY
        else:
            used, method = best_single(pool), SINGLE

    stack = np.vstack([pts[s] for s in used])
    centre = stack.mean(axis=0)
    if not on_board(centre, max_r):
        return None
    spread = float(np.max(np.linalg.norm(stack - centre, axis=1))) if len(used) > 1 else 0.0
    dropped = tuple(sorted(set(off_board) | {s for s in slots if s not in used}))
    return FusedPoint(
        x_mm=float(centre[0]),
        y_mm=float(centre[1]),
        method=method,
        used_slots=tuple(sorted(used)),
        dropped_slots=dropped,
        spread_mm=spread,
    )


__all__ = ["MAJORITY", "SINGLE", "UNANIMOUS", "FusedPoint", "fuse_points", "on_board"]
