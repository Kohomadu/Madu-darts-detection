"""Segment Autodarts visit lifecycle from ``throws[]`` length changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VisitEvent:
    """Base marker for visit lifecycle observations."""

    t_mono: float
    t_recv: float
    """Wall/receive time when the state was observed (for skew notes)."""


@dataclass(frozen=True)
class DartObserved(VisitEvent):
    """``throws[]`` grew by one; ``throw`` is the newest entry."""

    index: int
    throw: dict[str, Any]
    throws_so_far: list[dict[str, Any]]


@dataclass(frozen=True)
class VisitClosed(VisitEvent):
    """``throws`` went empty after a non-empty visit (takeout finished)."""

    dart_count: int


class VisitSegmenter:
    """Track Autodarts ``throws[]`` deltas into dart / visit-closed events.

    Autodarts pushes the full visit-so-far on each detection. We only care about
    length increases (new stuck dart) and empty-after-nonempty (takeout done).
    """

    def __init__(self) -> None:
        self._prev_len = 0
        self._visit_darts = 0

    @property
    def throws_len(self) -> int:
        return self._prev_len

    def observe(
        self,
        t_mono: float,
        t_recv: float,
        throws: list[dict[str, Any]] | None,
    ) -> list[VisitEvent]:
        throws = list(throws or [])
        n = len(throws)
        events: list[VisitEvent] = []

        if n > self._prev_len:
            for index in range(self._prev_len, n):
                events.append(
                    DartObserved(
                        t_mono=float(t_mono),
                        t_recv=float(t_recv),
                        index=index,
                        throw=dict(throws[index]),
                        throws_so_far=[dict(t) for t in throws[: index + 1]],
                    )
                )
            self._visit_darts = n
        elif n == 0 and self._prev_len > 0:
            events.append(
                VisitClosed(
                    t_mono=float(t_mono),
                    t_recv=float(t_recv),
                    dart_count=self._visit_darts,
                )
            )
            self._visit_darts = 0

        self._prev_len = n
        return events
