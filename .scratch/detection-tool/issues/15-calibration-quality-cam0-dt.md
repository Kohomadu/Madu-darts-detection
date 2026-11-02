Status: claimed
Type: task
Model: premium
Blocked by: 04, 13

<!-- Live Auto+Accept still needed before Status: resolved -->

# Calibration quality: cam0 RMS / wire fit → doubles & trebles wrong

Live Board session 2026-11-02 after tickets 13–14. **Singles mostly fine; doubles and trebles systematically wrong.** Operator: cam0 (above physical 20) never gets the wires right; cam1 most consistent; cam2 between.

## Live Calibration snapshot (session mid-test)

| Cam | Mount | status | `rotateOffset` | RMS (mm) |
|-----|--------|--------|----------------|----------|
| 0 | above 20 | **warn** | 10 | **2.177** |
| 1 | near 16 | pass | 4 | 0.902 |
| 2 | near 15 | pass | 16 | 0.866 |

Pass threshold is effectively RMS ≲ 1.5 (`WARN` above). Cam0 is the outlier every time; when its tip vote is included, visit spreads jump to **6–8 mm** (V2 S8/S15, V3 S19s) vs **2–3 mm** when cams agree tightly (V1 T20).

## Live Hits (8 visits, all sealed by `reset` — takeout never finished; see [16](16-takeout-finish-empty-gate.md))

| V | Madu segments | Notes |
|---|----------------|-------|
| 1 | S1, **T20**, S5 | T20 correct once (UnanimousCam, spread ~3 mm) |
| 2 | S20, S8, S15 | Spreads 8 mm — cam0 pulls cluster |
| 3 | S19, S19, S3 | r≈121 near treble band; r≈161 near double — classic S↔T / S↔D |
| 4 | S20, M1, S12 | M1 BestCam r=186; cam0 vote unused / disagreeing |
| 5 | M16, S8, S6 | M16 r=178 (double-outer neighbourhood) |
| 6 | S20, S20, S20 | One at r≈96 (just inside Madu treble-inner 99.4) |
| 7 | S20, S1, 25 | Bull ok |
| 8 | S14, M14, M14 | Edge / double neighbourhood; cam0 vote wild on first dart |

Pattern: radial errors of a few mm from a soft cam0 homography flip beds in the **8 mm** treble/double rings. Singles are wide so they “work.”

Related Fog (map): Autodarts labels imply treble-inner ≤ **97 mm** vs Madu WDF **99.4** — even a perfect tip can S↔T vs Autodarts if radii stay wrong. Tackle calibration first; revisit geometry with labelled D/T once cam0 is green.

## Scope (premium)

Investigate and improve **Board-plane bind quality**, especially slot 0:

1. **Diagnose cam0 autofit** on live/capture frames: ellipse fit, orange/20 colour cue, wire intersections, which residual dominates RMS; compare to cam1 (good).
2. **Hardening**: tighter reject/refit, multi-frame suggest, exposure/glare handling (Target ring light + surround), optional operator-assisted wire nudge if auto stays weak.
3. **Downstream**: while cam0 RMS is warn, down-weight or drop cam0 in fusion (or require Cam+1 without it) so a bad H cannot veto D/T. Keep UnanimousCam when all three are healthy.
4. Re-check D/T on the Board after cam0 RMS is consistently **pass (&lt; ~1.2 mm)**; if D/T still fails, open/extend geometry radii ticket separately.

Use live captures under `GET /api/captures` from this session (e.g. `20261102T130311-84e65a` T20 good; `…130735…` / `…130823…` edge D/T fails) plus Calibration warped feeds.

## Done when

- On this Board, after Auto + Accept, cam0 status **pass** with RMS comparable to cam1/cam2 (target ≲ 1.2 mm) for typical lighting, or a documented hardware/FOV limit with a fusion workaround that still scores D/T reliably.
- Live or labelled set: doubles/trebles agreement materially up vs this session (session had ~1 confirmed T20 and multiple near-wire S/M mis-beds).
- Answer records root cause (fit bug vs glare vs geometry vs mount) and what changed.

## Answer

### Root cause

Not mount geometry and not primarily tip localization. **Colour autofit was reporting a soft cam0 bind as almost-OK.**

On live empty-Board frames (2026-11-02):

| Cam | Reported RMS | Colour-wire inliers | What happened |
|-----|-------------:|--------------------:|---------------|
| 0 | 2.18 warn | **15/40** | Warm mask flooded by LED surround / wood / glare → outer-envelope fallback. Treble rings were **WDF-scaled concentric** with the double ellipse; under perspective the bull sits ~57 px above that ellipse centre, so all 20 treble wire points landed tens of mm off and were RANSAC-rejected. Homography = double-only extrapolation → radial D/T flips. |
| 1 | 0.90 pass | 29/40 | Treble tight; far-side double ellipse slightly large (RANSAC drops those points). |
| 2 | 0.87 pass | 30/40 | Same pattern as cam1. |

RMS was computed **on inliers only**, so the badge could not see that cam0’s treble band was unbound.

### What changed

1. **Edge refine** (`calibration/refine.py`): after a soft colour seed (`< 28` colour inliers or RMS > 1.5), re-measure ring/wire edges along Board-plane rays (colour-gated) and RANSAC+LS refit. Healthy colour seeds (cam1/2, synthetic, 07 recording) are kept and only re-scored.
2. **Honest quality** on `CamCalibration`: `nInliers` / `nPoints` / per-band RMS; pass needs RMS ≤ 1.5 **and** enough edge inliers (not a thin colour subset). Badge shows `PASS 1.38 mm 174/321`.
3. **Multi-frame Auto**: `recalibrate` grabs ~5 frames; `suggest_best` keeps the strongest.
4. **Fusion guard**: when `prefer_pass_cams` and a cam is not `pass`, drop it if two pass cams already agree → `Cam+1`. `UnanimousCam` only with healthy cams.
5. **`madu-darts calib-diag <dir>`** for residual tables + overlays.

### Before / after on this Board’s empty frames

| Cam | Before | After (`calib-diag captures/live/_now`) |
|-----|--------|----------------------------------------|
| 0 | warn 2.18 (15/40 colour) | **pass 1.38 (174/321 edges; dbl 1.41 / trb 1.41)** |
| 1 | pass 0.90 | warn 1.50 (225/350) — colour H kept; edge-honest badge |
| 2 | pass 0.87 | **pass 1.48 (227/356)** |

Cam0 now binds **both** bands. Absolute RMS is a bit above the ≲ 1.2 stretch target but well inside pass, and the fusion guard covers residual soft cams.

### Verification

- Full suite **289 passed** (incl. 07-recording replay floor ≥ 20/24 and new refine/fusion tests).
- Live Auto + Accept + D/T throws: **pending** operator pull/restart on the Board (see Comments).
