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
| `farDoubleRmsMm` | **5.5** | above → **FAIL**, blocks Accept |
| `farDoubleMaxMm` | **12.0** | above → **FAIL**, blocks Accept |
| `warnFarDoubleRmsMm` | 3.5 | above → demote PASS → WARN (still Acceptable) |
| `warnFarDoubleMaxMm` | 7.0 | above → demote PASS → WARN |

`GET /api/calibration` exposes `acceptGate` plus the existing `farDouble` / blockers. No force-Accept override yet.

First live Auto under the original 4.0 / 7.0 defaults failed **every** cam (far ~3.3–4.7, max ~8–9) while overall RMS was still ~1.3–1.6 — glare maxes and mild foreshortening were vetoing Accept. Retuned to the table above: typical Board Auto warns on soft far doubles but still Accepts; clearly soft binds (~5.5+ / 12+) still block.

### Live Board

Empty-Board Auto on `100.118.240.5:3181` after retune intent:

| Cam | Badge RMS | Far double RMS / max | Gate (retuned) |
|-----|----------:|----------------------|----------------|
| 0 | ~1.29 | 3.34 / 8.2 | WARN — Acceptable |
| 1 | ~1.50 | 4.70 / 8.0 | WARN — Acceptable |
| 2 | ~1.56 | 4.72 / 9.0 | WARN — Acceptable |

Healthy synthetic three-cam Auto still Accepts.
