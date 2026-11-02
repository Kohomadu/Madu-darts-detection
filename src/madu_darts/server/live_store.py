"""In-process visit history + on-disk cam captures for live testing.

``throws[]`` clears on takeout; this store keeps finalized visits and frozen
frame packs so a remote agent can compare Segments and tips after the fact.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from madu_darts.hits import Hit
from madu_darts.turn import TurnEvent, TurnTransition

log = logging.getLogger(__name__)

DEFAULT_CAPTURE_ROOT = Path("captures") / "live"


def _encode_jpeg(image: np.ndarray, quality: int) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


@dataclass
class OpenVisit:
    """Hits / events for the Turn currently in progress (survives the clear on takeout)."""

    t_mono_open: float | None = None
    t_wall_open: float | None = None
    hits: list[Hit] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    capture_id: str | None = None

    @property
    def has_hits(self) -> bool:
        return bool(self.hits)


class LiveStore:
    """Ring buffers for visit history and capture packs under ``captures/live/``."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        max_visits: int = 50,
        max_captures: int = 30,
        jpeg_quality: int = 80,
    ) -> None:
        self.root = Path(root) if root is not None else DEFAULT_CAPTURE_ROOT
        self.max_visits = max(1, int(max_visits))
        self.max_captures = max(1, int(max_captures))
        self.jpeg_quality = int(jpeg_quality)
        self._lock = threading.RLock()
        self._visits: deque[dict[str, Any]] = deque(maxlen=self.max_visits)
        self._open = OpenVisit()
        self._visit_index = 0
        self._last_visit_id: str | None = None

    # --- open visit tracking ---

    def note_transition(self, tr: TurnTransition, hits: tuple[Hit, ...] | list[Hit]) -> None:
        """Record a Turn transition; keep a snapshot of Hits while they are still present."""
        with self._lock:
            if self._open.t_mono_open is None and tr.event in (
                TurnEvent.STARTED,
                TurnEvent.THROW_DETECTED,
                TurnEvent.WAKEUP,
            ):
                self._open.t_mono_open = float(tr.t_mono)
                self._open.t_wall_open = time.time()
            self._open.events.append(
                {
                    "tMono": float(tr.t_mono),
                    "status": tr.status.value,
                    "event": tr.event.value,
                    "numThrows": int(tr.num_hits),
                }
            )
            # Snapshot Hits whenever the strip content may have changed and is still on the controller.
            if tr.event in (TurnEvent.THROW_DETECTED, TurnEvent.BOUNCE_OUT) or (
                tr.event == TurnEvent.TAKEOUT_STARTED and hits
            ):
                self._open.hits = list(hits)

    def attach_capture(self, capture_id: str) -> None:
        with self._lock:
            self._open.capture_id = capture_id

    def open_capture_id(self) -> str | None:
        with self._lock:
            return self._open.capture_id

    def finalize(self, *, t_mono: float, reason: str) -> dict[str, Any] | None:
        """Seal the open visit into the history ring if it had Hits; returns the record or None."""
        with self._lock:
            if not self._open.has_hits:
                self._open = OpenVisit()
                return None
            self._visit_index += 1
            visit_id = f"v{self._visit_index:04d}-{uuid.uuid4().hex[:8]}"
            hits = list(self._open.hits)
            record = {
                "id": visit_id,
                "index": self._visit_index,
                "reason": reason,
                "tWall": self._open.t_wall_open or time.time(),
                "tWallClose": time.time(),
                "tMonoOpen": self._open.t_mono_open,
                "tMonoClose": float(t_mono),
                "throws": [h.to_autodarts_throw() for h in hits],
                "hits": [h.to_api() for h in hits],
                "events": list(self._open.events),
                "captureId": self._open.capture_id,
                "segmentNames": [h.autodarts_segment_name for h in hits],
            }
            self._visits.append(record)
            self._last_visit_id = visit_id
            self._open = OpenVisit()
            log.info(
                "history: visit %s (%s) → %s",
                visit_id,
                reason,
                " ".join(record["segmentNames"]),
            )
            return record

    def clear_history(self) -> None:
        with self._lock:
            self._visits.clear()
            self._last_visit_id = None
            # Do not wipe an open Turn mid-visit — only sealed history.

    def history(self) -> dict[str, Any]:
        with self._lock:
            current = None
            if self._open.has_hits:
                current = {
                    "throws": [h.to_autodarts_throw() for h in self._open.hits],
                    "hits": [h.to_api() for h in self._open.hits],
                    "events": list(self._open.events),
                    "captureId": self._open.capture_id,
                    "segmentNames": [h.autodarts_segment_name for h in self._open.hits],
                    "tMonoOpen": self._open.t_mono_open,
                    "tWall": self._open.t_wall_open,
                }
            return {
                "visits": list(self._visits),
                "current": current,
                "count": len(self._visits),
                "lastVisitId": self._last_visit_id,
            }

    def visit(self, visit_id: str) -> dict[str, Any] | None:
        with self._lock:
            for v in self._visits:
                if v["id"] == visit_id:
                    return dict(v)
            return None

    @property
    def history_count(self) -> int:
        with self._lock:
            return len(self._visits)

    @property
    def last_visit_id(self) -> str | None:
        with self._lock:
            return self._last_visit_id

    # --- captures ---

    def capture(
        self,
        frames: dict[int, np.ndarray],
        state: dict[str, Any],
        *,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """Freeze frames + state under ``captures/live/{id}/``; prune old packs."""
        capture_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        dest = self.root / capture_id
        dest.mkdir(parents=True, exist_ok=True)
        frame_paths: dict[str, str] = {}
        for slot, image in sorted(frames.items()):
            name = f"{int(slot)}.jpg"
            (dest / name).write_bytes(_encode_jpeg(image, self.jpeg_quality))
            frame_paths[str(int(slot))] = f"/api/captures/{capture_id}/{int(slot)}.jpg"
        meta = {
            "id": capture_id,
            "reason": reason,
            "tWall": time.time(),
            "slots": sorted(int(s) for s in frames),
            "state": state,
            "frames": frame_paths,
        }
        (dest / "state.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        self._prune_captures()
        log.info("capture %s (%s) slots=%s", capture_id, reason, meta["slots"])
        return {
            "id": capture_id,
            "reason": reason,
            "tWall": meta["tWall"],
            "state": state,
            "frames": frame_paths,
            "stateUrl": f"/api/captures/{capture_id}/state.json",
        }

    def list_captures(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            state_path = path / "state.json"
            entry: dict[str, Any] = {"id": path.name, "dir": str(path)}
            if state_path.is_file():
                try:
                    data = json.loads(state_path.read_text(encoding="utf-8"))
                    entry["tWall"] = data.get("tWall")
                    entry["reason"] = data.get("reason")
                    entry["slots"] = data.get("slots", [])
                    throws = (data.get("state") or {}).get("throws") or []
                    entry["segmentNames"] = [t.get("segmentName") for t in throws]
                except (OSError, json.JSONDecodeError):
                    pass
            out.append(entry)
        return out

    def capture_dir(self, capture_id: str) -> Path | None:
        path = self.root / capture_id
        return path if path.is_dir() else None

    def read_capture_jpeg(self, capture_id: str, slot: int) -> bytes | None:
        path = self.root / capture_id / f"{int(slot)}.jpg"
        return path.read_bytes() if path.is_file() else None

    def read_capture_state(self, capture_id: str) -> dict[str, Any] | None:
        path = self.root / capture_id / "state.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _prune_captures(self) -> None:
        if not self.root.is_dir():
            return
        dirs = sorted((p for p in self.root.iterdir() if p.is_dir()), key=lambda p: p.name)
        while len(dirs) > self.max_captures:
            old = dirs.pop(0)
            shutil.rmtree(old, ignore_errors=True)


__all__ = ["DEFAULT_CAPTURE_ROOT", "LiveStore", "OpenVisit"]
