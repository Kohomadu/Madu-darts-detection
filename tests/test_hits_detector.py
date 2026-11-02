"""HitDetector end-to-end on three synthetic cams: frames → gate → tips → fused Hit."""

from __future__ import annotations

import math

import numpy as np

from madu_darts.board import point_mm_to_segment
from madu_darts.calibration.homography import apply_homography
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits import UNANIMOUS, FusionConfig, HitDetector, TipConfig
from madu_darts.motion import BoardModel, MotionConfig, MotionGate
from tests.test_hits_tip_fusion import draw_dart

CAMS = {0: synthetic_camera("fronto"), 1: synthetic_camera("tilt_left"), 2: synthetic_camera("tilt_right")}


def _board_point(slot: int, px: tuple[float, float]) -> np.ndarray:
    return apply_homography(CAMS[slot].truth_homography, px)


def _run(target_mm: tuple[float, float], *, motion: MotionConfig | None = None) -> tuple:
    cfg = motion or MotionConfig()
    board = BoardModel((0, 1, 2))
    gate = MotionGate(board, cfg, slots=(0, 1, 2))
    detector = HitDetector(
        _board_point,
        board,
        slots=(0, 1, 2),
        motion_scale=cfg.scale,
        tip_config=TipConfig(),
        fusion_config=FusionConfig(collect_window_s=0.4),
    )
    empty = {s: c.image for s, c in CAMS.items()}
    board.capture_all(empty)
    gate.set_enabled(True)

    stuck = {s: draw_dart(c.image, c.pixel_of_mm(*target_mm), angle_deg=5.0) for s, c in CAMS.items()}
    # Approach frame: dart drawn a bit higher (still moving), then stuck + quiet frames.
    approach = {s: draw_dart(c.image, c.pixel_of_mm(*target_mm) + np.array([0.0, -30.0]), angle_deg=5.0) for s, c in CAMS.items()}

    t = 0.0
    hit = None
    for frames in [empty, empty, approach, stuck, stuck, stuck, stuck, stuck]:
        t += 0.1
        for event in gate.process_frames(frames, t):
            detector.offer(event, frames[event.slot])
        hit = detector.poll(t, latest_frames=frames) or hit
    if hit is None:
        for event in gate.flush():
            detector.offer(event, stuck[event.slot])
        hit = detector.poll(t + 1.0, force=True, latest_frames=stuck)
    return hit, board, gate, detector


def test_three_cams_agree_on_t20() -> None:
    target = (0.0, 103.4)
    hit, board, _, detector = _run(target)
    assert hit is not None
    assert hit.method == UNANIMOUS
    assert hit.segment.name == "T20"
    assert math.hypot(hit.x_mm - target[0], hit.y_mm - target[1]) <= 4.0
    assert len(hit.slot_votes) == 3 and all(v.used for v in hit.slot_votes)
    assert hit.to_autodarts_throw()["segmentName"] == "T20"
    # Dart folded into the background → references changed on every cam.
    assert all(not np.array_equal(board.reference(s), CAMS[s].image) for s in CAMS)
    assert not detector.pending


def test_second_dart_is_detected_against_committed_background() -> None:
    first = (0.0, 103.4)
    hit1, board, gate, detector = _run(first)
    assert hit1 is not None and hit1.segment.name == "T20"

    second = (-60.0, 20.0)
    frames_with_both = {
        s: draw_dart(draw_dart(c.image, c.pixel_of_mm(*first), angle_deg=5.0), c.pixel_of_mm(*second), angle_deg=-6.0)
        for s, c in CAMS.items()
    }
    gate.reset()
    gate.set_enabled(True)
    t = 10.0
    hit2 = None
    for _ in range(6):
        t += 0.1
        for event in gate.process_frames(frames_with_both, t):
            detector.offer(event, frames_with_both[event.slot])
        hit2 = detector.poll(t, latest_frames=frames_with_both) or hit2
    if hit2 is None:
        for event in gate.flush():
            detector.offer(event, frames_with_both[event.slot])
        hit2 = detector.poll(t + 1.0, force=True, latest_frames=frames_with_both)
    assert hit2 is not None
    assert hit2.segment.name == point_mm_to_segment(*second).name
    assert math.hypot(hit2.x_mm - second[0], hit2.y_mm - second[1]) <= 4.0


def test_detector_waits_for_window_then_emits_single_cam() -> None:
    board = BoardModel((0, 1, 2))
    gate = MotionGate(board, MotionConfig(), slots=(0, 1, 2))
    detector = HitDetector(_board_point, board, slots=(0, 1, 2), fusion_config=FusionConfig(collect_window_s=0.5))
    board.capture_all({s: c.image for s, c in CAMS.items()})
    gate.set_enabled(True)
    target = (40.0, -120.0)
    stuck0 = draw_dart(CAMS[0].image, CAMS[0].pixel_of_mm(*target))
    t = 0.0
    for _ in range(6):
        t += 0.1
        for event in gate.process_frames({0: stuck0}, t):
            detector.offer(event, stuck0)
    for event in gate.flush():
        detector.offer(event, stuck0)
    assert detector.pending
    assert detector.poll(t) is None  # other cams still have time to report
    hit = detector.poll(t + 0.6)
    assert hit is not None and hit.method == "BestCam" and hit.slot_votes[0].slot == 0
    assert hit.segment.name == point_mm_to_segment(*target).name
