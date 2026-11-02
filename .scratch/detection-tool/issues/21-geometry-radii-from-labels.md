Status: needs-triage
Type: task
Model: auto
Blocked by: 09, 07

# Board radii from labelled Hits — wire-centre vs WDF edge

Autodarts labelled throws imply treble-inner ≲ 97 mm and double ≈ 167 mm (coords × 170) vs Madu WDF 99.4 / 162–170. Systematic bed flips (S↔T, D↔M) can be geometry, not tip error. Fog item: revisit once ≥ 20 labelled D/T darts exist.

## Scope

1. Collect / use labelled Hits (Autodarts recordings + live overrides that match truth) with Board-mm tips.
2. Fit or estimate treble/double inner/outer radii (and document wire-centre vs wire-edge assumption).
3. Ship as config (or ADR + `geometry` constants) with a replay A/B: WDF vs fitted on the same corpus.
4. Do **not** change sector clock or bull radii unless evidence demands it.

Out of scope: per-cam distortion (22); ONNX tip (27).

## Done when

- Written decision: keep WDF, adopt fitted radii, or dual-mode config.
- Replay scorecard on ≥ 20 D/T (+ singles) shows whether bed errors drop.
- Answer + map Fog updated; GLOSSARY/ADR touch if constants change.
