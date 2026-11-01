"""Settle-then-lock exposure / white-balance behaviour."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from madu_darts.cameras.capture import apply_image_controls
from madu_darts.cameras.config import CameraConfig


@dataclass
class FakeCv2:
    CAP_PROP_AUTO_EXPOSURE: int = 1
    CAP_PROP_EXPOSURE: int = 2
    CAP_PROP_AUTO_WB: int = 3
    CAP_PROP_WB_TEMPERATURE: int = 4


@dataclass
class FakeCap:
    props: dict[int, float] = field(default_factory=dict)
    sets: list[tuple[int, float]] = field(default_factory=list)
    reads: int = 0
    reject_set: set[int] = field(default_factory=set)

    def set(self, prop: int, value: float) -> bool:
        self.sets.append((prop, float(value)))
        if prop in self.reject_set:
            return False
        self.props[prop] = float(value)
        return True

    def get(self, prop: int) -> float:
        return float(self.props.get(prop, float("nan")))

    def read(self) -> tuple[bool, object]:
        self.reads += 1
        # Simulate auto-exposure converging while we warm up.
        if self.reads >= 5:
            self.props[FakeCv2.CAP_PROP_EXPOSURE] = -5.0
            self.props[FakeCv2.CAP_PROP_WB_TEMPERATURE] = 4500.0
        return True, object()


CV2 = FakeCv2()


def test_settle_then_lock_pins_auto_converged_values() -> None:
    cap = FakeCap(props={CV2.CAP_PROP_EXPOSURE: -12.0, CV2.CAP_PROP_WB_TEMPERATURE: 2800.0})
    apply_image_controls(cap, CV2, CameraConfig(settle_frames=8))

    assert cap.reads == 8
    # Auto enabled first, then manual + settled values written.
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 0.75) in cap.sets
    assert (CV2.CAP_PROP_AUTO_WB, 1.0) in cap.sets
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 0.25) in cap.sets
    assert (CV2.CAP_PROP_AUTO_WB, 0.0) in cap.sets
    assert (CV2.CAP_PROP_EXPOSURE, -5.0) in cap.sets
    assert (CV2.CAP_PROP_WB_TEMPERATURE, 4500.0) in cap.sets
    assert cap.props[CV2.CAP_PROP_EXPOSURE] == -5.0
    assert cap.props[CV2.CAP_PROP_WB_TEMPERATURE] == 4500.0


def test_absolute_overrides_win_over_settled_values() -> None:
    cap = FakeCap()
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(settle_frames=3, exposure=-4.0, white_balance_temperature=5600.0),
    )
    assert (CV2.CAP_PROP_EXPOSURE, -4.0) in cap.sets
    assert (CV2.CAP_PROP_WB_TEMPERATURE, 5600.0) in cap.sets


def test_no_lock_skips_settle_and_writes() -> None:
    cap = FakeCap()
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(lock_exposure=False, lock_white_balance=False, settle_frames=20),
    )
    assert cap.reads == 0
    assert cap.sets == []


def test_lock_exposure_only_still_settles() -> None:
    cap = FakeCap()
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(lock_exposure=True, lock_white_balance=False, settle_frames=5),
    )
    assert cap.reads == 5
    assert any(p == CV2.CAP_PROP_AUTO_EXPOSURE for p, _ in cap.sets)
    assert not any(p == CV2.CAP_PROP_AUTO_WB for p, _ in cap.sets)
    assert (CV2.CAP_PROP_EXPOSURE, -5.0) in cap.sets


def test_auto_exposure_falls_back_when_first_value_rejected() -> None:
    cap = FakeCap(reject_set={})
    # Reject 0.75, accept 3.0 for auto-on.
    original_set = cap.set

    def selective_set(prop: int, value: float) -> bool:
        if prop == CV2.CAP_PROP_AUTO_EXPOSURE and value == 0.75:
            cap.sets.append((prop, float(value)))
            return False
        return original_set(prop, value)

    cap.set = selective_set  # type: ignore[method-assign]
    apply_image_controls(cap, CV2, CameraConfig(settle_frames=2, lock_white_balance=False))
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 3.0) in cap.sets


def test_missing_settled_value_still_disables_auto() -> None:
    cap = FakeCap()
    # Never converges — get stays NaN; we still switch to manual.
    cap.read = lambda: (True, object())  # type: ignore[method-assign]
    apply_image_controls(cap, CV2, CameraConfig(settle_frames=2, lock_white_balance=False))
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 0.25) in cap.sets
    assert not any(p == CV2.CAP_PROP_EXPOSURE for p, _ in cap.sets)
