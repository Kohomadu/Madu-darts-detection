"""Tip localization + fusion knobs (Autodarts ``detection`` defaults where known)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from madu_darts.calibration.mount import DEFAULT_MOUNT_ANGLES_DEG


@dataclass(frozen=True)
class TipConfig:
    """Per-cam classical tip finder.

    ``kernel`` / ``threshold`` mirror Autodarts 2.1 ``detection: {kernel: 5, threshold: 16}``.
    """

    kernel: int = 5
    threshold: int = 16
    #: Full-res padding around the settled-change bbox (px).
    roi_pad_px: int = 40
    #: Components smaller than this (px) or than ``component_rel`` × largest are ignored.
    min_component_px: int = 30
    component_rel: float = 0.03
    #: Minimum changed pixels to attempt an axis fit.
    min_points: int = 20
    #: Perpendicular band (px) around the fitted axis that counts as the dart.
    axis_inlier_px: float = 10.0
    #: Tip = mean of the k farthest inliers along the axis.
    tip_top_k: int = 4
    #: Dart axis must be at least this long (px) to be a dart, not a speck.
    min_length_px: float = 25.0
    #: Reject blobs that are not elongated (hand / multi-blob): major/minor variance ratio.
    min_elongation: float = 2.0
    #: Reject when the changed region spans more than this fraction of the frame.
    max_frame_fraction: float = 0.6

    def to_api(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "threshold": self.threshold,
            "roiPadPx": self.roi_pad_px,
            "axisInlierPx": self.axis_inlier_px,
            "tipTopK": self.tip_top_k,
            "minLengthPx": self.min_length_px,
            "minElongation": self.min_elongation,
        }


@dataclass(frozen=True)
class FusionConfig:
    """Multi-view fusion on the Board plane."""

    #: Two cams agree when their Board-plane tips are within this distance.
    agree_mm: float = 15.0
    #: Seconds to wait for the other cams after the first settled change (live).
    collect_window_s: float = 0.4
    #: Minimum cams required to claim a Hit.
    min_cams: int = 1
    #: Reject per-cam / fused tips farther from the bull than this (mm). Double outer is
    #: 170 mm; ~200 leaves a little room for tip noise / just-outside misses, and kills
    #: arm/body false Hits at r ≫ 300 (ticket 14).
    max_hit_radius_mm: float = 200.0
    #: Ticket 15: when True, a non-pass cam is dropped if two pass cams already agree.
    prefer_pass_cams: bool = True
    #: Ticket 24: drop cams whose tip sits in a prior dart footprint / near a stuck tip.
    drop_occluded_cams: bool = True
    #: Full-res pad around a committed Hit's settled bbox when testing tip occlusion.
    occlusion_bbox_pad_px: float = 24.0
    #: Board-mm radius around a prior tip: a cam tip this close is occluded only when
    #: at least one other cam is farther away (locked onto the old dart).
    occlusion_tip_radius_mm: float = 8.0
    #: Per-slot Board mount angles (deg clockwise from +y). Used to prefer the
    #: near-hemisphere cam on wire straddles and soft multi-cam ties.
    mount_angles_deg: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_MOUNT_ANGLES_DEG))
    #: When agreeing cams still span more than this, weight the mean toward the
    #: near-mount cam instead of a plain average (tight UnanimousCam stays equal).
    soft_tie_spread_mm: float = 4.0

    def to_api(self) -> dict[str, Any]:
        return {
            "agreeMm": self.agree_mm,
            "collectWindowS": self.collect_window_s,
            "minCams": self.min_cams,
            "maxHitRadiusMm": self.max_hit_radius_mm,
            "preferPassCams": self.prefer_pass_cams,
            "dropOccludedCams": self.drop_occluded_cams,
            "occlusionBboxPadPx": self.occlusion_bbox_pad_px,
            "occlusionTipRadiusMm": self.occlusion_tip_radius_mm,
            "softTieSpreadMm": self.soft_tie_spread_mm,
            "mountAnglesDeg": {str(k): float(v) for k, v in sorted(self.mount_angles_deg.items())},
        }


__all__ = ["FusionConfig", "TipConfig"]
