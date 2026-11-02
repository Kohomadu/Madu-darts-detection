"""Orchestrate Autodarts state + frame ring → on-disk Recording."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from madu_darts.record.board_client import BoardClient
from madu_darts.record.frames import FrameSource, NullFrameSource, RingSampler
from madu_darts.record.ring_buffer import FrameRingBuffer
from madu_darts.record.visit import DartObserved, VisitClosed, VisitSegmenter
from madu_darts.record.writer import SessionWriter

log = logging.getLogger(__name__)


class VisitRecorder:
    """Dev tool: subscribe/poll Autodarts, dump frames around each stuck dart."""

    def __init__(
        self,
        board: BoardClient,
        out_dir: Path,
        *,
        frames: FrameSource | None = None,
        ring_window_s: float = 2.0,
        sample_fps: float = 10.0,
        poll_hz: float = 5.0,
        calibration: dict[str, Any] | None = None,
    ) -> None:
        self._board = board
        self._frames = frames or NullFrameSource()
        self._writer = SessionWriter(Path(out_dir), board_url=board.board_url)
        self._ring = FrameRingBuffer(window_s=ring_window_s)
        self._sample_fps = sample_fps
        self._sampler = RingSampler(self._frames, self._ring, fps=sample_fps)
        self._segmenter = VisitSegmenter()
        self._poll_hz = poll_hz
        self._calibration = calibration
        self._visit_open = False
        self._sample_stop = threading.Event()
        self._sample_thread: threading.Thread | None = None

    @property
    def session_dir(self) -> Path:
        return self._writer.session_dir

    def prepare(self) -> Path:
        """Fetch Autodarts ellipses (unless overridden) and start the frame source."""
        calib = self._calibration
        if calib is None:
            try:
                ellipses = self._board.fetch_calibration_ellipses()
                calib = {
                    "source": "autodarts",
                    "boardUrl": self._board.board_url,
                    "ellipses": ellipses,
                    "note": (
                        "Autodarts ellipses captured for geometry reference. "
                        "Madu homographies are preferred when available via --madu."
                    ),
                }
            except Exception as exc:
                log.warning("could not fetch Autodarts ellipses: %s", exc)
                calib = {"source": "none", "error": str(exc)}
        self._writer.write_calibration(calib)
        self._frames.start()
        self._start_sampler()
        return self.session_dir

    def _start_sampler(self) -> None:
        if isinstance(self._frames, NullFrameSource):
            return
        self._sample_stop.clear()

        def _loop() -> None:
            interval = 1.0 / max(self._sample_fps, 0.1)
            while not self._sample_stop.wait(interval):
                self._sampler.tick()

        self._sample_thread = threading.Thread(target=_loop, name="madu-ring-sampler", daemon=True)
        self._sample_thread.start()

    def _stop_sampler(self) -> None:
        self._sample_stop.set()
        if self._sample_thread is not None:
            self._sample_thread.join(timeout=2.0)
            self._sample_thread = None

    def run(self, *, duration_s: float | None = None) -> Path:
        """Block until Ctrl-C / duration, writing visits as they close."""
        self.prepare()
        log.info("recording session at %s (board %s)", self.session_dir, self._board.board_url)
        try:
            for state in self._board.poll_states(hz=self._poll_hz, stop_after_s=duration_s):
                self.handle_state(state.t_mono, state.t_recv, state.throws, state.status, state.event)
        except KeyboardInterrupt:
            log.info("recording stopped by user")
        finally:
            self._stop_sampler()
            if self._visit_open:
                # Force-close so partial visits still get a meta.json.
                self._writer.end_visit(time.monotonic())
                self._visit_open = False
            self._frames.stop()
        return self.session_dir

    def handle_state(
        self,
        t_mono: float,
        t_recv: float,
        throws: list[dict[str, Any]],
        status: str | None = None,
        event: str | None = None,
    ) -> None:
        """Process one Autodarts state observation (also used by tests)."""
        self._sampler.tick(t_mono)
        for item in self._segmenter.observe(t_mono, t_recv, throws):
            if isinstance(item, DartObserved):
                if not self._visit_open:
                    self._writer.begin_visit(t_mono, status=status, event=event)
                    self._visit_open = True
                self._writer.record_dart(
                    t_mono=item.t_mono,
                    t_recv=item.t_recv,
                    index=item.index,
                    throw=item.throw,
                    throws_so_far=item.throws_so_far,
                    frames=self._ring.snapshot(),
                    status=status,
                    event=event,
                )
            elif isinstance(item, VisitClosed):
                if self._visit_open:
                    self._writer.end_visit(item.t_mono)
                    self._visit_open = False
                    self._ring.clear()
