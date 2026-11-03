Status: needs-triage
Type: grilling
Model: premium
Blocked by:

# Deepen Calibration bind-from-frames (Binder)

Architecture review **Strong**. `CalibrationSession` Accept / rotate / `board_point` is a healthy seam (ADR 0002). The *suggest* path is shallow layering: colour rings/wires → RANSAC → edge refine → quality / residuals → session rotate-20 + bind lock. Soft far-double / weak-green / multi-frame ranking decisions span autofit, refine, residuals, and Accept gates with no single locality.

## Problem

Understanding “frames → CamCalibration” requires bouncing across several modules. Deleting any one file mostly moves complexity; deleting the *split* would concentrate the suggest decision.

## Direction

Keep Session as operator / Accept / state module. Behind `suggest`, one deep Binder: frames + slot + mount context → `CamCalibration` (or typed failure). Colour detect, refine, residual field, and badge metrics stay internal. Session only applies bind-lock, rotate defaults/persistence, Accept.

## Involved areas

Calibration autofit, refine, residuals, model, mount, session; DetectionService recalibrate / frame packs; replay bind path.

## Done when (after grill + `/to-spec`)

- Spec published with test seam at Binder (or Session.suggest if that stays the external seam).
- Soft far-double / multi-frame ranking have locality inside Binder.
- ADR 0002 Accept gate unchanged; bind store remains persistence, not a skip of Accept.

## Out of scope here

Hit claiming; ScoringRuntime; UI redesign; skipping Calibration on startup.
