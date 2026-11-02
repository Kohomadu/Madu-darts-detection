"""Multi-view fusion of per-cam Board-plane tips (Autodarts ``method`` vocabulary)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from madu_darts.board import DOUBLE_OUTER_MM, TREBLE_INNER_MM, TREBLE_OUTER_MM
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
    occluded_slots: tuple[int, ...] = ()

    @property
    def board_mm(self) -> tuple[float, float]:
        return (self.x_mm, self.y_mm)


Box = tuple[int, int, int, int]  # x, y, w, h full-res px


def tip_in_padded_box(tip_px: tuple[float, float] | np.ndarray, box: Box, pad_px: float) -> bool:
    """True when the tip lies inside ``box`` expanded by ``pad_px`` on each side."""
    x, y, w, h = box
    u, v = float(tip_px[0]), float(tip_px[1])
    return (x - pad_px) <= u <= (x + w + pad_px) and (y - pad_px) <= v <= (y + h + pad_px)


def occluded_slots(
    tips_px: dict[int, tuple[float, float]],
    tips_mm: dict[int, tuple[float, float]],
    *,
    prior_footprints: list[dict[int, Box]] | None = None,
    prior_tips_mm: list[tuple[float, float]] | None = None,
    bbox_pad_px: float = 24.0,
    tip_radius_mm: float = 8.0,
) -> frozenset[int]:
    """Slots whose tip likely locked onto a previously stuck dart (ticket 24).

    A slot is occluded when:

    1. its tip pixel sits inside that cam's padded footprint from a prior Hit, or
    2. its Board-mm tip is within ``tip_radius_mm`` of a prior tip **and** at least
       one other cam in this group is farther from that prior tip — so peers see
       a new dart while this cam stayed on the old one.
    """
    out: set[int] = set()
    footprints = prior_footprints or []
    priors = list(prior_tips_mm or [])
    for slot, tip_px in tips_px.items():
        for fp in footprints:
            box = fp.get(slot)
            if box is not None and tip_in_padded_box(tip_px, box, bbox_pad_px):
                out.add(int(slot))
                break

    if priors and len(tips_mm) >= 2:
        for slot, tip in tips_mm.items():
            p = np.asarray(tip, dtype=np.float64)
            for prior in priors:
                q = np.asarray(prior, dtype=np.float64)
                if float(np.linalg.norm(p - q)) > tip_radius_mm:
                    continue
                others_far = any(
                    float(np.linalg.norm(np.asarray(tips_mm[o], dtype=np.float64) - q)) > tip_radius_mm
                    for o in tips_mm
                    if o != slot
                )
                if others_far:
                    out.add(int(slot))
                    break
    return frozenset(out)


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _radius_mm(xy: tuple[float, float] | np.ndarray) -> float:
    p = np.asarray(xy, dtype=np.float64).reshape(2)
    return float(np.hypot(p[0], p[1]))


def on_board(xy: tuple[float, float] | np.ndarray, max_radius_mm: float) -> bool:
    """True when the Board-plane tip is inside the hit gate radius (ticket 14)."""
    return _radius_mm(xy) <= float(max_radius_mm)


def _resolve_double_outer_straddle(
    used: list[int],
    pts: dict[int, np.ndarray],
    conf: dict[int, float],
    method: str,
) -> tuple[list[int], str]:
    """If used cams straddle the outer double wire, keep only the inside vote(s).

    Live 2026-11-02 V15/V17: cams within ``agree_mm`` but on opposite sides of
    170 mm — the mean became a miss while one cam alone was a clean double.
    Prefer the on-Board side (dart in the double vs tip noise just outside).
    """
    if len(used) < 2:
        return used, method
    radii = {s: _radius_mm(pts[s]) for s in used}
    inside = [s for s in used if radii[s] <= DOUBLE_OUTER_MM]
    outside = [s for s in used if radii[s] > DOUBLE_OUTER_MM]
    if not inside or not outside:
        return used, method
    if len(inside) == 1:
        return inside, SINGLE
    return inside, MAJORITY if len(inside) >= 2 else SINGLE


# Only treat tips this close to a treble wire as a straddle (not deep singles).
_TREBLE_STRADDLE_MM = 8.0


def _resolve_treble_wire_straddle(
    used: list[int],
    pts: dict[int, np.ndarray],
    conf: dict[int, float],
    method: str,
) -> tuple[list[int], str]:
    """If used cams straddle a treble wire, keep only the on-treble vote(s).

    Ticket 25 / live S↔T: cams within ``agree_mm`` but some just inside
    treble-inner (or just outside treble-outer) while another is on the treble
    band — the mean slides to Single. Prefer tips in ``[TREBLE_INNER, TREBLE_OUTER]``.
    Deep singles / doubles are ignored so normal UnanimousCam groups stay intact.
    """
    if len(used) < 2:
        return used, method
    radii = {s: _radius_mm(pts[s]) for s in used}
    on_treble = [s for s in used if TREBLE_INNER_MM <= radii[s] <= TREBLE_OUTER_MM]
    near_inner = [
        s
        for s in used
        if TREBLE_INNER_MM - _TREBLE_STRADDLE_MM <= radii[s] < TREBLE_INNER_MM
    ]
    near_outer = [
        s
        for s in used
        if TREBLE_OUTER_MM < radii[s] <= TREBLE_OUTER_MM + _TREBLE_STRADDLE_MM
    ]
    off_near = near_inner + near_outer
    if not on_treble or not off_near:
        return used, method
    if len(on_treble) == 1:
        return on_treble, SINGLE
    return on_treble, MAJORITY


def fuse_points(
    points_mm: dict[int, tuple[float, float]],
    confidences: dict[int, float] | None = None,
    config: FusionConfig | None = None,
    *,
    fit_ok: dict[int, bool] | None = None,
    occluded: frozenset[int] | set[int] | None = None,
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

    Live follow-up: cams that spatially agree but straddle the outer double wire
    keep only the inside vote(s) so a soft tip just outside cannot flip D→M.

    Ticket 25: same idea on the treble annulus — keep on-treble vote(s) when peers
    straddle into Single inside treble-inner or outside treble-outer.

    Ticket 24: ``occluded`` cams (tip in a prior dart footprint / stuck on a prior
    tip while peers moved on) are dropped when at least one clear cam remains.
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
    occluded_set = frozenset(int(s) for s in (occluded or ()) if int(s) in pts)

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

    # Ticket 24: drop occluded cams only while a clear peer remains.
    if cfg.drop_occluded_cams and occluded_set:
        clear = [s for s in pool if s not in occluded_set]
        if clear:
            pool = clear

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

    used, method = _resolve_double_outer_straddle(used, pts, conf, method)
    used, method = _resolve_treble_wire_straddle(used, pts, conf, method)

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
        occluded_slots=tuple(sorted(occluded_set)),
    )


__all__ = [
    "MAJORITY",
    "SINGLE",
    "UNANIMOUS",
    "FusedPoint",
    "fuse_points",
    "occluded_slots",
    "on_board",
    "tip_in_padded_box",
]
