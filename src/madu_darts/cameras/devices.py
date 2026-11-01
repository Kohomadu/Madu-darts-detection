"""USB camera identity: prefer location over index/serial alone."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Autodarts-style: `…-usb-0:7.2:1.0` or bare `7.2` / `7.3`.
_LOCATION_IN_PATH = re.compile(
    r"(?:usb[-_]?\d*:)?(\d+(?:\.\d+)+)(?::\d+(?:\.\d+)*)?",
    re.IGNORECASE,
)
_BARE_LOCATION = re.compile(r"^\d+(?:\.\d+)+$")


@dataclass(frozen=True)
class CameraDevice:
    """One enumerated capture device."""

    index: int
    name: str
    location: str | None
    """Short USB port path when known (e.g. ``7.2``)."""

    path: str | None = None
    """Raw by-path / device path string when available."""


def normalize_location(raw: str) -> str | None:
    """Extract a short USB location like ``7.2`` from Autodarts/V4L path ids.

    Accepts bare locations (``7.2``), Autodarts query ids
    (``…&location=…-usb-0:7.2:1.0``), and Linux ``/dev/v4l/by-path`` names.
    """
    text = raw.strip()
    if not text:
        return None

    # Autodarts cam id: vid=…&pid=…&location=…-usb-0:7.2:1.0
    if "location=" in text.lower():
        for part in text.split("&"):
            key, _, value = part.partition("=")
            if key.strip().lower() == "location":
                text = value.strip()
                break

    if _BARE_LOCATION.match(text):
        return text

    # Prefer the usb-N:X.Y:… group when present.
    usb_match = re.search(
        r"usb[-_]?\d*:(\d+(?:\.\d+)+)",
        text,
        re.IGNORECASE,
    )
    if usb_match:
        return usb_match.group(1)

    matches = _LOCATION_IN_PATH.findall(text)
    if matches:
        # Last dotted group is usually the port path (avoid bus-only digits).
        dotted = [m for m in matches if "." in m]
        if dotted:
            return dotted[-1]
        return matches[-1]
    return None


def match_devices_by_location(
    devices: list[CameraDevice],
    locations: list[str],
    *,
    index_overrides: dict[str, int] | None = None,
) -> dict[str, CameraDevice]:
    """Resolve each requested USB location to exactly one device.

    Raises ``LookupError`` if a location cannot be resolved uniquely.
    ``index_overrides`` maps location → OpenCV index when path identity is
    unavailable (Windows-dev fallback).
    """
    overrides = index_overrides or {}
    by_location: dict[str, list[CameraDevice]] = {}
    for device in devices:
        if device.location is None:
            continue
        by_location.setdefault(device.location, []).append(device)

    by_index = {d.index: d for d in devices}
    resolved: dict[str, CameraDevice] = {}

    for location in locations:
        if location in overrides:
            index = overrides[location]
            if index not in by_index:
                raise LookupError(
                    f"location {location!r} override index {index} not in device list"
                )
            resolved[location] = by_index[index]
            continue

        candidates = by_location.get(location, [])
        if len(candidates) == 1:
            resolved[location] = candidates[0]
            continue
        if len(candidates) > 1:
            detail = ", ".join(
                f"index={d.index} name={d.name!r}" for d in candidates
            )
            raise LookupError(
                f"location {location!r} matched {len(candidates)} devices "
                f"({detail}); USB location must be unique"
            )
        raise LookupError(
            f"no camera with USB location {location!r}; "
            "set location_index_overrides or fix cabling"
        )

    return resolved
