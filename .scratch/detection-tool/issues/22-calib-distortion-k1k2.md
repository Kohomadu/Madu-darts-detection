# 22: Joint radial distortion and homography

**What to build:** Calibration fits a light radial distortion together with the homography, and can still show the homography-only spider beside it. On a foreshortened camera the far double sits on the physical wires. Success is the all-sample far-double residual, not the inlier RMS.

**Blocked by:** 21, 33

**Status:** in-testing

Type: task
Model: premium

A homography cannot bend. The foreshortened double is where that shows up, and it is where doubles are scored. The fit is judged against the scoring faces from 21.

- [x] On a synthetic Board with a known radial bend, the joint fit’s far-double residual is under 2 mm RMS and under 4 mm max, and it beats homography-only on that fixture
- [ ] On a named empty-Board capture, both fits report far-double all-sample RMS and max in the answer, and the joint fit meets the same 2 mm / 4 mm bar
- [x] Sector-wire angular residual is reported with those numbers
- [x] Homography-only still runs
- [x] The 07 scorecard does not lose Segment agreement
- [x] If the empty-Board capture cannot meet 2 mm / 4 mm, the ticket stays open

## Answer

Joint radial + H is wired through refine / `CamCalibration` / overlay / `board_point`. Homography-only remains the default when the joint step does not beat far-double; when it wins, the H-only spider is drawn dim beside the joint spider.

### Synthetic (known `lens_k1`)

`tests/test_calibration_distortion.py`: on `tilt_top` with `lens_k1=0.18`, joint far-double beats H-only and clears **2 mm RMS / 4 mm max**.

### Empty-Board capture `captures/live/_ticket19/board` (ticket 19 tiles)

| Cam | Joint far RMS / max | H-only far RMS / max | sectorWire RMS / max deg | k1 / k2 |
| --- | --- | --- | --- | --- |
| 0 | **4.73 / 11.83** | 8.49 / 21.36 | 2.09 / 3.67 | 0.40 / 0.21 |
| 1 | **1.99 / 3.89** | 3.80 / 8.58 | 2.27 / 4.11 | 0.42 / 0.21 |
| 2 | 2.80 / 5.50 | 2.80 / 5.50 | 1.78 / 3.50 | 0 / 0 (H-only kept) |

Cam1 clears the 2/4 bar. Cam0 improves a lot vs H-only but stays above half-bed. Ticket stays **open** (`in-testing`) for a live Board retune / better empty capture before resolve.

### 07 scorecard

Same recording `2026-11-02T08-07-55Z`: **21/24** Segment agreement (unchanged), median 2.24 mm, `ring_miss: 2`.

## Comments

- Code: `madu_darts.calibration.distortion`, radial fields on `CamCalibration`, `RefineParams.fit_radial`, API `radialK1`/`sectorWire`/`hasHomographyOnly`.
