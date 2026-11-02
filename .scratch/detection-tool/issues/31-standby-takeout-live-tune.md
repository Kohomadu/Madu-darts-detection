Status: needs-triage
Type: task
Model: auto
Blocked by: 10, 16, 11

# Live-tune takeout / standby on real hands

Recordings (07) have no hand frames; `takeoutStarted` latency and `is_takeout` (≥ 2500 px × 12 frames) are still Fog. Tune on the live Board with real takeouts and idle standby.

## Scope

1. Capture several hand-takeout visits (with `/api/captures` + history events).
2. Adjust takeout motion / quiet / soft-empty knobs if false takeouts or stuck `takeoutInProgress` appear.
3. Confirm standby after idle and wakeup on approach; rename Madu-only events only if Autodarts strings are now known.
4. Document recommended config in Answer + `GET /api/config` defaults if changed.

## Done when

- ≥ 5 real takeouts seal as `takeoutFinished` without Reset.
- No systematic false takeout on settle-only Turns.
- Standby/wakeup checked once on the Board.
