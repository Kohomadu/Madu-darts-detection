"""Ticket 13: mount rotate-20 defaults applied after suggest + last-Accepted persistence."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from madu_darts.calibration import (
    DEFAULT_ROTATE_OFFSETS,
    CalibrationSession,
    CamCalibration,
    load_rotate_offsets,
    save_rotate_offsets,
)
from madu_darts.server import DetectionService, ServiceConfig, create_app
from fastapi.testclient import TestClient
from tests.test_server import Factory


def _fake(results: dict[int, CamCalibration]):
    def suggester(image, slot, params):
        return results[slot]

    return suggester


def _good(slot: int) -> CamCalibration:
    return CamCalibration(slot=slot, homography=np.eye(3), rms_mm=0.5, rotate_offset=0)


FRAMES = {0: np.zeros((2, 2, 3), np.uint8), 1: np.zeros((2, 2, 3), np.uint8), 2: np.zeros((2, 2, 3), np.uint8)}


def test_default_board_offsets() -> None:
    assert DEFAULT_ROTATE_OFFSETS == {0: 10, 1: 4, 2: 16}


def test_suggest_applies_mount_defaults() -> None:
    session = CalibrationSession(
        suggester=_fake({0: _good(0), 1: _good(1), 2: _good(2)}),
        default_rotate_offsets=DEFAULT_ROTATE_OFFSETS,
        offset_store=None,
    )
    session.suggest_all(FRAMES)
    assert {s: session.get(s).rotate_offset for s in (0, 1, 2)} == {0: 10, 1: 4, 2: 16}


def test_accept_persists_and_reloads_offsets(tmp_path: Path) -> None:
    store = tmp_path / "offsets.json"
    session = CalibrationSession(
        suggester=_fake({0: _good(0), 1: _good(1), 2: _good(2)}),
        default_rotate_offsets={0: 10, 1: 4, 2: 16},
        offset_store=store,
    )
    session.suggest_all(FRAMES)
    session.rotate_left(0)  # 10 → 11 (operator fine-tune)
    session.accept()
    assert store.is_file()
    saved = json.loads(store.read_text(encoding="utf-8"))["rotateOffsets"]
    assert saved == {"0": 11, "1": 4, "2": 16}
    assert load_rotate_offsets(store, defaults={0: 10, 1: 4, 2: 16})[0] == 11

    session2 = CalibrationSession(
        suggester=_fake({0: _good(0), 1: _good(1), 2: _good(2)}),
        default_rotate_offsets={0: 10, 1: 4, 2: 16},
        offset_store=store,
    )
    session2.suggest_all(FRAMES)
    assert session2.get(0).rotate_offset == 11
    assert session2.get(1).rotate_offset == 4
    assert session2.get(2).rotate_offset == 16


def test_detection_service_auto_calibrate_uses_board_defaults(tmp_path: Path) -> None:
    factory = Factory()
    service = DetectionService(
        ServiceConfig(
            first_frame_timeout_s=2.0,
            stream_fps=50.0,
            rotate_offsets=dict(DEFAULT_ROTATE_OFFSETS),
            offset_store=str(tmp_path / "offsets.json"),
            bind_store=str(tmp_path / "bind.json"),
        ),
        ingest_factory=factory,
    )
    client = TestClient(create_app(service))
    with client:
        snap = client.get("/api/calibration").json()
        # Startup suggest_all already ran with mount defaults.
        assert snap["cams"]["0"]["rotateOffset"] == 10
        assert snap["cams"]["1"]["rotateOffset"] == 4
        assert snap["cams"]["2"]["rotateOffset"] == 16
        # Re-auto keeps them.
        snap = client.post("/api/calibration/auto").json()
        assert snap["cams"]["0"]["rotateOffset"] == 10
