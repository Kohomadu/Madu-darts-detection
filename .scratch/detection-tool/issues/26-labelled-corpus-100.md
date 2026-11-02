Status: ready-for-agent
Type: task
Model: auto
Blocked by: 07, 09

# Labelled corpus ≥100 darts — scorecard before any learned tip

Ticket 12: classical tip saturated on n=24; decide with more data whether ONNX is needed. This ticket is the data + scorecard work only.

## Scope

1. Record 5–10 sessions (`madu-darts record --frames autodarts` or Board live captures with known truth), aiming for **≥ 100 darts**, including ≥ 20 doubles/trebles and some bounce-outs/takeouts if possible.
2. Replay / shadow-compare scorecard: singles %, D/T %, median mm, wire-straddle counts.
3. Update ticket 12 + map Fog with go/no-go for [27](27-onnx-tip-in-crop.md).
4. Store meta under `captures/recordings/`; large JPEGs stay gitignored.

Out of scope: training a model; changing fusion heuristics (24/25 can land in parallel).

## Done when

- Scorecard checked into the ticket Answer (table + recording paths).
- Explicit recommendation: classical enough / need 24–25 first / proceed to 27.
