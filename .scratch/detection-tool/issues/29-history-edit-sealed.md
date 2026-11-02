Status: needs-triage
Type: task
Model: auto
Blocked by: 18

# Override sealed history visits (v2)

Ticket 18: Override only affects the live strip while Hits remain; sealed `/api/history` rows are immutable. Operators sometimes notice a wrong Segment only after takeout.

## Scope

1. `PATCH /api/history/{visitId}/hits/{index}` (or equivalent) with same body as live Override.
2. Update sealed record + optional capture `state.json` note; do not rewrite JPEGs.
3. Detection History UI: edit control on a sealed row.
4. Audit: `method: Manual`, timestamp / event in visit `events[]`.

Out of scope: editing Autodarts cloud; bulk re-score.

## Done when

- Sealed visit Segment changes persist across refresh; WS/history clients see it.
- Answer documents that Recheck still does not rewrite sealed rows (or explicitly adds sealed Recheck as a non-goal).
