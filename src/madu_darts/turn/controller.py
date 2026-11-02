"""Turn state machine: Hit commit (cap 3), bounce-out retraction, takeout clear, start/stop/reset, standby.

Autodarts ``status`` / ``event`` semantics (research §2.2, checklist steps 10–11, 14):

    throw ──Hit──► throw/throwDetected ──3rd Hit──► takeout/throwDetected
      ▲                                                  │ hand (is_takeout) or Board already empty
      │                                                  ▼
      └──── throw/takeoutFinished ◄── quiet + empty ── takeoutInProgress/takeoutStarted

A committed dart whose footprint reverts to the pre-commit background without
a hand in view is a bounce-out / fall: the Hit is retracted (Movement red),
never scored as stuck. The controller owns the ``BoardModel`` lifecycle around
these transitions; ``MotionGate`` and ``HitDetector`` stay oblivious to Turns.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from madu_darts.hits import Hit, HitDetector
from madu_darts.motion import BoardModel, MotionGate, SettledChange
from madu_darts.motion.gate import _diff_mask, _prep
from madu_darts.turn.config import TurnConfig
from madu_darts.turn.types import BounceOut, TurnEvent, TurnSnapshot, TurnStatus, TurnTransition

log = logging.getLogger(__name__)

Box = tuple[int, int, int, int]  # x, y, w, h (full-res pixels)


def _overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _union(a: Box, b: Box) -> Box:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _clip(box: Box, shape: tuple[int, ...]) -> Box:
    h, w = shape[:2]
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(w, box[0] + box[2]), min(h, box[1] + box[3])
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


@dataclass
class _Committed:
    hit: Hit
    #: Per-cam reference *before* this dart was folded in (bounce-out test).
    before: dict[int, np.ndarray]
    #: Per-cam full-res bbox of the settled change that produced the Hit.
    footprints: dict[int, Box]


@dataclass
class _Retraction:
    t_mono: float
    footprints: dict[int, Box]
    absorbed: set[int] = field(default_factory=set)


class TurnController:
    """Drives gate → detector per frame batch and owns the visit lifecycle."""

    def __init__(
        self,
        board_model: BoardModel,
        motion_gate: MotionGate,
        hit_detector: HitDetector,
        *,
        config: TurnConfig | None = None,
        slots: tuple[int, ...] | None = None,
        history: int = 200,
        on_transition: Callable[[TurnTransition], None] | None = None,
    ) -> None:
        self.board = board_model
        self.gate = motion_gate
        self.detector = hit_detector
        self.config = config or TurnConfig()
        self._slots = tuple(slots or board_model.slots)
        self._lock = threading.RLock()
        #: Called inside the controller lock right after each status/event change
        #: (the stream (11) snapshots the state here so no transition is coalesced).
        self.on_transition = on_transition

        self._running = False
        self._status = TurnStatus.THROW
        self._event = TurnEvent.STOPPED
        self._committed: list[_Committed] = []
        self._offered: dict[int, Box] = {}
        self._empty_refs: dict[int, np.ndarray] = {}
        #: BoardModel snapshot at ``takeoutStarted`` (darts still in) for the removed-footprint test.
        self._takeout_full_refs: dict[int, np.ndarray] = {}
        self._quiet_frames = 0
        self._last_motion_t: float | None = None
        self._takeout_started_t: float | None = None
        self._last_retraction: _Retraction | None = None
        self._last_empty_debug: dict[str, object] = {}
        self._bounce_outs: list[BounceOut] = []
        self._ignored = 0
        self._standby = False
        self._standby_frames: dict[int, np.ndarray] = {}
        self._last_standby_poll = float("-inf")
        self._version = 0
        self._history: deque[TurnTransition] = deque(maxlen=history)
        self._unread: list[TurnTransition] = []

    # --- read side ---

    @property
    def running(self) -> bool:
        return self._running

    @property
    def status(self) -> TurnStatus:
        return self._status

    @property
    def event(self) -> TurnEvent:
        return self._event

    @property
    def hits(self) -> tuple[Hit, ...]:
        with self._lock:
            return tuple(c.hit for c in self._committed)

    def empty_refs(self) -> dict[int, np.ndarray]:
        """Copy of Accept/Start empty-Board frames (ticket 17 Recheck)."""
        with self._lock:
            return {s: f.copy() for s, f in self._empty_refs.items()}

    @property
    def standby(self) -> bool:
        return self._standby

    @property
    def version(self) -> int:
        return self._version

    @property
    def history(self) -> list[TurnTransition]:
        with self._lock:
            return list(self._history)

    def drain_transitions(self) -> list[TurnTransition]:
        with self._lock:
            out = list(self._unread)
            self._unread.clear()
            return out

    def snapshot(self) -> TurnSnapshot:
        with self._lock:
            return TurnSnapshot(
                running=self._running,
                status=self._status,
                event=self._event,
                hits=tuple(c.hit for c in self._committed),
                standby=self._standby,
                pending=self.detector.pending,
                bounce_outs=tuple(self._bounce_outs),
                ignored_changes=self._ignored,
                version=self._version,
            )

    # --- operator controls ---

    def start(self, frames: dict[int, np.ndarray], t_mono: float) -> TurnTransition:
        """Begin detecting: the Board is taken as empty on ``frames`` (post-Accept / Start)."""
        with self._lock:
            self._clear_turn()
            self._adopt_empty(frames)
            self.gate.reset()
            self.gate.set_enabled(True)
            self.detector.reset()
            self._running = True
            self._standby = False
            self._last_motion_t = float(t_mono)
            self._quiet_frames = 0
            return self._set(TurnStatus.THROW, TurnEvent.STARTED, t_mono)

    def stop(self, t_mono: float) -> TurnTransition:
        """Park detection (``running: false``); Hits stay visible until Start / Reset."""
        with self._lock:
            self.gate.set_enabled(False)
            self.detector.reset()
            self._offered.clear()
            self._running = False
            self._standby = False
            return self._set(self._status, TurnEvent.STOPPED, t_mono)

    def reset(self, frames: dict[int, np.ndarray] | None, t_mono: float) -> TurnTransition:
        """Clear the Turn (keeps Calibration); ``frames`` become the empty Board when given."""
        with self._lock:
            self._clear_turn()
            if frames:
                self._adopt_empty(frames)
            self.gate.reset()
            self.detector.reset()
            self._standby = False
            if self._running:
                self.gate.set_enabled(True)
                self._last_motion_t = float(t_mono)
            return self._set(TurnStatus.THROW, TurnEvent.RESET, t_mono)

    # --- per frame batch ---

    def process(self, frames: dict[int, np.ndarray], t_mono: float) -> list[TurnTransition]:
        """Feed one batch of cam frames; returns the transitions it caused."""
        with self._lock:
            if not self._running:
                return []
            mark = len(self._unread)
            cfg = self.config

            if self._standby:
                if t_mono - self._last_standby_poll < cfg.standby_poll_s:
                    return []
                self._last_standby_poll = t_mono
                if self._motion_since_standby(frames):
                    self._wake(t_mono)
                else:
                    return []
            elif (
                cfg.standby_minutes > 0
                and self._last_motion_t is not None
                and t_mono - self._last_motion_t >= cfg.standby_minutes * 60.0
            ):
                self._enter_standby(frames, t_mono)
                return list(self._unread[mark:])

            events = self.gate.process_frames(frames, t_mono)
            states = self.gate.states()
            moving_any = any(s.is_moving for s in states.values())
            hand = any(s.is_takeout for s in states.values())
            if moving_any:
                self._last_motion_t = t_mono
                self._quiet_frames = 0
            else:
                self._quiet_frames += 1

            if hand and self._status != TurnStatus.TAKEOUT_IN_PROGRESS:
                self._begin_takeout(t_mono)

            for event in events:
                frame = frames.get(event.slot)
                if frame is None:
                    continue
                self._handle_settled(event, frame, frames, t_mono)

            self._maybe_commit_hit(frames, t_mono)

            if (
                not moving_any
                and self._quiet_frames >= cfg.quiet_frames
                and not self.detector.pending
                and (self._committed or self._status == TurnStatus.TAKEOUT_IN_PROGRESS)
            ):
                cleared = self._board_cleared(frames)
                soft = self._board_empty(
                    frames, max_px=cfg.empty_soft_max_changed_pixels
                )
                zero_recover = (
                    self._status == TurnStatus.TAKEOUT_IN_PROGRESS
                    and not self._committed
                    and self._takeout_started_t is not None
                    and t_mono - self._takeout_started_t >= cfg.false_takeout_recover_s
                )
                # Hits still listed but Board nearly empty vs Accept refs for long enough → finish
                # (ticket 16); never force-adopt while darts clearly remain.
                soft_force = (
                    self._status == TurnStatus.TAKEOUT_IN_PROGRESS
                    and bool(self._committed)
                    and soft
                    and self._takeout_started_t is not None
                    and t_mono - self._takeout_started_t >= cfg.takeout_force_finish_s
                )
                if cleared or zero_recover or soft_force:
                    if self._status != TurnStatus.TAKEOUT_IN_PROGRESS:
                        # Hand too quick to classify (or jump-cut replay): the darts are gone anyway.
                        self._begin_takeout(t_mono)
                    if soft_force and not cleared:
                        log.info(
                            "takeout soft-force after %.1fs (emptyDiff=%s)",
                            t_mono - float(self._takeout_started_t or t_mono),
                            self._last_empty_debug.get("emptyDiffPx"),
                        )
                    elif zero_recover and not cleared:
                        log.info("zero-dart takeout recovered: adopting current frames as empty Board")
                    self._finish_takeout(frames, t_mono)

            return list(self._unread[mark:])

    def flush(self, frames: dict[int, np.ndarray], t_mono: float) -> list[TurnTransition]:
        """Replay helper: finish pending settles on frozen frames and force the Hit decision.

        Recording windows (07) end at Autodarts' detection time, often before
        ``stableNumFrames`` quiet frames exist; live play never needs this.
        """
        with self._lock:
            if not self._running:
                return []
            mark = len(self._unread)
            for event in self.gate.flush(frames):
                frame = frames.get(event.slot)
                if frame is not None:
                    self._handle_settled(event, frame, frames, t_mono)
            self._maybe_commit_hit(frames, t_mono, force=True)
            return list(self._unread[mark:])

    # --- settled-change routing ---

    def _handle_settled(self, event: SettledChange, frame: np.ndarray, frames: dict[int, np.ndarray], t: float) -> None:
        if self._status == TurnStatus.TAKEOUT_IN_PROGRESS:
            return  # hand in view: settles are not darts; finish re-captures the Board
        if self._absorb_retraction(event, frame, t):
            return
        if len(self._committed) >= 2 and self._board_empty(frames):
            # Several darts vanished at once with no hand classified (hand too quick,
            # or a jump-cut in replay): that is a takeout, not a bounce-out.
            self._begin_takeout(t)
            self._finish_takeout(frames, t)
            return
        if self._committed and self._is_bounce_out(event, frame, frames, t):
            return
        if len(self._committed) >= self.config.max_hits:
            # Fourth dart (or anything else) while three are stuck: never scored; fold in so
            # later diffs stay clean until the takeout clears everything.
            self._ignored += 1
            self.board.commit(event.slot, frame)
            log.info("settled change on cam %s ignored: %d Hits already stuck", event.slot, len(self._committed))
            return
        self._offered[event.slot] = self.detector.bbox_full_res(event)
        self.detector.offer(event, frame)

    def _maybe_commit_hit(self, frames: dict[int, np.ndarray], t: float, *, force: bool = False) -> None:
        if not self.detector.pending or not (force or self.detector.ready(t)):
            return
        before = {s: ref for s in self._slots if (ref := self.board.reference(s)) is not None}
        prior_footprints = [dict(rec.footprints) for rec in self._committed]
        prior_tips_mm = [(rec.hit.x_mm, rec.hit.y_mm) for rec in self._committed]
        hit = self.detector.poll(
            t,
            force=force,
            latest_frames=frames,
            prior_footprints=prior_footprints or None,
            prior_tips_mm=prior_tips_mm or None,
        )
        footprints = dict(self._offered)
        self._offered.clear()
        if hit is None:
            return
        self._committed.append(_Committed(hit=hit, before=before, footprints=footprints))
        status = TurnStatus.TAKEOUT if len(self._committed) >= self.config.max_hits else TurnStatus.THROW
        self._set(status, TurnEvent.THROW_DETECTED, t)
        log.info("Hit %d/%d: %s (%s)", len(self._committed), self.config.max_hits, hit.autodarts_segment_name, hit.method)

    # --- bounce-out ---

    def _is_bounce_out(self, event: SettledChange, frame: np.ndarray, frames: dict[int, np.ndarray], t: float) -> bool:
        slot = int(event.slot)
        bbox = self.detector.bbox_full_res(event)
        ref_now = self.board.reference(slot)
        if ref_now is None:
            return False
        min_px = self.gate.config.min_changed_pixels
        for idx in range(len(self._committed) - 1, -1, -1):
            rec = self._committed[idx]
            footprint = rec.footprints.get(slot)
            ref_before = rec.before.get(slot)
            if footprint is None or ref_before is None or not _overlaps(bbox, footprint):
                continue
            roi = _clip(_union(bbox, footprint), frame.shape)
            d_after = self._changed_pixels(frame, ref_now, roi)
            d_before = self._changed_pixels(frame, ref_before, roi)
            if d_after >= min_px and d_before <= self.config.revert_ratio * d_after:
                self._retract(idx, slot, frame, frames, t)
                return True
        return False

    def _retract(self, idx: int, slot: int, frame: np.ndarray, frames: dict[int, np.ndarray], t: float) -> None:
        rec = self._committed.pop(idx)
        self._bounce_outs.append(BounceOut(hit=rec.hit, index=idx, slot=slot, t_mono=t))
        # The current frame is the truth on this cam; quiet cams too. Cams still
        # moving will settle on their own and get absorbed via the retraction window.
        self.board.commit(slot, frame)
        states = self.gate.states()
        for s, f in frames.items():
            if s != slot and s in self._slots and s in states and not states[s].is_moving:
                self.board.commit(s, f)
        self._last_retraction = _Retraction(t_mono=t, footprints=rec.footprints, absorbed={slot})
        status = self._status
        if status == TurnStatus.TAKEOUT and len(self._committed) < self.config.max_hits:
            status = TurnStatus.THROW
        self._set(status, TurnEvent.BOUNCE_OUT, t)
        log.info("bounce-out: retracted Hit %d (%s) on cam %s", idx, rec.hit.autodarts_segment_name, slot)

    def _absorb_retraction(self, event: SettledChange, frame: np.ndarray, t: float) -> bool:
        r = self._last_retraction
        if r is None or t - r.t_mono > self.config.retraction_window_s or event.slot in r.absorbed:
            return False
        footprint = r.footprints.get(int(event.slot))
        if footprint is not None and not _overlaps(self.detector.bbox_full_res(event), footprint):
            return False
        r.absorbed.add(int(event.slot))
        self.board.commit(event.slot, frame)
        return True

    # --- takeout ---

    def _begin_takeout(self, t: float) -> None:
        self._takeout_started_t = t
        self._takeout_full_refs = {
            s: ref for s in self._slots if (ref := self.board.reference(s)) is not None
        }
        self.detector.reset()
        self._offered.clear()
        self._set(TurnStatus.TAKEOUT_IN_PROGRESS, TurnEvent.TAKEOUT_STARTED, t)

    def _finish_takeout(self, frames: dict[int, np.ndarray], t: float) -> None:
        self._clear_turn()
        self._takeout_full_refs = {}
        self._adopt_empty(frames)
        self.gate.reset()
        self.detector.reset()
        self._set(TurnStatus.THROW, TurnEvent.TAKEOUT_FINISHED, t)

    def _board_empty(self, frames: dict[int, np.ndarray], *, max_px: int | None = None) -> bool:
        limit = self.config.empty_max_changed_pixels if max_px is None else max_px
        judged = 0
        for slot in self._slots:
            frame, ref = frames.get(slot), self._empty_refs.get(slot)
            if frame is None or ref is None:
                continue
            judged += 1
            if self._changed_pixels(frame, ref) > limit:
                return False
        return judged > 0

    def _darts_removed(self, frames: dict[int, np.ndarray]) -> bool:
        """True when every judged cam differs enough from the takeout-start (dart) background."""
        if not self._takeout_full_refs:
            return False
        judged = 0
        for slot in self._slots:
            frame, full = frames.get(slot), self._takeout_full_refs.get(slot)
            if frame is None or full is None:
                continue
            judged += 1
            if self._changed_pixels(frame, full) < self.config.dart_removed_min_pixels:
                return False
        return judged > 0

    def _board_cleared(self, frames: dict[int, np.ndarray]) -> bool:
        """Strict empty, or (during takeout) soft empty + dart footprints gone (ticket 16)."""
        debug = self.empty_debug(frames)
        self._last_empty_debug = debug
        if self._board_empty(frames):
            return True
        if self._status != TurnStatus.TAKEOUT_IN_PROGRESS:
            return False
        soft = self._board_empty(frames, max_px=self.config.empty_soft_max_changed_pixels)
        removed = self._darts_removed(frames)
        return soft and removed

    def empty_debug(self, frames: dict[int, np.ndarray] | None = None) -> dict[str, object]:
        """Per-cam empty / dart-bg diffs for ``/api/state`` (live takeout diagnosis)."""
        frames = frames or {}
        empty: dict[str, int] = {}
        dart_bg: dict[str, int] = {}
        takeout_full: dict[str, int] = {}
        for slot in self._slots:
            frame = frames.get(slot)
            if frame is None:
                continue
            key = str(slot)
            eref = self._empty_refs.get(slot)
            if eref is not None:
                empty[key] = self._changed_pixels(frame, eref)
            bref = self.board.reference(slot)
            if bref is not None:
                dart_bg[key] = self._changed_pixels(frame, bref)
            fref = self._takeout_full_refs.get(slot)
            if fref is not None:
                takeout_full[key] = self._changed_pixels(frame, fref)
        return {
            "emptyDiffPx": empty,
            "dartBgDiffPx": dart_bg,
            "takeoutFullDiffPx": takeout_full,
            "takeoutStartedTMono": self._takeout_started_t,
        }

    # --- standby ---

    def _enter_standby(self, frames: dict[int, np.ndarray], t: float) -> None:
        self.gate.set_enabled(False)
        self.detector.reset()
        self._offered.clear()
        self._standby_frames = {s: f.copy() for s, f in frames.items() if s in self._slots}
        self._standby = True
        self._last_standby_poll = t
        self._set(self._status, TurnEvent.STANDBY, t)
        log.info("standby after %.0f min without motion", self.config.standby_minutes)

    def _motion_since_standby(self, frames: dict[int, np.ndarray]) -> bool:
        min_px = self.gate.config.min_changed_pixels
        for slot, frame in frames.items():
            ref = self._standby_frames.get(slot)
            if ref is not None and self._changed_pixels(frame, ref) >= min_px:
                return True
        return False

    def _wake(self, t: float) -> None:
        self._standby = False
        self._standby_frames = {}
        self._last_motion_t = t
        self._quiet_frames = 0
        self.gate.reset()
        self.gate.set_enabled(True)
        self._set(self._status, TurnEvent.WAKEUP, t)

    # --- helpers ---

    def replace_hits(self, hits: list[Hit], frames: dict[int, np.ndarray], t_mono: float) -> TurnTransition:
        """Replace committed Hits after a vision Recheck (ticket 17); refresh BoardModel."""
        with self._lock:
            if not self._running:
                raise RuntimeError("detection not running")
            if not self._committed:
                raise RuntimeError("no Hits to recheck")
            if not hits:
                raise RuntimeError("recheck produced no Hits")
            if len(hits) > self.config.max_hits:
                hits = hits[: self.config.max_hits]
            # Keep bounce-out footprints empty — Recheck commits the whole Board as current.
            new_committed: list[_Committed] = []
            for hit in hits:
                new_committed.append(
                    _Committed(hit=hit, before={s: frames[s].copy() for s in frames if s in self._slots}, footprints={})
                )
            self._committed = new_committed
            self._offered.clear()
            self.detector.reset()
            for slot, frame in frames.items():
                if slot in self._slots:
                    self.board.commit(slot, frame)
            status = TurnStatus.TAKEOUT if len(self._committed) >= self.config.max_hits else TurnStatus.THROW
            return self._set(status, TurnEvent.RECHECK, t_mono)

    def override_hit(self, index: int, hit: Hit, t_mono: float) -> TurnTransition:
        """Replace one committed Hit with a manual correction (ticket 18)."""
        with self._lock:
            if not self._committed:
                raise RuntimeError("no Hits to override")
            if index < 0 or index >= len(self._committed):
                raise IndexError(f"hit index {index} out of range")
            old = self._committed[index]
            self._committed[index] = _Committed(hit=hit, before=old.before, footprints=old.footprints)
            return self._set(self._status, TurnEvent.OVERRIDE, t_mono)

    def _clear_turn(self) -> None:
        self._committed.clear()
        self._offered.clear()
        self._bounce_outs.clear()
        self._ignored = 0
        self._last_retraction = None
        self._takeout_started_t = None
        self._takeout_full_refs = {}
        self._quiet_frames = 0

    def _adopt_empty(self, frames: dict[int, np.ndarray]) -> None:
        for slot, frame in frames.items():
            if slot in self._slots:
                self._empty_refs[slot] = np.ascontiguousarray(frame.copy())
                self.board.capture(slot, frame)

    def _changed_pixels(self, frame: np.ndarray, ref: np.ndarray, roi: Box | None = None) -> int:
        cfg = self.gate.config
        if roi is not None:
            x, y, w, h = roi
            frame, ref = frame[y : y + h, x : x + w], ref[y : y + h, x : x + w]
        a, b = _prep(frame, cfg.scale), _prep(ref, cfg.scale)
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
        return int(np.count_nonzero(_diff_mask(cv2.absdiff(a, b), cfg.kernel, cfg.threshold)))

    def _set(self, status: TurnStatus, event: TurnEvent, t: float) -> TurnTransition:
        self._status, self._event = status, event
        self._version += 1
        tr = TurnTransition(t_mono=float(t), status=status, event=event, num_hits=len(self._committed))
        self._history.append(tr)
        self._unread.append(tr)
        if self.on_transition is not None:
            try:
                self.on_transition(tr)
            except Exception as exc:  # a stream subscriber must never break detection
                log.warning("on_transition failed: %s", exc)
        return tr


__all__ = ["TurnController"]
