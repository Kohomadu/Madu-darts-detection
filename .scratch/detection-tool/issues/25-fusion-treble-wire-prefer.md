Status: ready-for-agent
Type: task
Model: auto
Blocked by: 09

# Fusion: prefer inside-treble when cams straddle the treble wire

Outer-double prefer-inside fixed live D→M straddles. Same class of error on the **treble** annulus (live S8 vs T8 when cam0 is T8 and the Cam+1 mean slides inside treble-inner).

## Scope

1. When fused / multi-cam votes straddle `TREBLE_INNER`–`TREBLE_OUTER` (or disagree on Treble vs Single across that wire), prefer the on-treble or inside-treble policy consistent with the double-wire fix (document which).
2. Mirror tests from the double-wire fusion tests with treble targets.
3. Confirm Recheck / live Hits benefit; no geometry radius change (that’s 21).

## Done when

- Unit: cam votes across treble wire → Segment stays T* when the stronger / inside vote says treble (policy recorded in Answer).
- Live or capture replay of an S↔T straddle shows improvement or explicit residual limitation.
