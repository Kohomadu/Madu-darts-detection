"""Settle-then-lock exposure / white-balance behaviour."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

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
    frame_mean: float = 80.0
    reject_auto_on_first: bool = False

    def set(self, prop: int, value: float) -> bool:
        value = float(value)
        self.sets.append((prop, value))
        if (
            self.reject_auto_on_first
            and prop == FakeCv2.CAP_PROP_AUTO_EXPOSURE
            and value == 3.0
            and not any(p == prop and v == 3.0 for p, v in self.sets[:-1])
        ):
            # First native-auto attempt fails; OpenCV float fallback should win.
            return False
        self.props[prop] = value
        return True

    def get(self, prop: int) -> float:
        return float(self.props.get(prop, float("nan")))

    def read(self) -> tuple[bool, object]:
        self.reads += 1
        if self.reads >= 5:
            self.props[FakeCv2.CAP_PROP_EXPOSURE] = -5.0
            self.props[FakeCv2.CAP_PROP_WB_TEMPERATURE] = 4500.0
        return True, np.full((8, 8, 3), self.frame_mean, dtype=np.uint8)


CV2 = FakeCv2()


def test_default_config_does_not_lock() -> None:
    cfg = CameraConfig()
    assert cfg.lock_exposure is False
    assert cfg.lock_white_balance is False


def test_unlocked_still_enables_auto_and_warms_up() -> None:
    cap = FakeCap()
    apply_image_controls(cap, CV2, CameraConfig())
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 3.0) in cap.sets
    assert (CV2.CAP_PROP_AUTO_WB, 1.0) in cap.sets
    assert cap.reads == 8
    assert not any(p == CV2.CAP_PROP_AUTO_EXPOSURE and v == 1.0 for p, v in cap.sets)


def test_settle_then_lock_pins_auto_converged_values_when_bright() -> None:
    cap = FakeCap(frame_mean=80.0)
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(lock_exposure=True, lock_white_balance=True, settle_frames=8),
    )
    assert cap.reads >= 8
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 3.0) in cap.sets
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 1.0) in cap.sets
    assert (CV2.CAP_PROP_EXPOSURE, -5.0) in cap.sets
    assert (CV2.CAP_PROP_WB_TEMPERATURE, 4500.0) in cap.sets


def test_dark_post_lock_re_enables_auto() -> None:
    cap = FakeCap(frame_mean=5.0)
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(lock_exposure=True, lock_white_balance=True, settle_frames=5, min_lock_mean=25.0),
    )
    # Final action should put auto back on after the dark check.
    auto_on_indexes = [i for i, (p, v) in enumerate(cap.sets) if p == CV2.CAP_PROP_AUTO_EXPOSURE and v == 3.0]
    auto_off_indexes = [i for i, (p, v) in enumerate(cap.sets) if p == CV2.CAP_PROP_AUTO_EXPOSURE and v == 1.0]
    assert auto_off_indexes and auto_on_indexes
    assert max(auto_on_indexes) > max(auto_off_indexes)


def test_absolute_overrides_win_over_settled_values() -> None:
    cap = FakeCap(frame_mean=90.0)
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(
            lock_exposure=True,
            lock_white_balance=True,
            settle_frames=3,
            exposure=-4.0,
            white_balance_temperature=5600.0,
        ),
    )
    assert (CV2.CAP_PROP_EXPOSURE, -4.0) in cap.sets
    assert (CV2.CAP_PROP_WB_TEMPERATURE, 5600.0) in cap.sets


def test_auto_exposure_falls_back_when_native_value_rejected() -> None:
    cap = FakeCap(reject_auto_on_first=True, frame_mean=90.0)
    apply_image_controls(
        cap,
        CV2,
        CameraConfig(lock_exposure=True, lock_white_balance=False, settle_frames=2),
    )
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 0.75) in cap.sets
