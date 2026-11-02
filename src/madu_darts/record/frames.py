"""Frame sources for the visit recorder (local cams, Madu, or Autodarts MJPEG)."""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

import numpy as np

from madu_darts.cameras import CameraIngest, IngestConfig
from madu_darts.record.mjpeg import extract_jpeg_frames
from madu_darts.server.service import FramePump

log = logging.getLogger(__name__)


class FrameSource(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest(self) -> dict[int, np.ndarray]: ...


class NullFrameSource:
    """Throws-only recording (no cam frames)."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def latest(self) -> dict[int, np.ndarray]:
        return {}


class LocalPumpFrameSource:
    """``CameraIngest`` + ``FramePump`` — intended to run on the Board."""

    def __init__(self, config: IngestConfig | None = None, *, fps: float = 10.0) -> None:
        self._config = config or IngestConfig()
        self._fps = fps
        self._ingest: CameraIngest | None = None
        self._pump: FramePump | None = None

    def start(self) -> None:
        ingest = CameraIngest(self._config)
        ingest.open()
        pump = FramePump(ingest, fps=self._fps)
        pump.start()
        self._ingest = ingest
        self._pump = pump

    def stop(self) -> None:
        if self._pump is not None:
            self._pump.stop()
            self._pump.join(timeout=2.0)
            self._pump = None
        if self._ingest is not None:
            self._ingest.close()
            self._ingest = None

    def latest(self) -> dict[int, np.ndarray]:
        if self._pump is None:
            return {}
        return {slot: frame.image for slot, frame in self._pump.latest().items()}


class MaduFeedFrameSource:
    """Pull latest JPEG tiles from a running Madu Calibration view (`:3181`)."""

    def __init__(self, madu_url: str, *, slots: tuple[int, ...] = (0, 1, 2), timeout_s: float = 2.0) -> None:
        self._base = madu_url.rstrip("/")
        self._slots = slots
        self._timeout_s = timeout_s

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def latest(self) -> dict[int, np.ndarray]:
        import cv2

        out: dict[int, np.ndarray] = {}
        for slot in self._slots:
            url = f"{self._base}/api/calibration/{slot}/feed.jpg"
            try:
                with urllib.request.urlopen(url, timeout=self._timeout_s) as resp:
                    data = np.frombuffer(resp.read(), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if image is not None:
                    out[slot] = image
            except Exception as exc:
                log.debug("madu feed %s failed: %s", url, exc)
        return out


class AutodartsStreamFrameSource:
    """Background readers for Autodarts ``GET /api/streams/live?cam=N`` MJPEG.

    Same feeds the Board Manager cameras page uses — reachable from Windows over
    the LAN without opening USB devices.
    """

    def __init__(
        self,
        board_url: str,
        *,
        slots: tuple[int, ...] = (0, 1, 2),
        warp: bool = False,
        reconnect_s: float = 2.0,
    ) -> None:
        self._base = board_url.rstrip("/")
        self._slots = slots
        self._warp = warp
        self._reconnect_s = reconnect_s
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: dict[int, np.ndarray] = {}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("AutodartsStreamFrameSource already started")
        self._stop.clear()
        for slot in self._slots:
            thread = threading.Thread(
                target=self._run_slot,
                name=f"madu-ad-mjpeg-{slot}",
                args=(slot,),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()

    def latest(self) -> dict[int, np.ndarray]:
        with self._lock:
            return {slot: image for slot, image in self._latest.items()}

    def _stream_url(self, slot: int) -> str:
        url = f"{self._base}/api/streams/live?cam={int(slot)}"
        if self._warp:
            url += "&warp=true"
        return url

    def _run_slot(self, slot: int) -> None:
        import cv2

        while not self._stop.is_set():
            url = self._stream_url(slot)
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    buf = b""
                    while not self._stop.is_set():
                        chunk = resp.read(16384)
                        if not chunk:
                            break
                        buf += chunk
                        frames, buf = extract_jpeg_frames(buf)
                        if len(buf) > 8_000_000:
                            buf = buf[-1_000_000:]
                        for jpeg in frames:
                            image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if image is None:
                                continue
                            with self._lock:
                                self._latest[slot] = image
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if not self._stop.is_set():
                    log.warning("Autodarts MJPEG cam %s failed: %s", slot, exc)
            if not self._stop.is_set():
                self._stop.wait(self._reconnect_s)


class RingSampler:
    """Sample a ``FrameSource`` into a ring buffer at a fixed rate."""

    def __init__(self, source: FrameSource, buffer: Any, *, fps: float = 10.0) -> None:
        self._source = source
        self._buffer = buffer
        self._interval = 1.0 / max(fps, 0.1)
        self._next = 0.0

    def tick(self, t_mono: float | None = None) -> None:
        now = time.monotonic() if t_mono is None else float(t_mono)
        if now < self._next:
            return
        frames = self._source.latest()
        if frames:
            self._buffer.push(now, frames)
        self._next = now + self._interval
