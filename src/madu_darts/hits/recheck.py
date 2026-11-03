"""Mid-Turn vision Recheck: re-detect all stuck darts vs empty-Board refs (ticket 17).

Diffes current frames against the Turn's Accept/Start empty references (not the
dart-committed BoardModel), finds up to N tips per cam, associates across cams,
and fuses with the same claiming rules as live Hits. Tip localization uses the
shared tip core with stricter Recheck floors (claiming policy, not a tip fork).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from madu_darts.hits.claiming import hit_from_fusion
from madu_darts.hits.config import FusionConfig, TipConfig
from madu_darts.hits.fusion import fuse_points, on_board
from madu_darts.hits.hit import Hit
from madu_darts.hits.tip import TipCandidate, locate_tips_vs_empty

log = logging.getLogger(__name__)

BoardPointFn = Callable[[int, tuple[float, float]], Any]
RECHECK_METHOD = "Recheck"

# Live TipConfig.min_elongation is 2.0; empty-ref multi-blob recheck sees flight/shaft
# stubs at ~2.1 that become BestCam Miss/garbage (Board visit #6 → M7). Be stricter.
# Claiming policy: these floors are parameters on the shared tip core, not a fork.
RECHECK_MIN_ELONGATION = 3.5
RECHECK_MIN_TIP_CONFIDENCE = 0.35
#: Keep the prior Hit when a recheck candidate is this far (mm) and only BestCam-weak.
RECHECK_KEEP_PRIOR_JUMP_MM = 40.0


def _associate_and_fuse(
    tips_mm: dict[int, list[tuple[TipCandidate, tuple[float, float]]]],
    *,
    expected: int,
    fusion: FusionConfig,
    fit_ok: dict[int, bool] | None,
    t_mono: float,
) -> list[Hit]:
    """Greedy multi-view association → fused Hits (unordered)."""
    # Flatten remaining tips per cam.
    remaining: dict[int, list[tuple[TipCandidate, tuple[float, float]]]] = {
        s: list(v) for s, v in tips_mm.items() if v
    }
    hits: list[Hit] = []
    agree = float(fusion.agree_mm)

    while len(hits) < expected and any(remaining.values()):
        # Seed = highest-confidence remaining tip.
        seed_slot, seed_i, seed_conf = -1, -1, -1.0
        for slot, items in remaining.items():
            for i, (tip, _xy) in enumerate(items):
                if tip.confidence > seed_conf:
                    seed_slot, seed_i, seed_conf = slot, i, tip.confidence
        if seed_slot < 0:
            break
        seed_tip, seed_xy = remaining[seed_slot].pop(seed_i)
        if not remaining[seed_slot]:
            remaining.pop(seed_slot, None)

        group_tips: dict[int, TipCandidate] = {seed_slot: seed_tip}
        group_mm: dict[int, tuple[float, float]] = {seed_slot: seed_xy}
        # Pull nearest tip from each other cam within agree_mm of seed.
        for slot in list(remaining):
            best_j, best_d = -1, float("inf")
            for j, (_tip, xy) in enumerate(remaining[slot]):
                d = float(np.hypot(xy[0] - seed_xy[0], xy[1] - seed_xy[1]))
                if d < best_d:
                    best_d, best_j = d, j
            if best_j >= 0 and best_d <= agree:
                tip, xy = remaining[slot].pop(best_j)
                group_tips[slot] = tip
                group_mm[slot] = xy
                if not remaining[slot]:
                    remaining.pop(slot, None)

        fused = fuse_points(
            group_mm,
            {s: t.confidence for s, t in group_tips.items()},
            fusion,
            fit_ok=None if fit_ok is None else {s: fit_ok.get(s, True) for s in group_mm},
        )
        if fused is None:
            continue
        method = RECHECK_METHOD if fused.method == "UnanimousCam" else fused.method
        hits.append(
            hit_from_fusion(
                fused,
                group_tips,
                group_mm,
                t_mono=t_mono,
                method=method,
            )
        )

    hits.sort(key=lambda h: -h.confidence)
    return hits[:expected]


def _order_like_previous(new_hits: list[Hit], previous: tuple[Hit, ...]) -> list[Hit]:
    """Assign new Hits to previous dart indices by nearest Board-mm match."""
    if not previous or not new_hits:
        return new_hits
    n = min(len(previous), len(new_hits))
    used_new: set[int] = set()
    ordered: list[Hit | None] = [None] * len(previous)
    for i, prev in enumerate(previous):
        best_j, best_d = -1, float("inf")
        for j, hit in enumerate(new_hits):
            if j in used_new:
                continue
            d = float(np.hypot(hit.x_mm - prev.x_mm, hit.y_mm - prev.y_mm))
            if d < best_d:
                best_d, best_j = d, j
        if best_j >= 0:
            used_new.add(best_j)
            ordered[i] = new_hits[best_j]
    # Fill any holes with leftover new hits / previous.
    leftovers = [h for j, h in enumerate(new_hits) if j not in used_new]
    out: list[Hit] = []
    for i, hit in enumerate(ordered):
        if hit is not None:
            out.append(hit)
        elif leftovers:
            out.append(leftovers.pop(0))
        else:
            out.append(previous[i])
    out.extend(leftovers)
    return out[: max(len(previous), n)]


def _n_used_cams(hit: Hit) -> int:
    if not hit.slot_votes:
        return 0
    return sum(1 for v in hit.slot_votes if v.used)


def _should_keep_previous(prev: Hit, new: Hit) -> bool:
    """True when the recheck candidate is too weak/suspicious to overwrite ``prev``.

    Allows strong corrections (wrong Segment → multi-cam / high-conf tip nearby or far).
    Blocks Board visit #6 style stubs: BestCam Miss / mid-Board garbage with conf ~0.25.
    """
    if new.confidence < RECHECK_MIN_TIP_CONFIDENCE:
        return True
    if new.segment.bed == "Miss" and prev.segment.bed != "Miss":
        return True
    n_used = _n_used_cams(new)
    dist = float(np.hypot(new.x_mm - prev.x_mm, new.y_mm - prev.y_mm))
    # Weak single-cam tip that jumped far from the prior — likely a wrong blob.
    if n_used <= 1 and dist >= RECHECK_KEEP_PRIOR_JUMP_MM and new.confidence < max(0.45, float(prev.confidence)):
        return True
    return False


def _merge_keeping_strong_priors(ordered: list[Hit], previous: tuple[Hit, ...]) -> list[Hit]:
    """Per-slot: keep previous when the matched recheck Hit fails quality gates."""
    out: list[Hit] = []
    for i, prev in enumerate(previous):
        if i >= len(ordered):
            out.append(prev)
            continue
        new = ordered[i]
        if _should_keep_previous(prev, new):
            log.info(
                "recheck: keep prior Hit %d %s (rejected %s conf=%.3f method=%s)",
                i,
                prev.autodarts_segment_name,
                new.autodarts_segment_name,
                new.confidence,
                new.method,
            )
            out.append(prev)
        else:
            out.append(new)
    return out


def recheck_hits(
    frames: dict[int, np.ndarray],
    empty_refs: dict[int, np.ndarray],
    previous: tuple[Hit, ...],
    board_point: BoardPointFn,
    *,
    tip_config: TipConfig | None = None,
    fusion_config: FusionConfig | None = None,
    tip_directions: dict[int, tuple[float, float]] | None = None,
    fit_ok: dict[int, bool] | None = None,
    t_mono: float = 0.0,
) -> list[Hit]:
    """Recheck entry: re-detect stuck darts; list aligned to ``previous`` when possible."""
    if not previous:
        return []
    tip_cfg = tip_config or TipConfig()
    fusion = fusion_config or FusionConfig()
    dirs = tip_directions or {}
    expected = len(previous)
    tips_mm: dict[int, list[tuple[TipCandidate, tuple[float, float]]]] = {}

    for slot, frame in frames.items():
        ref = empty_refs.get(slot)
        if ref is None:
            continue
        tips = locate_tips_vs_empty(
            ref,
            frame,
            max_darts=expected,
            slot=slot,
            config=tip_cfg,
            tip_direction=dirs.get(slot, (0.0, 1.0)),
            min_elongation=RECHECK_MIN_ELONGATION,
            min_confidence=RECHECK_MIN_TIP_CONFIDENCE,
        )
        mapped: list[tuple[TipCandidate, tuple[float, float]]] = []
        for tip in tips:
            try:
                mm = np.asarray(board_point(slot, tip.tip_px), dtype=np.float64).reshape(2)
            except Exception as exc:
                log.debug("recheck board_point failed cam %s: %s", slot, exc)
                continue
            xy = (float(mm[0]), float(mm[1]))
            if not on_board(xy, fusion.max_hit_radius_mm):
                continue
            mapped.append((tip, xy))
        if mapped:
            tips_mm[slot] = mapped

    fused = _associate_and_fuse(
        tips_mm, expected=expected, fusion=fusion, fit_ok=fit_ok, t_mono=t_mono
    )
    if not fused:
        return list(previous)
    ordered = _order_like_previous(fused, previous)
    # Pad with previous if recheck found fewer.
    while len(ordered) < len(previous):
        ordered.append(previous[len(ordered)])
    ordered = ordered[: len(previous)]
    return _merge_keeping_strong_priors(ordered, previous)


__all__ = [
    "RECHECK_KEEP_PRIOR_JUMP_MM",
    "RECHECK_METHOD",
    "RECHECK_MIN_ELONGATION",
    "RECHECK_MIN_TIP_CONFIDENCE",
    "recheck_hits",
]
