"""Ticket 22: joint radial + homography vs H-only on a known lens bend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from madu_darts.board import DOUBLE_INNER_MM, DOUBLE_OUTER_MM
from madu_darts.calibration.distortion import (
    RadialParams,
    distort_points,
    fit_joint_homography_radial,
    image_to_board_mm_radial,
)
from madu_darts.calibration.homography import board_mm_to_image, fit_homography, polar_mm
from madu_darts.calibration.refine import RefineParams, refine_homography
from madu_darts.calibration.residuals import residual_field_from_correspondences, summarize_residuals
from madu_darts.calibration.synthetic import synthetic_camera

EMPTY_BOARD = Path(__file__).resolve().parents[1] / "captures" / "live" / "_ticket19" / "board"


def _double_grid_mm(n_angles: int = 36) -> np.ndarray:
    angles = np.linspace(0.0, 360.0, n_angles, endpoint=False)
    pts = []
    for r in (DOUBLE_INNER_MM, DOUBLE_OUTER_MM, 164.5):
        for a in angles:
            pts.append(polar_mm(r, float(a)))
    # A few treble + wire samples so H is well constrained.
    for r in (99.0, 107.0, 80.0, 130.0):
        for a in angles[::2]:
            pts.append(polar_mm(r, float(a)))
    return np.asarray(pts, dtype=np.float64)


def _far_stats(homography, points_px, points_mm, *, radial=None):
    field = residual_field_from_correspondences(homography, points_px, points_mm, radial=radial)
    assert field is not None
    summary = summarize_residuals(field, homography, 0, radial=radial)
    far = summary["farDouble"]
    assert far is not None
    return far, summary.get("sectorWire")


def test_joint_fit_beats_homography_only_on_known_lens_bend() -> None:
    cam = synthetic_camera("tilt_top", lens_k1=0.18, lens_k2=-0.05)
    mm = _double_grid_mm()
    ideal_px = board_mm_to_image(cam.truth_homography, 0, mm)
    radial_truth = cam.lens_radial()
    assert radial_truth is not None
    obs_px = distort_points(ideal_px, radial_truth)

    h_only, _ = fit_homography(obs_px, mm, ransac_threshold_mm=3.0)
    h_joint, radial_fit, _ = fit_joint_homography_radial(
        obs_px,
        mm,
        seed_homography=h_only,
        ransac_threshold_mm=2.0,
        image_shape=cam.image.shape[:2],
    )

    far_only, wire_only = _far_stats(h_only, obs_px, mm)
    far_joint, wire_joint = _far_stats(h_joint, obs_px, mm, radial=radial_fit)

    assert far_joint["rmsMm"] < far_only["rmsMm"]
    assert far_joint["rmsMm"] < 2.0
    assert far_joint["maxMm"] < 4.0
    assert abs(radial_fit.k1) + abs(radial_fit.k2) > 0.02
    # Round-trip a far double sample through the joint model.
    sample = polar_mm(DOUBLE_OUTER_MM, 0.0)
    mapped = image_to_board_mm_radial(h_joint, 0, distort_points(board_mm_to_image(cam.truth_homography, 0, sample), radial_truth), radial_fit)
    assert float(np.linalg.norm(mapped - np.asarray(sample))) < 3.0
    assert wire_joint is not None or wire_only is not None


def test_refine_joint_path_on_synthetic_lens_image() -> None:
    cam = synthetic_camera("tilt_top", lens_k1=0.16)
    refined, quality = refine_homography(
        cam.image,
        cam.raw_homography,
        RefineParams(max_iters=3, fit_radial=True, min_inliers=24),
    )
    assert quality.n_points >= 40
    assert quality.points_px is not None and quality.points_mm is not None

    # H-only baseline on the same measured edges.
    h_only, _ = fit_homography(quality.points_px, quality.points_mm, ransac_threshold_mm=2.0)
    far_only, _ = _far_stats(h_only, quality.points_px, quality.points_mm)
    radial = quality.radial()
    far_joint, sector = _far_stats(refined, quality.points_px, quality.points_mm, radial=radial)

    if radial is not None:
        assert far_joint["rmsMm"] <= far_only["rmsMm"] + 0.05
        assert far_joint["rmsMm"] < 2.0
        assert far_joint["maxMm"] < 4.0
        assert quality.homography_only is not None
    else:
        # If the joint step declined, H-only must still be the returned model.
        assert abs(quality.radial_k1) < 1e-9
    assert sector is None or "rmsDeg" in sector


@pytest.mark.skipif(not (EMPTY_BOARD / "0.jpg").is_file(), reason="ticket19 empty-Board capture missing")
def test_empty_board_capture_joint_vs_homography_only() -> None:
    import cv2

    from madu_darts.calibration.autofit import suggest

    rows = []
    for slot in (0, 1, 2):
        image = cv2.imread(str(EMPTY_BOARD / f"{slot}.jpg"))
        assert image is not None
        cal = suggest(image, slot=slot)
        assert cal.homography is not None
        assert cal.residuals is not None
        joint = summarize_residuals(
            cal.residuals, cal.homography, cal.rotate_offset, radial=cal.radial()
        )
        # Re-score the same samples under H-only (drop radial / use stored H-only).
        h_only = cal.homography_only if cal.homography_only is not None else cal.homography
        only_field = residual_field_from_correspondences(
            h_only,
            cal.residuals.points_px,
            cal.residuals.points_mm,
            cal.residuals.inlier,
            radial=None,
        )
        assert only_field is not None
        only = summarize_residuals(only_field, h_only, cal.rotate_offset, radial=None)
        rows.append(
            {
                "slot": slot,
                "joint_far": joint.get("farDouble"),
                "only_far": only.get("farDouble"),
                "sector": joint.get("sectorWire"),
                "k1": cal.radial_k1,
                "k2": cal.radial_k2,
            }
        )

    # Print both fits for the ticket answer; assert joint meets the bar when radial engaged.
    print("empty-Board _ticket19/board joint vs H-only:")
    for row in rows:
        jf, of = row["joint_far"], row["only_far"]
        print(
            f"  cam{row['slot']}: joint far {jf} | H-only far {of} | "
            f"sectorWire {row['sector']} | k1={row['k1']:.4f} k2={row['k2']:.4f}"
        )

    joint_ok = True
    for row in rows:
        far = row["joint_far"]
        if far is None:
            joint_ok = False
            continue
        if float(far["rmsMm"]) > 2.0 or float(far["maxMm"]) > 4.0:
            joint_ok = False
    # Ticket: if empty-Board cannot meet 2/4, leave open — soft-fail with a clear message.
    if not joint_ok:
        pytest.xfail(
            "empty-Board capture joint far-double above 2 mm / 4 mm — ticket 22 stays open for live retune"
        )
