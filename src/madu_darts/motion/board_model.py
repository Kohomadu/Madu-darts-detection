"""Empty-Board / stuck-dart background reference per cam."""

from __future__ import annotations

import threading

import numpy as np


class BoardModel:
    """Per-slot grayscale (full-res) reference the motion gate diffs against.

    Capture an empty Board right after Accept (and after Reset / takeout
    finished). After a Hit is committed (tickets 09/10), ``commit`` folds the
    new dart into the background so the next dart's diff only shows the new one.
    """

    def __init__(self, slots: tuple[int, ...] = (0, 1, 2)) -> None:
        self._slots = tuple(int(s) for s in slots)
        self._lock = threading.RLock()
        self._refs: dict[int, np.ndarray] = {}

    @property
    def slots(self) -> tuple[int, ...]:
        return self._slots

    def reference(self, slot: int) -> np.ndarray | None:
        with self._lock:
            ref = self._refs.get(int(slot))
            return None if ref is None else ref.copy()

    def has_reference(self, slot: int) -> bool:
        with self._lock:
            return int(slot) in self._refs

    def capture(self, slot: int, frame: np.ndarray) -> None:
        """Store / replace the empty-Board (or post-takeout) reference."""
        with self._lock:
            self._refs[int(slot)] = np.ascontiguousarray(frame.copy())

    def capture_all(self, frames: dict[int, np.ndarray]) -> None:
        for slot, frame in frames.items():
            self.capture(slot, frame)

    def commit(self, slot: int, frame: np.ndarray) -> None:
        """Fold a stuck dart into the background after a Hit is committed."""
        self.capture(slot, frame)

    def clear(self, slot: int | None = None) -> None:
        with self._lock:
            if slot is None:
                self._refs.clear()
            else:
                self._refs.pop(int(slot), None)

    def reset(self) -> None:
        self.clear()


__all__ = ["BoardModel"]
