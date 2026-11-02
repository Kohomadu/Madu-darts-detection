Status: ready-for-human
Type: task
Model: auto
Blocked by: 17

# Manual Hit override — Autodarts free-tier score correction

Operator corrects any Hit on the **current Turn strip** by Segment name or Board-mm point without re-running vision. Available anytime Hits are visible (throw / takeout / after Recheck).

## Scope

1. `PATCH /api/state/hits/{index}` with `{segmentName}` (centroid placement) or `{xMm,yMm}`; `method: Manual`.
2. Detection UI: click Hit chip → segment pad or Board SVG click; Cancel leaves unchanged.
3. v1 does **not** rewrite sealed `/api/history`. Recheck (17) may overwrite an override (document).

## Done when

- Override updates `throws[i]` + Board SVG; WS clients see it.
- Unit + Detection smoke.

## Answers

### Behaviour

- `PATCH /api/state/hits/{index}` body: `{segmentName}` → `segment_name_to_mm` centroid, or `{xMm,yMm}` → `point_mm_to_segment`. Hit `method: Manual`.
- `TurnController.override_hit` emits event `override`; live store snapshots open-visit Hits; WS clients get the new `throws[]`.
- Detection: click a filled chip → picker (type `D20` / `T5` / `Bull` / `25`, or click Board SVG). Cancel closes without change.
- **Recheck after an override overwrites it** (vision replace of all Hits). Sealed `/api/history` is not edited in v1.

### Before / after (synthetic `:3199`)

| Step | throws[0] | method | event |
|------|-----------|--------|-------|
| Detected | D15 | (vision) | `throwDetected` |
| Override | D6 | Manual | `override` |
| Recheck | D16 | BestCam | `recheck` (overwrote Manual) |
| Override | T20 | Manual | `override` |

Detection HTML includes `#recheck`, `#picker`, and `/api/state/hits/` PATCH. Unit: `test_override_hit_sets_manual_method`, server `test_recheck_and_override_api`.
