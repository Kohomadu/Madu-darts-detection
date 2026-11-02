Status: resolved
Type: task
Model: auto
Blocked by: 07

# Background model, motion gate, settle (`stableNumFrames`)

Per-cam “something changed and has stopped moving” detector, Autodarts-style. Output is a stream of **settled change events** (per cam, with the diff mask / ROI) that the tip localizer in 09 consumes. No Hits yet.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §4 steps 4–6; Vision tab semantics (Motion yellow → settling → stable) in §1.

## Scope

**Background / board model (step 4)**
- Per cam: empty-Board reference frame captured right after Accept (and on Reset / takeout finished).
- After a Hit is committed (09/10), fold the new dart into the background so the next dart diff only shows the new one.
- Expose `BoardModel.reference(slot)` and `BoardModel.commit(slot, frame)`.

**Motion gate (step 5)**
- Downscale ×4, grayscale, abs-diff vs background and vs previous frame, blur/threshold (start: kernel 3, threshold 16 — Autodarts defaults), morphological open, count changed pixels.
- States per cam: `idle` → `motion` (yellow) → `settling` → `stable`. Emit `motion_state` with `isMoving`, `isStable`, `frameCounts.{motion,stable}`, changed-pixel count, bounding box — mirror Autodarts’ debug fields so a Vision-like tile is cheap later.

**Settle (step 6)**
- Require `stableNumFrames` (default **3**) consecutive low-diff frames after motion before emitting a settled-change event; never act on the first motion frame.
- Hand/takeout heuristic hook: if the changed area is large / long-lived, classify as `takeout`-like and suppress (full takeout logic lives in 10).

**Integration**
- Runs inside `DetectionService` on the `FramePump` frames; gated by `CalibrationSession.require_accepted()` (no Accept → detector idle).
- Debug endpoint `GET /api/state/motion` (per-cam motion_state) and a tiny Vision-like tile per cam in the Calibration page (yellow/green/gray).

## Done when

- On replay of the 07 recording, every Autodarts dart produces exactly one settled-change event per visible cam within ~0.5 s of Autodarts’ detection time; no events during still periods; takeout produces 0 settled-change events (suppressed).
- Thresholds/scale/`stableNumFrames` live in a config dataclass and in `GET /api/config`.
- Unit tests on synthetic frame sequences (step change, flicker, slow hand) + replay-based test.

## Answer

Shipped Autodarts-shaped background / motion / settle; 07 recording replay meets the settle gate; tip localizer (09) can consume `SettledChange` events.

### Code
- `madu_darts.motion`: `MotionConfig` (Autodarts defaults: scale 4, kernel 3, threshold 16, `stableNumFrames` 3), `BoardModel.reference` / `capture` / `commit`, `MotionGate` (`idle → motion → settling → stable`) emitting `SettledChange` (mask + bbox + changed pixels).
- `DetectionService`: `FramePump` listener feeds the gate; armed on Accept (`arm_motion_from_latest`), parked on Reset / revoked Accept (`sync_motion_with_calibration`).
- API: `GET /api/state/motion`, `GET /api/config` (motion knobs). Calibration page: per-cam Vision-like tile (gray idle / yellow motion|settling / green stable).
- `MotionGate.flush()` pads truncated recording windows with a frozen last frame so settle can complete when the 07 ring buffer ends at Autodarts’ detection time.

### Verification
- Synthetic: step change → one settle after N quiet frames; flicker ignored; large/long motion suppressed as takeout; commit hides prior dart.
- Replay of [2026-11-02T08-07-55Z](../captures/recordings/2026-11-02T08-07-55Z/): **24 darts × 3 cams → exactly one settled-change each**, within 0.5 s of Autodarts `t_mono`; still prefixes emit nothing.
- Full suite: **237 passed**.
