"""HTTP(+optional WS) client for Autodarts local ``/api/state`` (dev tool only)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoardState:
    """One observation of Autodarts local board state."""

    payload: dict[str, Any]
    t_mono: float
    t_recv: float
    """``time.time()`` when the response body was received."""

    @property
    def throws(self) -> list[dict[str, Any]]:
        raw = self.payload.get("throws")
        return list(raw) if isinstance(raw, list) else []

    @property
    def status(self) -> str | None:
        value = self.payload.get("status")
        return str(value) if value is not None else None

    @property
    def event(self) -> str | None:
        value = self.payload.get("event")
        return str(value) if value is not None else None


class BoardClient:
    """Poll ``GET /api/state``; optionally listen on ``ws://…/api/events``."""

    def __init__(self, board_url: str, *, timeout_s: float = 5.0) -> None:
        self.board_url = board_url.rstrip("/")
        self.timeout_s = timeout_s

    def get_json(self, path: str) -> Any:
        url = f"{self.board_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_state(self) -> BoardState:
        t_mono = time.monotonic()
        payload = self.get_json("/api/state")
        t_recv = time.time()
        if not isinstance(payload, dict):
            raise TypeError(f"/api/state expected object, got {type(payload)!r}")
        return BoardState(payload=payload, t_mono=t_mono, t_recv=t_recv)

    def fetch_calibration_ellipses(self) -> dict[str, Any]:
        data = self.get_json("/api/config/calibration/ellipses")
        return data if isinstance(data, dict) else {}

    def poll_states(self, *, hz: float = 5.0, stop_after_s: float | None = None) -> Iterator[BoardState]:
        """Yield state snapshots at ``hz`` (fallback when WS is unused)."""
        interval = 1.0 / max(hz, 0.1)
        deadline = None if stop_after_s is None else time.monotonic() + stop_after_s
        while deadline is None or time.monotonic() < deadline:
            started = time.monotonic()
            try:
                yield self.fetch_state()
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                log.warning("board state poll failed: %s", exc)
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def events_url(self) -> str:
        parsed = urlparse(self.board_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/events", "", "", ""))
