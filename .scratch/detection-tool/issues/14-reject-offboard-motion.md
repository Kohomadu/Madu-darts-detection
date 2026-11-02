Status: resolved
Type: task
Model: auto
Blocked by: 09, 10

# Reject off-Board motion (arms / body) as Hits

Live Board 2026-11-02 (`100.118.240.5:3181`): after Accept, the Turn filled with **Miss / BestCam** Hits while the Board was empty — arm and body motion in the wide cam FOV (outside the scoring disk) settles, tip-fits a long blob, and fusion accepts a single-cam point hundreds of mm off the Board.

**Pause further accuracy testing until this lands** — otherwise live history is dominated by false Hits.

## Evidence

`GET /api/history` after two “visits” (operator Reset; auto-captures on 3rd false Hit):

| Visit | Segments | Methods | Board-plane radii (mm) |
|-------|----------|---------|-------------------------|
| V3 | M8, M16, M16 | BestCam ×3 | 421, 742, 494 |
| V4 | M9, M4, M19 | BestCam ×3 | 719, 547, 391 |

Scoring disk outer double = **170 mm**. All six points are 2–4× outside. Capture packs `20261102T125416-188b01` and `20261102T125444-42bf8e`: **empty Board**, hand/arm visible at FOV edge (tablet / reach into frame). Current open Turn also showed `M8` with no dart stuck.

Root cause chain: motion gate has **no Board ROI** → tip localizer accepts elongated off-Board change → fusion `min_cams=1` / `BestCam` promotes it to a Hit → Turn commits.

## Scope

Gate false Hits **before** Turn commit (prefer reject in `HitDetector` / fusion, not only in the UI):

1. **Board-plane radius reject** — drop a per-cam tip (or the fused point) when `hypot(x_mm, y_mm) > max_hit_radius_mm` (suggest default **≈ 190–200 mm**: double outer 170 + small margin for tip noise / slightly long throws that are still near the wire). Never score `M*` from a point at r ≥ 400 mm.
2. **Optional image-space ROI** — after Calibration Accept, mask motion / tip search to the projected double-outer (or surround) ellipse per cam so arms outside the ring never settle as darts. Stronger than (1) alone; can be phase 2 if radius reject is enough.
3. **Fusion floor for outliers** — do not emit `BestCam` when the only surviving cam is outside the radius; require ≥ 2 agreeing cams **or** a single cam whose tip is inside the disk. (Keep `min_cams=1` for real single-cam dart visibility when the tip is on-Board.)
4. Config knobs on `TipConfig` / `FusionConfig` (or a small `HitGateConfig`) exposed via `GET /api/config`; document in Answer.

Do **not** treat this as “raise takeout sensitivity” — takeout already suppresses huge changes; these were dart-sized arm motions that settled quietly.

## Done when

- Unit test: synthetic off-Board tip (r ≫ 170) offered on one or more cams → `HitDetector.poll` returns `None`; on-Board T20 still scores.
- Replay of the 07 recording accuracy does not regress (same floor as ticket 09).
- Live / synthetic: waving an arm in FOV outside the Board with empty Board produces **no** Hit; a real dart still does.
- Ticket Answer notes the chosen radius / ROI and any live re-check on the Board.

## Related

- [12](12-learned-tip-detector.md) — tip quality on real darts; this ticket is false-positive rejection, orthogonal.
- Motion takeout heuristic (08) — different failure mode (hand over Board).

## Answer

Resolved 2026-11-02. Phase 1 only: **Board-plane radius reject** (no image ROI mask yet).

### Code
- `FusionConfig.max_hit_radius_mm = 200.0` (double outer 170 + margin; live false Hits were r≈390–740). Exposed as `maxHitRadiusMm` on `GET /api/config.fusion`.
- `on_board(xy, max_r)` + `fuse_points` drops tips outside the radius before fusion; fused centre re-checked. Off-Board-only groups → `None` (no Hit).
- `HitDetector.offer` rejects the cam immediately when the projected tip is off-Board (logs `r=… > max_hit_radius_mm`); slot marked rejected so the collect window can still complete. Settled frames are still committed so the background does not keep re-firing on the same arm.

### Verification
- Unit: `test_fuse_rejects_off_board_arm_tips` (live-scale coordinates + mixed on/off Board); `test_detector_rejects_off_board_tips_no_hit`.
- 07 replay floor unchanged (`test_hits_replay`). Full suite green.

### Live re-check (after pull)
Wave an arm in FOV with empty Board → strip must stay empty. Then throw a real dart → Hit. Image-space Board ROI mask left as a follow-up if arms still settle often enough to thrash the background.
