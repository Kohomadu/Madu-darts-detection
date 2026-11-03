# 22: Joint radial distortion and homography

**What to build:** Calibration fits a light radial distortion together with the homography, and can still show the homography-only spider beside it. On a foreshortened camera the far double sits on the physical wires. Success is the all-sample far-double residual, not the inlier RMS.

**Blocked by:** 21, 33

**Status:** ready-for-agent

Type: task
Model: premium

A homography cannot bend. The foreshortened double is where that shows up, and it is where doubles are scored. The fit is judged against the scoring faces from 21.

- [ ] On a synthetic Board with a known radial bend, the joint fit’s far-double residual is under 2 mm RMS and under 4 mm max, and it beats homography-only on that fixture
- [ ] On a named empty-Board capture, both fits report far-double all-sample RMS and max in the answer, and the joint fit meets the same 2 mm / 4 mm bar
- [ ] Sector-wire angular residual is reported with those numbers
- [ ] Homography-only still runs
- [ ] The 07 scorecard does not lose Segment agreement
- [ ] If the empty-Board capture cannot meet 2 mm / 4 mm, the ticket stays open
