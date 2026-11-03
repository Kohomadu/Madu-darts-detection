# 34: Calibration view shows the far-double residual

**What to build:** After Auto, the Calibration view badge is the far-double residual on every measured sample, residual dots are visible without an extra toggle, and a pan or fine-rotate nudge cannot be Accepted until that camera is remeasured. Inlier RMS may stay as a secondary figure. Today’s Accept fail lines stay as they are until 35.

**Blocked by:** None (can start immediately).

**Status:** in-testing

Type: task
Model: auto

The inlier badge can read about 1.4 mm while the foreshortened double on the same bind is several millimetres out. A nudge that clears the residual can still be Accepted.

- [x] After Auto, the badge number is the far-double all-sample residual, and the dots are on
- [x] A pan or fine-rotate nudge blocks Accept until that camera is remeasured, and the badge is not a stale pass
- [x] A bind past the current far-double fail lines still cannot be Accepted
- [x] A healthy synthetic fit still Accepts

## Answer

- Overlay badge and Calibration API `displayRmsMm` prefer far-double all-sample RMS; inlier RMS stays as a secondary figure.
- `DetectionService` defaults `show_residuals` to true; the Residuals checkbox starts checked.
- Nudge clears residuals / RMS / inlier counts; `accept_block_reasons` blocks with “bind nudged…” until `rescore`. Live nudge HTTP handlers remeasure from the current frame when one is available.
- Accept fail lines remain 5.5 / 12 (ticket 23) until 35.
