"""Fixed-duration per-slot frame ring for visit recording."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BufferedFrame:
    """One cam frame stamped with the recorder's monotonic clock."""

    t_mono: float
    image: Any
    """BGR ndarray (OpenCV); owned by the buffer until overwritten."""


class FrameRingBuffer:
    """Keep the last ``window_s`` seconds of frames for each camera slot.

    Push at a reduced rate (e.g. 10 fps); older samples fall off the back.
    ``snapshot()`` returns a shallow copy of the current window for dumping.
    """

    def __init__(self, window_s: float = 2.0, slots: tuple[int, ...] = (0, 1, 2)) -> None:
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._window_s = float(window_s)
        self._slots = tuple(int(s) for s in slots)
        self._buffers: dict[int, deque[BufferedFrame]] = {s: deque() for s in self._slots}

    @property
    def window_s(self) -> float:
        return self._window_s

    @property
    def slots(self) -> tuple[int, ...]:
        return self._slots

    def push(self, t_mono: float, frames: Mapping[int, Any]) -> None:
        """Append frames at ``t_mono`` and drop samples older than the window."""
        for slot, image in frames.items():
            if slot not in self._buffers:
                continue
            self._buffers[slot].append(BufferedFrame(t_mono=float(t_mono), image=image))
        cutoff = float(t_mono) - self._window_s
        for buf in self._buffers.values():
            while buf and buf[0].t_mono < cutoff:
                buf.popleft()

    def snapshot(self) -> dict[int, list[BufferedFrame]]:
        """Copy of the current window per slot (images are not deep-copied)."""
        return {slot: list(self._buffers[slot]) for slot in self._slots}

    def clear(self) -> None:
        for buf in self._buffers.values():
            buf.clear()
