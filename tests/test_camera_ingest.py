"""CameraIngest orchestration with fake enumerator + capture factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from madu_darts.cameras import (
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    CameraConfig,
    CameraDevice,
    CameraIngest,
    CameraSlot,
    IngestConfig,
)
from madu_darts.cameras.capture import CaptureHandle


@dataclass
class FakeHandle:
    frame: Any
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: float = float(DEFAULT_FPS)
    opened: bool = True
    released: bool = False
    fail_read: bool = False

    def is_opened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, Any]:
        if self.fail_read:
            return False, None
        return True, self.frame

    def release(self) -> None:
        self.released = True
        self.opened = False


class FakeFactory:
    def __init__(self) -> None:
        self.opened: list[tuple[CameraDevice, CameraConfig]] = []
        self.handles: dict[int, FakeHandle] = {}

    def open(self, device: CameraDevice, config: CameraConfig) -> CaptureHandle:
        self.opened.append((device, config))
        handle = FakeHandle(frame=[[device.index]])
        self.handles[device.index] = handle
        return handle


class FakeEnum:
    def __init__(self, devices: list[CameraDevice]) -> None:
        self._devices = devices

    def list_devices(self) -> list[CameraDevice]:
        return list(self._devices)


def _three_devices() -> list[CameraDevice]:
    return [
        CameraDevice(index=10, name="cam0", location="7.2"),
        CameraDevice(index=11, name="cam1", location="7.3"),
        CameraDevice(index=12, name="cam2", location="7.4"),
    ]


def test_defaults_match_autodarts() -> None:
    assert DEFAULT_WIDTH == 1280
    assert DEFAULT_HEIGHT == 720
    assert DEFAULT_FPS == 30
    cfg = IngestConfig()
    assert [s.location for s in cfg.slots] == ["7.2", "7.3", "7.4"]


def test_open_read_close_by_usb_location() -> None:
    factory = FakeFactory()
    ingest = CameraIngest(
        IngestConfig(),
        enumerator=FakeEnum(_three_devices()),
        capture_factory=factory,
    )

    ingest.open()
    assert ingest.is_open
    assert [d.index for d, _ in factory.opened] == [10, 11, 12]
    assert all(cfg.width == 1280 for _, cfg in factory.opened)
    assert all(cfg.lock_exposure is False for _, cfg in factory.opened)
    assert all(cfg.lock_white_balance is False for _, cfg in factory.opened)

    frames = ingest.read()
    assert set(frames) == {0, 1, 2}
    assert frames[0].location == "7.2"
    assert frames[1].image == [[11]]

    stats = ingest.stats()
    assert [s.slot for s in stats] == [0, 1, 2]
    assert stats[0].width == DEFAULT_WIDTH

    ingest.close()
    assert not ingest.is_open
    assert all(h.released for h in factory.handles.values())


def test_context_manager() -> None:
    factory = FakeFactory()
    with CameraIngest(
        IngestConfig(),
        enumerator=FakeEnum(_three_devices()),
        capture_factory=factory,
    ) as ingest:
        assert ingest.is_open
    assert all(h.released for h in factory.handles.values())


def test_rotate_180_flips_ndarray_axes() -> None:
    import numpy as np

    devices = _three_devices()

    class RotatingFactory(FakeFactory):
        def open(self, device: CameraDevice, config: CameraConfig) -> CaptureHandle:
            self.opened.append((device, config))
            frame = np.array([[1, 2], [3, 4]], dtype=np.uint8)
            handle = FakeHandle(frame=frame)
            self.handles[device.index] = handle
            return handle

    rotating = RotatingFactory()
    slots = (
        CameraSlot(0, "7.2", rotate_180=True),
        CameraSlot(1, "7.3"),
        CameraSlot(2, "7.4"),
    )
    ingest = CameraIngest(
        IngestConfig(slots=slots),
        enumerator=FakeEnum(devices),
        capture_factory=rotating,
    )
    ingest.open()
    frames = ingest.read()
    np.testing.assert_array_equal(frames[0].image, [[4, 3], [2, 1]])
    np.testing.assert_array_equal(frames[1].image, [[1, 2], [3, 4]])
    ingest.close()


def test_open_fails_cleanly_when_location_missing() -> None:
    ingest = CameraIngest(
        IngestConfig(),
        enumerator=FakeEnum([CameraDevice(0, "only", "7.2")]),
        capture_factory=FakeFactory(),
    )
    with pytest.raises(LookupError):
        ingest.open()
    assert not ingest.is_open


def test_partial_open_failure_releases_already_opened() -> None:
    devices = _three_devices()

    class BoomFactory(FakeFactory):
        def open(self, device: CameraDevice, config: CameraConfig) -> CaptureHandle:
            if device.location == "7.3":
                raise RuntimeError("boom")
            return super().open(device, config)

    factory = BoomFactory()
    ingest = CameraIngest(
        IngestConfig(),
        enumerator=FakeEnum(devices),
        capture_factory=factory,
    )
    with pytest.raises(RuntimeError, match="boom"):
        ingest.open()
    assert not ingest.is_open
    assert factory.handles[10].released


def test_read_omits_failed_frames() -> None:
    factory = FakeFactory()
    ingest = CameraIngest(
        IngestConfig(),
        enumerator=FakeEnum(_three_devices()),
        capture_factory=factory,
    )
    ingest.open()
    factory.handles[11].fail_read = True
    frames = ingest.read()
    assert set(frames) == {0, 2}
    ingest.close()


def test_windows_style_index_overrides() -> None:
    devices = [
        CameraDevice(index=0, name="a", location=None),
        CameraDevice(index=1, name="b", location=None),
        CameraDevice(index=2, name="c", location=None),
    ]
    factory = FakeFactory()
    ingest = CameraIngest(
        IngestConfig(
            location_index_overrides={"7.2": 0, "7.3": 1, "7.4": 2},
        ),
        enumerator=FakeEnum(devices),
        capture_factory=factory,
    )
    ingest.open()
    assert [d.index for d, _ in factory.opened] == [0, 1, 2]
    ingest.close()
