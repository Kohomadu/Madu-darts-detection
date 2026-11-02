Status: needs-triage
Type: task
Model: premium
Blocked by: 26, 12

# ONNX tip-in-crop — learned localizer with classical fallback

Only if [26](26-labelled-corpus-100.md) shows the classical gate still missed after fusion polish (24/25). Small heatmap/keypoint model on the settled-change crop (A-Dartment / `lksmlr` style), not full-frame YOLO scoring.

## Scope

1. Train/export ONNX from Autodarts-labelled tips (Board mm → image via `board_mm_to_image`) on 1280×720 crops around the settle bbox.
2. `HitDetector` path: try ONNX tip; fall back to classical `locate_tip` on failure / low conf.
3. Fusion / Turn / Autodarts `throws[]` API unchanged.
4. Document runtime deps (onnxruntime), CPU budget on the Board host, and disable flag.

Out of scope: replacing Calibration; end-to-end learned referee; cloud training pipeline (local/repro script is enough).

## Done when

- Scorecard on the 26 corpus: singles / D/T / median meet or beat classical with no live FPS collapse.
- Classical-only still works with ONNX disabled.
- Answer + ticket 12 resolution note.
