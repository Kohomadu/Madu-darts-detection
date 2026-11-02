Status: resolved
Type: research
Model: human+auto
Blocked by:

# Confirm live throw schema on Autodarts 2.1.0

Fog from [05](05-autodarts-behavioural-study.md): board was in takeout with `throws: []` during probe. During an active visit with stuck darts, check whether `/api/state.throws` still populates locally on 2.1.0 (and whether `ws://…/api/events` pushes `state` with throw objects), or if throw payloads are cloud-only as inventwo reports.

## Why

Madu owns its Hit stream either way; this is only to know how closely we can compare against the live Board during development.

## How

Throw 1–3 darts on the Autodarts Board, then capture `GET /api/state` (and optionally a short `/api/events` listen). Append results under Answer; set Status resolved.

## Comments

- 2026-11-01: Claimed and probed from Windows. Madu Calibration on `:3181` is up (accepted). **Autodarts `:3180` connection refused** — Detection/Desktop not reachable. Need Autodarts started on the Board, then 1–3 stuck throws while the agent polls `/api/state` + WS.
- 2026-11-02: Autodarts `:3180` up; live 3-dart visit captured.

## Answer

**Local throw data still works on Autodarts 2.1.0.** inventwo’s “v2+ cloud-only throws” claim does **not** hold for this Board build.

### Evidence (2026-11-02, `100.118.240.5:3180`)

- Idle/start: `GET /api/state` → `status:"throw"`, `event:"started"`, `throws:[]`.
- After each stuck dart, both HTTP and WS updated with the **full visit-so-far**:
  - `GET /api/state` non-empty `throws[]`
  - `ws://…/api/events` messages `{type:"state", data:{…, throws:[…]}}`
- Visit captured: **S18** (SingleOuter) → **S20** (SingleInner) → **S14** (SingleInner); after dart 3 `status` became `"takeout"` while `event` stayed `"throwDetected"`.
- `numThrows` was **absent/null** on this build (unlike 1.0.7 captures).
- Artifacts: [captures/06-live-throw-2026-11-02/](../captures/06-live-throw-2026-11-02/).

### Live 2.1.0 throw object (flat, not nested `coords`/`segment`)

```json
{
  "bed": "SingleOuter",
  "bouncer": false,
  "coordsX": 0.4027691926180652,
  "coordsY": 0.7505815104550483,
  "failed": false,
  "method": "UnanimousCam",
  "multiplier": 1,
  "segmentName": "S18",
  "segmentNumber": 18
}
```

Implication for Madu: we can poll/compare against local Autodarts state during development; prefer emitting an Autodarts-shaped visit stream ourselves, accepting either nested 1.0.7 or flat 2.1 field layouts when reading peers.
