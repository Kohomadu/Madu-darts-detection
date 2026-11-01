Status: resolved
Type: research
Model: premium

# Research three-cam dart detection approaches

Investigate open / documented three-camera steel-tip dart scoring systems (Autodarts-class peers). Capture how they calibrate, detect stuck darts, map to Segments, expose local APIs, and what licenses allow. Do not rely on Autodarts cloud API docs as a dependency path.

## Answer

Autodarts-class scorers calibrate each camera to a Board plane (homography and/or PnP), wait for stick-and-settle after motion, localize tips, fuse views, then map polar `(r, θ)` to Segments using WDF radii and the clockwise 20-sector clock. Autodarts is UX-only for Madu: proprietary Detection, account required, and v2 throw events are cloud WebSocket—not a local scoring dependency. Reuse **ideas** from Autodarts / ARU-DART / A-Dartment; reuse **code** from Apache-2.0 `lksmlr/autodarts` and MIT Dart Vader; treat OpenDartboard’s local WS API as a shape reference but note GPL-3.0 if copying code. ARU-DART has no LICENSE → do not copy source. Full write-up: [research-three-cam-approaches.md](../research-three-cam-approaches.md).
