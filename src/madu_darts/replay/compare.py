"""Shadow-compare Madu Hits vs Autodarts throws for a Recording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from madu_darts.replay.coords import mm_error
from madu_darts.replay.pipeline import EchoAutodartsPipeline, HitHypothesis, Pipeline, load_visits, throw_xy_mm


@dataclass(frozen=True)
class DartComparison:
    visit_index: int
    dart_index: int
    autodarts_segment: str
    madu_segment: str
    autodarts_x_mm: float
    autodarts_y_mm: float
    madu_x_mm: float | None
    madu_y_mm: float | None
    error_mm: float | None
    agree: bool
    method: str | None = None

    @property
    def kind(self) -> str:
        """``single`` / ``double-treble`` / ``bull`` / ``miss`` by the Autodarts label."""
        name = self.autodarts_segment
        if name in ("25", "Bull"):
            return "bull"
        if name.startswith("M"):
            return "miss"
        if name[:1] in ("D", "T"):
            return "double-treble"
        return "single"


def replay(recording: Path | str, pipeline: Pipeline | None = None) -> list[DartComparison]:
    """Run ``pipeline`` over every visit in a recording; default echoes Autodarts."""
    root = Path(recording)
    pipe: Pipeline = pipeline or EchoAutodartsPipeline()
    rows: list[DartComparison] = []
    for visit_dir, meta in load_visits(root):
        hyps = pipe.detect_visit(visit_dir, meta)
        for i, throw in enumerate(meta.throws):
            ax, ay = throw_xy_mm(throw)
            hyp: HitHypothesis | None = hyps[i] if i < len(hyps) else None
            if hyp is not None and (hyp.x_mm != hyp.x_mm or hyp.y_mm != hyp.y_mm):  # NaN → no Hit
                hyp = None
            if hyp is None:
                rows.append(
                    DartComparison(
                        visit_index=meta.visit_index,
                        dart_index=i,
                        autodarts_segment=str(throw.get("segmentName", "")),
                        madu_segment="",
                        autodarts_x_mm=ax,
                        autodarts_y_mm=ay,
                        madu_x_mm=None,
                        madu_y_mm=None,
                        error_mm=None,
                        agree=False,
                    )
                )
                continue
            err = mm_error(ax, ay, hyp.x_mm, hyp.y_mm)
            rows.append(
                DartComparison(
                    visit_index=meta.visit_index,
                    dart_index=i,
                    autodarts_segment=str(throw.get("segmentName", "")),
                    madu_segment=hyp.segment_name,
                    autodarts_x_mm=ax,
                    autodarts_y_mm=ay,
                    madu_x_mm=hyp.x_mm,
                    madu_y_mm=hyp.y_mm,
                    error_mm=err,
                    agree=str(throw.get("segmentName", "")) == hyp.segment_name,
                    method=hyp.method,
                )
            )
    return rows


@dataclass(frozen=True)
class AccuracySummary:
    """Ticket 09 gate metrics for a replay run."""

    total: int
    agree: int
    median_error_mm: float | None
    by_kind: dict[str, tuple[int, int]]
    missing: int

    @property
    def agreement(self) -> float:
        return self.agree / self.total if self.total else 0.0

    def rate(self, kind: str) -> float | None:
        ok, n = self.by_kind.get(kind, (0, 0))
        return ok / n if n else None


def summarize(rows: list[DartComparison]) -> AccuracySummary:
    errors = sorted(r.error_mm for r in rows if r.error_mm is not None)
    median = None
    if errors:
        mid = len(errors) // 2
        median = errors[mid] if len(errors) % 2 else (errors[mid - 1] + errors[mid]) / 2.0
    by_kind: dict[str, tuple[int, int]] = {}
    for r in rows:
        ok, n = by_kind.get(r.kind, (0, 0))
        by_kind[r.kind] = (ok + int(r.agree), n + 1)
    return AccuracySummary(
        total=len(rows),
        agree=sum(1 for r in rows if r.agree),
        median_error_mm=median,
        by_kind=by_kind,
        missing=sum(1 for r in rows if r.madu_x_mm is None),
    )


def format_comparison_table(rows: list[DartComparison]) -> str:
    """Human-readable per-dart table + agreement %."""
    if not rows:
        return "(no darts)"
    header = (
        f"{'V':>2} {'#':>2}  {'AD':<6} {'Madu':<6}  "
        f"{'ADx':>8} {'ADy':>8}  {'Mx':>8} {'My':>8}  {'errmm':>7}  ok  method"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        mx = f"{r.madu_x_mm:8.2f}" if r.madu_x_mm is not None else f"{'—':>8}"
        my = f"{r.madu_y_mm:8.2f}" if r.madu_y_mm is not None else f"{'—':>8}"
        err = f"{r.error_mm:7.2f}" if r.error_mm is not None else f"{'—':>7}"
        lines.append(
            f"{r.visit_index:2d} {r.dart_index:2d}  {r.autodarts_segment:<6} {r.madu_segment:<6}  "
            f"{r.autodarts_x_mm:8.2f} {r.autodarts_y_mm:8.2f}  {mx} {my}  {err}  "
            f"{'Y' if r.agree else 'N'}   {r.method or ''}"
        )
    summary = summarize(rows)
    lines.append("-" * len(header))
    lines.append(f"agreement: {summary.agree}/{summary.total} ({100.0 * summary.agreement:.1f}%)")
    if summary.median_error_mm is not None:
        lines.append(f"median error: {summary.median_error_mm:.2f} mm")
    for kind, (ok, n) in sorted(summary.by_kind.items()):
        lines.append(f"  {kind}: {ok}/{n}")
    if summary.missing:
        lines.append(f"  no Hit: {summary.missing}")
    return "\n".join(lines)
