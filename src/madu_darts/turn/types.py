"""Turn status / event vocabulary (Autodarts 2.1 strings + Madu extensions) and snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from madu_darts.hits import Hit


class TurnStatus(str, Enum):
    """Autodarts 2.1 ``status`` values (camelCase) — see research §2.2."""

    THROW = "throw"
    TAKEOUT = "takeout"
    TAKEOUT_IN_PROGRESS = "takeoutInProgress"


class TurnEvent(str, Enum):
    """Autodarts 2.1 ``event`` values plus Madu extensions (marked)."""

    STARTED = "started"
    STOPPED = "stopped"
    THROW_DETECTED = "throwDetected"
    TAKEOUT_STARTED = "takeoutStarted"
    TAKEOUT_FINISHED = "takeoutFinished"
    CALIBRATION_FINISHED = "calibrationFinished"
    # Madu extensions (no 2.1 counterpart observed).
    RESET = "reset"
    BOUNCE_OUT = "bounceOut"
    STANDBY = "standby"
    WAKEUP = "wakeup"
    RECHECK = "recheck"
    OVERRIDE = "override"


@dataclass(frozen=True)
class BounceOut:
    """A committed Hit retracted because its footprint vanished without a hand (Movement red)."""

    hit: Hit
    index: int
    slot: int
    t_mono: float

    def to_api(self) -> dict[str, Any]:
        return {"index": self.index, "slot": self.slot, "tMono": self.t_mono, "throw": self.hit.to_autodarts_throw()}


@dataclass(frozen=True)
class TurnTransition:
    """One status/event change — the replay table and the (11) stream key off these."""

    t_mono: float
    status: TurnStatus
    event: TurnEvent
    num_hits: int

    def to_api(self) -> dict[str, Any]:
        return {"tMono": self.t_mono, "status": self.status.value, "event": self.event.value, "numThrows": self.num_hits}


@dataclass(frozen=True)
class TurnSnapshot:
    running: bool
    status: TurnStatus
    event: TurnEvent
    hits: tuple[Hit, ...] = field(default_factory=tuple)
    standby: bool = False
    pending: bool = False
    bounce_outs: tuple[BounceOut, ...] = field(default_factory=tuple)
    ignored_changes: int = 0
    version: int = 0

    def to_autodarts_state(self) -> dict[str, Any]:
        """Autodarts 2.1 ``/api/state`` core (ADR 0004); ``calibration`` is merged by the app."""
        return {
            "connected": True,
            "running": self.running,
            "status": self.status.value,
            "event": self.event.value,
            "throws": [h.to_autodarts_throw() for h in self.hits],
        }

    def to_api(self) -> dict[str, Any]:
        out = self.to_autodarts_state()
        out.update(
            {
                "numThrows": len(self.hits),
                "standby": self.standby,
                "pending": self.pending,
                "hits": [h.to_api() for h in self.hits],
                "bounceOuts": [b.to_api() for b in self.bounce_outs],
                "ignoredChanges": self.ignored_changes,
                "version": self.version,
            }
        )
        return out


__all__ = ["BounceOut", "TurnEvent", "TurnSnapshot", "TurnStatus", "TurnTransition"]
