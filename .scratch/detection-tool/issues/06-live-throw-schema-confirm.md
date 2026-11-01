Status: needs-info
Type: research
Model: human+auto
Blocked by:

# Confirm live throw schema on Autodarts 2.1.0

Fog from [05](05-autodarts-behavioural-study.md): board was in takeout with `throws: []` during probe. During an active visit with stuck darts, check whether `/api/state.throws` still populates locally on 2.1.0 (and whether `ws://…/api/events` pushes `state` with throw objects), or if throw payloads are cloud-only as inventwo reports.

## Why

Madu owns its Hit stream either way; this is only to know how closely we can compare against the live Board during development.

## How

Throw 1–3 darts on the Autodarts Board, then capture `GET /api/state` (and optionally a short `/api/events` listen). Append results under Answer; set Status resolved.
