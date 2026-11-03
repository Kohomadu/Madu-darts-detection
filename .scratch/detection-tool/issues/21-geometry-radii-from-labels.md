# 21: Scoring-face spider

**What to build:** The spider, the Segment map, and Calibration residuals use one WDF scoring-face convention. The double and treble rings are 8.0 mm inside-to-inside, and the wire thickness is one named constant, so those rings are not “outside edge minus 8 mm”. Bull radii stay. The 33 scorecard on the 07 Recording shows whether ring misses move. This ticket does not fit a second radius set to Autodarts labels.

**Blocked by:** 33

**Status:** ready-for-agent

Type: task
Model: premium

WDF playing rules measure the ring inside-to-inside and the 170.0 mm and 107.4 mm figures to the outside of the outer wire. Wire stock is 1.27–1.85 mm. An outside-edge model is shifted from the face the point actually scores against by about that thickness, on every camera, before any pixel error. Evidence: [research-spider-calibration-accuracy.md](../research-spider-calibration-accuracy.md).

- [ ] One wire-thickness constant feeds the spider, the Segment boundaries, and the residual targets
- [ ] A point on the scoring face of the outer double wire maps to the double, and a point just outside that face does not; the same holds for the treble ring
- [ ] The 07 scorecard from 33 is in the answer, before and after
- [ ] If ring misses do not drop, the answer records the remaining radial bias and does not adopt another radius set
