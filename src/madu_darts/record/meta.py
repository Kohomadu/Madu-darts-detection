"""Recording session / visit ``meta.json`` schema."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from madu_darts.board.geometry import DOUBLE_OUTER_OUTSIDE_MM

# Autodarts ``coordsX/Y`` ÷ WDF outside edge of the outer double (170 mm), not the scoring face.
COORDS_NORM_RADIUS_MM = float(DOUBLE_OUTER_OUTSIDE_MM)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RecordingMeta:
    """Once-per-session sidecar (calibration ref + Autodarts coords convention)."""

    session_id: str
    board_url: str
    calibration_ref: str = "calibration.json"
    coords_norm_radius_mm: float = COORDS_NORM_RADIUS_MM
    created_t_wall: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sessionId": self.session_id,
            "boardUrl": self.board_url,
            "calibrationRef": self.calibration_ref,
            "coordsNormRadiusMm": self.coords_norm_radius_mm,
            "createdTWall": self.created_t_wall,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingMeta:
        return cls(
            session_id=str(data["sessionId"]),
            board_url=str(data["boardUrl"]),
            calibration_ref=str(data.get("calibrationRef", "calibration.json")),
            coords_norm_radius_mm=float(data.get("coordsNormRadiusMm", COORDS_NORM_RADIUS_MM)),
            created_t_wall=data.get("createdTWall"),
            notes=str(data.get("notes", "")),
        )


@dataclass
class VisitMeta:
    """Per-visit labels + frame index for offline replay."""

    visit_index: int
    throws: list[dict[str, Any]]
    darts: list[dict[str, Any]] = field(default_factory=list)
    opened_t_mono: float | None = None
    closed_t_mono: float | None = None
    autodarts_status: str | None = None
    autodarts_event: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "visitIndex": self.visit_index,
            "openedTMono": self.opened_t_mono,
            "closedTMono": self.closed_t_mono,
            "autodartsStatus": self.autodarts_status,
            "autodartsEvent": self.autodarts_event,
            "throws": self.throws,
            "darts": self.darts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisitMeta:
        if "throws" not in data:
            raise ValueError("visit meta missing required key 'throws'")
        return cls(
            visit_index=int(data.get("visitIndex", 0)),
            throws=list(data["throws"]),
            darts=list(data.get("darts", [])),
            opened_t_mono=data.get("openedTMono"),
            closed_t_mono=data.get("closedTMono"),
            autodarts_status=data.get("autodartsStatus"),
            autodarts_event=data.get("autodartsEvent"),
        )


def save_visit_meta(path: Path, meta: VisitMeta) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_visit_meta(path: Path) -> VisitMeta:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("visit meta must be a JSON object")
    return VisitMeta.from_dict(data)


def save_recording_meta(path: Path, meta: RecordingMeta) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_recording_meta(path: Path) -> RecordingMeta:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("recording meta must be a JSON object")
    return RecordingMeta.from_dict(data)
