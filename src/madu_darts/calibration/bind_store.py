"""Persist Accepted per-cam Board binds so Auto/restart cannot silently wipe them.

Stores rotate-20 + the full homography. Extends the older offsets-only file used
by ticket 13; both formats remain readable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from madu_darts.calibration.model import CamCalibration
from madu_darts.calibration.mount import DEFAULT_OFFSET_STORE

log = logging.getLogger(__name__)

DEFAULT_BIND_STORE = Path("captures") / "calibration_bind.json"


def _homography_list(h: np.ndarray) -> list[float]:
    return [float(x) for x in np.asarray(h, dtype=np.float64).reshape(9)]


def save_binds(path: Path, cals: dict[int, CamCalibration]) -> None:
    """Write every cam that has a fit; missing slots are omitted."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cams: dict[str, Any] = {}
    for slot, cal in sorted(cals.items()):
        if not cal.has_fit or cal.homography is None:
            continue
        cams[str(int(slot))] = {
            "rotateOffset": int(cal.rotate_offset) % 20,
            "homography": _homography_list(cal.homography),
        }
    payload = {"cams": cams}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Keep the legacy offsets file in sync for older tooling.
    try:
        from madu_darts.calibration.mount import save_rotate_offsets

        save_rotate_offsets(
            path.parent / DEFAULT_OFFSET_STORE.name,
            {s: c.rotate_offset for s, c in cals.items() if c.has_fit},
        )
    except OSError as exc:
        log.warning("could not mirror rotate offsets: %s", exc)


def load_binds(path: Path | None) -> dict[int, CamCalibration]:
    """Return saved cams keyed by slot; empty when missing or unreadable."""
    if path is None or not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("could not load calibration binds from %s: %s", path, exc)
        return {}
    raw = data.get("cams", data) if isinstance(data, dict) else {}
    out: dict[int, CamCalibration] = {}
    for key, value in dict(raw).items():
        try:
            slot = int(key)
            if not isinstance(value, dict):
                continue
            h_list = value.get("homography")
            if not h_list or len(h_list) != 9:
                continue
            h = np.asarray(h_list, dtype=np.float64).reshape(3, 3)
            offset = int(value.get("rotateOffset", 0)) % 20
            out[slot] = CamCalibration(slot=slot, homography=h, rotate_offset=offset)
        except (TypeError, ValueError) as exc:
            log.warning("skipping bind for cam %s: %s", key, exc)
    return out


__all__ = ["DEFAULT_BIND_STORE", "load_binds", "save_binds"]
