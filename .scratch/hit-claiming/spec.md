Status: resolved

# Deepen Hit claiming

## Problem Statement

Operators and developers cannot trust that live settle, mid-Turn Recheck, and manual Hit override will produce the same Segment for the same Board geometry. Tip localization, multi-cam fusion (including wire straddles and occlusion), and Segment assignment are assembled differently on each path. Bugs fixed on one path (stub tips, far BestCam, outer-double preference) do not automatically apply to the others. Understanding “how a settled change becomes a Segment” means bouncing across several shallow modules whose interfaces are nearly as rich as their implementations.

## Solution

One deep Hit-claiming module sits behind a single external interface: given Calibration `board_point`, camera frames / settled tips / empty-Board refs, and prior Hits where needed, it returns ordered Hits with Segments. Live settle-window claiming, mid-Turn Recheck, and Segment resolution for manual override are three entries into that same implementation. The Turn module only commits, retracts, and replaces Hits. Tip localization is unified so Recheck and live share one tip core (strictness via parameters, not a second implementation). Detection and Autodarts-shaped projection behaviour stay as they are; only the claiming path deepens.

## User Stories

1. As an operator, I want live Hits and Recheck Hits to use the same fusion and Segment rules, so that pressing Recheck does not invent a different scoring dialect.
2. As an operator, I want a Recheck after a wrong first Hit to restore the correct Segments without resetting the Turn, so that I can keep throwing.
3. As an operator, I want Recheck to reject stub tips and weak BestCam garbage the same way live claiming would, so that visit failures like a false Miss do not come back through Recheck alone.
4. As an operator, I want Recheck to keep a strong prior Hit when the new candidate is far and weak, so that a noisy re-detect does not wipe a good Segment.
5. As an operator, I want Recheck to allow a nearby bed correction when the new evidence is solid, so that a soft mis-Hit can be fixed.
6. As an operator, I want Recheck to allow a far correction when multiple cams agree, so that a badly fused Hit can still be rescued.
7. As an operator, I want Recheck to refuse to run when the Board looks empty vs empty refs, so that takeout is not mistaken for stuck darts.
8. As an operator, I want Recheck to refuse to run with zero Hits, so that the control only means “re-score what is stuck.”
9. As an operator, I want Recheck to keep Hit cardinality (never invent a fourth Hit), so that the Detection view Hit strip stays Turn-legal.
10. As an operator, I want live settle to wait for the multi-cam collect window then emit one Hit, so that cams that settle a few frames apart still fuse once.
11. As an operator, I want a second dart to be claimed against the dart-committed Board background, so that earlier Hits do not steal the next change mask.
12. As an operator, I want off-Board tip motion (arm FOV, hand-like blobs) rejected as non-Hits on the live path, so that scoring does not fire on takeout gestures.
13. As an operator, I want the same off-Board rejection on Recheck, so that empty-ref blobs outside the Board cannot become Segments.
14. As an operator, I want fusion to prefer the on-Board side when cams straddle the outer double wire, so that soft doubles are not flipped to Miss.
15. As an operator, I want fusion to prefer the treble when cams straddle the treble wire, so that T-ring Hits stay on treble.
16. As an operator, I want fusion to drop warn-status cams when pass cams agree, so that a soft Calibration slot does not drag the Hit.
17. As an operator, I want fusion to drop an occluded cam when peers remain, so that a dart shaft hiding a tip does not poison the fuse.
18. As an operator, I want soft ties to weight the near-mount cam, so that geometry closer to a cam wins when votes split.
19. As an operator, I want unanimous / majority / single-cam methods to remain visible on Hits, so that Autodarts-shaped throws stay comparable in shadow runs.
20. As an operator, I want a manual Hit override to assign Segment from Board-mm or segmentName through the same Segment rules as live claiming, so that Manual Hits match the Board map.
21. As an operator, I want a manual override to set method Manual and full confidence without re-running tip find, so that I can correct a Segment without waiting for vision.
22. As an operator, I want override to preserve slot votes from the replaced Hit where possible, so that history still shows which cams contributed.
23. As a developer, I want one Hit-claiming interface to learn, so that I do not reassemble tip → fuse → Segment in DetectionService or Turn.
24. As a developer, I want tip axis-fit, elongation, tip-top-k, and confidence in one implementation, so that Recheck floors are parameters not a fork.
25. As a developer, I want WDF ring radii used in wire-straddle preference to live with Board geometry knowledge inside claiming, so that fusion does not own a second Segment vocabulary.
26. As a developer, I want Turn to call claim / recheck-claim and then commit or replace Hits, so that Turn stays a Turn state machine not a vision orchestrator.
27. As a developer, I want DetectionService to gate Accept, frames, empty refs, and empty-Board checks, then call the Hit-claiming module, so that service does not hand-wire fusion FitStatus and tip config into three call sites.
28. As a developer, I want existing tip-fusion, detector, and Recheck behavioural tests to keep passing through the deepened interface (or thin adapters), so that tickets 09/14/15/17/18/24/25 do not regress.
29. As a developer, I want new tests to assert Hit claim outcomes (Segment, method, cardinality, keep-prior) rather than private tip helpers, so that refactors inside claiming do not churn the suite.
30. As a developer, I want Recording replay and live detection to be able to share the same claiming module later, so that shadow-compare stays honest without duplicating fuse rules.
31. As a developer, I want Autodarts-shaped throw fields (coords, segmentName, bed, multiplier, method) unchanged on Hit projection, so that ADR 0004 diffs keep working.
32. As a developer, I want Calibration Accept and every-startup Calibration unchanged, so that ADR 0002 is not reopened by this work.
33. As a developer, I want no runtime Autodarts dependency introduced by claiming, so that ADR 0001 stays intact.
34. As an AFK agent, I want a single module boundary for claiming, so that tip and fuse internals can move without rewriting Turn or HTTP handlers.
35. As an AFK agent, I want Recheck’s keep-prior jump / elongation / confidence gates documented as claiming policy, so that I do not reintroduce a Recheck-only fork.
36. As an AFK agent, I want Segment assignment for live, Recheck, and override to call the same Board geometry mapping, so that three copies of point_mm_to_segment wiring disappear from callers.
37. As an operator, I want Detection view Recheck and override controls to keep working with the same HTTP contracts, so that the UI does not need a redesign for this deepen.
38. As an operator, I want the Hit strip after Recheck or override to update via the existing state stream, so that LAN Detection view stays in sync (ADR 0003 / 0004).
39. As a developer, I want deleting the Recheck tip fork to concentrate complexity in the tip core, so that the deletion test passes for the shallow duplicate.
40. As a developer, I want fuse_points and tip helpers to become internal seams of Hit claiming (callable by claiming’s own tests if needed), so that external callers stop treating them as the product interface.

## Implementation Decisions

- Deepen one Hit-claiming module as the sole external seam for producing Hits with Segments from vision (and for resolving Segment on manual Board-mm / segmentName override).
- Live settle-window collection remains an entry that consumes settled per-cam changes and emits at most one new Hit per dart; Recheck remains an entry that re-detects vs empty-Board refs and returns a list aligned to previous Hits; override remains an entry that builds a Manual Hit from Board-mm or segmentName without tip find.
- Turn continues to own Turn lifecycle (start / stop / reset / takeout / max three Hits) and only commits, replaces, or overrides Hits produced by claiming; Turn does not assemble tip → fuse → Segment.
- DetectionService continues to own Calibration Accept gating, latest frames, empty-ref access, “Board looks empty” Recheck gate, FitStatus → fit_ok projection, capture side effects, and Autodarts-shaped state publish; it stops hand-assembling recheck_hits / point_mm_to_segment for override beyond calling the claiming interface.
- Unify tip localization: one tip-from-mask / component-points implementation; live bbox ROI and Recheck multi-blob empty-ref find are adapters or entry params; Recheck elongation / confidence floors are parameters on that core, not a second module.
- Wire-straddle preference, occlusion drop, warn-cam drop, and near-mount soft-tie behaviour stay inside claiming’s fusion implementation; callers pass Calibration fit_ok and mount context, not fusion policy.
- Segment assignment (Board-mm → Segment, including Autodarts bed/multiplier/name fields on Hit) happens inside claiming for live and Recheck; override uses the same Segment mapping through the claiming interface rather than DetectionService calling Board geometry directly.
- Hit’s Autodarts throw projection remains the ADR 0004 adapter; claiming does not change the published throw shape.
- Prefer evolving the existing Hit detector / Hits package into the deep module over introducing a parallel ScoringRuntime or Board-observation module in this effort.
- Public exports should shrink toward the claiming interface and Hit types; tip and fuse helpers may remain importable for tests/migration but are not the seam callers should learn.
- No change to Calibration Session Accept flow, camera ingest, MotionGate settle signalling, or Detection view HTML contracts beyond continued use of existing Recheck / override endpoints.
- Private peeks such as DetectionService reading Turn empty-board helpers for the Recheck gate may remain for this spec if a Board-observation deepen is out of scope; do not expand new private peeks.

## Testing Decisions

- Good tests assert external behaviour at the Hit-claiming seam: given frames / tips / empty refs / priors / fit_ok, the ordered Hits’ Segments, methods, cardinality, and keep-prior vs replace outcomes are correct. Do not assert private tip axis internals or fuse helper call order.
- Primary module under test: Hit claiming (live entry, Recheck entry, override/Segment resolution entry).
- Turn tests continue to cover commit / replace_hits / override_hit transitions and events; they receive Hits from claiming or fixtures, not fused intermediates.
- DetectionService / HTTP tests continue to cover Accept gates, empty-Board Recheck refusal, and Autodarts-shaped state after recheck/override; they do not re-specify fusion policy.
- Prior art: existing tip-fusion tests (wire straddle, occlusion, warn-cam, off-Board), detector tests (multi-cam T20, second dart, collect window), Recheck tests (restore wrong first Hit, keep prior over stub/BestCam, nearby vs far correction, replace_hits cardinality), override tests (Manual method), Hit Autodarts projection tests, and Recording pipeline accuracy floors. Migrate or retarget those behaviours to the claiming interface without dropping coverage.
- Prefer synthetic Board geometry and synthetic tip/frame fixtures already used in Hits tests; live Board Recording regression remains a floor, not the only proof.
- When unifying tip code, keep behavioural cases that currently live only under Recheck (stricter elongation / confidence) as claiming-policy tests with explicit params.

## Out of Scope

- Calibration suggest / Binder deepen (autofit, refine, residuals, Accept quality gates).
- ScoringRuntime extraction shared with Recording replay (may follow once claiming is one interface).
- Board observation module (empty refs / changed_pixels / is_empty as a public seam); MotionGate private-helper cleanup beyond what claiming needs.
- DetectionService state choreography (sync_motion + publish_state collapse).
- Learned / ONNX tip detector, labelled corpus, or AI referee.
- Match UI, game modes, 501 math.
- Changing ADR 0004 throw shape or adding Autodarts cloud/runtime dependency.
- Skipping Calibration Accept or persisting Calibration to skip the startup gate (ADR 0002).
- Redesigning Detection view or Calibration view UI.
- Sealed history edit / mid-history Recheck of past visits.

## Further Notes

- Origin: architecture review 2026-11-03; top recommendation was deepen Hit claiming with tip unification as the first internal step.
- Confirmed test seam: one Hit-claiming external interface; live, Recheck, and override are entries into it; Turn commits only.
- Suggested internal sequence for an implementing agent: (1) unify tip core and point Recheck at it with stricter params — [issues/01-unify-tip-core.md](issues/01-unify-tip-core.md), (2) route Segment assignment for live/Recheck/override through one place inside claiming, (3) narrow DetectionService/Turn call sites to the claiming interface, (4) shrink public Hits exports and keep behavioural tests green.
- Sibling architecture tickets (Binder, ScoringRuntime, Board observation, state choreography): [../architecture-deepen/map.md](../architecture-deepen/map.md).
- Fog tickets that motivated the deepen (fusion wire preference, occlusion drop, Recheck hardening) should remain green; this spec is structural, not a new scoring heuristic.

## Implementation notes

Shipped 2026-11-03:

1. Tip core unified in `hits/tip.py` (`tip_from_component_points`); Recheck tip fork removed.
2. Claiming seam in `hits/claiming.py`: `claim_settled`, `hit_from_fusion`, `resolve_manual`; Recheck entry remains `recheck_hits`.
3. `HitDetector.poll` → `claim_settled`; DetectionService override → `resolve_manual`; Turn still only commits/replaces.
4. Package `__init__` documents claiming as the external seam; tip/fuse stay importable for tests.
5. Behavioural suite green (`test_hits_*`, turn, recheck/override API). Replay max-error floor at 18.25 mm also fails on pre-change `main` (pre-existing, not this deepen).
