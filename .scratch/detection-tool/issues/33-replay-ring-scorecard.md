# 33: Replay scorecard — ring miss vs neighbour

**What to build:** Replaying a labelled Recording reports every dart’s distance to the nearest ring wire and the nearest sector wire, and classes a wrong Segment as a ring miss, a neighbour, or a bull. Later Calibration and fusion work is judged on this report. The 07 Recording is the fixture.

**Blocked by:** None (can start immediately).

**Status:** resolved

Type: task
Model: auto

Evidence: [research-spider-calibration-accuracy.md](../research-spider-calibration-accuracy.md). An 8 mm double or treble ring leaves 4 mm from its centre to a wire, so a single agreement percentage hides the misses that matter.

- [x] The report lists every dart on the 07 Recording, not only an aggregate percent
- [x] A wrong Segment closer to a ring wire than to a sector wire is a ring miss; the opposite is a neighbour; bulls are their own class
- [x] The summary still shows Segment agreement, median millimetres, and the ring-miss and neighbour counts
- [x] A test covers a synthetic point just inside a double, just across that wire, and one sector over

## Answer

Pure geometry helpers live next to `point_mm_to_segment`: `distance_to_nearest_ring_wire_mm`, `distance_to_nearest_sector_wire_mm`, `classify_segment_disagreement`. Replay enriches every `DartComparison` with those distances and a `miss_class`, and `format_comparison_table` prints them plus summary counts.

07 Recording (`2026-11-02T08-07-55Z`) after this change: **21/24** agree, median **2.77 mm**, `ring_miss: 2`, `neighbour: 1`, `bull_disagree: 0`. The two ring misses and one neighbour are the rows later tickets should move.
