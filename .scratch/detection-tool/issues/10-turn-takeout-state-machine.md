Status: ready-for-agent
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
