"""DetectionService + FastAPI Calibration API with a fake ingest feeding synthetic frames."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from madu_darts.calibration.synthetic import synthetic_camera

from madu_darts.cameras import CameraDevice, CamFrame, CamStats, IngestConfig
from madu_darts.server import DetectionService, ServiceConfig, create_app
from madu_darts.server.app import MJPEG_BOUNDARY

CAMS = {
    0: synthetic_camera("fronto", rotation_sectors=0),
    1: synthetic_camera("tilt_left", rotation_sectors=2),
    2: synthetic_camera("tilt_right", rotation_sectors=10),
}


@dataclass
class FakeIngest:
    config: IngestConfig
    frames: dict[int, np.ndarray]
    fail_open: str | None = None
    opened: bool = False
    closed: int = 0
    reads: int = 0

    def list_devices(self) -> list[CameraDevice]:
        return [CameraDevice(index=i, name=f"USB Camera {i}", location=s.location, path=None) for i, s in enumerate(self.config.slots)]

    def matched_devices(self) -> dict[int, CameraDevice]:
        if not self.opened:
            return {}
        return {s.slot: CameraDevice(index=s.slot, name=f"USB Camera {s.slot}", location=s.location) for s in self.config.slots}

    def open(self) -> None:
        if self.fail_open:
            raise RuntimeError(self.fail_open)
        self.opened = True

    def close(self) -> None:
        self.opened = False
        self.closed += 1

    @property
    def is_open(self) -> bool:
        return self.opened

    def read(self) -> dict[int, CamFrame]:
        if not self.opened:
            raise RuntimeError("not open")
        self.reads += 1
        out = {}
        for s in self.config.slots:
            if s.slot in self.frames:
                img = self.frames[s.slot]
                if s.rotate_180:
                    img = img[::-1, ::-1].copy()
                out[s.slot] = CamFrame(slot=s.slot, location=s.location, image=img)
        return out

    def stats(self) -> list[CamStats]:
        c = self.config.capture
        return [CamStats(slot=s.slot, location=s.location, is_opened=True, width=c.width, height=c.height, fps=float(c.fps)) for s in self.config.slots]


@dataclass
class Factory:
    frames: dict[int, np.ndarray] = field(default_factory=lambda: {s: c.image for s, c in CAMS.items()})
    fail_open: str | None = None
    created: list[FakeIngest] = field(default_factory=list)

    def __call__(self, config: IngestConfig) -> FakeIngest:
        ingest = FakeIngest(config=config, frames=self.frames, fail_open=self.fail_open)
        self.created.append(ingest)
        return ingest


def make_client(factory: Factory | None = None) -> tuple[TestClient, DetectionService, Factory]:
    factory = factory or Factory()
    service = DetectionService(ServiceConfig(first_frame_timeout_s=2.0, stream_fps=50.0), ingest_factory=factory)
    client = TestClient(create_app(service))
    return client, service, factory


# --- lifecycle / startup auto-suggest ---


def test_startup_opens_cameras_and_suggests_all() -> None:
    client, service, factory = make_client()
    with client:
        snap = client.get("/api/calibration").json()
        assert snap["accepted"] is False
        assert snap["canAccept"] is True
        assert {c["status"] for c in snap["cams"].values()} == {"pass"}
        assert len(factory.created) == 1 and factory.created[0].opened
        state = client.get("/api/state").json()
        assert state["status"] == "calibrationRequired"
        assert state["cameras"]["open"] is True
    assert factory.created[0].closed == 1  # shutdown closes ingest


def test_index_serves_calibration_view() -> None:
    client, _, _ = make_client()
    with client:
        res = client.get("/")
        assert res.status_code == 200
        assert "Calibration" in res.text and "/api/calibration" in res.text
        assert client.get("/api/version").json()["version"]


# --- rotate / accept / reset ---


def test_rotate_endpoints_update_offset_and_reject_unknown_slot() -> None:
    client, _, _ = make_client()
    with client:
        snap = client.post("/api/calibration/1/rotate-left").json()
        assert snap["cams"]["1"]["rotateOffset"] == 1
        snap = client.post("/api/calibration/1/rotate-right").json()
        snap = client.post("/api/calibration/1/rotate-right").json()
        assert snap["cams"]["1"]["rotateOffset"] == 19
        assert client.post("/api/calibration/9/rotate-left").status_code == 404
        assert client.get("/api/calibration/9/warped.jpg").status_code == 404


def test_rotate_without_fit_is_conflict() -> None:
    client, _, _ = make_client(Factory(frames={}))  # cams open but no frames
    with client:
        snap = client.get("/api/calibration").json()
        assert snap["cams"]["0"]["status"] == "none"
        assert client.post("/api/calibration/0/rotate-left").status_code == 409


def test_accept_flow_and_revocation() -> None:
    client, service, _ = make_client()
    with client:
        for slot, cam in CAMS.items():
            for _ in range(cam.correct_offset):
                client.post(f"/api/calibration/{slot}/rotate-left")

        res = client.post("/api/calibration/accept")
        assert res.status_code == 200 and res.json()["accepted"] is True
        assert client.get("/api/state").json()["status"] == "ready"

        # Gate is open: the Hit pipeline seam maps a T20 pixel to T20 on every cam.
        from madu_darts.board import point_mm_to_segment

        for slot, cam in CAMS.items():
            mm = service.session.board_point(slot, cam.pixel_of_mm(0.0, 103.4))
            assert point_mm_to_segment(*mm).name == "T20"

        client.post("/api/calibration/2/rotate-left")
        assert client.get("/api/calibration").json()["accepted"] is False

        client.post("/api/calibration/2/rotate-right")
        client.post("/api/calibration/accept")
        assert client.post("/api/calibration/reset").json()["accepted"] is False


def test_accept_blocked_returns_409_with_blockers() -> None:
    frames = {s: c.image for s, c in CAMS.items() if s != 2}
    client, _, _ = make_client(Factory(frames=frames))
    with client:
        res = client.post("/api/calibration/accept")
        assert res.status_code == 409
        assert res.json()["blockers"] == ["cam 2: no frame from camera"]


def test_auto_endpoints_resuggest() -> None:
    client, _, _ = make_client()
    with client:
        client.post("/api/calibration/0/rotate-left")
        snap = client.post("/api/calibration/auto/0").json()
        assert snap["cams"]["0"]["rotateOffset"] == 0  # fresh suggestion resets rotation
        client.post("/api/calibration/1/rotate-left")
        snap = client.post("/api/calibration/auto").json()
        assert all(c["rotateOffset"] == 0 for c in snap["cams"].values())
        assert client.post("/api/calibration/auto/7").status_code == 404


def test_autodarts_shaped_ellipses_endpoint() -> None:
    client, _, _ = make_client()
    with client:
        data = client.get("/api/config/calibration/ellipses").json()
        assert set(data) == {"0", "1", "2"}
        assert {"bull", "doubleOuter", "doubleOuterPoints", "trebleInner"} <= set(data["0"])


# --- images ---


def test_warped_and_feed_snapshots_are_jpeg() -> None:
    client, _, _ = make_client()
    with client:
        for url in ("/api/calibration/0/warped.jpg", "/api/calibration/1/feed.jpg"):
            res = client.get(url)
            assert res.status_code == 200
            assert res.headers["content-type"] == "image/jpeg"
            assert res.content[:2] == b"\xff\xd8"


def test_mjpeg_stream_yields_requested_frames() -> None:
    client, _, _ = make_client()
    with client:
        res = client.get("/stream/0.mjpg?frames=3")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("multipart/x-mixed-replace")
        body = res.content
        assert body.count(f"--{MJPEG_BOUNDARY}\r\n".encode()) == 3
        assert body.count(b"\xff\xd8") >= 3
        assert body.endswith(f"--{MJPEG_BOUNDARY}--\r\n".encode())
        assert client.get("/stream/5.mjpg?frames=1").status_code == 404


# --- cameras ---


def test_cam_config_devices_and_stats() -> None:
    client, _, _ = make_client()
    with client:
        cfg = client.get("/api/cams/config").json()
        assert (cfg["width"], cfg["height"], cfg["fps"]) == (1280, 720, 30)
        assert [s["location"] for s in cfg["slots"]] == ["7.2", "7.3", "7.4"]
        assert cfg["slots"][0]["device"]["name"] == "USB Camera 0"
        assert cfg["camerasOpen"] is True and cfg["error"] is None

        devices = client.get("/api/cams/devices").json()
        assert len(devices) == 3 and devices[1]["location"] == "7.3"

        stats = client.get("/api/cams/stats").json()
        assert len(stats["cams"]) == 3 and stats["cams"][0]["width"] == 1280


def test_patch_cam_config_reopens_and_recalibrates() -> None:
    client, _, factory = make_client()
    with client:
        client.post("/api/calibration/0/rotate-left")
        cfg = client.patch("/api/cams/config", json={"fps": 15, "rotate180": {"1": True}}).json()
        assert cfg["fps"] == 15 and cfg["width"] == 1280
        assert cfg["slots"][1]["rotate180"] is True and cfg["slots"][0]["rotate180"] is False
        assert len(factory.created) == 2 and factory.created[0].closed == 1
        assert factory.created[1].config.capture.fps == 15

        snap = client.get("/api/calibration").json()
        assert snap["cams"]["0"]["rotateOffset"] == 0  # re-suggested after reopen
        assert snap["cams"]["1"]["status"] == "pass"  # flipped frame still fits

        assert client.patch("/api/cams/config", json={"fps": 0}).status_code == 422


def test_camera_open_failure_still_serves_view_and_can_retry() -> None:
    factory = Factory(fail_open="no device at location 7.2")
    client, _, _ = make_client(factory)
    with client:
        cfg = client.get("/api/cams/config").json()
        assert cfg["camerasOpen"] is False
        assert "7.2" in cfg["error"]
        assert client.get("/").status_code == 200
        state = client.get("/api/state").json()
        assert state["cameras"]["open"] is False
        assert client.get("/api/calibration").json()["cams"]["0"]["status"] == "none"
        # Feed falls back to a placeholder instead of erroring.
        assert client.get("/api/calibration/0/feed.jpg").status_code == 200

        factory.fail_open = None
        cfg = client.post("/api/cams/reopen").json()
        assert cfg["camerasOpen"] is True and cfg["error"] is None
        assert client.get("/api/calibration").json()["canAccept"] is True


def test_devices_listed_even_when_cameras_closed() -> None:
    factory = Factory(fail_open="busy")
    client, _, _ = make_client(factory)
    with client:
        assert len(client.get("/api/cams/devices").json()) == 3


# --- service without HTTP ---


def test_service_stop_is_idempotent_and_frames_empty_after_stop() -> None:
    factory = Factory()
    service = DetectionService(ServiceConfig(first_frame_timeout_s=1.0), ingest_factory=factory)
    service.start()
    assert set(service.latest_frames()) == {0, 1, 2}
    service.stop()
    service.stop()
    assert service.latest_frames() == {}
    assert service.frame(0) is None
    assert factory.created[0].closed == 1


def test_service_recalibrate_single_slot_without_frame_marks_missing() -> None:
    factory = Factory(frames={0: CAMS[0].image, 1: CAMS[1].image})
    service = DetectionService(ServiceConfig(first_frame_timeout_s=0.3), ingest_factory=factory)
    service.start()
    try:
        snap = service.recalibrate(2)
        assert snap["cams"]["2"]["error"] == "no frame from camera"
        snap = service.recalibrate(0)
        assert snap["cams"]["0"]["status"] == "pass"
    finally:
        service.stop()
