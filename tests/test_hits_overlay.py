"""Ticket 30: tip vote + fused Hit overlay on a cam image."""

from __future__ import annotations

import numpy as np

from madu_darts.board.geometry import DOUBLE_INNER_MM, ring_side_of_point
from madu_darts.calibration import CamCalibration
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits.hit import Hit, SlotVote
from madu_darts.hits.overlay import draw_hit_debug
from madu_darts.hits.tip import TipCandidate
from madu_darts.board.geometry import point_mm_to_segment


def _tip(slot: int, px: tuple[float, float]) -> TipCandidate:
    return TipCandidate(
        slot=slot,
        tip_px=(float(px[0]), float(px[1])),
        flight_px=(float(px[0]), float(px[1]) - 40.0),
        axis_dir=(0.0, 1.0),
        length_px=40.0,
        inlier_fraction=0.9,
        elongation=8.0,
        area_px=2000,
        confidence=0.9,
    )


def test_ring_side_inside_double_inner() -> None:
    side = ring_side_of_point(0.0, DOUBLE_INNER_MM - 1.0)
    assert side["wireMm"] == DOUBLE_INNER_MM
    assert side["side"] == "inside"


def test_draw_hit_debug_marks_used_and_dropped_votes() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0, homography=cam.truth_homography, rms_mm=0.5)
    used_px = cam.pixel_of_mm(0.0, 166.0)
    drop_px = cam.pixel_of_mm(20.0, 166.0)
    hit = Hit(
        x_mm=0.0,
        y_mm=166.0,
        segment=point_mm_to_segment(0.0, 166.0),
        method="Cam+1",
        confidence=0.9,
        t_mono=1.0,
        slot_votes=(
            SlotVote(slot=0, tip=_tip(0, tuple(used_px)), x_mm=0.0, y_mm=166.0, used=True),
            SlotVote(slot=1, tip=_tip(1, tuple(drop_px)), x_mm=20.0, y_mm=166.0, used=False),
        ),
        spread_mm=3.0,
    )
    before = cam.image.copy()
    out = draw_hit_debug(cam.image, slot=0, cal=cal, hits=[hit])
    assert out is not cam.image
    assert not np.array_equal(out, before)
    # Used vote drawn near tip; fused cross also near the same tip on this cam.
    uy, ux = int(round(used_px[1])), int(round(used_px[0]))
    patch = out[max(0, uy - 12) : uy + 12, max(0, ux - 12) : ux + 12]
    assert patch.size > 0
    # Green keep colour present somewhere in the patch.
    assert (patch[:, :, 1] > 150).any()


def test_draw_hit_debug_noop_without_fit() -> None:
    cam = synthetic_camera("fronto")
    cal = CamCalibration(slot=0)
    out = draw_hit_debug(cam.image, slot=0, cal=cal, hits=[])
    np.testing.assert_array_equal(out, cam.image)
