"""Turn / takeout knobs (Autodarts-shaped where a counterpart exists)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TurnConfig:
    """Visit lifecycle settings around committed Hits.

    Pixel budgets are at motion scale (320×180 for 1280×720 ÷ 4). On the 07
    recording one stuck dart changes 120–720 px per cam, three darts 580–1550,
    and the empty Board drifts 0 px between visits — ``empty_max_changed_pixels``
    sits well below the smallest dart. Live Boards after a visit often need the
    softer takeout-finish path (ticket 16).
    """

    #: Hits per Turn (Autodarts: three darts, then ``status: takeout``).
    max_hits: int = 3
    #: Per-cam diff vs the empty-Board reference at or below this on every cam → Board empty
    #: (strict path; lighting-matched Accept reference).
    empty_max_changed_pixels: int = 60
    #: Softer empty cap used with ``dart_removed`` during ``takeoutInProgress`` (ticket 16).
    empty_soft_max_changed_pixels: int = 500
    #: Per-cam diff vs the takeout-start (dart-committed) background above this → footprints gone.
    dart_removed_min_pixels: int = 200
    #: Consecutive frames with no cam moving before the empty / recovery checks run.
    quiet_frames: int = 3
    #: Footprint ROI diff vs the pre-commit reference ≤ ratio × diff vs the current
    #: reference → the dart is gone (bounce-out / fall) rather than a new dart. A real
    #: fall leaves near-zero residue; two of three darts vanishing together sits at 1/3.
    revert_ratio: float = 0.25
    #: Other cams' settled changes within this window after a retraction are the
    #: same dart leaving, not new darts.
    retraction_window_s: float = 1.0
    #: Zero-dart takeout (hand seen, nothing to remove) quiet for this long but not
    #: empty vs the old reference → adopt the current frames as the empty Board.
    false_takeout_recover_s: float = 3.0
    #: Takeout-in-progress with Hits still stuck, quiet this long → force finish (adopt frames).
    takeout_force_finish_s: float = 4.0
    #: No motion for this long → standby (gate parked, frames sampled at ``standby_poll_s``).
    #: Autodarts ``cam.standbyMinutes`` default 60. ``0`` disables.
    standby_minutes: float = 60.0
    standby_poll_s: float = 1.0

    def to_api(self) -> dict[str, Any]:
        return {
            "maxHits": self.max_hits,
            "emptyMaxChangedPixels": self.empty_max_changed_pixels,
            "emptySoftMaxChangedPixels": self.empty_soft_max_changed_pixels,
            "dartRemovedMinPixels": self.dart_removed_min_pixels,
            "quietFrames": self.quiet_frames,
            "revertRatio": self.revert_ratio,
            "retractionWindowS": self.retraction_window_s,
            "falseTakeoutRecoverS": self.false_takeout_recover_s,
            "takeoutForceFinishS": self.takeout_force_finish_s,
            "standbyMinutes": self.standby_minutes,
            "standbyPollS": self.standby_poll_s,
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["TurnConfig"]
