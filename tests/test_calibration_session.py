"""CalibrationSession: suggestions, rotate-20, Accept gate (ADR 0002), snapshot export."""

from __future__ import annotations

import numpy as np
import pytest
from madu_darts.calibration.synthetic import synthetic_camera

from madu_darts.board import point_mm_to_segment
from madu_darts.calibration import (
    AcceptBlocked,
    AutoFitError,
    AutoFitParams,
    CalibrationNotAccepted,
    CalibrationSession,
    CamCalibration,
    FitStatus,
)

T20_MM = (0.0, 103.4)


def _fake_suggester(results: dict[int, CamCalibration | str]):
    """Suggester returning canned results per slot; a str means AutoFitError(reason)."""
    calls: list[int] = []

    def suggester(image: np.ndarray, slot: int, params: AutoFitParams | None) -> CamCalibration:
        calls.append(slot)
        result = results[slot]
        if isinstance(result, str):
            raise AutoFitError(result)
        return result

    suggester.calls = calls  # type: ignore[attr-defined]
    return suggester


def _good(slot: int, rms: float = 0.5) -> CamCalibration:
    return CamCalibration(slot=slot, homography=np.eye(3), rms_mm=rms)


FRAMES = {0: np.zeros((2, 2, 3), np.uint8), 1: np.zeros((2, 2, 3), np.uint8), 2: np.zeros((2, 2, 3), np.uint8)}


# --- initial state / gate ---


def test_starts_unaccepted_with_no_fits() -> None:
    session = CalibrationSession()
    assert session.slots == (0, 1, 2)
    assert not session.accepted
    for slot in session.slots:
        assert session.get(slot).status is FitStatus.NONE
        assert session.error(slot) is None
    assert session.blockers() == ["cam 0: no Board-plane fit", "cam 1: no Board-plane fit", "cam 2: no Board-plane fit"]
    assert not session.can_accept()


def test_requires_at_least_one_slot() -> None:
    with pytest.raises(ValueError):
        CalibrationSession(slots=())


def test_unknown_slot_raises_key_error() -> None:
    session = CalibrationSession(slots=(0,))
    with pytest.raises(KeyError):
        session.get(7)
    with pytest.raises(KeyError):
        session.rotate_left(7)


def test_gate_blocks_before_accept() -> None:
    session = CalibrationSession(slots=(0,), suggester=_fake_suggester({0: _good(0)}))
    session.suggest_all(FRAMES)
    with pytest.raises(CalibrationNotAccepted):
        session.require_accepted()
    with pytest.raises(CalibrationNotAccepted):
        session.board_point(0, (10.0, 10.0))


# --- suggestions ---


def test_suggest_all_records_fits_and_failures() -> None:
    suggester = _fake_suggester({0: _good(0), 1: "ring size ratio off", 2: _good(2, rms=2.0)})
    session = CalibrationSession(suggester=suggester)
    result = session.suggest_all(FRAMES)

    assert suggester.calls == [0, 1, 2]
    assert result[0].status is FitStatus.PASS
    assert result[1].status is FitStatus.NONE and session.error(1) == "ring size ratio off"
    assert result[2].status is FitStatus.WARN
    assert session.blockers() == ["cam 1: ring size ratio off"]


def test_suggest_all_marks_missing_frames() -> None:
    session = CalibrationSession(suggester=_fake_suggester({0: _good(0), 1: _good(1), 2: _good(2)}))
    session.suggest_all({0: FRAMES[0], 2: FRAMES[2]})
    assert session.get(1).status is FitStatus.NONE
    assert session.error(1) == "no frame from camera"
    assert session.blockers() == ["cam 1: no frame from camera"]


def test_resuggest_clears_previous_error() -> None:
    results: dict[int, CamCalibration | str] = {0: "blank"}
    session = CalibrationSession(slots=(0,), suggester=_fake_suggester(results))
    session.suggest(0, FRAMES[0])
    assert session.error(0) == "blank"
    results[0] = _good(0)
    session.suggest(0, FRAMES[0])
    assert session.error(0) is None
    assert session.get(0).status is FitStatus.PASS


# --- accept / reset / revoke ---


def test_accept_requires_all_cams_pass_or_warn() -> None:
    session = CalibrationSession(suggester=_fake_suggester({0: _good(0), 1: "no board", 2: _good(2)}))
    session.suggest_all(FRAMES)
    with pytest.raises(AcceptBlocked) as info:
        session.accept()
    assert info.value.blockers == ["cam 1: no board"]
    assert not session.accepted


def test_accept_blocked_by_fail_status() -> None:
    session = CalibrationSession(slots=(0,), suggester=_fake_suggester({0: _good(0, rms=9.0)}))
    session.suggest_all(FRAMES)
    assert session.blockers() == ["cam 0: fit RMS 9.00 mm too high"]
    with pytest.raises(AcceptBlocked):
        session.accept()


def test_accept_then_gate_opens_and_reset_closes() -> None:
    session = CalibrationSession(suggester=_fake_suggester({0: _good(0), 1: _good(1, rms=2.5), 2: _good(2)}))
    session.suggest_all(FRAMES)
    assert session.can_accept()
    session.accept()
    assert session.accepted
    session.require_accepted()
    np.testing.assert_allclose(session.board_point(0, (3.0, 4.0)), (3.0, 4.0))

    session.reset()
    assert not session.accepted
    with pytest.raises(CalibrationNotAccepted):
        session.board_point(0, (3.0, 4.0))
    # Fits are kept after reset so the operator can re-Accept without recalibrating.
    assert session.get(1).status is FitStatus.WARN
    session.accept()
    assert session.accepted


@pytest.mark.parametrize("action", ["rotate_left", "rotate_right", "suggest_force"])
def test_any_cam_change_revokes_accept(action: str) -> None:
    session = CalibrationSession(suggester=_fake_suggester({0: _good(0), 1: _good(1), 2: _good(2)}))
    session.suggest_all(FRAMES)
    session.accept()
    if action == "suggest_force":
        # Bound cams ignore Auto unless force (Re-Auto / Reset bind).
        session.suggest(1, FRAMES[1], force=True)
    else:
        getattr(session, action)(1)
    assert not session.accepted


def test_bound_cam_skips_auto_until_force(tmp_path) -> None:
    store = tmp_path / "bind.json"
    session = CalibrationSession(
        suggester=_fake_suggester({0: _good(0), 1: _good(1), 2: _good(2)}),
        bind_store=store,
        offset_store=None,
    )
    session.suggest_all(FRAMES)
    session.accept()
    assert session.is_bound(1)
    h_before = session.get(1).homography.copy()

    suggester = _fake_suggester({0: _good(0, rms=0.4), 1: _good(1, rms=0.4), 2: _good(2, rms=0.4)})
    session2 = CalibrationSession(suggester=suggester, bind_store=store, offset_store=None)
    assert session2.load_saved_binds()
    assert session2.is_bound(1)
    session2.suggest(1, FRAMES[1])  # no force — keep saved bind
    assert suggester.calls == []
    np.testing.assert_allclose(session2.get(1).homography, h_before)
    session2.suggest(1, FRAMES[1], force=True)
    assert suggester.calls == [1]
    assert not session2.is_bound(1)


def test_nudge_pan_and_revert_auto() -> None:
    session = CalibrationSession(slots=(0,), suggester=_fake_suggester({0: _good(0)}))
    session.suggest(0, FRAMES[0])
    seed_h = session.get(0).homography.copy()
    session.nudge_pan(0, 5.0, -3.0)
    assert not np.allclose(session.get(0).homography, seed_h)
    session.revert_auto(0)
    np.testing.assert_allclose(session.get(0).homography, seed_h)


def test_rotate_requires_a_fit() -> None:
    session = CalibrationSession(slots=(0,))
    with pytest.raises(ValueError):
        session.rotate_left(0)


def test_rotate_left_right_update_offset() -> None:
    session = CalibrationSession(slots=(0,), suggester=_fake_suggester({0: _good(0)}))
    session.suggest_all(FRAMES)
    assert session.rotate_left(0).rotate_offset == 1
    assert session.rotate_left(0).rotate_offset == 2
    assert session.rotate_right(0).rotate_offset == 1
    assert session.get(0).rotate_offset == 1


# --- end to end with real auto-fit on synthetic cams ---


def test_real_autofit_rotate_accept_and_score_t20() -> None:
    cams = {
        0: synthetic_camera("fronto", rotation_sectors=0),
        1: synthetic_camera("tilt_left", rotation_sectors=2),
        2: synthetic_camera("tilt_right", rotation_sectors=10),
    }
    session = CalibrationSession()
    session.suggest_all({slot: cam.image for slot, cam in cams.items()})
    assert session.can_accept(), session.blockers()

    # Operator rotates each cam onto the physical 20 (even rotations: suggestion exact modulo arrows).
    for slot, cam in cams.items():
        steps = cam.correct_offset  # rotate_left adds +1 per press
        for _ in range(steps):
            session.rotate_left(slot)

    session.accept()
    assert session.accepted
    for slot, cam in cams.items():
        mm = session.board_point(slot, cam.pixel_of_mm(*T20_MM))
        assert point_mm_to_segment(*mm).name == "T20"

    ellipses = session.to_autodarts_ellipses()
    assert set(ellipses) == {"0", "1", "2"}
    assert "doubleOuter" in ellipses["0"] and "bull" in ellipses["0"]


# --- snapshot ---


def test_snapshot_is_json_shaped() -> None:
    import json

    session = CalibrationSession(suggester=_fake_suggester({0: _good(0), 1: "blank", 2: _good(2, rms=2.0)}))
    session.suggest_all(FRAMES)
    session.rotate_left(0)
    snap = session.snapshot()
    json.dumps(snap)  # must be serialisable

    assert snap["accepted"] is False
    assert snap["canAccept"] is False
    assert snap["blockers"] == ["cam 1: blank"]
    assert snap["acceptGate"] == {
        "farDoubleRmsMm": 5.5,
        "farDoubleMaxMm": 12.0,
        "warnFarDoubleRmsMm": 3.5,
        "warnFarDoubleMaxMm": 7.0,
    }
    assert snap["cams"]["0"] == {
        "status": "pass",
        "rotateOffset": 1,
        "rmsMm": 0.5,
        "nInliers": None,
        "nPoints": None,
        "coverage": None,
        "rmsDoubleMm": None,
        "rmsTrebleMm": None,
        "maxResidualMm": None,
        "maxDoubleMm": None,
        "maxTrebleMm": None,
        "farDouble": None,
        "nearDouble": None,
        "error": None,
        "hasFit": True,
        "bindLocked": False,
        "hasAutoSeed": True,
    }
    assert snap["cams"]["1"]["status"] == "none" and snap["cams"]["1"]["error"] == "blank"
    assert snap["cams"]["2"]["status"] == "warn"
    assert session.to_autodarts_ellipses() == {}  # fakes carry no rings
