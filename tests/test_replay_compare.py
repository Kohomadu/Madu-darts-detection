"""Shadow-compare replay API (stub pipeline echoes Autodarts)."""

from __future__ import annotations

import json
from pathlib import Path

from madu_darts.board.geometry import DOUBLE_OUTER_MM, point_mm_to_segment
from madu_darts.record.meta import COORDS_NORM_RADIUS_MM
from madu_darts.replay import EchoAutodartsPipeline, autodarts_coords_to_mm, format_comparison_table, replay


def _write_fixture(root: Path) -> Path:
    session = root / "session-test"
    visit = session / "visit-00"
    visit.mkdir(parents=True)
    throws = [
        {
            "bed": "SingleOuter",
            "bouncer": False,
            "coordsX": 0.4027691926180652,
            "coordsY": 0.7505815104550483,
            "failed": False,
            "method": "UnanimousCam",
            "multiplier": 1,
            "segmentName": "S18",
            "segmentNumber": 18,
        },
        {
            "bed": "SingleInner",
            "bouncer": False,
            "coordsX": -0.04990356346450389,
            "coordsY": 0.44710749766518343,
            "failed": False,
            "method": "UnanimousCam",
            "multiplier": 1,
            "segmentName": "S20",
            "segmentNumber": 20,
        },
    ]
    (visit / "meta.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "visitIndex": 0,
                "throws": throws,
                "darts": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return session


def test_echo_pipeline_agrees_100_percent(tmp_path: Path) -> None:
    recording = _write_fixture(tmp_path)
    rows = replay(recording, EchoAutodartsPipeline())
    assert len(rows) == 2
    assert all(r.agree for r in rows)
    assert all(r.error_mm is not None and r.error_mm < 1e-9 for r in rows)
    table = format_comparison_table(rows)
    assert "S18" in table and "agreement: 2/2" in table


def test_autodarts_coords_norm_is_outer_double_radius() -> None:
    # Live 06 capture: S18 SingleOuter lands outside treble, inside double.
    assert COORDS_NORM_RADIUS_MM == DOUBLE_OUTER_MM == 170.0
    x_mm, y_mm = autodarts_coords_to_mm(0.4027691926180652, 0.7505815104550483)
    seg = point_mm_to_segment(x_mm, y_mm)
    assert seg.name == "S18"
    assert seg.bed == "SingleOuter"
