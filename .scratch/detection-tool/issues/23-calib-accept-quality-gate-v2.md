Status: needs-triage
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
