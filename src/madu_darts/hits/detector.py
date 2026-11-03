"""Settled changes (08) → per-cam tips → fused Board point → Hit.

``HitDetector`` collects one ``SettledChange`` per cam for the same dart (cams
settle a few frames apart), fuses once every cam has reported or the collect
window elapses, and folds the new dart into the ``BoardModel`` so the next
dart diffs cleanly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from madu_darts.hits.claiming import claim_settled
from madu_darts.hits.config import FusionConfig, TipConfig
from madu_darts.hits.fusion import occluded_slots, on_board
from madu_darts.hits.hit import Hit
from madu_darts.hits.tip import TipCandidate, locate_tip
from madu_darts.motion import BoardModel, SettledChange

log = logging.getLogger(__name__)

BoardPointFn = Callable[[int, tuple[float, float]], Any]
FitOkFn = Callable[[], dict[int, bool]]
Box = tuple[int, int, int, int]


@dataclass
class _Pending:
    first_t: float
    candidates: dict[int, TipCandidate] = field(default_factory=dict)
    points_mm: dict[int, tuple[float, float]] = field(default_factory=dict)
    frames: dict[int, np.ndarray] = field(default_factory=dict)
    rejected: set[int] = field(default_factory=set)

    @property
    def reported(self) -> set[int]:
        return set(self.candidates) | self.rejected


class HitDetector:
    def __init__(
        self,
        board_point: BoardPointFn,
        board_model: BoardModel,
        *,
        slots: tuple[int, ...],
        motion_scale: float = 4.0,
        tip_config: TipConfig | None = None,
        fusion_config: FusionConfig | None = None,
        tip_directions: dict[int, tuple[float, float]] | None = None,
        fit_ok: FitOkFn | None = None,
    ) -> None:
        self._board_point = board_point
        self._board = board_model
        self._slots = tuple(slots)
        self._scale = float(motion_scale)
        self.tip_config = tip_config or TipConfig()
        self.fusion_config = fusion_config or FusionConfig()
        self._tip_dirs = tip_directions or {}
        self._fit_ok = fit_ok
        self._pending: _Pending | None = None
        self.last_candidates: dict[int, TipCandidate] = {}

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def reset(self) -> None:
        self._pending = None
        self.last_candidates = {}

    def bbox_full_res(self, event: SettledChange) -> tuple[int, int, int, int]:
        s = self._scale
        return (
            int(event.bbox.x * s),
            int(event.bbox.y * s),
            int(max(1, event.bbox.w * s)),
            int(max(1, event.bbox.h * s)),
        )

    def offer(self, event: SettledChange, frame: np.ndarray) -> TipCandidate | None:
        """Register one cam's settled change with the frame it settled on."""
        slot = int(event.slot)
        if slot not in self._slots:
            return None
        background = self._board.reference(slot)
        if background is None:
            return None
        if self._pending is None:
            self._pending = _Pending(first_t=float(event.t_mono))
        pending = self._pending
        pending.frames[slot] = frame
        candidate = locate_tip(
            background,
            frame,
            self.bbox_full_res(event),
            slot=slot,
            config=self.tip_config,
            tip_direction=self._tip_dirs.get(slot, (0.0, 1.0)),
        )
        if candidate is None:
            pending.rejected.add(slot)
            return None
        try:
            mm = np.asarray(self._board_point(slot, candidate.tip_px), dtype=np.float64).reshape(2)
        except Exception as exc:  # calibration revoked mid-visit etc.
            log.debug("board_point failed for slot %s: %s", slot, exc)
            pending.rejected.add(slot)
            return None
        xy = (float(mm[0]), float(mm[1]))
        # Arms / body in the wide FOV project far outside the scoring disk (ticket 14).
        if not on_board(xy, self.fusion_config.max_hit_radius_mm):
            log.info(
                "cam %s tip rejected: r=%.1f mm > max_hit_radius_mm=%.1f",
                slot,
                float(np.hypot(xy[0], xy[1])),
                self.fusion_config.max_hit_radius_mm,
            )
            pending.rejected.add(slot)
            return None
        pending.candidates[slot] = candidate
        pending.points_mm[slot] = xy
        self.last_candidates[slot] = candidate
        return candidate

    def ready(self, now: float) -> bool:
        pending = self._pending
        if pending is None:
            return False
        if pending.reported >= set(self._slots):
            return True
        return (now - pending.first_t) >= self.fusion_config.collect_window_s

    def poll(
        self,
        now: float,
        *,
        force: bool = False,
        latest_frames: dict[int, np.ndarray] | None = None,
        prior_footprints: list[dict[int, Box]] | None = None,
        prior_tips_mm: list[tuple[float, float]] | None = None,
    ) -> Hit | None:
        """Emit a Hit when the group is complete (or ``force``); commits frames into the BoardModel.

        ``prior_footprints`` / ``prior_tips_mm`` are already-committed darts in this Turn
        (ticket 24): tips that locked onto those footprints are dropped in fusion when
        another cam remains clear.
        """
        pending = self._pending
        if pending is None:
            return None
        if not force and not self.ready(now):
            return None
        self._pending = None

        fit_ok = self._fit_ok() if self._fit_ok is not None else None
        tips_px = {s: cand.tip_px for s, cand in pending.candidates.items()}
        occluded = occluded_slots(
            tips_px,
            pending.points_mm,
            prior_footprints=prior_footprints,
            prior_tips_mm=prior_tips_mm,
            bbox_pad_px=self.fusion_config.occlusion_bbox_pad_px,
            tip_radius_mm=self.fusion_config.occlusion_tip_radius_mm,
        )
        if occluded:
            log.info("occlusion drop candidates: slots %s", sorted(occluded))
        hit = claim_settled(
            pending.points_mm,
            pending.candidates,
            fusion_config=self.fusion_config,
            fit_ok=fit_ok,
            occluded=occluded,
            t_mono=float(max(c for c in [pending.first_t] + [now])),
        )
        # Fold the settled frames into the background regardless, so a missed
        # dart does not pollute the next diff.
        for slot, frame in pending.frames.items():
            self._board.commit(slot, frame)
        if latest_frames:
            for slot, frame in latest_frames.items():
                if slot in self._slots and slot not in pending.frames:
                    self._board.commit(slot, frame)
        return hit


__all__ = ["HitDetector"]
