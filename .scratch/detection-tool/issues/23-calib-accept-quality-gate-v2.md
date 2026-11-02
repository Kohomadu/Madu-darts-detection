Status: resolved
Type: task
Model: auto
Blocked by: 15, 19

# Accept quality gate v2 — refuse pretty-but-soft binds

Ticket 15 raised coverage / honest RMS; operators can still Accept a bind that looks OK on the spiderweb but fails in the double/treble annulus. Tighten the gate using residual overlay metrics.

## Scope

1. Accept blockers from per-band RMS, inlier coverage, and/or max residual in the double (and optionally treble) annulus.
2. Surface blockers in the Calibration UI (reuse `AcceptBlocked` shape).
3. Tunable thresholds in config; document defaults chosen from live Board captures.

Out of scope: wire nudge (20); changing tip fusion.

## Done when

- Soft cam0-style binds that 15’s badges would warn on cannot Accept without an explicit override (if any).
- Healthy synthetic + cam1/2-class fits still Accept.
- Answer lists final thresholds + one live example that was blocked then fixed.

## Answer

Accept and the badge now look at the foreshortened double from ticket 19’s residual summary (all measured samples, not inlier-only RMS).

Defaults (`AcceptGateParams`, overridable on `CalibrationSession`):

| Knob | Default | Effect |
|------|--------:|--------|
| `farDoubleRmsMm` | **4.0** | above → **FAIL**, blocks Accept |
| `farDoubleMaxMm` | **7.0** | above → **FAIL**, blocks Accept |
| `warnFarDoubleRmsMm` | 3.0 | above → demote PASS → WARN (still Acceptable) |
| `warnFarDoubleMaxMm` | 5.5 | above → demote PASS → WARN |

`GET /api/calibration` exposes `acceptGate` plus the existing `farDouble` / blockers. No force-Accept override yet.

### Live Board (same process as ticket 19 overlay check)

Empty-Board Auto on `100.118.240.5:3181` with residual metrics present:

| Cam | Badge RMS | Far double RMS / max | Gate |
|-----|----------:|----------------------|------|
| 0 | pass 1.48 | **5.39 / 8.5** | **block** (soft foreshortened double) |
| 1 | pass 1.47 | 3.50 / 6.0 | WARN demotion only — still Acceptable |
| 2 | warn 1.54 | **4.76 / 8.5** | **block** |

So Accept is refused until Auto (or later nudge/distortion) brings cam0/cam2’s far double under the thresholds — which is the ticket. Healthy synthetic three-cam Auto still Accepts.
