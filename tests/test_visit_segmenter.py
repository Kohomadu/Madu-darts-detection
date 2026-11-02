"""Visit segmentation from Autodarts ``throws[]`` length deltas."""

from __future__ import annotations

from madu_darts.record.visit import DartObserved, VisitClosed, VisitEvent, VisitSegmenter


def _throw(name: str, x: float = 0.1, y: float = 0.2) -> dict:
    return {
        "bed": "SingleOuter",
        "bouncer": False,
        "coordsX": x,
        "coordsY": y,
        "failed": False,
        "method": "UnanimousCam",
        "multiplier": 1,
        "segmentName": name,
        "segmentNumber": int(name[1:]) if name[0] == "S" else 0,
    }


def test_length_increase_emits_dart_with_new_throw_only() -> None:
    seg = VisitSegmenter()
    events = seg.observe(t_mono=1.0, t_recv=1.01, throws=[_throw("S20")])
    assert len(events) == 1
    assert isinstance(events[0], DartObserved)
    assert events[0].index == 0
    assert events[0].throw["segmentName"] == "S20"
    assert events[0].throws_so_far == [_throw("S20")]
    assert events[0].t_mono == 1.0
    assert events[0].t_recv == 1.01


def test_second_dart_and_takeout_close_visit() -> None:
    seg = VisitSegmenter()
    assert seg.observe(1.0, 1.0, [_throw("S20")])[0].index == 0
    second = seg.observe(2.0, 2.0, [_throw("S20"), _throw("T19", x=0.3, y=0.4)])
    assert len(second) == 1
    assert second[0].index == 1
    assert second[0].throw["segmentName"] == "T19"

    closed = seg.observe(3.0, 3.0, [])
    assert len(closed) == 1
    assert isinstance(closed[0], VisitClosed)
    assert closed[0].dart_count == 2
    assert closed[0].t_mono == 3.0


def test_idle_empty_and_same_length_are_silent() -> None:
    seg = VisitSegmenter()
    assert seg.observe(0.0, 0.0, []) == []
    throws = [_throw("S1")]
    seg.observe(1.0, 1.0, throws)
    assert seg.observe(1.5, 1.5, throws) == []  # same length, no new dart


def test_visit_events_are_typed() -> None:
    assert issubclass(DartObserved, VisitEvent)
    assert issubclass(VisitClosed, VisitEvent)
