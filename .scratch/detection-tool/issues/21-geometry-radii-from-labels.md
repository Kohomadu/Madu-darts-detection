# 21: Scoring-face spider

**What to build:** The spider, the Segment map, and Calibration residuals use one WDF scoring-face convention. The double and treble rings are 8.0 mm inside-to-inside, and the wire thickness is one named constant, so those rings are not “outside edge minus 8 mm”. Bull radii stay. The 33 scorecard on the 07 Recording shows whether ring misses move. This ticket does not fit a second radius set to Autodarts labels.

**Blocked by:** 33

**Status:** resolved

Type: task
Model: premium

WDF playing rules measure the ring inside-to-inside and the 170.0 mm and 107.4 mm figures to the outside of the outer wire. Wire stock is 1.27–1.85 mm. An outside-edge model is shifted from the face the point actually scores against by about that thickness, on every camera, before any pixel error. Evidence: [research-spider-calibration-accuracy.md](../research-spider-calibration-accuracy.md).

- [x] One wire-thickness constant feeds the spider, the Segment boundaries, and the residual targets
- [x] A point on the scoring face of the outer double wire maps to the double, and a point just outside that face does not; the same holds for the treble ring
- [x] The 07 scorecard from 33 is in the answer, before and after
- [x] If ring misses do not drop, the answer records the remaining radial bias and does not adopt another radius set

## Answer

Convention shipped in `board/geometry.py`:

| Constant | Value | Role |
| --- | ---: | --- |
| `WIRE_THICKNESS_MM` | 1.5 | Named stock (WDF allows 1.27–1.85) |
| `BED_WIDTH_MM` | 8.0 | Inside-to-inside |
| `DOUBLE_OUTER_OUTSIDE_MM` | 170.0 | WDF / Autodarts coords ÷ |
| `TREBLE_OUTER_OUTSIDE_MM` | 107.4 | WDF outside edge |
| `DOUBLE_OUTER_MM` / `INNER` | 168.5 / 160.5 | Scoring faces |
| `TREBLE_OUTER_MM` / `INNER` | 105.9 / 97.9 | Scoring faces |

Wire stock between scoring face and outside edge still scores that ring. Autodarts `coordsX/Y` stay ÷ 170.

07 Recording scorecard: **before** 21/24, ring_miss 2, neighbour 1, median 2.77 mm → **after** 21/24, ring_miss 2, neighbour 1, median 2.66 mm. Ring misses did not drop. Remaining bias is fit/distortion (ticket 22), not another radius table. No Autodarts-fitted radius set adopted.
