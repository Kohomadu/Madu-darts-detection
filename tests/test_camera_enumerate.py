"""Linux by-path enumeration (fake filesystem)."""

from __future__ import annotations

from pathlib import Path

from madu_darts.cameras.enumerate import (
    CompositeEnumerator,
    IndexProbeEnumerator,
    LinuxByPathEnumerator,
    devices_from_by_path_entries,
)


def test_linux_by_path_reads_usb_locations() -> None:
    entries = [
        (
            "platform-xhci-usb-0:7.2:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.2:1.0-video-index0",
            "/dev/video0",
        ),
        (
            "platform-xhci-usb-0:7.2:1.0-video-index1",  # metadata — skipped
            "/dev/v4l/by-path/platform-xhci-usb-0:7.2:1.0-video-index1",
            "/dev/video1",
        ),
        (
            "platform-xhci-usb-0:7.3:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.3:1.0-video-index0",
            "/dev/video2",
        ),
        (
            "platform-xhci-usb-0:7.4:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.4:1.0-video-index0",
            "/dev/video4",
        ),
    ]
    devices = devices_from_by_path_entries(entries)
    assert [(d.location, d.index) for d in devices] == [
        ("7.2", 0),
        ("7.3", 2),
        ("7.4", 4),
    ]


def test_linux_by_path_skips_uvc_metadata_iface_that_shares_port() -> None:
    """Real Boards: each cam has …:1.0 (capture) and …:1.1 (metadata), both index0.

    Without filtering, short location ``7.2`` matches 2 devices and open fails.
    """
    entries = [
        (
            "platform-xhci-usb-0:7.2:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.2:1.0-video-index0",
            "/dev/video0",
        ),
        (
            "platform-xhci-usb-0:7.2:1.1-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.2:1.1-video-index0",
            "/dev/video1",
        ),
        (
            "platform-xhci-usb-0:7.3:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.3:1.0-video-index0",
            "/dev/video2",
        ),
        (
            "platform-xhci-usb-0:7.3:1.1-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.3:1.1-video-index0",
            "/dev/video3",
        ),
        (
            "platform-xhci-usb-0:7.4:1.0-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.4:1.0-video-index0",
            "/dev/video4",
        ),
        (
            "platform-xhci-usb-0:7.4:1.1-video-index0",
            "/dev/v4l/by-path/platform-xhci-usb-0:7.4:1.1-video-index0",
            "/dev/video5",
        ),
    ]
    devices = devices_from_by_path_entries(entries)
    assert [(d.location, d.index) for d in devices] == [
        ("7.2", 0),
        ("7.3", 2),
        ("7.4", 4),
    ]


def test_linux_by_path_missing_dir_returns_empty(tmp_path: Path) -> None:
    devices = LinuxByPathEnumerator(tmp_path / "missing").list_devices()
    assert devices == []


def test_index_probe_keeps_open_indices_only() -> None:
    class FakeCap:
        def __init__(self, opened: bool) -> None:
            self._opened = opened
            self.released = False

        def isOpened(self) -> bool:
            return self._opened

        def release(self) -> None:
            self.released = True

    opened_at = {1, 3}

    def opener(index: int) -> FakeCap:
        return FakeCap(index in opened_at)

    devices = IndexProbeEnumerator(max_index=5, opener=opener).list_devices()
    assert [d.index for d in devices] == [1, 3]
    assert all(d.location is None for d in devices)


def test_composite_falls_back_when_preferred_empty() -> None:
    class Empty:
        def list_devices(self):
            return []

    class Fallback:
        def list_devices(self):
            from madu_darts.cameras.devices import CameraDevice

            return [CameraDevice(index=0, name="cam", location=None)]

    devices = CompositeEnumerator(Empty(), Fallback()).list_devices()
    assert len(devices) == 1
    assert devices[0].index == 0
