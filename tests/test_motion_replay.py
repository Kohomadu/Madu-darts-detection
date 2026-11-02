"""Replay preferred 07 recording through the motion gate (skipped without JPEGs)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from madu_darts.motion import BoardModel, MotionConfig, MotionGate

RECORDING = (
    Path(__file__).resolve().parents[1]
    / ".scratch"
    / "detection-tool"
    / "captures"
    / "recordings"
    / "2026-11-02T08-07-55Z"
)

# Autodarts detection times land at the end of each dart window; allow half a second.
TOLERANCE_S = 0.5


def _has_pixels(recording: Path) -> bool:
    if not recording.is_dir():
        return False
    return any(recording.glob("visit-*/cam0/*.jpg"))


@pytest.mark.skipif(not _has_pixels(RECORDING), reason="07 recording JPEGs not present locally")
def test_recording_emits_one_settle_per_dart_per_cam() -> None:
    cfg = MotionConfig()  # Autodarts defaults (scale 4, stableNumFrames 3, …)
    visits = sorted(RECORDING.glob("visit-*"))
    assert visits, "recording has no visits"

    total_darts = 0
    for visit_dir in visits:
        meta = json.loads((visit_dir / "meta.json").read_text(encoding="utf-8"))
        darts = meta["darts"]
        total_darts += len(darts)
        board = BoardModel((0, 1, 2))
        gate = MotionGate(board, cfg, slots=(0, 1, 2))
        gate.set_enabled(True)

        # Empty-Board reference: first frame of dart 0 per cam.
        first = darts[0]
        refs = {}
        for cam, paths in first["frames"].items():
            img = cv2.imread(str(visit_dir / paths[0]))
            assert img is not None, paths[0]
            refs[int(cam)] = img
        board.capture_all(refs)

        for dart in darts:
            t_detect = float(dart["t_mono"])
            # Merge per-cam frames by timestamp so cams stay roughly in lockstep.
            by_t: dict[float, dict[int, np.ndarray]] = {}
            for cam, paths in dart["frames"].items():
                for path in paths:
                    # …/d00_015_t9354.250.jpg
                    stem = Path(path).stem
                    t = float(stem.split("_t", 1)[1])
                    img = cv2.imread(str(visit_dir / path))
                    assert img is not None, path
                    by_t.setdefault(t, {})[int(cam)] = img

            before = len(gate.peek_events())
            for t in sorted(by_t):
                gate.process_frames(by_t[t], t)
            gate.flush()
            new_events = gate.peek_events()[before:]

            # Exactly one settled-change per cam that saw the dart.
            cams_with_frames = {int(c) for c in dart["frames"]}
            by_cam: dict[int, list] = {c: [] for c in cams_with_frames}
            for ev in new_events:
                by_cam.setdefault(ev.slot, []).append(ev)

            for cam in cams_with_frames:
                events = by_cam.get(cam, [])
                assert len(events) == 1, (
                    f"{visit_dir.name} dart {dart['index']} cam {cam}: "
                    f"expected 1 settled event, got {len(events)}"
                )
                assert abs(events[0].t_mono - t_detect) <= TOLERANCE_S, (
                    f"{visit_dir.name} dart {dart['index']} cam {cam}: "
                    f"settle t={events[0].t_mono} vs autodarts {t_detect}"
                )

            # Fold stuck dart into background for the next dart (09/10 seam).
            last_t = max(by_t)
            for cam, img in by_t[last_t].items():
                board.commit(cam, img)
                # Reset per-cam phase so the next impact is a fresh motion cycle.
            gate.reset()
            gate.set_enabled(True)

    assert total_darts == 24


@pytest.mark.skipif(not _has_pixels(RECORDING), reason="07 recording JPEGs not present locally")
def test_still_prefix_emits_nothing() -> None:
    """Frames before the dart arrives must not settle."""
    visit = RECORDING / "visit-00"
    meta = json.loads((visit / "meta.json").read_text(encoding="utf-8"))
    dart = meta["darts"][0]
    cfg = MotionConfig()
    board = BoardModel((0,))
    gate = MotionGate(board, cfg, slots=(0,))
    gate.set_enabled(True)
    paths = dart["frames"]["0"]
    first = cv2.imread(str(visit / paths[0]))
    board.capture(0, first)
    # Only the quiet prefix (exclude last 4 frames where impact lives).
    for path in paths[:-4]:
        img = cv2.imread(str(visit / path))
        stem = Path(path).stem
        t = float(stem.split("_t", 1)[1])
        assert gate.process_frame(0, img, t) is None
    assert gate.drain_events() == []
