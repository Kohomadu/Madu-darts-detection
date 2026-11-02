Status: resolved
Type: task
Model: auto
Blocked by: 09

# Turn state machine: Hit commit, cap 3, bounce-out, takeout clear

Own the visit lifecycle around Hits, matching Autodarts `status` / `event` semantics so the Detection view and stream (11) are drop-in comparable.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §4 steps 10–11 and 14; live 2.1 status/event strings in §2.2 (`throw` / `takeout` / `takeoutInProgress`, `started` / `throwDetected` / `takeoutStarted` / `takeoutFinished`). Glossary: **Turn**, **Hit**, bounce-out ≠ Hit.

## Scope

- States: `throw` (may throw) → `throwDetected` on each committed Hit → after 3 Hits status `takeout` → hand detected `takeoutInProgress` / `takeoutStarted` → Board empty `takeoutFinished` → back to `throw`, Hit strip cleared.
- Commit a Hit only after settle + fusion success; fold it into the background model (08).
- Cap 3 Hits per Turn; further settled changes while 3 are stuck are ignored (or flagged) until takeout.
- **Bounce-out / fall**: a committed dart whose footprint disappears without a hand present → retract the Hit (Movement **red** semantics); never scored as stuck.
- **Takeout**: large/long change (hand) → `takeoutInProgress`; when the diff vs the empty-Board reference is quiet again and no dart footprints remain → `takeoutFinished`, reset background to empty reference.
- Zero-dart false takeout recovery and explicit `POST /api/reset` (clears Turn, keeps Calibration), `POST /api/start|stop` (detector on/off), standby minutes (step 14) as config.

## Done when

- Replay of the 07 recording reproduces Autodarts’ `throws[]` growth per visit and empties on takeout; status/event sequence matches per visit (table in the replay output).
- Unit tests for: 3-cap, bounce-out retraction, takeout clear, reset mid-Turn, standby.

## Answer

Resolved 2026-11-02. `madu_darts.turn` owns the visit lifecycle; `MotionGate` (08) and `HitDetector` (09) stay Turn-agnostic.

### Code

- `src/madu_darts/turn/config.py` — `TurnConfig`: `max_hits 3`, `empty_max_changed_pixels 60` (motion scale; one stuck dart on the 07 recording is 120–720 px per cam, three darts 580–1550, empty-Board drift between visits 0), `quiet_frames 3`, `revert_ratio 0.25`, `retraction_window_s 1.0`, `false_takeout_recover_s 3.0`, `standby_minutes 60` (Autodarts `cam.standbyMinutes`), `standby_poll_s 1.0`. `to_api()` → `GET /api/config.turn`.
- `src/madu_darts/turn/types.py` — `TurnStatus` (`throw` / `takeout` / `takeoutInProgress`), `TurnEvent` (2.1 strings `started`, `stopped`, `throwDetected`, `takeoutStarted`, `takeoutFinished`, `calibrationFinished` + Madu extensions `reset`, `bounceOut`, `standby`, `wakeup`), `BounceOut`, `TurnTransition`, `TurnSnapshot.to_autodarts_state()` → `{connected, running, status, event, throws}` (ADR 0004 core; 11 merges `calibration`).
- `src/madu_darts/turn/controller.py` — `TurnController(board_model, gate, detector)`: `start(frames, t)` (Board taken as empty), `stop(t)`, `reset(frames, t)`, `process(frames, t) -> transitions`, `flush()` (replay), `snapshot()`, `history`, `drain_transitions()`.
  - **Commit**: settled change → tip → fusion → Hit; snapshot of the pre-commit references + per-cam footprint bbox kept per Hit. Third Hit → `status: takeout`.
  - **Cap 3**: further settled changes are counted (`ignoredChanges`) and folded into the background, never scored.
  - **Bounce-out**: a settled change overlapping a committed footprint whose ROI diff vs the *pre-commit* reference is ≤ `revert_ratio` × the diff vs the current reference → the dart is gone → Hit retracted (`event: bounceOut`, Movement red). Works for the last dart and for an earlier dart knocked out while later ones stay. Other cams' settles for the same fall are absorbed within `retraction_window_s`.
  - **Takeout**: any cam `is_takeout` (large + long change, 08 heuristic) → `takeoutInProgress` / `takeoutStarted`, throws retained, settles ignored. Once no cam moves for `quiet_frames` and every cam's diff vs the *empty-Board* reference ≤ 60 px → `takeoutFinished`, Turn cleared, current frames adopted as the new empty reference (absorbs lighting drift), gate/detector reset, `status: throw`. Partial takeout (one dart left) keeps waiting. Two or more darts vanishing with no hand classified (hand too quick, or a jump-cut in replay) is treated as a takeout, not a bounce-out.
  - **Zero-dart false takeout**: hand seen with nothing stuck, quiet for `false_takeout_recover_s` but not “empty” vs the old reference → current frames adopted as empty, `takeoutFinished`. `POST /api/reset` does the same immediately.
  - **Standby**: no motion for `standby_minutes` → gate parked, frames sampled every `standby_poll_s`; motion vs the standby frame → `wakeup`, gate re-armed.
- `src/madu_darts/server/service.py` — `DetectionService.turn`; pump → `turn.process`; Accept → `turn.start`; `start_detection` / `stop_detection` / `reset_turn` / `turn_state`; Calibration reset stops + clears the Turn.
- `src/madu_darts/server/app.py` — `GET /api/state/turn` (and `/api/state/hits` alias), `PUT|POST /api/start` (409 until Accepted), `PUT|POST /api/stop`, `POST /api/reset` — Autodarts' documented control routes.
- `src/madu_darts/replay/madu_pipeline.py` — `MaduPipeline` now runs a `TurnController` per visit; `VisitTrace` + `format_turn_table`; `madu-darts replay` prints the Turn table after the accuracy table. The recording holds no takeout frames (windows end at Autodarts' detection), so the takeout is exercised on the *next* visit's real empty-Board frames.

### Replay of the 07 recording (`--rotate-offsets 10,4,16`)

| V | Autodarts at close | AD | Madu | ok | Madu sequence |
|---|---|---|---|---|---|
| 0–7 | `takeout` / `throwDetected` | 3 | 3 | Y | `throw/started → throw/throwDetected(1) → throw/throwDetected(2) → takeout/throwDetected(3) → takeoutInProgress/takeoutStarted → throw/takeoutFinished` |

8/8 visits match status/event + `throws[]` growth and clear on takeout. Hit accuracy unchanged from 09 (20/24, median 3.76 mm) — the controller only sequences decisions.

### Verification

- `tests/test_turn_controller.py` (10, synthetic three-cam harness): 3 Hits → `takeout`, 4th ignored; bounce-out of the last dart; bounce-out of an earlier dart keeps the later ones; hand takeout clears and re-captures the empty Board; partial takeout waits; zero-dart false takeout recovers under a lighting change; reset mid-Turn; stop/start; standby + wakeup; API shape.
- `tests/test_hits_replay.py::test_turn_sequence_matches_autodarts_per_visit` (skips without JPEGs).
- `tests/test_server.py::test_turn_controls_and_state_endpoints`.
- Full suite: 266 passed.

### Open

- No real hand/takeout frames exist in any recording yet (the 07 recorder closes the visit at Autodarts' detection). Live validation of `takeoutStarted` timing vs Autodarts' `:3180` is the first thing to do in 11's side-by-side.
- Event names `reset` / `bounceOut` / `standby` / `wakeup` are Madu extensions; swap to Autodarts strings if 11's live comparison reveals them.
