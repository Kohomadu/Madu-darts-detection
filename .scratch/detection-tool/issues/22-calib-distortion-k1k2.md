Status: needs-triage
Type: task
Model: premium
Blocked by: 19, 21

# Optional radial distortion (k1/k2) before homography

Cam0’s perspective still softens the far ring after edge refine (ticket 15). A-Dartment-style joint fit of light distortion + H may bind the double/treble without jumping to full PnP.

## Scope

1. Prototype k1/k2 (or equivalent) in the autofit / refine path; keep H-only as default until Accept quality improves on cam0.
2. Measure: residual overlay (19) + live D/T Hits before/after.
3. Config flag; document failure modes (overfit on empty Board colour noise).

Out of scope: full PnP + triangulation (stays Fog); replacing Accept UX.

## Done when

- Cam0 far-ring residual improves without regressing cam1/2 or 07 replay floor.
- Answer: ship default on, opt-in, or defer to PnP Fog with evidence.
