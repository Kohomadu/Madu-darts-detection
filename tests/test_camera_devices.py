"""USB location parsing and device matching."""

from __future__ import annotations

import pytest

from madu_darts.cameras.devices import (
    CameraDevice,
    match_devices_by_location,
    normalize_location,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7.2", "7.2"),
        ("7.3", "7.3"),
        (
            "platform-xhci-hcd.0.auto-usb-0:7.2:1.0-video-index0",
            "7.2",
        ),
        (
            "vid=0bda&pid=5844&serial=ABC&location=pci-0000:00:14.0-usb-0:7.4:1.0",
            "7.4",
        ),
        ("usb-0:7.3:1.0", "7.3"),
        ("", None),
    ],
)
def test_normalize_location(raw: str, expected: str | None) -> None:
    assert normalize_location(raw) == expected


def test_match_by_unique_locations() -> None:
    devices = [
        CameraDevice(index=0, name="a", location="7.2"),
        CameraDevice(index=1, name="b", location="7.3"),
        CameraDevice(index=2, name="c", location="7.4"),
    ]
    matched = match_devices_by_location(devices, ["7.2", "7.3", "7.4"])
    assert matched["7.2"].index == 0
    assert matched["7.3"].index == 1
    assert matched["7.4"].index == 2


def test_match_prefers_index_override_when_location_missing() -> None:
    devices = [
        CameraDevice(index=0, name="a", location=None),
        CameraDevice(index=1, name="b", location=None),
        CameraDevice(index=2, name="c", location=None),
    ]
    matched = match_devices_by_location(
        devices,
        ["7.2", "7.3", "7.4"],
        index_overrides={"7.2": 0, "7.3": 1, "7.4": 2},
    )
    assert matched["7.2"].index == 0
    assert matched["7.4"].index == 2


def test_match_raises_when_location_missing() -> None:
    devices = [CameraDevice(index=0, name="a", location="7.2")]
    with pytest.raises(LookupError, match="7.3"):
        match_devices_by_location(devices, ["7.2", "7.3"])


def test_match_raises_on_duplicate_location() -> None:
    devices = [
        CameraDevice(index=0, name="a", location="7.2"),
        CameraDevice(index=1, name="b", location="7.2"),
    ]
    with pytest.raises(LookupError, match="unique"):
        match_devices_by_location(devices, ["7.2"])
