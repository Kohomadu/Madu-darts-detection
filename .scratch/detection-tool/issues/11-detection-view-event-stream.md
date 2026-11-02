Status: ready-for-agent
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
