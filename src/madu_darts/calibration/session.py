"""Calibration session: per-cam suggestions, rotate-20, and the operator Accept gate.

ADR 0002: every detection-process startup runs Calibration before Hits are
claimed. ``CalibrationSession`` holds the in-memory state for one process run;
Accepted binds may be persisted (homography + rotate-20) so Auto/restart cannot
silently wipe operator-tuned spiders. ``require_accepted`` / ``board_point`` are
the seams the Hit pipeline must go through, so no Accept -> no Hits.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from madu_darts.calibration.autofit import AutoFitError, AutoFitParams, suggest, suggest_best
from madu_darts.calibration.bind_store import load_binds, save_binds
from madu_darts.calibration.homography import board_mm_to_image, image_to_board_mm, rings_from_homography
from madu_darts.calibration.model import (
    AcceptGateParams,
    CalibrationNotAccepted,
    CamCalibration,
    FitStatus,
    accept_block_reasons,
)
from madu_darts.calibration.mount import load_rotate_offsets, save_rotate_offsets
from madu_darts.calibration.refine import apply_quality, evaluate_fit, measure_board_edges
from madu_darts.calibration.residuals import summarize_residuals

log = logging.getLogger(__name__)

ACCEPTABLE = frozenset({FitStatus.PASS, FitStatus.WARN})

Suggester = Callable[[np.ndarray, int, AutoFitParams | None], CamCalibration]

# Default pan / fine-rotate steps (image px / degrees).
DEFAULT_PAN_STEP_PX = 2.0
DEFAULT_FINE_ROTATE_DEG = 1.0


class AcceptBlocked(RuntimeError):
    """Accept refused; ``blockers`` lists the per-cam reasons."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__("; ".join(blockers))
        self.blockers = blockers


def _image_similarity(bull_uv: np.ndarray, *, dx: float, dy: float, ddeg: float) -> np.ndarray:
    """3x3 image-space similarity: rotate ``ddeg`` CCW (math) about bull, then translate."""
    bx, by = float(bull_uv[0]), float(bull_uv[1])
    rad = math.radians(ddeg)
    c, s = math.cos(rad), math.sin(rad)
    # Standard 2D rotation about bull, then + (dx, dy).
    return np.array(
        [
            [c, -s, -c * bx + s * by + bx + dx],
            [s, c, -s * bx - c * by + by + dy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


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
        bind_store: Path | str | None = None,
        accept_gate: AcceptGateParams | None = None,
    ) -> None:
        self._slots = tuple(int(s) for s in slots)
        if not self._slots:
            raise ValueError("CalibrationSession needs at least one slot")
        self._params = params
        self._suggester = suggester
        self._accept_gate = accept_gate or AcceptGateParams()
        self._offset_store = None if offset_store is None else Path(offset_store)
        self._bind_store = None if bind_store is None else Path(bind_store)
        # Empty defaults unless the product wiring (DetectionService) passes the Board mounts.
        defaults = dict(default_rotate_offsets or {})
        self._rotate_offsets = load_rotate_offsets(self._offset_store, defaults=defaults)
        self._lock = threading.RLock()
        self._cals: dict[int, CamCalibration] = {s: CamCalibration(slot=s) for s in self._slots}
        self._errors: dict[int, str | None] = {s: None for s in self._slots}
        self._accepted = False
        # Slots with an Accepted/saved bind: Auto must not overwrite without force/reset.
        self._bound_slots: set[int] = set()
        # Last Auto result per slot (session seed for Undo).
        self._auto_seeds: dict[int, CamCalibration] = {}

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

    def is_bound(self, slot: int) -> bool:
        with self._lock:
            return self._check(slot) in self._bound_slots

    @property
    def accept_gate(self) -> AcceptGateParams:
        return self._accept_gate

    def blockers(self) -> list[str]:
        """Why Accept is currently refused (empty when it would succeed).

        Ticket 23: a PASS badge from inlier-only RMS is not enough — a soft
        foreshortened double (residual overlay) also blocks Accept.
        """
        with self._lock:
            out: list[str] = []
            for slot in self._slots:
                cal = self._cals[slot]
                for reason in accept_block_reasons(cal, error=self._errors[slot], params=self._accept_gate):
                    out.append(f"cam {slot}: {reason}")
            return out

    def can_accept(self) -> bool:
        return not self.blockers()

    # --- mutate (any change to a cam revokes Accept) ---

    def suggest(self, slot: int, image: np.ndarray | list[np.ndarray], *, force: bool = False) -> CamCalibration:
        """Run auto-fit for one cam; a failure leaves the cam at ``none`` with a reason.

        ``image`` may be a single frame or a short list (multi-frame Auto, ticket 15).
        On success, applies the mount / last-Accepted ``rotate_offset`` for this slot
        so ring cams land on physical 20 without arrow presses (ticket 13).

        Bound (Accepted/saved) cams are left untouched unless ``force=True`` (Reset bind /
        Re-Auto).
        """
        slot = self._check(slot)
        with self._lock:
            if not force and slot in self._bound_slots and self._cals[slot].has_fit:
                return self._cals[slot]
            if force:
                self._bound_slots.discard(slot)
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
            if cal.has_fit:
                self._auto_seeds[slot] = cal
            else:
                self._auto_seeds.pop(slot, None)
        return cal

    def suggest_all(
        self,
        frames: Mapping[int, np.ndarray] | Mapping[int, list[np.ndarray]],
        *,
        force: bool = False,
    ) -> dict[int, CamCalibration]:
        """Auto-fit every slot that has a frame; bound slots skipped unless ``force``."""
        result: dict[int, CamCalibration] = {}
        for slot in self._slots:
            image = frames.get(slot)
            if image is None or (isinstance(image, list) and not image):
                if force or not self.is_bound(slot):
                    result[slot] = self.clear(slot, "no frame from camera")
                else:
                    result[slot] = self.get(slot)
            else:
                result[slot] = self.suggest(slot, image, force=force)
        return result

    def clear(self, slot: int, reason: str) -> CamCalibration:
        """Drop a cam's fit (e.g. no frame) and record why; revokes Accept."""
        slot = self._check(slot)
        with self._lock:
            self._cals[slot] = CamCalibration(slot=slot)
            self._errors[slot] = reason
            self._accepted = False
            self._bound_slots.discard(slot)
            self._auto_seeds.pop(slot, None)
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

    def nudge_pan(self, slot: int, dx_px: float, dy_px: float) -> CamCalibration:
        """Translate the spider in image space; keeps ``board_point`` consistent with the draw."""
        return self._nudge_image(slot, dx=float(dx_px), dy=float(dy_px), ddeg=0.0)

    def nudge_rotate(self, slot: int, delta_deg: float) -> CamCalibration:
        """Fine-rotate the spider about the bull in image space (degrees, math CCW)."""
        return self._nudge_image(slot, dx=0.0, dy=0.0, ddeg=float(delta_deg))

    def _nudge_image(self, slot: int, *, dx: float, dy: float, ddeg: float) -> CamCalibration:
        slot = self._check(slot)
        with self._lock:
            cal = self._cals[slot]
            if not cal.has_fit or cal.homography is None:
                raise ValueError(f"cam {slot} has no fit to nudge")
            bull = board_mm_to_image(cal.homography, cal.rotate_offset, (0.0, 0.0))
            m = _image_similarity(bull, dx=dx, dy=dy, ddeg=ddeg)
            h_new = cal.homography @ np.linalg.inv(m)
            rings = rings_from_homography(h_new)
            # Nudge invalidates residual field (samples were for the old H).
            cal = replace(cal, homography=h_new, rings=rings, residuals=None, rms_mm=None)
            self._cals[slot] = cal
            self._accepted = False
            return cal

    def revert_auto(self, slot: int) -> CamCalibration:
        """Restore this session's last Auto seed for ``slot`` (Undo after nudge)."""
        slot = self._check(slot)
        with self._lock:
            seed = self._auto_seeds.get(slot)
            if seed is None or not seed.has_fit:
                raise ValueError(f"cam {slot} has no Auto seed to revert to")
            self._cals[slot] = seed
            self._errors[slot] = None
            self._accepted = False
            return seed

    def reset_bind(self, slot: int) -> CamCalibration:
        """Allow Auto to overwrite this cam's saved bind (keeps current fit until Re-Auto)."""
        slot = self._check(slot)
        with self._lock:
            self._bound_slots.discard(slot)
            self._accepted = False
            return self._cals[slot]

    def load_saved_binds(self) -> bool:
        """Load on-disk binds into live cams. Returns True when at least one bind loaded."""
        if self._bind_store is None:
            return False
        binds = load_binds(self._bind_store)
        if not binds:
            return False
        with self._lock:
            loaded = False
            for slot in self._slots:
                cal = binds.get(slot)
                if cal is None or not cal.has_fit or cal.homography is None:
                    continue
                rings = rings_from_homography(cal.homography)
                self._cals[slot] = replace(cal, rings=rings)
                self._errors[slot] = None
                self._bound_slots.add(slot)
                self._rotate_offsets[slot] = int(cal.rotate_offset) % 20
                loaded = True
            self._accepted = False
            return loaded

    def rescore(self, frames: Mapping[int, np.ndarray]) -> None:
        """Re-measure residuals / RMS for current Hs against live frames (does not change H)."""
        with self._lock:
            for slot in self._slots:
                cal = self._cals[slot]
                image = frames.get(slot)
                if image is None or not cal.has_fit or cal.homography is None:
                    continue
                px, mm = measure_board_edges(image, cal.homography)
                if len(px) == 0:
                    continue
                quality = evaluate_fit(cal.homography, px, mm)
                self._cals[slot] = apply_quality(cal, quality)

    def accept(self) -> None:
        """Operator confirms the overlays; raises ``AcceptBlocked`` if any cam is not pass/warn."""
        with self._lock:
            blockers = self.blockers()
            if blockers:
                raise AcceptBlocked(blockers)
            self._accepted = True
            # Remember what the operator signed off on for the next autofit / bind store.
            fitted = {slot: self._cals[slot] for slot in self._slots if self._cals[slot].has_fit}
            self._rotate_offsets = {slot: cal.rotate_offset for slot, cal in fitted.items()}
            self._bound_slots = set(fitted)
            store = self._offset_store
            bind_store = self._bind_store
            offsets = dict(self._rotate_offsets)
            binds = dict(fitted)
        if store is not None and offsets:
            try:
                save_rotate_offsets(store, offsets)
            except OSError as exc:
                log.warning("could not save rotate offsets to %s: %s", store, exc)
        if bind_store is not None and binds:
            try:
                save_binds(bind_store, binds)
            except OSError as exc:
                log.warning("could not save calibration binds to %s: %s", bind_store, exc)

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
                    "bindLocked": slot in self._bound_slots,
                    "hasAutoSeed": slot in self._auto_seeds,
                }
            return {
                "accepted": self._accepted,
                "canAccept": not self.blockers(),
                "blockers": self.blockers(),
                "acceptGate": self._accept_gate.to_api(),
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
