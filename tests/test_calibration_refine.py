"""Edge-based homography refinement (ticket 15 + soft-far polish gate)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from madu_darts.calibration import (
    FitStatus,
    RefineParams,
    measure_board_edges,
    refine_homography,
    suggest,
)
from madu_darts.calibration.autofit import _edge_seed_needs_polish
from madu_darts.calibration.homography import apply_homography, board_mm_to_image
from madu_darts.calibration.refine import FitQuality, evaluate_fit
from madu_darts.calibration.residuals import residual_field_from_correspondences, summarize_residuals
from madu_darts.calibration.synthetic import synthetic_camera

GRID_MM = np.array(
    [(x, y) for x in range(-160, 161, 40) for y in range(-160, 161, 40) if x * x + y * y <= 165**2],
    dtype=np.float64,
)


@pytest.mark.parametrize("pose", ["fronto", "tilt_top", "tilt_left"])
def test_refine_from_noisy_seed_recovers_board_plane(pose: str) -> None:
    cam = synthetic_camera(pose, rotation_sectors=0)
    # Perturb the truth H slightly so colour-less refine still has a usable seed.
    noise = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, -1.5], [0.0, 0.0, 1.0]], dtype=np.float64)
    seed = noise @ cam.truth_homography
    refined, quality = refine_homography(cam.image, seed, RefineParams(max_iters=3))
    assert quality.n_inliers >= 40
    assert quality.rms_mm < 1.5
    px = board_mm_to_image(cam.truth_homography, 0, GRID_MM)
    mapped = apply_homography(refined, px)
    rms = float(np.sqrt(np.mean(np.sum((mapped - GRID_MM) ** 2, axis=1))))
    assert rms < 1.5
    # Better than the intentionally-perturbed seed.
    seed_mapped = apply_homography(seed, px)
    seed_rms = float(np.sqrt(np.mean(np.sum((seed_mapped - GRID_MM) ** 2, axis=1))))
    assert rms < seed_rms


def test_suggest_with_refine_still_passes_synthetic() -> None:
    cam = synthetic_camera("tilt_right", rotation_sectors=0)
    cal = suggest(cam.image, slot=0)
    assert cal.status is FitStatus.PASS
    assert cal.n_inliers is not None and cal.n_points is not None
    assert cal.n_inliers >= 40
    assert cal.rms_mm is not None and cal.rms_mm < 1.5
    assert cal.rms_double_mm is not None and cal.rms_treble_mm is not None


def test_measure_board_edges_finds_rings_on_synthetic() -> None:
    cam = synthetic_camera("fronto")
    px, mm = measure_board_edges(cam.image, cam.truth_homography, RefineParams(ring_angles=36))
    assert len(px) >= 30
    rad = np.hypot(mm[:, 0], mm[:, 1])
    assert np.any((rad > 95) & (rad < 110))  # treble neighbourhood
    assert np.any(rad > 155)  # double neighbourhood


def test_edge_seed_needs_polish_on_soft_far_double() -> None:
    """Colour-healthy H against a bulged far double must still request polish."""
    # bias 8 mm → far-double WARN band (rms > 3.5 or max > 7); 6 mm stays under.
    cam = synthetic_camera("tilt_top", far_double_bias_mm=8.0, far_angle_deg=0.0)
    px, mm = measure_board_edges(cam.image, cam.truth_homography, RefineParams(ring_angles=36))
    seed_edge = evaluate_fit(cam.truth_homography, px, mm)
    assert seed_edge.n_inliers >= 40  # coverage looks usable
    field = residual_field_from_correspondences(
        cam.truth_homography, seed_edge.points_px, seed_edge.points_mm, seed_edge.inlier_mask
    )
    assert field is not None
    far = summarize_residuals(field, cam.truth_homography, 0)["farDouble"]
    assert far is not None and (far["rmsMm"] > 3.5 or far["maxMm"] > 7.0)
    assert _edge_seed_needs_polish(seed_edge, cam.truth_homography) is True


def test_edge_seed_skips_polish_on_clean_synthetic() -> None:
    cam = synthetic_camera("fronto")
    px, mm = measure_board_edges(cam.image, cam.truth_homography, RefineParams(ring_angles=36))
    seed_edge = evaluate_fit(cam.truth_homography, px, mm)
    assert seed_edge.n_inliers >= 40
    assert _edge_seed_needs_polish(seed_edge, cam.truth_homography) is False


def test_suggest_soft_far_enters_refine_even_when_colour_looks_healthy() -> None:
    """Soft foreshortened double must call refine_homography (not colour-only rescore)."""
    # 12 mm bias: after scoring-face midpoints (ticket 21) an 8 mm bias can be
    # absorbed into the colour H enough that far-double looks PASS (~2 mm).
    cam = synthetic_camera("tilt_top", far_double_bias_mm=12.0, far_angle_deg=0.0)
    calls: list[object] = []

    real_refine = refine_homography

    def spy(image, seed, params=None):
        calls.append(seed)
        return real_refine(image, seed, params)

    with patch("madu_darts.calibration.autofit.refine_homography", side_effect=spy):
        cal = suggest(cam.image, slot=0)
    assert calls, "soft far-double seed must enter edge polish"
    assert cal.homography is not None
    assert cal.residuals is not None


def test_suggest_clean_synthetic_can_skip_refine_when_edges_tight() -> None:
    """Clean fronto: colour seed + tight edges → no forced polish required."""
    cam = synthetic_camera("fronto")
    calls: list[object] = []

    def spy(image, seed, params=None):
        calls.append(seed)
        return seed, FitQuality(rms_mm=0.0, n_inliers=0, n_points=0)

    with patch("madu_darts.calibration.autofit.refine_homography", side_effect=spy):
        cal = suggest(cam.image, slot=0)
    # May still refine if colour_weak; if not called, edges were tight enough.
    if not calls:
        assert cal.status is FitStatus.PASS
        assert cal.rms_mm is not None and cal.rms_mm < 1.5
    else:
        # Colour path was weak — refine ran; still must pass.
        assert cal.status is FitStatus.PASS
