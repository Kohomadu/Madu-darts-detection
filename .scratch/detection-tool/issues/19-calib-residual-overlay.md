Status: resolved
Type: task
Model: auto
Blocked by: 15

# Calibration residual overlay — see where the spiderweb is soft

Operators currently judge Accept from RMS + a spiderweb that can look “fine” while cam0’s far double / treble band is soft. Ticket 15 added honest inlier counts; this ticket makes residuals **visible** on the Calibration view.

## Scope

1. After Auto / Accept, compute per-cam wire (or ring-sample) residuals in Board mm and/or image px.
2. Overlay on the Calibration tile and/or warped Board: heatmap, quiver, or colour-coded samples (far double annulus called out).
3. Expose a compact summary in `GET /api/calibration` (e.g. per-band RMS, max residual) for agents / debug.
4. Reuse `calib-diag` math where possible; prefer live UI over CLI-only.

Out of scope: clicking to nudge wires (20), distortion model (22), changing Accept thresholds (23).

## Done when

- Calibration view shows where each cam’s bind is weak without reading logs.
- Unit or golden check on a known soft cam0 empty-Board capture.
- Answer includes a screenshot / capture id from the live Board.

## Answer

After Auto, each cam keeps the measured wire and ring samples from the ticket 15 edge fit. The Calibration tile draws them as coloured dots (green ≤ 0.75 mm, yellow ≤ 1.5, orange ≤ 3, red above) with a short quiver back to the ideal wire, and magenta arcs on the foreshortened half of the double annulus labelled `FAR <max>`. The same drawing is in the warped inset. `GET /api/calibration` adds `maxResidualMm`, `maxDoubleMm`, `maxTrebleMm`, `farDouble`, and `nearDouble`. Band RMS here includes outliers; the existing inlier-only `rmsDoubleMm` / pass badge is unchanged (ticket 23). `madu-darts calib-diag` prints the max and far-double columns and writes the same overlays.

The double-annulus stats use the inner/outer double wires (about 158–174 mm), not the r=150 sector-wire samples, which were inflating a `≥ 150` gate on tilted frames.

### Live empty Board

Capture `20261102T183706-8fded2` on `100.118.240.5:3181` (`status: throw`, `event: reset`, `throws: []`). Raw frames refit locally (the process on the Board is still the previous build, so its page does not show this overlay until restart):

| Cam | Badge | Far double RMS / max | Near double RMS / max | Far angle |
|-----|-------|----------------------|-----------------------|-----------|
| 0 | pass 1.43 mm | **4.60 / 12.5** | 2.48 / 6.2 | 180° (opposite 20, top of the cam0 frame) |
| 1 | pass 1.47 mm | 4.99 / 8.0 | 1.93 / 4.5 | 60° |
| 2 | warn 1.59 mm | 4.69 / 8.5 | 2.70 / 7.0 | 300° |

Cam0’s inlier double RMS stays 1.30 mm. The overlay is what shows the far double sitting off the spiderweb. Tiles: `captures/live/_ticket19/board/tile{0,1,2}.jpg` (gitignored).

### Check

- Golden: synthetic `tilt_top` with the far double bulged 6 mm. Against the true plane, far-double RMS beats the near side by more than 1.5 mm. After `suggest`, far max stays above near max (`tests/test_calibration_residuals.py`).
- Calibration page on synthetic `:3181`: each cam row shows `far dbl`, the feed/inset show the dots and magenta arcs, and rotate-right moves cam 2’s offset 0 → 19 with the far angle tracking the same physical side.
