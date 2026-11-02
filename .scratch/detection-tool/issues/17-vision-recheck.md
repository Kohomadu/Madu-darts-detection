Status: ready-for-human
Type: task
Model: premium
Blocked by: 11, 15

# Vision Recheck — mid-Turn classical re-detect (Autodarts AI Referee analogue)

Autodarts Plus “robot button” re-analyzes camera footage for darts still on the Board. Madu ships a **classical** Recheck first: operator-triggered re-diff of current frames vs the Turn’s empty-Board refs → tip → fusion → replace Hits.

## Scope

1. `POST /api/recheck` — gate: Calibration accepted, Turn running, `1..3` Hits, Board not empty vs `_empty_refs`.
2. Per-cam multi-dart tip find against **empty refs** (not dart-committed BoardModel); associate across cams; fuse with existing rules (prefer-pass, double-wire straddle).
3. `TurnController.replace_hits`; refresh BoardModel from current frames; emit Madu `recheck` event + updated `throws[]`.
4. Detection view **Recheck** button; optional capture `reason=recheck`.

Out of scope: learned referee (12), sealed-history recheck, manual segment pick (18).

## Done when

- Synthetic wrong Hit → Recheck restores correct Segments from empty-ref diff.
- Live: mis-Hit mid-Turn updates strip without Reset.
- Tests + Answer with algorithm + before/after.

## Answers

### Algorithm

1. Gate: Accepted Calibration, Turn `running`, `1..3` committed Hits, Board still non-empty vs `_empty_refs` (else 409).
2. Snapshot latest frames; per cam `locate_tips_vs_empty` = change mask vs empty refs → up to N elongated components → tip toward Board (same axis/elongation rules as live tip).
3. Greedy associate across cams within `agree_mm`; `fuse_points` (prefer-pass / double-wire straddle).
4. Order to previous Hits by Board-mm nearest; pad missing slots with previous; never invent a 4th.
5. `TurnController.replace_hits` → BoardModel commit current frames → event `recheck` → optional capture `reason=recheck`.

Key files: `hits/recheck.py`, `turn/controller.py` (`replace_hits`, `empty_refs`), `POST /api/recheck`, Detection **Recheck** button.

### Before / after

**Unit (static stuck frames):** three darts at T20 / S11 / S6; first Hit forced to D16 → Recheck → `{T20,S11,S6}` restored (`tests/test_hits_recheck.py`).

**Synthetic serve (`:3199`, mid-Turn):**

| Step | throws[0] | event |
|------|-----------|-------|
| Detected | D15 | `throwDetected` |
| Force bad | D6 (`Manual`) | `override` |
| Recheck | D16 (`BestCam`) | `recheck` |
| (strip updated without Reset) | | |

Recheck replaced the Manual override with a fresh vision Hit (adjacent double on the scripted dart — tip noise on synthetic script; static unit case restores exact Segments).

**Camera Board (`100.118.240.5:3181`):** still running pre-17 build (`POST /api/recheck` → 404). Needs pull + restart on the Board host for live-cam validation; code + synthetic path are green.

### Tests

`tests/test_hits_recheck.py` + `tests/test_server.py::test_recheck_and_override_api`; hits/turn/server suite **44 passed**.

### Follow-up hardening (Board visit #6)

Live: auto `S20·T1·S8` then Recheck ×3 → `…·M7` before `…·T8`. Bad presses used stub blobs (`elong≈2.1`, `conf≈0.25`) as BestCam Miss / mid-Board junk.

Shipped: recheck tip floor `elong≥3.5` / `conf≥0.35`; per-slot keep prior when new is Miss-over-on-Board, low conf, or weak BestCam jump ≥40 mm. Still allows nearby S8→T8 and far multi-cam corrections.
