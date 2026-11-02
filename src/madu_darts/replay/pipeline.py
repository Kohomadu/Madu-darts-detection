"""Detection pipeline seam used by replay (``EchoAutodartsPipeline`` stub + ``MaduPipeline``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from madu_darts.record.meta import VisitMeta, load_visit_meta
from madu_darts.replay.coords import autodarts_coords_to_mm


@dataclass(frozen=True)
class HitHypothesis:
    """One Madu Hit guess for a recorded dart (Segment + Board-plane mm)."""

    segment_name: str
    x_mm: float
    y_mm: float
    number: int | None = None
    multiplier: int | None = None
    bed: str | None = None
    method: str | None = None


class Pipeline(Protocol):
    def detect_visit(self, visit_dir: Path, meta: VisitMeta) -> list[HitHypothesis]:
        """Return one hypothesis per dart in visit order (may be shorter on misses)."""


class EchoAutodartsPipeline:
    """Stub: echo Autodarts labels so the compare table / harness can ship first."""

    def detect_visit(self, visit_dir: Path, meta: VisitMeta) -> list[HitHypothesis]:
        _ = visit_dir
        out: list[HitHypothesis] = []
        for throw in meta.throws:
            x_mm, y_mm = autodarts_coords_to_mm(float(throw["coordsX"]), float(throw["coordsY"]))
            out.append(
                HitHypothesis(
                    segment_name=str(throw.get("segmentName", "")),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    number=throw.get("segmentNumber"),
                    multiplier=throw.get("multiplier"),
                    bed=throw.get("bed"),
                )
            )
        return out


def load_visits(recording: Path) -> list[tuple[Path, VisitMeta]]:
    root = Path(recording)
    visits: list[tuple[Path, VisitMeta]] = []
    for path in sorted(root.glob("visit-*")):
        if not path.is_dir():
            continue
        meta_path = path / "meta.json"
        if not meta_path.is_file():
            continue
        visits.append((path, load_visit_meta(meta_path)))
    return visits


def throw_xy_mm(throw: dict[str, Any]) -> tuple[float, float]:
    return autodarts_coords_to_mm(float(throw["coordsX"]), float(throw["coordsY"]))
