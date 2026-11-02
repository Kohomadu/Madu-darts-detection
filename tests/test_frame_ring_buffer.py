"""Frame ring buffer retains a fixed time window of per-slot frames."""

from __future__ import annotations

import numpy as np

from madu_darts.record.ring_buffer import BufferedFrame, FrameRingBuffer


def _frame(value: int) -> np.ndarray:
    return np.full((2, 2, 3), value, dtype=np.uint8)


def test_ring_buffer_keeps_only_frames_inside_window() -> None:
    buf = FrameRingBuffer(window_s=1.0, slots=(0, 1))
    buf.push(0.0, {0: _frame(1), 1: _frame(10)})
    buf.push(0.4, {0: _frame(2), 1: _frame(20)})
    buf.push(1.1, {0: _frame(3), 1: _frame(30)})  # drops t=0.0 (age 1.1 > 1.0)

    snap = buf.snapshot()
    assert [f.t_mono for f in snap[0]] == [0.4, 1.1]
    assert [int(f.image[0, 0, 0]) for f in snap[0]] == [2, 3]
    assert [int(f.image[0, 0, 0]) for f in snap[1]] == [20, 30]


def test_ring_buffer_snapshot_is_a_copy() -> None:
    buf = FrameRingBuffer(window_s=2.0, slots=(0,))
    buf.push(1.0, {0: _frame(7)})
    snap = buf.snapshot()
    buf.push(1.5, {0: _frame(8)})
    assert len(snap[0]) == 1
    assert isinstance(snap[0][0], BufferedFrame)
    assert int(snap[0][0].image[0, 0, 0]) == 7
