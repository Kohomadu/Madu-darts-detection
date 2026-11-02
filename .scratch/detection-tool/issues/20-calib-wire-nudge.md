Status: ready-for-human
Type: task
Model: auto
Blocked by: 19

# Calibration wire nudge — operator recovery when overlay is almost right

When autofit is close but one ring/sector is visibly off, the operator today only has rotate-20. Add a light manual nudge so Accept can match what the eye sees.

## Shipped (v1 — spiderweb reliability)

- Per-cam **pan** (N/E/S/W) + **fine rotate** (±1°) composed into H.
- **Undo Auto** restores the session Auto seed.
- **Accept** persists full bind (`captures/calibration_bind.json`); Auto cannot overwrite without Reset bind / Re-Auto.

## Remaining scope (optional v2)

1. Calibration UI: click/drag 1–2 spiderweb samples (or a ring handle) → re-solve homography with the nudged constraints.
2. Nudge must clear or re-evaluate Accept quality; never silently leave a stale PASS badge.

Out of scope: full ARU-DART-style multi-click from scratch; learned calibration.

## Done when

- Operator can fix a visibly skewed sector/ring and Accept without Reset+Auto roulette.
- Undo / “revert to last Auto” restores the pre-nudge fit.
- Answer notes live Board before/after overlay.
