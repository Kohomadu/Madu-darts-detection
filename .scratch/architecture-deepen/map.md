# Architecture deepen

## Notes

Follow-ups from the 2026-11-03 architecture review (`%TEMP%/architecture-review-20261103-090236.html`). Vocabulary: module / interface / depth / seam / adapter / leverage / locality (`codebase-design`). Domain terms from `GLOSSARY.md`.

**Hit claiming** (review #1) already has a spec: [../hit-claiming/spec.md](../hit-claiming/spec.md) (`ready-for-agent`). Tip unify (review #3) is the first internal step of that spec — see [../hit-claiming/issues/01-unify-tip-core.md](../hit-claiming/issues/01-unify-tip-core.md).

These tickets are **not** ready to implement until grilled / `/to-spec`. Strength badges from the review: Strong / Worth exploring / Speculative.

## Decisions-so-far

- Hit-claiming external seam confirmed: live settle + Recheck + override → one claiming interface; Turn commits only.
- Prefer existing seams over new ones; ScoringRuntime waits until claiming is one interface both live and replay can share.
- Do not re-litigate ADR 0001–0004 unless friction warrants; Binder supports ADR 0002 (Accept still required).

## Fog

- [01](issues/01-calib-binder.md) Calibration Binder (Strong)
- [02](issues/02-scoring-runtime.md) ScoringRuntime (Worth exploring; blocked on hit-claiming)
- [03](issues/03-board-observation.md) Board observation (Worth exploring)
- [04](issues/04-state-choreography.md) DetectionService state choreography (Speculative)
