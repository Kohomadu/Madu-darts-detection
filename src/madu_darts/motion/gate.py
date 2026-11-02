"""Per-cam motion gate: idle → motion → settling → stable + settled-change events."""

from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np

from madu_darts.motion.board_model import BoardModel
from madu_darts.motion.config import MotionConfig
from madu_darts.motion.types import BoundingBox, CamMotionState, MotionPhase, SettledChange


def _prep(frame: np.ndarray, scale: float) -> np.ndarray:
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    if scale <= 1.0:
        return gray
    h, w = gray.shape[:2]
    return cv2.resize(
        gray,
        (max(1, int(round(w / scale))), max(1, int(round(h / scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _diff_mask(diff: np.ndarray, kernel: int, threshold: int) -> np.ndarray:
    k = max(1, int(kernel))
    blur = cv2.blur(diff, (k, k))
    _, binary = cv2.threshold(blur, int(threshold), 255, cv2.THRESH_BINARY)
    if k >= 2:
        element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, element)
    return binary


def _bbox(mask: np.ndarray) -> BoundingBox | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return BoundingBox(x=x0, y=y0, w=x1 - x0 + 1, h=y1 - y0 + 1)


class _CamGate:
    """State machine for a single camera slot."""

    def __init__(self, slot: int, config: MotionConfig) -> None:
        self.slot = slot
        self.config = config
        self.phase = MotionPhase.IDLE
        self.prev: np.ndarray | None = None
        self.last_frame: np.ndarray | None = None
        self.last_t: float = 0.0
        self.motion_frames = 0
        self.stable_frames = 0
        self.takeout_frames = 0
        self.is_takeout = False
        self._pending_mask: np.ndarray | None = None
        self._pending_bbox: BoundingBox | None = None
        self._pending_changed = 0
        self._last_motion_pixels = 0
        self._last_changed_pixels = 0
        self._last_bbox: BoundingBox | None = None

    def reset(self) -> None:
        self.phase = MotionPhase.IDLE
        self.prev = None
        self.last_frame = None
        self.motion_frames = 0
        self.stable_frames = 0
        self.takeout_frames = 0
        self.is_takeout = False
        self._pending_mask = None
        self._pending_bbox = None
        self._pending_changed = 0
        self._last_motion_pixels = 0
        self._last_changed_pixels = 0
        self._last_bbox = None

    def state(self) -> CamMotionState:
        # Vision tile: yellow while impact or still settling; green once stable; gray idle.
        return CamMotionState(
            slot=self.slot,
            phase=self.phase,
            is_moving=self.phase in (MotionPhase.MOTION, MotionPhase.SETTLING),
            is_stable=self.phase in (MotionPhase.IDLE, MotionPhase.STABLE),
            is_takeout=self.is_takeout,
            changed_pixels=self._last_changed_pixels,
            motion_pixels=self._last_motion_pixels,
            frame_counts={
                "motion": self.motion_frames,
                "stable": self.stable_frames,
                "takeout": self.takeout_frames,
            },
            bbox=self._last_bbox,
        )

    def process(self, frame: np.ndarray, background: np.ndarray | None, t_mono: float) -> SettledChange | None:
        cfg = self.config
        prep = _prep(frame, cfg.scale)
        self.last_frame = np.ascontiguousarray(frame)
        self.last_t = float(t_mono)

        if background is None:
            self.prev = prep
            self.phase = MotionPhase.IDLE
            self._last_motion_pixels = 0
            self._last_changed_pixels = 0
            self._last_bbox = None
            return None

        bg = _prep(background, cfg.scale)
        if bg.shape != prep.shape:
            bg = cv2.resize(bg, (prep.shape[1], prep.shape[0]), interpolation=cv2.INTER_AREA)

        # Seed prev from the empty-Board reference so the first post-Accept /
        # post-commit frame can register as motion (not a zero-diff noop).
        if self.prev is None:
            self.prev = bg
        motion_mask = _diff_mask(cv2.absdiff(prep, self.prev), cfg.kernel, cfg.threshold)
        change_mask = _diff_mask(cv2.absdiff(prep, bg), cfg.kernel, cfg.threshold)

        motion_pixels = int(np.count_nonzero(motion_mask))
        changed_pixels = int(np.count_nonzero(change_mask))
        bbox = _bbox(change_mask)
        self._last_motion_pixels = motion_pixels
        self._last_changed_pixels = changed_pixels
        self._last_bbox = bbox
        self.prev = prep

        moving = motion_pixels >= cfg.min_changed_pixels
        has_change = changed_pixels >= cfg.min_changed_pixels

        if moving and changed_pixels >= cfg.takeout_min_changed_pixels:
            self.takeout_frames += 1
            if self.takeout_frames >= cfg.takeout_min_motion_frames:
                self.is_takeout = True
        elif not moving:
            # Quiet frames decay takeout streak but keep classification until idle.
            pass

        event: SettledChange | None = None

        if self.phase == MotionPhase.IDLE:
            if moving and has_change:
                self.phase = MotionPhase.MOTION
                self.motion_frames = 1
                self.stable_frames = 0
                self._arm_pending(change_mask, bbox, changed_pixels)
        elif self.phase == MotionPhase.MOTION:
            if moving:
                self.motion_frames += 1
                self.stable_frames = 0
                self._arm_pending(change_mask, bbox, changed_pixels)
            elif has_change:
                self.phase = MotionPhase.SETTLING
                self.stable_frames = 1
                self._arm_pending(change_mask, bbox, changed_pixels)
                event = self._maybe_settle(t_mono)
            else:
                self._return_idle()
        elif self.phase == MotionPhase.SETTLING:
            if moving:
                self.phase = MotionPhase.MOTION
                self.motion_frames += 1
                self.stable_frames = 0
                self._arm_pending(change_mask, bbox, changed_pixels)
            elif has_change:
                self.stable_frames += 1
                self._arm_pending(change_mask, bbox, changed_pixels)
                event = self._maybe_settle(t_mono)
            else:
                self._return_idle()
        elif self.phase == MotionPhase.STABLE:
            if moving and has_change:
                self.phase = MotionPhase.MOTION
                self.motion_frames = 1
                self.stable_frames = 0
                self.is_takeout = False
                self.takeout_frames = 0
                self._arm_pending(change_mask, bbox, changed_pixels)

        # Fix is_moving on the public state for Vision tile: yellow while motion/settling.
        return event

    def _arm_pending(self, mask: np.ndarray, bbox: BoundingBox | None, changed: int) -> None:
        self._pending_mask = mask.copy()
        self._pending_bbox = bbox
        self._pending_changed = changed

    def _return_idle(self) -> None:
        self.phase = MotionPhase.IDLE
        self.motion_frames = 0
        self.stable_frames = 0
        self.takeout_frames = 0
        self.is_takeout = False
        self._pending_mask = None
        self._pending_bbox = None
        self._pending_changed = 0

    def _maybe_settle(self, t_mono: float) -> SettledChange | None:
        if self.stable_frames < self.config.stable_num_frames:
            return None
        if self.is_takeout:
            # Suppress settle; stay stable so we don't re-emit.
            self.phase = MotionPhase.STABLE
            self._pending_mask = None
            return None
        if self._pending_mask is None or self._pending_bbox is None:
            self.phase = MotionPhase.STABLE
            return None
        event = SettledChange(
            slot=self.slot,
            t_mono=float(t_mono),
            changed_pixels=self._pending_changed,
            bbox=self._pending_bbox,
            mask=self._pending_mask.copy(),
            kind="dart",
        )
        self.phase = MotionPhase.STABLE
        self._pending_mask = None
        return event


class MotionGate:
    """Multi-cam motion gate driven by ``BoardModel`` references."""

    def __init__(
        self,
        board: BoardModel,
        config: MotionConfig | None = None,
        *,
        slots: tuple[int, ...] | None = None,
    ) -> None:
        self.board = board
        self.config = config or MotionConfig()
        self._slots = slots or board.slots
        self._lock = threading.RLock()
        self._cams = {s: _CamGate(s, self.config) for s in self._slots}
        self._events: list[SettledChange] = []
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                for cam in self._cams.values():
                    cam.reset()

    def reset(self) -> None:
        with self._lock:
            for cam in self._cams.values():
                cam.reset()
            self._events.clear()

    def process_frame(self, slot: int, frame: np.ndarray, t_mono: float) -> SettledChange | None:
        with self._lock:
            if not self._enabled:
                return None
            cam = self._cams.get(int(slot))
            if cam is None:
                return None
            bg = self.board.reference(slot)
            event = cam.process(frame, bg, t_mono)
            if event is not None:
                self._events.append(event)
            return event

    def process_frames(self, frames: dict[int, np.ndarray], t_mono: float) -> list[SettledChange]:
        out: list[SettledChange] = []
        for slot, frame in frames.items():
            event = self.process_frame(slot, frame, t_mono)
            if event is not None:
                out.append(event)
        return out

    def flush(self, frames: dict[int, np.ndarray] | None = None, *, max_pad: int | None = None) -> list[SettledChange]:
        """Repeat the last seen frame (or provided frames) until pending settles fire.

        Recording windows from ticket 07 often end at Autodarts' detection time,
        leaving fewer than ``stableNumFrames`` quiet frames. Padding with a frozen
        last frame completes the settle without inventing new motion.
        """
        with self._lock:
            if not self._enabled:
                return []
            pad_limit = self.config.stable_num_frames + 2 if max_pad is None else max_pad
            emitted: list[SettledChange] = []
            for _ in range(max(0, pad_limit)):
                progressed = False
                for slot, cam in self._cams.items():
                    if cam.phase not in (MotionPhase.MOTION, MotionPhase.SETTLING):
                        continue
                    if frames is not None and slot in frames:
                        frame = frames[slot]
                    elif cam.last_frame is not None:
                        frame = cam.last_frame
                    else:
                        continue
                    t = cam.last_t
                    bg = self.board.reference(slot)
                    event = cam.process(frame, bg, t)
                    progressed = True
                    if event is not None:
                        self._events.append(event)
                        emitted.append(event)
                if not progressed:
                    break
            return emitted

    def states(self) -> dict[int, CamMotionState]:
        with self._lock:
            return {slot: cam.state() for slot, cam in self._cams.items()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "cams": {str(slot): cam.state().to_api() for slot, cam in self._cams.items()},
            }

    def drain_events(self) -> list[SettledChange]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def peek_events(self) -> list[SettledChange]:
        with self._lock:
            return list(self._events)


__all__ = ["MotionGate", "_diff_mask", "_prep"]
