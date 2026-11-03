"""Detection debug overlays: tip votes, fused Hit, ring-side (ticket 30)."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np

from madu_darts.board.geometry import point_mm_to_segment, ring_side_of_point
from madu_darts.calibration.homography import board_mm_to_image
from madu_darts.calibration.model import CamCalibration
from madu_darts.hits.hit import Hit

USED_BGR = (60, 200, 60)
DROPPED_BGR = (40, 140, 255)
FUSED_BGR = (255, 160, 40)
TEXT_BGR = (240, 240, 240)


def _tip_px(vote: Mapping[str, Any] | Any) -> tuple[float, float] | None:
    tip = getattr(vote, "tip", None)
    if tip is not None:
        px = getattr(tip, "tip_px", None)
        if px is not None and len(px) >= 2:
            return float(px[0]), float(px[1])
    if isinstance(vote, Mapping):
        tip_d = vote.get("tip") or {}
        px = tip_d.get("tipPx") or tip_d.get("tip_px")
        if px is not None and len(px) >= 2:
            return float(px[0]), float(px[1])
    return None


def _vote_mm(vote: Mapping[str, Any] | Any) -> tuple[float, float] | None:
    if hasattr(vote, "x_mm") and hasattr(vote, "y_mm"):
        return float(vote.x_mm), float(vote.y_mm)
    if isinstance(vote, Mapping) and "xMm" in vote and "yMm" in vote:
        return float(vote["xMm"]), float(vote["yMm"])
    return None


def _vote_used(vote: Mapping[str, Any] | Any) -> bool:
    if hasattr(vote, "used"):
        return bool(vote.used)
    if isinstance(vote, Mapping):
        return bool(vote.get("used", False))
    return False


def _hit_votes(hit: Hit | Mapping[str, Any]) -> Sequence[Any]:
    if isinstance(hit, Hit):
        return hit.slot_votes
    madu = hit.get("madu") if isinstance(hit, Mapping) else None
    if isinstance(madu, Mapping):
        return list(madu.get("votes") or [])
    return []


def _hit_xy(hit: Hit | Mapping[str, Any]) -> tuple[float, float] | None:
    if isinstance(hit, Hit):
        return hit.x_mm, hit.y_mm
    if isinstance(hit, Mapping):
        madu = hit.get("madu") or {}
        if "xMm" in madu and "yMm" in madu:
            return float(madu["xMm"]), float(madu["yMm"])
        if "xMm" in hit and "yMm" in hit:
            return float(hit["xMm"]), float(hit["yMm"])
    return None


def draw_hit_debug(
    image: np.ndarray,
    slot: int,
    cal: CamCalibration | None,
    hits: Iterable[Hit | Mapping[str, Any]],
) -> np.ndarray:
    """Draw this cam's tip votes and each fused Hit projected back into the image.

    Opt-in only — callers keep default streams unchanged when they skip this.
    """
    out = np.asarray(image).copy()
    if cal is None or not cal.has_fit or cal.homography is None:
        return out

    for hit in hits:
        for vote in _hit_votes(hit):
            vote_slot = getattr(vote, "slot", None)
            if vote_slot is None and isinstance(vote, Mapping):
                vote_slot = vote.get("slot")
            if int(vote_slot) != int(slot):
                continue
            tip = _tip_px(vote)
            mm = _vote_mm(vote)
            if tip is None:
                continue
            used = _vote_used(vote)
            colour = USED_BGR if used else DROPPED_BGR
            cx, cy = int(round(tip[0])), int(round(tip[1]))
            cv2.circle(out, (cx, cy), 8, colour, 2, lineType=cv2.LINE_AA)
            label = "keep" if used else "drop"
            if mm is not None:
                side = ring_side_of_point(mm[0], mm[1])
                bed = point_mm_to_segment(mm[0], mm[1]).name
                label = f"{label} {bed} {side['side']}"
            cv2.putText(
                out,
                label,
                (cx + 10, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                TEXT_BGR,
                1,
                cv2.LINE_AA,
            )

        fused = _hit_xy(hit)
        if fused is None:
            continue
        proj = np.asarray(board_mm_to_image(cal.homography, cal.rotate_offset, fused), dtype=np.float64)
        if proj.ndim > 1:
            proj = proj[0]
        fx, fy = int(round(float(proj[0]))), int(round(float(proj[1])))
        cv2.drawMarker(out, (fx, fy), FUSED_BGR, markerType=cv2.MARKER_CROSS, markerSize=16, thickness=2)
        side = ring_side_of_point(fused[0], fused[1])
        cv2.putText(
            out,
            f"fused {side['side']}",
            (fx + 10, fy + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            FUSED_BGR,
            1,
            cv2.LINE_AA,
        )
    return out


__all__ = ["draw_hit_debug"]
