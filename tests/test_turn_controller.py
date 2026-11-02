"""TurnController on three synthetic cams: cap 3, bounce-out, takeout clear, reset, start/stop, standby."""

from __future__ import annotations

import cv2
import numpy as np

from madu_darts.calibration.homography import apply_homography
from madu_darts.calibration.synthetic import synthetic_camera
from madu_darts.hits import FusionConfig, HitDetector, TipConfig
from madu_darts.motion import BoardModel, MotionConfig, MotionGate
from madu_darts.turn import TurnConfig, TurnController, TurnEvent, TurnStatus
from tests.test_hits_tip_fusion import draw_dart

CAMS = {0: synthetic_camera("fronto"), 1: synthetic_camera("tilt_left"), 2: synthetic_camera("tilt_right")}
SLOTS = (0, 1, 2)
T20 = (0.0, 103.4)
S11 = (-130.0, 0.0)
D16 = (-135.0, -98.0)
S6 = (120.0, 0.0)
ANGLES = {T20: 5.0, S11: 1.0, D16: -3.0, S6: -7.0}  # per dart, so a removal only changes that dart


def _board_point(slot: int, px: tuple[float, float]) -> np.ndarray:
    return apply_homography(CAMS[slot].truth_homography, px)


class Sim:
    """Frame generator + controller harness with a monotonic clock."""

    def __init__(self, turn: TurnConfig | None = None, motion: MotionConfig | None = None) -> None:
        self.motion = motion or MotionConfig()
        self.board = BoardModel(SLOTS)
        self.gate = MotionGate(self.board, self.motion, slots=SLOTS)
        self.detector = HitDetector(
            _board_point,
            self.board,
            slots=SLOTS,
            motion_scale=self.motion.scale,
            tip_config=TipConfig(),
            fusion_config=FusionConfig(collect_window_s=0.4),
        )
        self.ctrl = TurnController(self.board, self.gate, self.detector, config=turn or TurnConfig(), slots=SLOTS)
        self.t = 0.0
        self.transitions = []
        self.ctrl.start(self.frames([]), self.t)

    # --- frames ---

    def frames(self, darts: list[tuple[float, float]], *, shift_px: float = 0.0, brightness: int = 0) -> dict[int, np.ndarray]:
        out = {}
        for slot, cam in CAMS.items():
            img = cam.image
            for target in darts:
                px = cam.pixel_of_mm(*target) + np.array([0.0, -shift_px])
                img = draw_dart(img, px, angle_deg=ANGLES[target])
            if brightness:
                img = cv2.add(img, np.full_like(img, brightness))
            out[slot] = img
        return out

    def hand_frames(self, darts: list[tuple[float, float]], n: int = 16) -> list[dict[int, np.ndarray]]:
        base = self.frames(darts)
        seq = []
        for i in range(n):
            frames = {}
            for slot, img in base.items():
                f = img.copy()
                cx = int(200 + (900 * i) / max(1, n - 1))
                cv2.circle(f, (cx, 360), 150, (60, 40, 30), -1)
                frames[slot] = f
            seq.append(frames)
        return seq

    # --- feeding ---

    def feed(self, frames: dict[int, np.ndarray], n: int = 1, dt: float = 0.1) -> list:
        out = []
        for _ in range(n):
            self.t += dt
            out.extend(self.ctrl.process(frames, self.t))
        self.transitions.extend(out)
        return out

    def feed_seq(self, seq: list[dict[int, np.ndarray]], dt: float = 0.1) -> list:
        out = []
        for frames in seq:
            out.extend(self.feed(frames, dt=dt))
        return out

    def throw(self, stuck: list[tuple[float, float]]) -> list:
        """Approach frame (dart still moving) then the stuck Board held for 8 frames."""
        out = self.feed(self.frames(stuck, shift_px=30.0))
        out += self.feed(self.frames(stuck), n=8)
        return out

    @property
    def names(self) -> list[str]:
        return [h.autodarts_segment_name for h in self.ctrl.hits]


def _seq(transitions) -> list[tuple[str, str, int]]:
    return [(tr.status.value, tr.event.value, tr.num_hits) for tr in transitions]


# --- commit / cap ---


def test_three_hits_then_takeout_status_and_fourth_is_ignored() -> None:
    sim = Sim()
    assert sim.ctrl.status == TurnStatus.THROW and sim.ctrl.event == TurnEvent.STARTED

    assert _seq(sim.throw([T20])) == [("throw", "throwDetected", 1)]
    assert _seq(sim.throw([T20, S11])) == [("throw", "throwDetected", 2)]
    assert _seq(sim.throw([T20, S11, D16])) == [("takeout", "throwDetected", 3)]
    assert sim.names == ["T20", "S11", "D16"]

    # Fourth dart while three are stuck: never scored, flagged, folded into the background.
    assert sim.throw([T20, S11, D16, S6]) == []
    snap = sim.ctrl.snapshot()
    assert len(snap.hits) == 3 and snap.ignored_changes >= 1 and snap.status == TurnStatus.TAKEOUT
    state = snap.to_autodarts_state()
    assert set(state) == {"connected", "running", "status", "event", "throws"}
    assert [t["segmentName"] for t in state["throws"]] == ["T20", "S11", "D16"]


# --- bounce-out ---


def test_bounce_out_retracts_last_hit_without_hand() -> None:
    sim = Sim()
    sim.throw([T20])
    sim.throw([T20, S11])
    assert sim.names == ["T20", "S11"]

    # Second dart falls out: footprint reverts to the pre-commit background, no hand in view.
    out = sim.feed(sim.frames([T20]), n=8)
    assert ("throw", "bounceOut", 1) in _seq(out)
    assert sim.names == ["T20"]
    snap = sim.ctrl.snapshot()
    assert len(snap.bounce_outs) == 1 and snap.bounce_outs[0].hit.autodarts_segment_name == "S11"
    # Other cams' settles for the same fall were absorbed — nothing new was scored.
    assert all(tr.event != TurnEvent.THROW_DETECTED for tr in out)

    # Board is consistent again: a replacement dart is scored normally.
    assert _seq(sim.throw([T20, D16])) == [("throw", "throwDetected", 2)]
    assert sim.names == ["T20", "D16"]


def test_bounce_out_of_earlier_dart_keeps_later_ones() -> None:
    sim = Sim()
    sim.throw([T20])
    sim.throw([T20, S6])
    sim.throw([T20, S6, D16])
    assert sim.ctrl.status == TurnStatus.TAKEOUT
    out = sim.feed(sim.frames([S6, D16]), n=8)  # the first dart (T20) drops
    assert ("throw", "bounceOut", 2) in _seq(out)
    assert sim.names == ["S6", "D16"]
    assert sim.ctrl.status == TurnStatus.THROW  # room for one more


# --- takeout ---


def test_hand_takeout_clears_turn_and_recaptures_empty_board() -> None:
    sim = Sim()
    for darts in ([T20], [T20, S11], [T20, S11, D16]):
        sim.throw(darts)
    assert sim.ctrl.status == TurnStatus.TAKEOUT

    out = sim.feed_seq(sim.hand_frames([T20, S11, D16]))
    assert ("takeoutInProgress", "takeoutStarted", 3) in _seq(out)
    assert sim.names == ["T20", "S11", "D16"]  # throws retained while the hand is in view

    out = sim.feed(sim.frames([]), n=8)
    assert _seq(out)[-1] == ("throw", "takeoutFinished", 0)
    assert sim.ctrl.hits == ()

    # Next Turn works against the re-captured empty Board.
    assert _seq(sim.throw([S6])) == [("throw", "throwDetected", 1)]
    assert sim.names == ["S6"]


def test_partial_takeout_waits_until_board_is_empty() -> None:
    sim = Sim()
    sim.throw([T20])
    sim.throw([T20, S11])
    sim.feed_seq(sim.hand_frames([T20, S11]))
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS
    sim.feed(sim.frames([S11]), n=8)  # one dart still in
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS and len(sim.ctrl.hits) == 2
    out = sim.feed(sim.frames([]), n=8)
    assert _seq(out)[-1] == ("throw", "takeoutFinished", 0)


def test_zero_dart_false_takeout_recovers_by_adopting_frames() -> None:
    sim = Sim(TurnConfig(false_takeout_recover_s=1.0))
    out = sim.feed_seq(sim.hand_frames([]))
    assert ("takeoutInProgress", "takeoutStarted", 0) in _seq(out)
    # Lighting changed under the hand: Board is not "empty" vs the old reference.
    bright = sim.frames([], brightness=40)
    out = sim.feed(bright, n=15)
    assert _seq(out)[-1] == ("throw", "takeoutFinished", 0)
    # The brighter Board is now the reference → a dart on it is detected.
    sim.feed(sim.frames([T20], shift_px=30.0, brightness=40))
    out = sim.feed(sim.frames([T20], brightness=40), n=8)
    assert ("throw", "throwDetected", 1) in _seq(out)


def test_takeout_finishes_via_soft_empty_and_darts_removed() -> None:
    """Strict emptyMax fails when Accept refs are stale; soft + dart-gone still clears (ticket 16)."""
    sim = Sim(
        TurnConfig(
            empty_max_changed_pixels=60,
            empty_soft_max_changed_pixels=5000,
            dart_removed_min_pixels=50,
            takeout_force_finish_s=60.0,
        )
    )
    for darts in ([T20], [T20, S11], [T20, S11, D16]):
        sim.throw(darts)
    sim.feed_seq(sim.hand_frames([T20, S11, D16]))
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS

    # Stale Accept refs (still look like a full Board) → strict empty never matches.
    stale = sim.frames([T20, S11, D16])
    sim.ctrl._empty_refs = {s: stale[s].copy() for s in SLOTS}
    empty = sim.frames([])
    dbg = sim.ctrl.empty_debug(empty)
    assert max(dbg["emptyDiffPx"].values()) > 60
    assert min(dbg["takeoutFullDiffPx"].values()) >= 50

    out = sim.feed(empty, n=8)
    assert _seq(out)[-1] == ("throw", "takeoutFinished", 0)
    assert sim.ctrl.hits == ()


def test_takeout_soft_force_when_nearly_empty_but_strict_fails() -> None:
    """Soft empty held for takeout_force_finish_s finishes even if dart-removed is inconclusive."""
    sim = Sim(
        TurnConfig(
            empty_max_changed_pixels=5,  # impossibly tight vs any residual
            empty_soft_max_changed_pixels=5000,
            dart_removed_min_pixels=10_000,  # never “removed” by pixel count
            takeout_force_finish_s=0.5,
            quiet_frames=2,
        )
    )
    for darts in ([T20], [T20, S11], [T20, S11, D16]):
        sim.throw(darts)
    sim.feed_seq(sim.hand_frames([T20, S11, D16]))
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS

    empty = sim.frames([])
    # Quiet but not long enough yet.
    sim.feed(empty, n=3, dt=0.1)
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS
    out = sim.feed(empty, n=8, dt=0.1)  # ≥0.5 s since takeoutStarted
    assert _seq(out)[-1] == ("throw", "takeoutFinished", 0)


def test_takeout_does_not_force_while_darts_still_in() -> None:
    sim = Sim(TurnConfig(takeout_force_finish_s=0.3, empty_soft_max_changed_pixels=200))
    for darts in ([T20], [T20, S11], [T20, S11, D16]):
        sim.throw(darts)
    sim.feed_seq(sim.hand_frames([T20, S11, D16]))
    # Hand left but darts remain — soft empty must fail; no finish after timeout.
    out = sim.feed(sim.frames([T20, S11, D16]), n=20, dt=0.1)
    assert sim.ctrl.status == TurnStatus.TAKEOUT_IN_PROGRESS
    assert all(tr.event != TurnEvent.TAKEOUT_FINISHED for tr in out)


# --- operator controls ---


def test_reset_mid_turn_clears_hits_keeps_running() -> None:
    sim = Sim()
    sim.throw([T20])
    sim.throw([T20, S11])
    tr = sim.ctrl.reset(sim.frames([]), sim.t)
    assert (tr.status, tr.event, tr.num_hits) == (TurnStatus.THROW, TurnEvent.RESET, 0)
    assert sim.ctrl.running and sim.ctrl.hits == () and sim.gate.enabled
    assert _seq(sim.throw([D16])) == [("throw", "throwDetected", 1)]


def test_stop_parks_detection_and_start_resumes() -> None:
    sim = Sim()
    sim.throw([T20])
    tr = sim.ctrl.stop(sim.t)
    assert tr.event == TurnEvent.STOPPED and not sim.ctrl.running and not sim.gate.enabled
    assert sim.ctrl.hits != ()  # visible until Start / Reset
    assert sim.throw([T20, S11]) == []  # ignored while stopped
    tr = sim.ctrl.start(sim.frames([]), sim.t)
    assert tr.event == TurnEvent.STARTED and sim.ctrl.hits == () and sim.ctrl.running
    assert _seq(sim.throw([S6])) == [("throw", "throwDetected", 1)]


def test_standby_after_idle_and_wakeup_on_motion() -> None:
    sim = Sim(TurnConfig(standby_minutes=0.01, standby_poll_s=0.2))  # 0.6 s
    out = sim.feed(sim.frames([]), n=10)  # 1.0 s quiet
    assert _seq(out) == [("throw", "standby", 0)]
    assert sim.ctrl.standby and not sim.gate.enabled
    assert sim.feed(sim.frames([]), n=5) == []  # still asleep, polled sparsely

    out = sim.feed(sim.frames([T20]), n=3)
    assert _seq(out)[0] == ("throw", "wakeup", 0)
    assert not sim.ctrl.standby and sim.gate.enabled
    out += sim.feed(sim.frames([T20]), n=8)
    assert ("throw", "throwDetected", 1) in _seq(out)


def test_snapshot_api_shape() -> None:
    sim = Sim()
    sim.throw([T20])
    api = sim.ctrl.snapshot().to_api()
    assert api["running"] is True and api["status"] == "throw" and api["event"] == "throwDetected"
    assert api["numThrows"] == 1 and api["throws"][0]["segmentName"] == "T20"
    assert api["hits"][0]["madu"]["segment"] == "T20"
    assert api["standby"] is False and api["bounceOuts"] == [] and api["version"] >= 2
