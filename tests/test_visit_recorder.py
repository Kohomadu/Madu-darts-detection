"""VisitRecorder wires throws deltas → on-disk visit trees."""

from __future__ import annotations

from pathlib import Path

from madu_darts.record.board_client import BoardClient
from madu_darts.record.frames import NullFrameSource
from madu_darts.record.recorder import VisitRecorder


def _throw(name: str, x: float = 0.1, y: float = 0.5) -> dict:
    return {
        "bed": "SingleOuter",
        "bouncer": False,
        "coordsX": x,
        "coordsY": y,
        "failed": False,
        "method": "UnanimousCam",
        "multiplier": 1,
        "segmentName": name,
        "segmentNumber": 20,
    }


def test_recorder_writes_visit_on_takeout(tmp_path: Path) -> None:
    board = BoardClient("http://example.invalid:3180")
    rec = VisitRecorder(
        board,
        tmp_path,
        frames=NullFrameSource(),
        calibration={"source": "test", "ellipses": {}},
    )
    rec.prepare()

    rec.handle_state(1.0, 1.0, [_throw("S20")], status="throw", event="throwDetected")
    rec.handle_state(
        2.0,
        2.0,
        [_throw("S20"), _throw("T19", x=0.2, y=0.3)],
        status="throw",
        event="throwDetected",
    )
    rec.handle_state(3.0, 3.0, [], status="throw", event="takeoutFinished")

    visit = rec.session_dir / "visit-00"
    assert (visit / "meta.json").is_file()
    assert (rec.session_dir / "calibration.json").is_file()
    assert (rec.session_dir / "session.json").is_file()
    text = (visit / "meta.json").read_text(encoding="utf-8")
    assert "S20" in text and "T19" in text
