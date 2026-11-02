"""Tip localization + fusion knobs (Autodarts ``detection`` defaults where known)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

    def to_api(self) -> dict[str, Any]:
        return {
            "agreeMm": self.agree_mm,
            "collectWindowS": self.collect_window_s,
            "minCams": self.min_cams,
            "maxHitRadiusMm": self.max_hit_radius_mm,
        }


__all__ = ["FusionConfig", "TipConfig"]
