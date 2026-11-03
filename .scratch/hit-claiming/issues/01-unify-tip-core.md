Status: resolved
Type: task
Model: auto
Blocked by:

# Unify tip localization (Hit claiming step 1)

Architecture review **#3 / Strong** — first internal step of [../spec.md](../spec.md). Axis fit, elongation, tip-top-k, and confidence are duplicated: live `locate_tip` vs Recheck `_tip_from_component_points` / `locate_tips_vs_empty`. Recheck hard-codes stricter floors (`RECHECK_MIN_ELONGATION`, etc.) in a second implementation. Ticket 17 / visit-#6 class bugs stay Recheck-local while live tip diverges.

## Scope

1. One tip-from-mask / component-points implementation shared by live and Recheck.
2. Bbox ROI vs full-frame multi-blob are adapters or entry params over the same core.
3. Strictness is parameters (Recheck floors), not a second module.
4. Keep Recheck behavioural tests green (stub / BestCam keep-prior, three-dart empty-ref find).

## Done when

- Recheck tip fork deleted or reduced to a thin adapter calling the shared core.
- Live detector tip path uses the same core.
- Existing tip + Recheck tests pass; no ScoringRuntime / Binder work in this ticket.

## Out of scope

Full Hit-claiming seam collapse (Segment routing + DetectionService call-site shrink) — follow-on after this; Calibration Binder; Board observation.

## Answer

Done as part of full [../spec.md](../spec.md) implement.

- Shared core: `tip_from_component_points` in `hits/tip.py`.
- Live `locate_tip` and Recheck `locate_tips_vs_empty` are adapters; Recheck passes `RECHECK_MIN_ELONGATION` / `RECHECK_MIN_TIP_CONFIDENCE`.
- Recheck tip fork deleted; `test_recheck_tip_fork_deleted` guards it.
- Follow-on Segment/call-site shrink also landed in the same pass (`hits/claiming.py`, DetectionService → `resolve_manual` / `recheck_hits`).
