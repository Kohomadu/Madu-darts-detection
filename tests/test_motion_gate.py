"""Synthetic motion-gate sequences: step change, flicker, slow hand / takeout."""

from __future__ import annotations

import numpy as np

from madu_darts.motion import BoardModel, MotionConfig, MotionGate, MotionPhase


def _frame(value: int, size: tuple[int, int] = (180, 320), *, blob: tuple[int, int, int, int] | None = None, blob_val: int = 255) -> np.ndarray:
    """Gray 3-channel frame; optional bright rectangle (y0,y1,x0,x1)."""
    img = np.full((size[0], size[1], 3), int(value), dtype=np.uint8)
    if blob is not None:
        y0, y1, x0, x1 = blob
        img[y0:y1, x0:x1] = blob_val
    return img


def _gate(**kwargs: object) -> tuple[BoardModel, MotionGate]:
    params: dict[str, object] = {
        "scale": 1.0,  # keep full synthetic resolution
        "kernel": 3,
        "threshold": 16,
        "stable_num_frames": 3,
        "min_changed_pixels": 40,
        "takeout_min_changed_pixels": 2500,
        "takeout_min_motion_frames": 8,
    }
    params.update(kwargs)
    cfg = MotionConfig(**params)  # type: ignore[arg-type]
    board = BoardModel((0,))
    gate = MotionGate(board, cfg, slots=(0,))
    gate.set_enabled(True)
    return board, gate


def test_step_change_emits_one_settled_after_stable_frames() -> None:
    board, gate = _gate()
    empty = _frame(40)
    board.capture(0, empty)

    # Still period — no events.
    for t in range(5):
        assert gate.process_frame(0, empty, float(t)) is None

    dart = _frame(40, blob=(60, 100, 140, 180))
    # First motion frame must not settle.
    assert gate.process_frame(0, dart, 10.0) is None
    assert gate.states()[0].phase == MotionPhase.MOTION

    # Dart still moving (shift blob).
    moving = _frame(40, blob=(62, 102, 142, 182))
    assert gate.process_frame(0, moving, 11.0) is None

    # Quiet frames with dart stuck — settle on 3rd stable.
    settled = None
    for i in range(5):
        settled = gate.process_frame(0, moving, 12.0 + i)
        if settled is not None:
            assert i + 1 >= 3  # stableNumFrames
            break
    assert settled is not None
    assert settled.slot == 0
    assert settled.changed_pixels >= 40
    assert settled.bbox.w > 0 and settled.bbox.h > 0

    # Further still frames with same dart — no second event until new motion.
    for i in range(5):
        assert gate.process_frame(0, moving, 20.0 + i) is None


def test_flicker_below_threshold_stays_idle() -> None:
    board, gate = _gate(min_changed_pixels=40)
    empty = _frame(40)
    board.capture(0, empty)
    # Tiny 2×2 sparkle — under min_changed_pixels after morph open.
    spark = empty.copy()
    spark[90:92, 160:162] = 255
    for t in range(10):
        assert gate.process_frame(0, spark if t % 2 else empty, float(t)) is None
    assert gate.states()[0].phase == MotionPhase.IDLE
    assert gate.drain_events() == []


def test_slow_hand_takeout_suppresses_settled_change() -> None:
    board, gate = _gate(
        takeout_min_changed_pixels=2000,
        takeout_min_motion_frames=5,
        stable_num_frames=3,
    )
    empty = _frame(40)
    board.capture(0, empty)

    # Large blob moving for several frames (hand / takeout).
    for i in range(8):
        hand = _frame(40, blob=(20 + i, 160 + i, 30, 300))
        assert gate.process_frame(0, hand, float(i)) is None

    # Hand leaves / board empty again — even if we settle, takeout suppresses.
    for i in range(6):
        assert gate.process_frame(0, empty, 20.0 + i) is None

    # If still classified takeout mid-settle on large residual, no dart event.
    assert all(e.kind == "dart" for e in gate.peek_events())  # none expected
    assert gate.drain_events() == []


def test_flush_pads_truncated_settle() -> None:
    board, gate = _gate(stable_num_frames=3)
    empty = _frame(40)
    board.capture(0, empty)
    dart = _frame(40, blob=(60, 100, 140, 180))
    assert gate.process_frame(0, dart, 1.0) is None  # motion
    assert gate.process_frame(0, dart, 2.0) is None  # first quiet / settling
    events = gate.flush()
    assert len(events) == 1
    assert events[0].slot == 0


def test_commit_hides_previous_dart_from_next_diff() -> None:
    board, gate = _gate()
    empty = _frame(40)
    board.capture(0, empty)
    dart1 = _frame(40, blob=(60, 100, 140, 180))
    for t, fr in enumerate([dart1, dart1, dart1, dart1, dart1]):
        gate.process_frame(0, fr, float(t))
    gate.flush()
    events = gate.drain_events()
    assert len(events) == 1

    board.commit(0, dart1)
    # Same dart stuck — should look like empty vs new background.
    for t in range(5):
        assert gate.process_frame(0, dart1, 10.0 + t) is None

    dart2 = _frame(40, blob=(60, 100, 140, 180))
    dart2[70:110, 200:240] = 255  # second dart beside first
    assert gate.process_frame(0, dart2, 20.0) is None
    for t in range(5):
        ev = gate.process_frame(0, dart2, 21.0 + t)
        if ev is not None:
            break
    else:
        gate.flush()
        ev = gate.drain_events()[-1]
    assert ev is not None
    assert ev.changed_pixels < events[0].changed_pixels * 2  # not both darts double-counted wildly
