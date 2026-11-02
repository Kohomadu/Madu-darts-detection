Status: ready-for-human
Type: task
Model: auto
Blocked by: 10

# Detection view + Madu-owned event stream

Operator surface for live play and the local, Autodarts-2.1-shaped state stream that a future match UI consumes. Same FastAPI app on `:3181` (ADR 0003), second page.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §4 steps 12–13; ADR 0004 (stream shape); Glossary **Detection view**.

## Scope

**Event stream (step 13)**
- `GET /api/state` grows to the Autodarts 2.1 shape: `{connected, running, status, event, throws:[{bed, bouncer, coordsX, coordsY, failed, method, multiplier, segmentName, segmentNumber}], calibration:{…}}` (keep existing `calibration` block).
- `ws://…:3181/api/events` pushes `{type:"state", data:{…}}` on every change (full visit-so-far, like Autodarts). Optional `{type:"motion", data:motion_state}` debug channel.
- Produced entirely by Madu (10); Autodarts is never read in the product path (ADR 0001).

**Detection view (step 12)**
- Page at `/detection`: virtual Board SVG with detected dart dots, top Hit strip (≤ 3 Segment labels for the current Turn), status pill (`throw` / `takeout` …), controls **Calibrate** (→ Calibration page), **Reset**, **Stop/Start**.
- Vision-like diagnostics tile per cam (motion yellow/stable green/idle gray) from 08.
- Driven by the WS stream; falls back to polling `/api/state`.

## Done when

- Live on the Board: throw 3 darts → strip fills with Madu Segments and dots land on the virtual Board; takeout clears it; `ws` clients receive the same sequence Autodarts emits for the same visit (compare side by side with `:3180`).
- Server tests for `/api/state` shape + WS push; a schema test asserting field-level compatibility with the 06 capture.

## Answer

Implemented 2026-11-02; code complete and verified end-to-end on synthetic cams. **Left for a human: the live Board side-by-side with `:3180`** (needs the physical Board + Autodarts running) — procedure below. Set back to `resolved` once that run is logged in `## Comments`.

### Event stream (step 13)

- `GET /api/state` now returns the Autodarts 2.1 shape: `{connected, running, status, event, throws:[{bed, bouncer, coordsX, coordsY, failed, method, multiplier, segmentName, segmentNumber}]}` plus Madu blocks `calibration` (the former Calibration snapshot, unchanged), `cameras` `{open, error}` and `madu` `{numThrows, standby, pending, bounceOuts, ignoredChanges, hits[], calibrationAccepted, version}`. The old `status: ready|calibrationRequired` is gone — `status` is the Turn status; "calibration required" is `running: false` + `madu.calibrationAccepted: false`.
- `ws://…:3181/api/events` → `{type:"state", data:{…full /api/state…}}` on connect and on every change. `?motion=1` adds `{type:"motion", data:motion_state}` at ~5 Hz.
- No transition is coalesced: `TurnController.on_transition` snapshots the full state inside the controller lock into `DetectionService` (`publish_state` → seq-numbered log, `wait_for_states` on a `Condition`); the WS handler drains everything newer than its last seq. Calibration mutations (`rotate`, `auto`, `accept`, `reset`) publish too; identical consecutive states are deduped. Produced entirely by Madu (ADR 0001 / 0004).

### Detection view (step 12)

- `/detection` (`server/static/detection.html`): virtual Board SVG (WDF radii, 20 up, clockwise) with numbered dart dots at `coords × 170 mm`; top Hit strip (3 slots: Segment, bed, method); status pill (`throw` green, `takeout*` yellow, `stopped` red, `standby` blue, `calibration required`); **Calibrate** → `/`, **Start/Stop** → `PUT /api/start|stop`, **Reset** → `POST /api/reset`; per-cam Vision tiles (idle gray / motion+settling yellow / stable green / takeout red) from `motion_state`; event log of status/event/throws changes. WS-driven, falls back to 500 ms polling of `/api/state` + `/api/state/motion` and reconnects every 3 s. Calibration page links to it.
- `madu-darts serve --synthetic-throws`: `SyntheticIngest(script=True)` loops a visit (T20 @3 s, S11 @6 s, D16 @9 s, hand sweep 11.5–12.7 s, empty, period 16 s) so the view and stream run without hardware.

### Verification

- `tests/test_server.py`: `test_api_state_is_field_compatible_with_autodarts_06_capture` (top-level keys ⊇ `state_with_throws.json`, extras exactly `{calibration, cameras, madu}`, WS envelope `{type, data}` = `ws_state_3darts.json`); `test_ws_events_push_each_turn_change_end_to_end` (dart drawn into the fake cams → pump → gate → tips → fusion → Turn → WS `throwDetected` with a throw whose keys equal the capture's, `T20`/`Triple`/×3; `?motion=1` channel; dart removed → `bounceOut` with empty `throws`; `PUT /api/stop` → `stopped` on the stream); `test_detection_view_is_served`. `tests/test_synthetic_ingest.py`, `tests/test_cli.py`. Full suite: 270 passed.
- Browser (`serve --synthetic-throws`, Calibration accepted on an empty Board): pill `throw`, strip `T20 Triple · UnanimousCam → S11 → D16`, dots at the right Board positions, `takeout → takeoutInProgress/takeoutStarted → throw/takeoutFinished` clearing the strip, tiles yellow→green, `live (ws)`; Stop/Start/Reset buttons drive the pill and the `event` field.
- Observed while testing: **Start / Reset / Accept take the current Board as empty.** Pressing them with darts stuck poisons the empty reference until the next `Reset` on an empty Board (the Turn then sits in `takeoutInProgress` because the Board never looks empty). Same semantic as Autodarts' "reset recovers a false takeout"; button tooltips say so. Worth a guard later (refuse Start when the gate sees a dart-sized diff? needs the empty reference first — chicken-and-egg; leave for the live run).

### Live check still to do (human, on the Board)

1. `madu-darts serve` on the Board host; Calibrate + Accept on an **empty** Board; open `/detection`.
2. In a second tab/script, `websocat ws://<board>:3181/api/events` and `websocat ws://<board>:3180/api/events` (Autodarts).
3. Throw 3 darts, take them out. Expect on both: `throw/throwDetected(1,2)`, `takeout/throwDetected(3)`, `takeoutInProgress/takeoutStarted`, `throw/takeoutFinished` (Autodarts emits the last two as it does; note any extra intermediate states it sends and the `takeoutStarted` latency vs Madu — that is the 10 Fog item).
4. Record a session with `madu-darts record --frames autodarts` in parallel so the first **hand frames** land in a recording (10's open point).
