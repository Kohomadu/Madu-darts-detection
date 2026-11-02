"""Recording ``meta.json`` schema round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from madu_darts.record.meta import (
    COORDS_NORM_RADIUS_MM,
    RecordingMeta,
    VisitMeta,
    load_visit_meta,
    save_visit_meta,
)


def _throw(name: str = "S20") -> dict:
    return {
        "bed": "SingleOuter",
        "bouncer": False,
        "coordsX": 0.1,
        "coordsY": 0.2,
        "failed": False,
        "method": "UnanimousCam",
        "multiplier": 1,
        "segmentName": name,
        "segmentNumber": 20,
    }


def test_visit_meta_round_trips_autodarts_throws(tmp_path: Path) -> None:
    meta = VisitMeta(
        visit_index=0,
        opened_t_mono=1.0,
        closed_t_mono=5.0,
        throws=[_throw("S20"), _throw("T19")],
        darts=[
            {
                "index": 0,
                "t_mono": 1.0,
                "t_recv": 1.01,
                "throw": _throw("S20"),
                "frames": {"0": ["cam0/000.jpg"], "1": [], "2": []},
            }
        ],
        autodarts_status="takeout",
        autodarts_event="throwDetected",
    )
    path = tmp_path / "meta.json"
    save_visit_meta(path, meta)
    loaded = load_visit_meta(path)
    assert loaded.visit_index == 0
    assert loaded.throws[1]["segmentName"] == "T19"
    assert loaded.darts[0]["frames"]["0"] == ["cam0/000.jpg"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 1


def test_recording_meta_documents_coords_norm_radius() -> None:
    session = RecordingMeta(
        session_id="2026-11-02T12-00-00",
        board_url="http://100.118.240.5:3180",
        calibration_ref="calibration.json",
        coords_norm_radius_mm=COORDS_NORM_RADIUS_MM,
    )
    assert session.coords_norm_radius_mm == 170.0
    dumped = session.to_dict()
    assert dumped["coordsNormRadiusMm"] == 170.0
    assert RecordingMeta.from_dict(dumped).coords_norm_radius_mm == 170.0


def test_load_rejects_missing_throws(tmp_path: Path) -> None:
    path = tmp_path / "meta.json"
    path.write_text("{\"schemaVersion\": 1, \"visitIndex\": 0}", encoding="utf-8")
    with pytest.raises(ValueError, match="throws"):
        load_visit_meta(path)
