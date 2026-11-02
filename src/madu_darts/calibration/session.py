"""Calibration session: per-cam suggestions, rotate-20, and the operator Accept gate.

ADR 0002: every detection-process startup runs Calibration before Hits are
claimed. ``CalibrationSession`` holds the in-memory state for one process run;
nothing is persisted. ``require_accepted`` / ``board_point`` are the seams the
Hit pipeline must go through, so no Accept -> no Hits.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from madu_darts.calibration.autofit import AutoFitError, AutoFitParams, suggest, suggest_best
from madu_darts.calibration.homography import image_to_board_mm
from madu_darts.calibration.model import CalibrationNotAccepted, CamCalibration, FitStatus
from madu_darts.calibration.residuals import summarize_residuals
from madu_darts.calibration.mount import load_rotate_offsets, save_rotate_offsets

log = logging.getLogger(__name__)

ACCEPTABLE = frozenset({FitStatus.PASS, FitStatus.WARN})

Suggester = Callable[[np.ndarray, int, AutoFitParams | None], CamCalibration]


class AcceptBlocked(RuntimeError):
    """Accept refused; ``blockers`` lists the per-cam reasons."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__("; ".join(blockers))
        self.blockers = blockers


class CalibrationSession:
    """Thread-safe Calibration state for the three Board cams."""

    def __init__(
        self,
        slots: Iterable[int] = (0, 1, 2),
        *,
        params: AutoFitParams | None = None,
        suggester: Suggester = suggest,
        default_rotate_offsets: Mapping[int, int] | None = None,
        offset_store: Path | str | None = None,
    ) -> None:
        self._slots = tuple(int(s) for s in slots)
        if not self._slots:
            raise ValueError("CalibrationSession needs at least one slot")
        self._params = params
        self._suggester = suggester
        self._offset_store = None if offset_store is None else Path(offset_store)
        # Empty defaults unless the product wiring (DetectionService) passes the Board mounts.
        defaults = dict(default_rotate_offsets or {})
        self._rotate_offsets = load_rotate_offsets(self._offset_store, defaults=defaults)
        self._lock = threading.RLock()
        self._cals: dict[int, CamCalibration] = {s: CamCalibration(slot=s) for s in self._slots}
        self._errors: dict[int, str | None] = {s: None for s in self._slots}
        self._accepted = False

    # --- read ---

    @property
    def slots(self) -> tuple[int, ...]:
        return self._slots

    @property
    def accepted(self) -> bool:
        with self._lock:
            return self._accepted

    def get(self, slot: int) -> CamCalibration:
        with self._lock:
            return self._cals[self._check(slot)]

    def error(self, slot: int) -> str | None:
        with self._lock:
            return self._errors[self._check(slot)]

    def blockers(self) -> list[str]:
        """Why Accept is currently refused (empty when it would succeed)."""
        with self._lock:
            out: list[str] = []
            for slot in self._slots:
                cal = self._cals[slot]
                if cal.status in ACCEPTABLE:
                    continue
                reason = self._errors[slot] or ("no Board-plane fit" if not cal.has_fit else f"fit RMS {cal.rms_mm:.2f} mm too high")
                out.append(f"cam {slot}: {reason}")
            return out

    def can_accept(self) -> bool:
        return not self.blockers()

    # --- mutate (any change to a cam revokes Accept) ---

    def suggest(self, slot: int, image: np.ndarray | list[np.ndarray]) -> CamCalibration:
        """Run auto-fit for one cam; a failure leaves the cam at ``none`` with a reason.

        ``image`` may be a single frame or a short list (multi-frame Auto, ticket 15).
        On success, applies the mount / last-Accepted ``rotate_offset`` for this slot
        so ring cams land on physical 20 without arrow presses (ticket 13).
        """
        slot = self._check(slot)
        try:
            if isinstance(image, list):
                if not image:
                    raise AutoFitError("no frame from camera")
                if len(image) == 1:
                    cal = self._suggester(image[0], slot, self._params)
                else:
                    # Multi-frame path always uses the real suggester chain (incl. refine).
                    cal = suggest_best(image, slot=slot, params=self._params)
            else:
                cal = self._suggester(image, slot, self._params)
            error: str | None = None
            offset = int(self._rotate_offsets.get(slot, 0)) % 20
            if cal.has_fit and offset:
                cal = replace(cal, rotate_offset=offset)
        except AutoFitError as exc:
            cal = CamCalibration(slot=slot)
            error = exc.reason
        with self._lock:
            self._cals[slot] = cal
            self._errors[slot] = error
            self._accepted = False
        return cal

    def suggest_all(
        self,
        frames: Mapping[int, np.ndarray] | Mapping[int, list[np.ndarray]],
    ) -> dict[int, CamCalibration]:
        """Auto-fit every slot that has a frame; slots without a frame become ``none``."""
        result: dict[int, CamCalibration] = {}
        for slot in self._slots:
            image = frames.get(slot)
            if image is None or (isinstance(image, list) and not image):
                result[slot] = self.clear(slot, "no frame from camera")
            else:
                result[slot] = self.suggest(slot, image)
        return result

    def clear(self, slot: int, reason: str) -> CamCalibration:
        """Drop a cam's fit (e.g. no frame) and record why; revokes Accept."""
        slot = self._check(slot)
        with self._lock:
            self._cals[slot] = CamCalibration(slot=slot)
            self._errors[slot] = reason
            self._accepted = False
            return self._cals[slot]

    def rotate_left(self, slot: int) -> CamCalibration:
        return self._rotate(slot, +1)

    def rotate_right(self, slot: int) -> CamCalibration:
        return self._rotate(slot, -1)

    def _rotate(self, slot: int, delta: int) -> CamCalibration:
        slot = self._check(slot)
        with self._lock:
            cal = self._cals[slot]
            if not cal.has_fit:
                raise ValueError(f"cam {slot} has no fit to rotate")
            cal = cal.rotated(delta)
            self._cals[slot] = cal
            self._accepted = False
            return cal

    def accept(self) -> None:
        """Operator confirms the overlays; raises ``AcceptBlocked`` if any cam is not pass/warn."""
        with self._lock:
            blockers = self.blockers()
            if blockers:
                raise AcceptBlocked(blockers)
            self._accepted = True
            # Remember what the operator signed off on for the next autofit.
            self._rotate_offsets = {slot: self._cals[slot].rotate_offset for slot in self._slots if self._cals[slot].has_fit}
            store = self._offset_store
        if store is not None and self._rotate_offsets:
            try:
                save_rotate_offsets(store, self._rotate_offsets)
            except OSError as exc:
                log.warning("could not save rotate offsets to %s: %s", store, exc)

    def reset(self) -> None:
        """Revoke Accept (fits are kept so the operator can re-check and re-Accept)."""
        with self._lock:
            self._accepted = False

    # --- gate ---

    def require_accepted(self) -> None:
        if not self.accepted:
            raise CalibrationNotAccepted("Calibration not accepted; no Hits may be claimed")

    def board_point(self, slot: int, point_px: Any) -> np.ndarray:
        """Image px -> Board mm for an accepted Calibration (the Hit pipeline's entry point)."""
        with self._lock:
            self.require_accepted()
            cal = self._cals[self._check(slot)]
            if not cal.has_fit:  # cannot happen after accept(), defensive
                raise CalibrationNotAccepted(f"cam {slot} has no fit")
            return image_to_board_mm(cal.homography, cal.rotate_offset, point_px)

    # --- export ---

    def snapshot(self) -> dict[str, Any]:
        """JSON-able state for the Calibration view."""
        with self._lock:
            cams: dict[str, Any] = {}
            for slot in self._slots:
                cal = self._cals[slot]
                residuals = (
                    summarize_residuals(cal.residuals, cal.homography, cal.rotate_offset)
                    if cal.residuals is not None and cal.homography is not None
                    else None
                )
                far = None if residuals is None else residuals["farDouble"]
                cams[str(slot)] = {
                    "status": cal.status.value,
                    "rotateOffset": cal.rotate_offset,
                    "rmsMm": cal.rms_mm,
                    "nInliers": cal.n_inliers,
                    "nPoints": cal.n_points,
                    "coverage": None if cal.coverage is None else round(cal.coverage, 3),
                    "rmsDoubleMm": cal.rms_double_mm,
                    "rmsTrebleMm": cal.rms_treble_mm,
                    "maxResidualMm": None if residuals is None else residuals["maxMm"],
                    "maxDoubleMm": None if residuals is None or residuals["double"] is None else residuals["double"]["maxMm"],
                    "maxTrebleMm": None if residuals is None or residuals["treble"] is None else residuals["treble"]["maxMm"],
                    "farDouble": far,
                    "nearDouble": None if residuals is None else residuals["nearDouble"],
                    "error": self._errors[slot],
                    "hasFit": cal.has_fit,
                }
            return {
                "accepted": self._accepted,
                "canAccept": not self.blockers(),
                "blockers": self.blockers(),
                "cams": cams,
            }

    def to_autodarts_ellipses(self) -> dict[str, Any]:
        """Shape of Autodarts ``GET /api/config/calibration/ellipses`` (cams without a fit omitted)."""
        with self._lock:
            return {
                str(slot): cal.rings.to_autodarts()
                for slot, cal in self._cals.items()
                if cal.rings is not None
            }

    def _check(self, slot: int) -> int:
        if slot not in self._cals:
            raise KeyError(f"unknown camera slot {slot}")
        return slot
