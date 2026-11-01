Status: resolved
Type: task
Model: auto
Blocked by:

# Camera ingest (3× USB)

Capture three USB webcam streams with configurable resolution/FPS (Autodarts defaults: 1280×720@30). Prefer USB **location** identity (this Board: `7.2`/`7.3`/`7.4`), not index/serial alone. Lock exposure/WB where drivers allow. Feeds the Calibration view.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) checklist §1–2.

## Answer

Shipped `madu_darts.cameras`: `CameraIngest` opens three slots by USB location (defaults `7.2`/`7.3`/`7.4`), capture defaults 1280×720@30, best-effort exposure/WB lock + optional per-slot 180° flip. Linux prefers `/dev/v4l/by-path`; Windows/dev can use `location_index_overrides`. Public seam: `open` / `read` → `{slot: CamFrame}` / `stats` / `close`. Tests mock enumerator + capture (22 new cases; suite 64 green).
