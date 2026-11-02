"""Mid-Turn vision Recheck: re-detect all stuck darts vs empty-Board refs (ticket 17).

Diffes current frames against the Turn's Accept/Start empty references (not the
dart-committed BoardModel), finds up to N tips per cam, associates across cams,
and fuses with the same rules as live Hits.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from madu_darts.board.geometry import point_mm_to_segment
from madu_darts.hits.config import FusionConfig, TipConfig
from madu_darts.hits.fusion import fuse_points, on_board
from madu_darts.hits.hit import Hit, SlotVote
from madu_darts.hits.tip import TipCandidate, dart_change_mask

log = logging.getLogger(__name__)

BoardPointFn = Callable[[int, tuple[float, float]], Any]
RECHECK_METHOD = "Recheck"

# Live TipConfig.min_elongation is 2.0; empty-ref multi-blob recheck sees flight/shaft
# stubs at ~2.1 that become BestCam Miss/garbage (Board visit #6 → M7). Be stricter.
RECHECK_MIN_ELONGATION = 3.5
RECHECK_MIN_TIP_CONFIDENCE = 0.35
#: Keep the prior Hit when a recheck candidate is this far (mm) and only BestCam-weak.
RECHECK_KEEP_PRIOR_JUMP_MM = 40.0


def _tip_from_component_points(
    pts: np.ndarray,
    *,
    slot: int,
    area_px: int,
    config: TipConfig,
    tip_direction: tuple[float, float],
    min_elongation: float | None = None,
    min_confidence: float | None = None,
) -> TipCandidate | None:
    """Axis + tip for one connected component's pixel coordinates."""
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


def locate_tips_vs_empty(
    background: np.ndarray,
    frame: np.ndarray,
    *,
    max_darts: int,
    slot: int = 0,
    config: TipConfig | None = None,
    tip_direction: tuple[float, float] = (0.0, 1.0),
) -> list[TipCandidate]:
    """Up to ``max_darts`` tip candidates from change vs an empty-Board reference."""
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
    out: list[TipCandidate] = []
    for area, label in comps[: max_darts * 3]:  # spare rejects after strict elong/conf gates
        ys, xs = np.nonzero(labels == label)
        if len(xs) < cfg.min_points:
            continue
        pts = np.column_stack([xs, ys])
        cand = _tip_from_component_points(
            pts,
            slot=slot,
            area_px=area,
            config=cfg,
            tip_direction=tip_direction,
            min_elongation=max(cfg.min_elongation, RECHECK_MIN_ELONGATION),
            min_confidence=RECHECK_MIN_TIP_CONFIDENCE,
        )
        if cand is not None:
            out.append(cand)
        if len(out) >= max_darts:
            break
    return out


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
        votes = tuple(
            SlotVote(
                slot=s,
                tip=group_tips[s],
                x_mm=group_mm[s][0],
                y_mm=group_mm[s][1],
                used=s in fused.used_slots,
            )
            for s in sorted(group_tips)
        )
        used_conf = [group_tips[s].confidence for s in fused.used_slots if s in group_tips]
        confidence = float(np.mean(used_conf)) if used_conf else 0.0
        segment = point_mm_to_segment(fused.x_mm, fused.y_mm)
        hits.append(
            Hit(
                x_mm=fused.x_mm,
                y_mm=fused.y_mm,
                segment=segment,
                method=RECHECK_METHOD if fused.method == "UnanimousCam" else fused.method,
                confidence=confidence,
                t_mono=t_mono,
                slot_votes=votes,
                spread_mm=fused.spread_mm,
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
    """Re-detect stuck darts; returns a list aligned to ``previous`` when possible."""
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
    "locate_tips_vs_empty",
    "recheck_hits",
]
