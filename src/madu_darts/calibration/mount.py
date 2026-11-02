"""Per-slot rotate-20 defaults for this Board's ring-mounted cams.

Autofit picks the warm wedge nearest screen-up as sector 20. On the ring that
is not the physical 20, so ``suggest`` leaves ``rotate_offset=0`` wrong every
startup. These defaults (live 2026-11-02 + 07-recording bind) are applied after
each suggest; last Accepted offsets are remembered on disk and win next time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Cam 0 above physical 20 → autofit paints opposite (3) → offset 10.
# Cam 1 near 16 → paints 13 as 20 → 4 left.
# Cam 2 near 15 → paints 14 as 20 → 4 right (= 16 left).
DEFAULT_ROTATE_OFFSETS: dict[int, int] = {0: 10, 1: 4, 2: 16}

# Board-plane mount angles (deg clockwise from +y / sector 20) for near-hemisphere
# fusion + mild near-weighted refine. Cam 0 sits above 20; cams 1/2 on the ring
# near sectors 16 and 15 (live Board 2026-11-02).
DEFAULT_MOUNT_ANGLES_DEG: dict[int, float] = {0: 0.0, 1: 234.0, 2: 126.0}

DEFAULT_OFFSET_STORE = Path("captures") / "calibration_offsets.json"


def load_rotate_offsets(
    path: Path | None,
    *,
    defaults: dict[int, int] | None = None,
) -> dict[int, int]:
    """Defaults, then on-disk last-Accepted offsets (disk wins per slot)."""
    out = dict(defaults if defaults is not None else DEFAULT_ROTATE_OFFSETS)
    if path is None or not Path(path).is_file():
        return out
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw = data.get("rotateOffsets", data) if isinstance(data, dict) else {}
        for key, value in dict(raw).items():
            out[int(key)] = int(value) % 20
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("could not load rotate offsets from %s: %s", path, exc)
    return out


def save_rotate_offsets(path: Path, offsets: dict[int, int]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "rotateOffsets": {str(int(s)): int(o) % 20 for s, o in sorted(offsets.items())},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "DEFAULT_MOUNT_ANGLES_DEG",
    "DEFAULT_OFFSET_STORE",
    "DEFAULT_ROTATE_OFFSETS",
    "load_rotate_offsets",
    "save_rotate_offsets",
]
