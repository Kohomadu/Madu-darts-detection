"""FastAPI app: Calibration view + Madu-owned local API (Autodarts-shaped where free).

Binds beyond loopback by default (ADR 0003: reachable over the Board's Tailscale IP).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from madu_darts.calibration import AcceptBlocked, draw_calibration_tile, draw_warped_board
from madu_darts.server.service import DetectionService

STATIC_DIR = Path(__file__).parent / "static"
MJPEG_BOUNDARY = "madu-frame"


class CamConfigPatch(BaseModel):
    width: int | None = Field(default=None, ge=160, le=4096)
    height: int | None = Field(default=None, ge=120, le=2160)
    fps: int | None = Field(default=None, ge=1, le=120)
    rotate180: dict[int, bool] | None = None


class CalibrationDisplayPatch(BaseModel):
    showResiduals: bool | None = None


class NudgePanBody(BaseModel):
    dx: float = 0.0
    dy: float = 0.0


class NudgeRotateBody(BaseModel):
    deg: float = 1.0


class HitOverridePatch(BaseModel):
    """Manual Hit correction: segment label and/or Board-mm point."""

    segmentName: str | None = None
    xMm: float | None = None
    yMm: float | None = None


def _encode_jpeg(image: np.ndarray, quality: int) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def _placeholder(width: int = 640, height: int = 360, text: str = "NO SIGNAL") -> np.ndarray:
    import cv2

    img = np.full((height, width, 3), 24, dtype=np.uint8)
    cv2.putText(img, text, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (90, 90, 90), 2, cv2.LINE_AA)
    return img


def create_app(service: DetectionService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await asyncio.to_thread(service.start)
        try:
            yield
        finally:
            await asyncio.to_thread(service.stop)

    app = FastAPI(title="Madu Darts detection", version="0.1.0", lifespan=lifespan)
    session = service.session

    def check_slot(slot: int) -> int:
        if slot not in session.slots:
            raise HTTPException(status_code=404, detail=f"unknown camera slot {slot}")
        return slot

    def feed_image(slot: int) -> np.ndarray:
        frame = service.frame(slot)
        if frame is None:
            return _placeholder()
        return draw_calibration_tile(frame, session.get(slot), show_residuals=service.show_residuals)

    def warped_image(slot: int) -> np.ndarray:
        frame = service.frame(slot)
        if frame is None:
            return _placeholder(400, 400)
        return draw_warped_board(frame, session.get(slot), show_residuals=service.show_residuals)

    # --- view ---

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/detection", response_class=HTMLResponse)
    def detection_view() -> str:
        return (STATIC_DIR / "detection.html").read_text(encoding="utf-8")

    # --- state ---

    @app.get("/api/version")
    def version() -> dict[str, str]:
        from madu_darts import __version__

        return {"version": __version__}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        """Autodarts 2.1 shape (ADR 0004) + ``calibration`` / ``cameras`` / ``madu`` blocks."""
        return service.api_state()

    @app.websocket("/api/events")
    async def events(ws: WebSocket, motion: int = Query(default=0)) -> None:
        """Push ``{type:"state", data}`` on every change (full visit-so-far); ``?motion=1`` adds
        a ``{type:"motion", data}`` debug channel at ~5 Hz."""
        await ws.accept()
        seq = service.state_seq
        motion_interval = 0.2
        last_motion = 0.0
        try:
            await ws.send_json({"type": "state", "data": service.api_state()})
            while True:
                for s, st in await asyncio.to_thread(service.wait_for_states, seq, 0.25):
                    seq = s
                    await ws.send_json({"type": "state", "data": st})
                if motion and time.monotonic() - last_motion >= motion_interval:
                    last_motion = time.monotonic()
                    await ws.send_json({"type": "motion", "data": service.motion_state()})
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/api/state/motion")
    def motion_state() -> dict[str, Any]:
        return service.motion_state()

    @app.get("/api/state/turn")
    def turn_state() -> dict[str, Any]:
        """Autodarts-shaped ``{running, status, event, throws}`` + Madu Turn debug fields."""
        return service.turn_state()

    @app.get("/api/state/hits")
    def hits_state() -> dict[str, Any]:
        return service.hits_state()

    @app.post("/api/state/hits/clear")
    def clear_hits() -> dict[str, Any]:
        return service.reset_turn()

    # --- detector controls (Autodarts: PUT /api/start|stop, POST /api/reset) ---

    @app.api_route("/api/start", methods=["PUT", "POST"])
    def start_detection() -> dict[str, Any]:
        if not session.accepted:
            raise HTTPException(status_code=409, detail="calibration not accepted")
        try:
            return service.start_detection()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.api_route("/api/stop", methods=["PUT", "POST"])
    def stop_detection() -> dict[str, Any]:
        return service.stop_detection()

    @app.post("/api/reset")
    def reset_turn() -> dict[str, Any]:
        return service.reset_turn()

    @app.post("/api/recheck")
    def recheck() -> dict[str, Any]:
        """Mid-Turn classical vision Recheck (ticket 17)."""
        if not session.accepted:
            raise HTTPException(status_code=409, detail="calibration not accepted")
        try:
            return service.recheck()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/state/hits/{index}")
    def override_hit(index: int, body: HitOverridePatch) -> dict[str, Any]:
        """Manual Hit override by segmentName or xMm/yMm (ticket 18)."""
        payload = body.model_dump(exclude_none=True)
        try:
            return service.override_hit(index, payload)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/config")
    def api_config() -> dict[str, Any]:
        return service.api_config()

    # --- visit history (survives takeout) + remote captures ---

    @app.get("/api/history")
    def history() -> dict[str, Any]:
        return service.history_state()

    @app.get("/api/history/{visit_id}")
    def history_one(visit_id: str) -> dict[str, Any]:
        visit = service.live.visit(visit_id)
        if visit is None:
            raise HTTPException(status_code=404, detail=f"unknown visit {visit_id}")
        return visit

    @app.post("/api/history/clear")
    def history_clear() -> dict[str, Any]:
        return service.clear_history()

    @app.post("/api/capture")
    def capture() -> dict[str, Any]:
        try:
            return service.capture_now(reason="manual")
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/captures")
    def captures() -> dict[str, Any]:
        return {"captures": service.live.list_captures()}

    @app.get("/api/captures/{capture_id}/state.json")
    def capture_state(capture_id: str) -> dict[str, Any]:
        data = service.live.read_capture_state(capture_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"unknown capture {capture_id}")
        return data

    @app.get("/api/captures/{capture_id}/{slot}.jpg")
    def capture_frame(capture_id: str, slot: int) -> Response:
        check_slot(slot)
        jpeg = service.live.read_capture_jpeg(capture_id, slot)
        if jpeg is None:
            raise HTTPException(status_code=404, detail=f"no frame for capture {capture_id} cam {slot}")
        return Response(jpeg, media_type="image/jpeg")

    # --- cameras ---

    @app.get("/api/cams/devices")
    def devices() -> list[dict[str, Any]]:
        return service.devices()

    @app.get("/api/cams/stats")
    def stats() -> dict[str, Any]:
        return service.stats()

    @app.get("/api/cams/config")
    def cam_config() -> dict[str, Any]:
        return service.cam_config()

    @app.get("/api/cams/{slot}/frame.jpg")
    def cam_frame_jpg(slot: int) -> Response:
        """Raw latest cam frame (no calibration overlay) for remote snaps."""
        check_slot(slot)
        frame = service.frame(slot)
        img = _placeholder() if frame is None else frame
        return Response(_encode_jpeg(img, service.config.jpeg_quality), media_type="image/jpeg")

    @app.patch("/api/cams/config")
    def patch_cam_config(patch: CamConfigPatch) -> dict[str, Any]:
        return service.update_cam_config(
            width=patch.width,
            height=patch.height,
            fps=patch.fps,
            rotate_180=patch.rotate180,
        )

    @app.post("/api/cams/reopen")
    def reopen() -> dict[str, Any]:
        if service.reopen_cameras():
            service.recalibrate()
        return service.cam_config()

    # --- calibration ---

    @app.get("/api/calibration")
    def calibration() -> dict[str, Any]:
        snap = session.snapshot()
        snap["showResiduals"] = service.show_residuals
        return snap

    @app.patch("/api/calibration/display")
    def calibration_display(body: CalibrationDisplayPatch) -> dict[str, Any]:
        if body.showResiduals is not None:
            service.set_show_residuals(body.showResiduals)
        snap = session.snapshot()
        snap["showResiduals"] = service.show_residuals
        return snap

    @app.get("/api/config/calibration/ellipses")
    def ellipses() -> dict[str, Any]:
        return session.to_autodarts_ellipses()

    @app.post("/api/calibration/auto")
    def auto_all(force: int = Query(default=0)) -> dict[str, Any]:
        snap = service.recalibrate(force=bool(force))
        service.sync_motion_with_calibration()
        service.publish_state()
        return snap

    @app.post("/api/calibration/auto/{slot}")
    def auto_one(slot: int, force: int = Query(default=0)) -> dict[str, Any]:
        snap = service.recalibrate(check_slot(slot), force=bool(force))
        service.sync_motion_with_calibration()
        service.publish_state()
        return snap

    @app.post("/api/calibration/{slot}/rotate-left")
    def rotate_left(slot: int) -> dict[str, Any]:
        return _rotate(check_slot(slot), left=True)

    @app.post("/api/calibration/{slot}/rotate-right")
    def rotate_right(slot: int) -> dict[str, Any]:
        return _rotate(check_slot(slot), left=False)

    def _rotate(slot: int, *, left: bool) -> dict[str, Any]:
        try:
            session.rotate_left(slot) if left else session.rotate_right(slot)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        service.sync_motion_with_calibration()
        service.publish_state()
        return session.snapshot()

    @app.post("/api/calibration/{slot}/nudge-pan")
    def nudge_pan(slot: int, body: NudgePanBody) -> dict[str, Any]:
        try:
            session.nudge_pan(check_slot(slot), body.dx, body.dy)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        service.sync_motion_with_calibration()
        service.publish_state()
        return session.snapshot()

    @app.post("/api/calibration/{slot}/nudge-rotate")
    def nudge_rotate(slot: int, body: NudgeRotateBody) -> dict[str, Any]:
        try:
            session.nudge_rotate(check_slot(slot), body.deg)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        service.sync_motion_with_calibration()
        service.publish_state()
        return session.snapshot()

    @app.post("/api/calibration/{slot}/revert-auto")
    def revert_auto(slot: int) -> dict[str, Any]:
        try:
            session.revert_auto(check_slot(slot))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        service.sync_motion_with_calibration()
        service.publish_state()
        return session.snapshot()

    @app.post("/api/calibration/{slot}/reset-bind")
    def reset_bind(slot: int) -> dict[str, Any]:
        session.reset_bind(check_slot(slot))
        service.sync_motion_with_calibration()
        service.publish_state()
        return session.snapshot()

    @app.post("/api/calibration/accept")
    def accept() -> JSONResponse:
        try:
            session.accept()
        except AcceptBlocked as exc:
            return JSONResponse(status_code=409, content={"detail": "accept blocked", "blockers": exc.blockers})
        service.on_calibration_accepted()
        service.publish_state()
        return JSONResponse(session.snapshot())

    @app.post("/api/calibration/reset")
    def reset() -> dict[str, Any]:
        session.reset()
        service.on_calibration_reset()
        service.publish_state()
        return session.snapshot()

    # --- images ---

    @app.get("/api/calibration/{slot}/feed.jpg")
    def feed_jpg(slot: int) -> Response:
        img = feed_image(check_slot(slot))
        return Response(_encode_jpeg(img, service.config.jpeg_quality), media_type="image/jpeg")

    @app.get("/api/calibration/{slot}/warped.jpg")
    def warped_jpg(slot: int) -> Response:
        img = warped_image(check_slot(slot))
        return Response(_encode_jpeg(img, service.config.jpeg_quality), media_type="image/jpeg")

    @app.get("/stream/{slot}.mjpg")
    async def stream(slot: int, frames: int | None = Query(default=None, ge=1, le=100000)) -> StreamingResponse:
        check_slot(slot)
        interval = 1.0 / max(service.config.stream_fps, 0.5)
        quality = service.config.jpeg_quality

        async def generate():
            sent = 0
            while frames is None or sent < frames:
                started = time.monotonic()
                jpeg = await asyncio.to_thread(lambda: _encode_jpeg(feed_image(slot), quality))
                yield (
                    f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n".encode()
                    + jpeg
                    + b"\r\n"
                )
                sent += 1
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))
            yield f"--{MJPEG_BOUNDARY}--\r\n".encode()

        return StreamingResponse(
            generate(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
        )

    return app
