Status: ready-for-agent
Type: task
Model: auto
Blocked by: 11, 09

# Cam MJPEG overlays — tip votes + fused Hit

Debugging overlay vs tip disagreements today requires downloading capture packs. Draw per-cam tip votes and the fused Hit on Detection Vision tiles / cam streams when debug is on.

## Scope

1. Overlay tip px (and optionally axis) per cam; mark used vs dropped votes; draw fused Board point projected back to each cam.
2. Toggle via query flag or Detection UI checkbox (default off for performance).
3. Works on live MJPEG and/or last capture preview.

Out of scope: Calibration spiderweb (already separate); editing Hits on the cam image (18 is Board SVG).

## Done when

- With three stuck darts, operator can see which cam pulled a wire-straddle.
- Answer includes one live screenshot.
