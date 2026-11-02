Status: ready-for-agent
Type: task
Model: premium
Blocked by: 08

# Tip localization + multi-view fusion → first Hit

Turn a settled-change event into a Board-plane point and a Segment. Classical approach first; learned detector only if accuracy falls short of the gate below.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §4 steps 7–9; §5 OSS gap-fill (ideas only, license-aware). Decision: classical-first (plan 2026-11-02).

## Scope

**Per-cam tip (step 7)**
- From the diff mask of the new dart: largest connected component, fit the dart axis (PCA / Hough line), take the extreme point along the axis toward the Board plane as the tip candidate; refine on the edge image in a small window.
- Confidence: component size, axis fit residual, tip sharpness.
- Reject: components touching the frame edge massively, multi-blob (hand), or no axis.

**Fusion (step 8)**
- Map each cam’s tip through its accepted homography → Board mm (`CalibrationSession.board_point`).
- Fuse: weighted mean by confidence with outlier rejection (drop a cam if > X mm from the other two); accept with **2-of-3** cams. Record `method` (`UnanimousCam` / `MajorityCam` / `SingleCam`) like Autodarts.
- Normalised `coordsX/Y` output in Autodarts’ convention (derive from recorded pairs in 07; document the scale).

**Segment (step 9)**
- `board.point_mm_to_segment` → Madu label (`T20`, `D16`, bulls, miss) and Autodarts-shaped `{segmentName, segmentNumber, multiplier, bed}`.

**Hit object**
- `Hit(slot_votes, board_mm, coords_norm, segment, method, confidence, t)`; no Turn logic yet (10).

## Done when (accuracy gate on the 07 recording)

- Segment agreement with Autodarts ≥ 90 % on singles, ≥ 80 % on doubles/trebles across the recorded visits; median Board-plane error ≤ 4 mm.
- Zero Hits emitted on takeout/hand sequences in the recording.
- If the gate is missed after reasonable tuning, append findings and open a follow-up for a learned tip detector (A-Dartment-style ONNX) instead of pushing heuristics further.
- Unit tests on synthetic darts (render a line + tip on a synthetic cam) + replay-based accuracy test.
