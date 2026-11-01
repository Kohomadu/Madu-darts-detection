"""Enumerate USB cameras; prefer Linux V4L by-path (USB location)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Protocol

from madu_darts.cameras.devices import CameraDevice, normalize_location

_BY_PATH_VIDEO = re.compile(r"-video-index(\d+)$")


class DeviceEnumerator(Protocol):
    def list_devices(self) -> list[CameraDevice]:
        """Return capture devices; location filled when known."""


class LinuxByPathEnumerator:
    """Read ``/dev/v4l/by-path`` symlinks for stable USB port identity."""

    def __init__(self, by_path_dir: str | Path = "/dev/v4l/by-path") -> None:
        self._by_path_dir = Path(by_path_dir)

    def list_devices(self) -> list[CameraDevice]:
        if not self._by_path_dir.is_dir():
            return []

        entries: list[tuple[str, str, str]] = []
        for entry in sorted(self._by_path_dir.iterdir()):
            try:
                target = os.path.realpath(entry)
            except OSError:
                target = str(entry)
            entries.append((entry.name, str(entry), target))
        return devices_from_by_path_entries(entries)


def devices_from_by_path_entries(
    entries: list[tuple[str, str, str]],
) -> list[CameraDevice]:
    """Build devices from ``(name, path, realpath_target)`` by-path rows.

    Pure helper so USB location parsing can be tested without creating
    Linux-style filenames (colons) on Windows.
    """
    devices: list[CameraDevice] = []
    for name, path, target in entries:
        match = _BY_PATH_VIDEO.search(name)
        if match is None:
            continue
        # UVC exposes capture at video-index0; index1+ are often metadata.
        path_index = int(match.group(1))
        if path_index != 0:
            continue
        devices.append(
            CameraDevice(
                index=_video_index_from_target(target, fallback=path_index),
                name=name,
                location=normalize_location(name),
                path=path,
            )
        )
    return devices


def _video_index_from_target(target: str, *, fallback: int) -> int:
    """Map ``/dev/videoN`` → N; keep by-path index as fallback."""
    base = Path(target).name
    if base.startswith("video") and base[5:].isdigit():
        return int(base[5:])
    return fallback


class IndexProbeEnumerator:
    """Probe OpenCV indices when by-path is unavailable (e.g. Windows).

    Location stays ``None`` unless the caller supplies overrides at match time.
    """

    def __init__(
        self,
        *,
        max_index: int = 8,
        opener: Callable[[int], object] | None = None,
    ) -> None:
        self._max_index = max_index
        self._opener = opener or _default_opencv_opener

    def list_devices(self) -> list[CameraDevice]:
        devices: list[CameraDevice] = []
        for index in range(self._max_index):
            cap = self._opener(index)
            try:
                opened = bool(getattr(cap, "isOpened")())
            except Exception:
                opened = False
            if not opened:
                _safe_release(cap)
                continue
            devices.append(
                CameraDevice(
                    index=index,
                    name=f"camera-{index}",
                    location=None,
                    path=None,
                )
            )
            _safe_release(cap)
        return devices


class CompositeEnumerator:
    """Prefer by-path devices; fall back to index probe if empty."""

    def __init__(
        self,
        preferred: DeviceEnumerator,
        fallback: DeviceEnumerator,
    ) -> None:
        self._preferred = preferred
        self._fallback = fallback

    def list_devices(self) -> list[CameraDevice]:
        devices = self._preferred.list_devices()
        if devices:
            return devices
        return self._fallback.list_devices()


def default_enumerator() -> DeviceEnumerator:
    return CompositeEnumerator(LinuxByPathEnumerator(), IndexProbeEnumerator())


def _default_opencv_opener(index: int) -> object:
    import cv2

    return cv2.VideoCapture(index)


def _safe_release(cap: object) -> None:
    release = getattr(cap, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            pass
