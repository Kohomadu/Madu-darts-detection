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
from fastapi import FastAPI, HTTPException, Query
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
        return draw_calibration_tile(frame, session.get(slot))

    def warped_image(slot: int) -> np.ndarray:
        frame = service.frame(slot)
        if frame is None:
            return _placeholder(400, 400)
        return draw_warped_board(frame, session.get(slot))

    # --- view ---

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    # --- state ---

    @app.get("/api/version")
    def version() -> dict[str, str]:
        from madu_darts import __version__

        return {"version": __version__}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        snap = session.snapshot()
        return {
            "status": "ready" if snap["accepted"] else "calibrationRequired",
            "calibration": snap,
            "cameras": {"open": service.cam_config()["camerasOpen"], "error": service.camera_error},
        }

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
        return session.snapshot()

    @app.get("/api/config/calibration/ellipses")
    def ellipses() -> dict[str, Any]:
        return session.to_autodarts_ellipses()

    @app.post("/api/calibration/auto")
    def auto_all() -> dict[str, Any]:
        return service.recalibrate()

    @app.post("/api/calibration/auto/{slot}")
    def auto_one(slot: int) -> dict[str, Any]:
        return service.recalibrate(check_slot(slot))

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
        return session.snapshot()

    @app.post("/api/calibration/accept")
    def accept() -> JSONResponse:
        try:
            session.accept()
        except AcceptBlocked as exc:
            return JSONResponse(status_code=409, content={"detail": "accept blocked", "blockers": exc.blockers})
        return JSONResponse(session.snapshot())

    @app.post("/api/calibration/reset")
    def reset() -> dict[str, Any]:
        session.reset()
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
