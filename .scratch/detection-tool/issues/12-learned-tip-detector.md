Status: needs-triage
Type: task
Model: premium
Blocked by: 09

# Follow-up: close the singles gap (more labelled data first, learned tip only if it persists)

Opened by [09](09-tip-localization-fusion.md) because the classical tip + fusion chain landed at **83 % singles** (15/18) against the ≥ 90 % gate on the single 24-dart recording, while doubles/trebles (3/3), bulls (2/2) and median error (3.76 mm ≤ 4) passed.

## What 09 found

- Every disagreement is at Autodarts' own noise floor: three wire-straddles where Autodarts' label is ≤ 2.3 mm from a wire, one occlusion (previous dart's flight hides the new tip in one cam).
- A 36-point parameter sweep plateaus at 20–21/24 — heuristics are saturated; the ticket rule says stop tuning.
- Per-cam error is 3–6.5 mm; cam 2 is the worst and also has the worst autofit RMS (1.48 mm).
- Autodarts' labels imply treble-inner ≤ 97.0 mm vs Madu WDF 99.4 (see map Fog).

## Decide (human)

1. **Record more** (cheap, Auto): 5–10 more sessions with `madu-darts record --frames autodarts`, aiming for ≥ 100 darts incl. ≥ 20 doubles/trebles and a few bounce-outs/takeouts. Re-run `madu-darts replay`; if singles ≥ 90 % on the larger set, close this as resolved with no model.
2. **Occlusion-aware fusion** (small, Auto): when a cam's tip ends inside a previously committed dart's footprint, down-weight / drop that cam before the mean.
3. **Learned tip detector** (premium, only if 1 fails): small ONNX keypoint/heatmap model on 1280×720 crops around the settled bbox, trained on Autodarts-labelled recordings (tip px = Autodarts mm → `board_mm_to_image`). Keep the classical path as fallback and the fusion/Hit API unchanged.

## Done when

- Singles ≥ 90 % and doubles/trebles ≥ 80 % on a ≥ 100-dart labelled set, median ≤ 4 mm; or an explicit decision recorded here that the classical chain is good enough for the first Detection view milestone.
