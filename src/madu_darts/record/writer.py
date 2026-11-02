"""Persist a recording session: calibration once, then visit-NN trees."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from madu_darts.record.meta import (
    RecordingMeta,
    VisitMeta,
    save_recording_meta,
    save_visit_meta,
)
from madu_darts.record.ring_buffer import BufferedFrame

JPEG_QUALITY = 90


def new_session_id(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H-%M-%SZ")


@dataclass
class SessionWriter:
    """Layout: ``<out>/<session>/{session.json,calibration.json,visit-NN/...}``."""

    root: Path
    board_url: str
    session_id: str | None = None
    jpeg_quality: int = JPEG_QUALITY
    _visit_index: int = field(default=0, init=False)
    _open_visit: _OpenVisit | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        if self.session_id is None:
            self.session_id = new_session_id()
        self.session_dir = self.root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        meta = RecordingMeta(
            session_id=self.session_id,
            board_url=self.board_url,
            created_t_wall=time.time(),
        )
        save_recording_meta(self.session_dir / "session.json", meta)

    def write_calibration(self, payload: dict[str, Any]) -> Path:
        path = self.session_dir / "calibration.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def begin_visit(self, t_mono: float, *, status: str | None = None, event: str | None = None) -> Path:
        if self._open_visit is not None:
            raise RuntimeError("visit already open; call end_visit() first")
        visit_dir = self.session_dir / f"visit-{self._visit_index:02d}"
        for slot in (0, 1, 2):
            (visit_dir / f"cam{slot}").mkdir(parents=True, exist_ok=True)
        self._open_visit = _OpenVisit(
            index=self._visit_index,
            path=visit_dir,
            opened_t_mono=t_mono,
            status=status,
            event=event,
        )
        self._visit_index += 1
        return visit_dir

    def record_dart(
        self,
        *,
        t_mono: float,
        t_recv: float,
        index: int,
        throw: dict[str, Any],
        throws_so_far: list[dict[str, Any]],
        frames: Mapping[int, list[BufferedFrame]],
        status: str | None = None,
        event: str | None = None,
    ) -> None:
        visit = self._require_open()
        if status is not None:
            visit.status = status
        if event is not None:
            visit.event = event
        visit.throws = [dict(t) for t in throws_so_far]
        frame_refs: dict[str, list[str]] = {}
        for slot, buffered in frames.items():
            rels: list[str] = []
            cam_dir = visit.path / f"cam{slot}"
            cam_dir.mkdir(parents=True, exist_ok=True)
            for i, bf in enumerate(buffered):
                name = f"d{index:02d}_{i:03d}_t{bf.t_mono:.3f}.jpg"
                _write_jpeg(cam_dir / name, bf.image, self.jpeg_quality)
                rels.append(f"cam{slot}/{name}")
            frame_refs[str(slot)] = rels
        visit.darts.append(
            {
                "index": index,
                "t_mono": t_mono,
                "t_recv": t_recv,
                "throw": dict(throw),
                "frames": frame_refs,
            }
        )

    def end_visit(self, t_mono: float) -> Path:
        visit = self._require_open()
        meta = VisitMeta(
            visit_index=visit.index,
            throws=visit.throws,
            darts=visit.darts,
            opened_t_mono=visit.opened_t_mono,
            closed_t_mono=t_mono,
            autodarts_status=visit.status,
            autodarts_event=visit.event,
        )
        path = visit.path / "meta.json"
        save_visit_meta(path, meta)
        self._open_visit = None
        return visit.path

    def _require_open(self) -> _OpenVisit:
        if self._open_visit is None:
            raise RuntimeError("no open visit; call begin_visit() first")
        return self._open_visit


@dataclass
class _OpenVisit:
    index: int
    path: Path
    opened_t_mono: float
    throws: list[dict[str, Any]] = field(default_factory=list)
    darts: list[dict[str, Any]] = field(default_factory=list)
    status: str | None = None
    event: str | None = None


def _write_jpeg(path: Path, image: Any, quality: int) -> None:
    import cv2
    import numpy as np

    arr = np.asarray(image)
    ok = cv2.imwrite(str(path), arr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError(f"failed to write JPEG {path}")
