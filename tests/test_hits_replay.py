"""Ticket 09 accuracy floor on the preferred 07 recording (skipped without JPEGs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from madu_darts.replay import MaduPipeline, replay, summarize

RECORDING = (
    Path(__file__).resolve().parents[1]
    / ".scratch"
    / "detection-tool"
    / "captures"
    / "recordings"
    / "2026-11-02T08-07-55Z"
)


def _has_pixels(recording: Path) -> bool:
    return recording.is_dir() and any(recording.glob("visit-*/cam0/*.jpg"))


@pytest.mark.skipif(not _has_pixels(RECORDING), reason="07 recording JPEGs not present locally")
def test_madu_pipeline_accuracy_floor_on_recording() -> None:
    pipeline = MaduPipeline()
    rows = replay(RECORDING, pipeline)
    summary = summarize(rows)

    assert summary.total == 24
    assert summary.missing == 0, "every Autodarts dart must yield a Hit"
    # Measured 2026-11-02: 20/24 agree, median 3.8 mm; doubles/trebles 3/3; bulls 2/2.
    assert summary.agree >= 20
    assert summary.median_error_mm is not None and summary.median_error_mm <= 4.0
    assert summary.rate("double-treble") is not None and summary.rate("double-treble") >= 0.8
    assert summary.rate("bull") == 1.0
    # Every disagreement is a near-wire / occlusion case: fused point still lands close.
    assert max(r.error_mm for r in rows if r.error_mm is not None) <= 15.0

    bind = pipeline.bind(RECORDING)
    assert set(bind.cals) == {0, 1, 2}
    assert bind.offsets == {0: 10, 1: 4, 2: 16}
