"""Visit history + auto/manual captures (live testing support)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from madu_darts.server import DetectionService, ServiceConfig, create_app
from tests.test_hits_tip_fusion import draw_dart
from tests.test_server import CAMS, Factory, _accept


def _wait_throws(client: TestClient, n: int, timeout_s: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout_s
    st = client.get("/api/state").json()
    while time.monotonic() < deadline:
        st = client.get("/api/state").json()
        if len(st.get("throws") or []) >= n:
            return st
        time.sleep(0.05)
    return st


@pytest.fixture
def live_client(tmp_path: Path):
    factory = Factory()
    service = DetectionService(
        ServiceConfig(
            first_frame_timeout_s=2.0,
            stream_fps=50.0,
            capture_root=str(tmp_path / "live"),
            rotate_offsets={},
            offset_store=None,
        ),
        ingest_factory=factory,
    )
    client = TestClient(create_app(service))
    return client, service, factory, tmp_path


def test_history_empty_then_current_and_sealed_on_reset(live_client) -> None:
    client, service, factory, _ = live_client
    with client:
        assert client.get("/api/history").json() == {
            "visits": [],
            "current": None,
            "count": 0,
            "lastVisitId": None,
        }
        _accept(client)
        time.sleep(0.3)
        for slot, cam in CAMS.items():
            factory.frames[slot] = draw_dart(cam.image, cam.pixel_of_mm(0.0, 103.4), angle_deg=5.0)
        st = _wait_throws(client, 1)
        assert st["throws"], "expected a Hit on the open Turn"
        hist = client.get("/api/history").json()
        assert hist["current"] is not None and hist["current"]["segmentNames"]
        assert hist["count"] == 0

        client.post("/api/reset")
        hist = client.get("/api/history").json()
        assert hist["count"] == 1 and hist["current"] is None
        visit = hist["visits"][0]
        assert visit["reason"] == "reset"
        assert visit["segmentNames"] == [st["throws"][0]["segmentName"]]
        assert client.get(f"/api/history/{visit['id']}").json()["id"] == visit["id"]
        assert client.get("/api/state").json()["madu"]["historyCount"] == 1
        assert client.get("/api/state").json()["madu"]["lastVisitId"] == visit["id"]


def test_manual_and_auto_capture_write_jpegs(live_client) -> None:
    client, service, factory, tmp_path = live_client
    with client:
        _accept(client)
        time.sleep(0.3)
        pack = client.post("/api/capture").json()
        assert pack["id"] and pack["frames"]
        for slot, url in pack["frames"].items():
            res = client.get(url)
            assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
            assert res.content[:2] == b"\xff\xd8"
        assert (tmp_path / "live" / pack["id"] / "state.json").is_file()
        assert client.get(f"/api/captures/{pack['id']}/state.json").json()["id"] == pack["id"]
        assert client.get("/api/captures").json()["captures"]

        raw = client.get("/api/cams/0/frame.jpg")
        assert raw.status_code == 200 and raw.content[:2] == b"\xff\xd8"

        targets = [(0.0, 103.4), (-130.0, 0.0), (-135.0, -98.0)]
        stuck: dict[int, np.ndarray] = {s: c.image for s, c in CAMS.items()}
        for i, target in enumerate(targets):
            stuck = {
                s: draw_dart(stuck[s], CAMS[s].pixel_of_mm(*target), angle_deg=5.0 - 4.0 * i) for s in CAMS
            }
            for slot in CAMS:
                factory.frames[slot] = stuck[slot]
            st = _wait_throws(client, i + 1)
            assert len(st["throws"]) >= i + 1, f"dart {i} not detected"

        assert st["status"] == "takeout" and st["madu"]["captureId"]
        auto_id = st["madu"]["captureId"]
        assert client.get(f"/api/captures/{auto_id}/1.jpg").status_code == 200

        for slot, cam in CAMS.items():
            factory.frames[slot] = cam.image
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            st = client.get("/api/state").json()
            if st["event"] == "takeoutFinished":
                break
            time.sleep(0.05)
        hist = client.get("/api/history").json()
        assert hist["count"] >= 1
        last = hist["visits"][-1]
        assert last["captureId"] == auto_id
        assert len(last["throws"]) == 3
        assert last["reason"] == "takeoutFinished"


def test_history_clear(live_client) -> None:
    client, _, factory, _ = live_client
    with client:
        _accept(client)
        time.sleep(0.3)
        for slot, cam in CAMS.items():
            factory.frames[slot] = draw_dart(cam.image, cam.pixel_of_mm(0.0, 103.4))
        assert _wait_throws(client, 1)["throws"]
        client.post("/api/reset")
        assert client.get("/api/history").json()["count"] == 1
        cleared = client.post("/api/history/clear").json()
        assert cleared["count"] == 0 and cleared["visits"] == []
