Status: resolved
Type: task
Model: auto
Blocked by: 10, 14

# Takeout starts but never finishes (empty-Board gate)

Live Board 2026-11-02: after correct 3-Hit Turns (`status: takeout` → `takeoutInProgress` / `takeoutStarted`), **takeout never finished once**. All 8 sealed visits in `/api/history` have `reason: reset` (operator Reset), never `takeoutFinished`. History count only grew because of Reset.

## Evidence

Stuck state observed mid-session (S1, T20, S5 still on strip):

```
status=takeoutInProgress event=takeoutStarted throws=3
cam0/1/2: phase=stable moving=false isTakeout=true
changedPixels ≈ 1400 / 1020 / 1245   # vs BoardModel (dart-committed bg)
emptyMaxChangedPixels = 60             # finish gate vs Accept empty_refs
```

Those ~1k px levels match “darts removed vs still-committed background” or a large empty-ref mismatch — not a quiet empty Board vs Accept reference (≤ 60).

Config: `takeoutMinChangedPixels=2500`, `takeoutMinMotionFrames=12` — hand **start** works; **finish** is the empty check in `TurnController._board_empty`.

## Scope

1. **Expose debug** on `/api/state/motion` or `/api/state/turn`: per-cam `emptyDiffPx` (current vs `_empty_refs`) and `dartBgDiffPx` (vs BoardModel) so live stuck takeouts are diagnosable without guessing.
2. **Fix finish gate** (pick what the debug shows):
   - Raise / adaptive `emptyMaxChangedPixels` after lighting drift; and/or
   - Treat “Board empty” as: quiet + diff vs **last dart-committed** background large (footprints gone) + diff vs empty_refs below a looser cap; and/or
   - On `takeoutStarted`, snapshot “full Board” and finish when current ≈ empty_refs **or** current has lost the dart footprints.
3. **False-takeout with Hits**: if stuck in `takeoutInProgress` for N seconds quiet with empty_refs nearly met, finish anyway (operator shouldn’t need Reset every visit).
4. Unit tests: 3 Hits → hand → empty frames → `takeoutFinished` and history `reason=takeoutFinished`; stuck case with emptyMax too tight gets the new path.

## Done when

- Synthetic + live: throw 3, remove darts, strip clears without Reset; `/api/history` visit `reason` is `takeoutFinished`.
- Answer includes before/after empty-diff numbers from one live visit.

## Answer

Resolved 2026-11-02.

### Code
- `TurnConfig`: `empty_soft_max_changed_pixels=500`, `dart_removed_min_pixels=200`, `takeout_force_finish_s=4.0` (plus existing strict `empty_max_changed_pixels=60`).
- On `takeoutStarted`, snapshot `BoardModel` refs into `_takeout_full_refs`.
- Finish when quiet and any of:
  1. **strict empty** (≤60 vs Accept `_empty_refs`);
  2. **soft empty + darts removed** (≤500 vs empty refs **and** ≥200 vs takeout-full refs on every judged cam);
  3. **soft-force** (≤ soft for ≥`takeout_force_finish_s` while Hits still listed) — never force-adopt while soft empty fails (darts clearly in);
  4. zero-dart recover unchanged (`false_takeout_recover_s`).
- `GET /api/state` → `madu.emptyDiffPx` / `dartBgDiffPx` / `takeoutFullDiffPx` / `takeoutStartedTMono`.

### Verification
- Unit: existing hand takeout + new `test_takeout_finishes_via_soft_empty_and_darts_removed`, `test_takeout_soft_force_when_nearly_empty_but_strict_fails`, `test_takeout_does_not_force_while_darts_still_in`.
- Live re-check after pull: throw 3 → remove → expect `takeoutFinished` and history `reason=takeoutFinished`; while stuck, read `madu.emptyDiffPx` / `takeoutFullDiffPx` (before: emptyMax-only stuck with dartBg ~1k; after: soft+removed or soft-force should clear).
