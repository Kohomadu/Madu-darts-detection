"""Edge-based homography refinement (ticket 15)."""

from __future__ import annotations

import numpy as np
import pytest

from madu_darts.calibration import (
    FitStatus,
    RefineParams,
    measure_board_edges,
    refine_homography,
    suggest,
)
from madu_darts.calibration.homography import apply_homography, board_mm_to_image
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
