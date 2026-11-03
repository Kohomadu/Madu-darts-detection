# Spider calibration accuracy: Madu detection and peer systems

Fetched: 2026-11-03

Related notes, not repeated here: [research-three-cam-approaches.md](research-three-cam-approaches.md), [research-autodarts-behaviour.md](research-autodarts-behaviour.md). Live Autodarts HTTP was not re-probed.

## Summary

Madu scores a stuck dart by diffing each camera against a background, waiting out motion, fitting a line to the change, and taking the tip at the Board end of that line. Each tip pixel goes through an accepted per-camera homography and a rotate-20 offset onto one millimetre plane; agreeing cameras are averaged, and `point_mm_to_segment` turns `(r, θ)` into a Segment with fixed radii. There is no lens model in the source. The spider drawn on the feed is that homography projected back as ideal rings and wires, and the badge RMS is the inlier-only residual of the points the fit kept. A live-session note records badge RMS near 1.4 mm on the same bind whose foreshortened double was 4.6 mm RMS (max 12.5 mm). The double and treble beds are 8.0 mm wide in the WDF rules, so the centre of a bed is 4 mm from a wire: a spider error of a few millimetres assigns the wrong Segment even when the tip pixel is perfect. A 0.1° sector error is 0.30 mm at the outer double wire; 0.5° is 1.48 mm there and 0.94 mm at the treble outer wire. Reading “99.9% spider” as 99.9% of the scoring disk classified correctly is a boundary band about 0.014 mm wide, which is tighter than the WDF’s own ±0.2 mm tolerance on the 170 mm radius and tighter than the wire (1.27–1.85 mm). That area figure does not protect Hits near wires. What does is a residual that stays small beside the dart’s distance to the wire after tip error is included. Autodarts, Scolia, Dartsee, Target OMNI, and GRAN EYE publish calibration UX and accuracy slogans, and do not publish the fit. Open-source calibrators that do publish a fit use homography, ellipses, or PnP, and several of them place the treble 0.4 mm off the WDF outer edge (107.0 vs 107.4). The only first-party millimetre residual measured on the wires themselves is Chase Bonfiglio’s A-Dartment figure, 0.46 / 0.71 / 0.56 mm on the fit’s own edge samples, which he states is not a tip-error number; that rig called 53 of 71 segments before the learned tip.

## How Madu detects a dart

Startup does not emit Hits until Calibration is Accepted ([ADR 0002](../../docs/adr/0002-calibration-every-startup.md), `CalibrationSession.require_accepted` / `board_point` in [`session.py`](../../src/madu_darts/calibration/session.py)). `DetectionService.start` opens the cameras, loads any saved binds, re-measures residuals on the current frames, and auto-fits only slots that are not already bound. Accept stays false until the operator confirms ([`service.py`](../../src/madu_darts/server/service.py) `start`, `load_saved_binds`).

Once detection is running, one pump batch is handled in this order ([`TurnController.process`](../../src/madu_darts/turn/controller.py)):

1. **Frames.** Three cameras, full-resolution BGR. Motion is computed on a downscale.
2. **Motion.** `MotionGate` diffs the downscaled gray frame against the previous frame and against `BoardModel`’s reference. Defaults match the Autodarts-shaped knobs: `scale=4`, `kernel=3`, `threshold=16`, `stable_num_frames=3`, `min_changed_pixels=40` ([`motion/config.py`](../../src/madu_darts/motion/config.py), [`motion/gate.py`](../../src/madu_darts/motion/gate.py)). Phases are `idle → motion → settling → stable`. A large change (`takeout_min_changed_pixels=2500` for `takeout_min_motion_frames=12`) is classified as takeout and does not settle a Hit.
3. **Settle.** After `stable_num_frames` quiet frames that still differ from the background, the gate emits a `SettledChange` with a bbox at motion scale. `HitDetector.bbox_full_res` multiplies that bbox by `motion_scale` before the tip search.
4. **Tip, per camera.** `locate_tip` builds a change mask (`detection` defaults `kernel=5`, `threshold=16`), keeps the large connected components inside the padded bbox, and fits `cv2.fitLine(..., DIST_HUBER)`. The tip is the mean of the `tip_top_k=4` inliers farthest along the axis in `tip_direction` (default image-down `(0, 1)`). Gates: `axis_inlier_px=10`, `min_length_px=25`, `min_elongation=2`, `min_points=20` ([`hits/tip.py`](../../src/madu_darts/hits/tip.py), [`hits/config.py`](../../src/madu_darts/hits/config.py)).
5. **Per-camera board plane.** `session.board_point` maps the tip pixel with `image_to_board_mm(homography, rotate_offset, tip_px)`. The effective matrix is `rotation_mm(rotate_offset) @ H`, a clockwise multiple of 18° ([`homography.py`](../../src/madu_darts/calibration/homography.py) `effective_homography`). Tips with radius above `max_hit_radius_mm=200` (outer double is 170) are dropped before fusion.
6. **Fusion.** Cams are collected for `collect_window_s=0.4`. `fuse_points` means the cameras whose board-plane tips lie within `agree_mm=15`. Method strings are `UnanimousCam`, `Cam+1`, `BestCam`. A cam whose fit status is not `PASS` is dropped when two passing cams already agree (`prefer_pass_cams`). Occluded tips (inside a prior footprint padded by 24 px, or within `occlusion_tip_radius_mm=8` of a prior tip while a peer moved on) are dropped when a clear cam remains. If the group straddles the outer double (`170` mm), only the inside votes are kept. If it straddles a treble wire within `_TREBLE_STRADDLE_MM=8`, only the on-treble votes are kept. A tight unanimous group (`spread ≤ soft_tie_spread_mm=4`) is an equal mean; a looser group is weighted toward the mount nearest the tip angle (`mount_angles_deg` default `{0: 0°, 1: 234°, 2: 126°}`, floor weight 0.15) ([`hits/fusion.py`](../../src/madu_darts/hits/fusion.py), [`calibration/mount.py`](../../src/madu_darts/calibration/mount.py)).
7. **Segment.** `claim_settled` → `point_mm_to_segment`. Non-unanimous Hits scale confidence by 0.8 ([`hits/claiming.py`](../../src/madu_darts/hits/claiming.py)). The settled frame is committed into `BoardModel` either way, so the next diff sees the dart as background.

`point_mm_to_segment` ([`board/geometry.py`](../../src/madu_darts/board/geometry.py), contract in [`tests/test_board_geometry.py`](../../tests/test_board_geometry.py)):

| Constant | mm | Role in the mapper |
|---|---:|---|
| `INNER_BULL_RADIUS_MM` | 6.35 | `r ≤ 6.35` → inner bull (`IB`, bed `DoubleBull`) |
| `OUTER_BULL_RADIUS_MM` | 15.9 | `r ≤ 15.9` → outer bull (`OB`) |
| `TREBLE_INNER_MM` | 99.4 | `99.4 < r ≤ 107.4` → treble; `r = 99.4` stays single |
| `TREBLE_OUTER_MM` | 107.4 | outer edge of treble, inclusive |
| `DOUBLE_INNER_MM` | 162.0 | `162 < r ≤ 170` → double; `r = 162` stays single |
| `DOUBLE_OUTER_MM` | 170.0 | `r > 170` → `MISS` |

Angle is `atan2(x, y)`, 0 at +y (sector 20), clockwise. Wires sit at ±9°. The wedge is half-open: the wire belongs to the clockwise-next sector (`_sector_number`). Sector order is the standard clockwise clock from 20. These radii are the WDF outside edges with an 8 mm band subtracted; the rules text is stricter than that subtraction, and that gap is in the accuracy section.

## How Madu calibrates the spider

The spider is one homography per camera from image pixels to board millimetres, plus an integer sector offset. Rings drawn in the Calibration view are samples of the WDF circles pushed back through that homography (`draw_spiderweb`, `RING_RADII_MM`). They are not a second measured model ([`overlay.py`](../../src/madu_darts/calibration/overlay.py)).

### What is fitted

`suggest` in [`autofit.py`](../../src/madu_darts/calibration/autofit.py):

1. HSV masks. Warm (red or Target-style orange, hue ≤ 20 or ≥ 170) and green. Morphological closing joins the 20 wedges of a band into an annulus. Annuli are chosen by area ratios against the WDF circles (`_RATIO_DOUBLE_INNER ≈ 0.908`, `_RATIO_TREBLE_OUTER ≈ 0.399`).
2. Colour runs around each band. Transitions become 20 wire angles. Image points are the mid-line of the double and treble ellipses at those angles: `_DOUBLE_MID_MM = 166.0`, `_TREBLE_MID_MM = 103.4` (midpoints of 162–170 and 99.4–107.4), not the wire faces.
3. `cv2.findHomography` RANSAC, `ransac_threshold_mm=3.0`, at least 28 inliers on the stacked 40 points when that set is used. Destinations are board millimetres, so the threshold is applied in the board plane. Inlier RMS is `reprojection_rms_mm` on the inliers only. `rotate_offset` from `suggest` itself is 0; the cyclic label search is only a fallback when the colour-suggested 20 fails to bind.
4. Optional edge refine (`refine=True`, 3 iterations). `measure_ring_edges` walks rays from 70 mm to 185 mm at 0.5 mm steps, 72 angles, and assigns each strong gradient peak to the nearest of the six WDF radii if it is within `ring_assign_mm=10`. `measure_wire_edges` looks ±4° around each nominal wire at radii 55, 80, 130, and 150 mm (those radii sit in the singles, not on the double bed). Refit uses RANSAC at `min(colour threshold, 2.5)` mm, then an unweighted-API least squares on inliers, with near-hemisphere inliers duplicated when `near_weight=1.5` (`mount_angle_deg` from the same mount table). Healthy colour seeds skip the refit and are only re-scored ([`refine.py`](../../src/madu_darts/calibration/refine.py), `suggest`).

Nothing in `src/madu_darts` estimates `k1`/`k2`, calls `calibrateCamera`, or calls `undistort`. A search of that tree on 2026-11-03 found no distortion terms. Ticket [22](issues/22-calib-distortion-k1k2.md) is a pointer at that absence, not an implementation.

`suggest_best` keeps the frame with the highest `n_inliers * 1000 + coverage * 100 − rms`. `DetectionService` grabs five frames for that. After a successful suggest, `CalibrationSession.suggest` writes `rotate_offset` from the last Accepted offsets, else the ring-mount defaults `{0: 10, 1: 4, 2: 16}` ([`mount.py`](../../src/madu_darts/calibration/mount.py)). The operator can still rotate by whole sectors (`rotate_left` / `rotate_right`, ±1 mod 20) or nudge the spider in the image (`nudge_pan`, `nudge_rotate`), which left-multiplies a similarity about the bull into `H`.

Ellipses stored on the cam (`RingFit`) are `cv2.fitEllipse` of the homography-projected WDF rings, exported in the Autodarts ellipse field shape (`angle`, `x`, `y`, `width`, `height`). They are a view of `H`, not an independent fit to pixels (`rings_from_homography`).

### What the operator Accepts

Accept requires every cam to have a fit and no `accept_block_reasons` ([`model.py`](../../src/madu_darts/calibration/model.py), `CalibrationSession.accept`). Any suggest, rotate, nudge, or clear sets `accepted` false.

Two different residuals are in play:

| Quantity | What it measures | Thresholds in code |
|---|---|---|
| `rms_mm` via `evaluate_fit` | RMS of samples with error ≤ the RANSAC threshold (default 2 mm in `evaluate_fit`; colour seed uses 3 mm). Outliers are omitted from this RMS. | `PASS_RMS_MM=1.5` and coverage ≥ 0.45 and ≥ 100 inliers → `PASS`. `WARN_RMS_MM=3.0` with thinner coverage → `WARN`. Above 3 mm → `FAIL`. |
| `farDouble` via `summarize_residuals` | RMS and max of **every** sample whose target radius is in `[DOUBLE_INNER−4, DOUBLE_OUTER+4]` = `[158, 174]` mm and whose angle is within 90° of the foreshortened side. Outliers stay in. | Fail Accept if RMS > `ACCEPT_FAR_DOUBLE_RMS_MM=5.5` or max > `ACCEPT_FAR_DOUBLE_MAX_MM=12.0`. Warn above 3.5 / 7.0. The same numbers demote the badge through `CamCalibration.status`. |

`rms_double_mm` inside `evaluate_fit` is a third number: inliers with target radius ≥ 150 mm, which includes the sector-wire samples at 150 mm. The comment in [`residuals.py`](../../src/madu_darts/calibration/residuals.py) says those samples are why the far-double band is not “everything outside 150 mm”.

`PASS` is the only status `HitDetector` treats as `fit_ok`. A `WARN` camera is dropped from fusion when two `PASS` cameras already agree.

### What the spider overlay can hide

`draw_spiderweb` projects the ideal circles and the 20 wires. Residual dots are off unless `show_residuals` is set; `DetectionService` defaults that flag to false, “for a clean spider”. A homography is a projective map of those ideal circles, so the overlay is smooth even where the lens bends or the far ring was an outlier. The warped inset (`draw_warped_board`) is the check that can show the physical wires missing the ideal rings; the badge text is still the inlier RMS, then demoted if `farDouble` is bad.

`nudge_pan` / `nudge_rotate` set `residuals=None` and `rms_mm=None`. With a homography and no RMS, `status` is `WARN`. `accept_block_reasons` only applies the far-double test when a residual field exists, and `WARN` is allowed through. A nudged bind can be Accepted with the quality numbers cleared. `rescore` (re-measure edges, do not change `H`) runs at startup after a saved bind is loaded; the Accept handler in [`app.py`](../../src/madu_darts/server/app.py) calls `session.accept` and does not call `rescore`.

### Session numbers (observation log, not a lab report)

[`.scratch/detection-tool/map.md`](map.md) records, as session notes: live Board accept with RMS about 0.7–1.3 mm, and capture `20261102T183706-8fded2` with badge RMS about 1.4 mm while cam0 far-double RMS was 4.6 mm (max 12.5). The gate comment in `model.py` records a different live Auto, used to retune the gate: overall RMS about 1.3–1.6 mm with far-double about 3.3–4.7 mm and max about 8–9 mm, which failed an earlier 4 / 7 mm gate on every camera. Under the constants in the tree today, a max of 12.5 mm fails Accept (`12.0`), and a far-double RMS of 4.6 mm alone is a warning (fail line 5.5, warn line 3.5). The 07-recording replay notes in the same map — 20/24 then 21/24 segment agreement with Autodarts, median 3.76 mm — compare Madu’s plane point with Autodarts’ labels. They are not a hand-measured tip error.

## What “99.9% spider” means in millimetres

Rules text below is WDF Playing and Tournament Rules, 28 February 2018, revision 20, section 4.01, as fetched 2026-11-03 from the PDF linked on the WDF rules page. The 12 August 2025 World Cup rules do not restate board dimensions.

Quoted measurements ([PDF](https://dartswdf.com/storage/uploads/fb05b306-c92c-4f08-b512-affb092a1b3d/2018-02-28_WDF_Playing_and_Tournament_Rules_rev20.pdf)):

- Conventional wire boards, double and treble, “measured inside to inside = 8.0 mm +/- 0.2 mm”. Strip boards are a different quantity, “apex to apex = 10.00 mm +/- 0.2 mm”.
- Wire section “maximum 1.85 mm or 1.27 mm minimum. (+/-.2 mm)”, round, triangular, or diamond. Non-wire bull walls “not greater than 1.6 mm {+/- 0.2 mm}”.
- “Bull” inside diameter 12.7 mm ± 0.2 mm → radius 6.35 mm.
- “25” ring inside diameter 31.8 mm ± 0.3 mm → radius 15.9 mm.
- “Outside edge of Double wire to Centre Bull 170.0 mm +/- 0.2 mm”.
- “Outside edge of Treble wire to Centre Bull 107.4 mm +/- 0.2 mm”.
- Outside edge of double to the opposite outside edge 340.0 mm ± 0.5 mm. Overall diameter 451.0 mm ± 3.0 mm.
- Section 3.03: “The score is counted from the side of the segment wire in which the point of the dart enters or touches the face of the dartboard.” Section 4.02: segment 20 is the darker colour and is at the top.

Madu’s 8 mm subtraction places the double bed on `[162, 170]` and the treble on `[99.4, 107.4]`, treating the outside edge and a point 8 mm inward as the two scoring faces. The rule’s 8.0 mm is inside-to-inside, and the 170.0 / 107.4 mm figures are outside edges of the outer wires. For a wire of thickness `T` in `[1.27, 1.85]` mm, the inner face of the outer double wire lies near `170 − T`, and the inner face of the inner wire lies near `170 − T − 8`:

| `T` (mm) | Inner face of outer double wire | Inner face 8 mm further in | Centre of the outer wire (`170 − T/2`) |
|---:|---:|---:|---:|
| 1.27 | 168.73 | 160.73 | 169.37 |
| 1.56 (mid of the allowed range) | 168.44 | 160.44 | 169.22 |
| 1.85 | 168.15 | 160.15 | 169.08 |

That is a radial shift of about 1.3–1.9 mm relative to a model whose outer boundary is the outside edge. It is 16–24% of the 8 mm bed and about a third to a half of the 4 mm from bed centre to a wire. The same arithmetic on the treble uses 107.4 mm as the outside edge. The allowed ±0.2 mm on the 8.0 mm bed is 2.5% of the bed; the ±0.2 mm on the 170 mm radius is 0.12% of that radius. A-Dartment states its radii are “measured to the centre of the wire”, which is the third column, not Madu’s outside-edge model ([chasebonfiglio.com/dart](https://chasebonfiglio.com/dart/)).

Angular width of a radial wire, small-angle `T / r` in degrees:

| `T` (mm) | At outer double `r = 170` | At treble outer `r = 107.4` |
|---:|---:|---:|
| 1.27 | 0.43° | 0.68° |
| 1.85 | 0.62° | 0.99° |

A zero-thickness spider has to assign one side of a band that itself subtends about half a degree at the double and about one degree at the treble. Madu’s half-open wedge assigns the mathematical line to the clockwise-next sector. That is a defined convention. It is not a measurement of which side of a 1.5 mm wire the point entered (WDF 3.03).

### Bed width and arc length

Double bed and treble bed, inside-to-inside: **8.0 mm ± 0.2 mm**. Madu uses 8.0 mm exactly (`TREBLE_OUTER_MM - 8`, `DOUBLE_OUTER_MM - 8`).

One 18° segment, arc length `2 π r × 18/360 = π r / 10`:

| Place | `r` (mm) | Arc of one segment (mm) | Half-sector, centre to wire (mm) |
|---|---:|---:|---:|
| Outer bull | 15.9 | 5.00 | 2.50 |
| Treble outer wire | 107.4 | 33.74 | 16.87 |
| Outer double wire | 170.0 | 53.41 | 26.70 |

Sector wires do not change the Segment inside the outer bull; the bull rows are only the geometric scale of an angular error. Radial beds are the thin ones: 8 mm, so 4 mm from the middle of a double or treble to either ring wire. The outer single, from 107.4 mm to 162 mm, is 54.6 mm deep.

### How far a small angle moves the boundary

Displacement along the tangent is `r × θ` with `θ` in radians (`θ° × π/180`).

| Angular error | At inner bull 6.35 mm | At outer bull 15.9 mm | At treble inner 99.4 | At treble outer 107.4 | At double inner 162 | At outer double 170 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.1° | 0.011 mm | 0.028 mm | 0.17 mm | 0.19 mm | 0.28 mm | 0.30 mm |
| 0.5° | 0.055 mm | 0.14 mm | 0.87 mm | 0.94 mm | 1.41 mm | 1.48 mm |
| 1.0° | 0.11 mm | 0.28 mm | 1.73 mm | 1.87 mm | 2.83 mm | 2.97 mm |

A 0.5° spider error at the treble is about 12% of the 8 mm bed and about half the wire’s own angular width there. The same 0.5° is 1.5 mm at the outer double, still under half a bed, and it is negligible beside a 4 mm radial miss. Radial error and angular error do not trade one-for-one: the dangerous direction on a double or treble is radial, because the bed is 8 mm and the sector is ~17–27 mm from centre to wire.

### Three readings of “99.9%”

Scoring disk used here: `r ≤ 170` mm, area `π × 170² = 90792 mm²`. Misclassified area at 0.1% is **90.8 mm²**.

**(a) 99.9% of that disk, tip perfect.** Decision boundaries inside the disk, using Madu’s radii: six circles (6.35, 15.9, 99.4, 107.4, 162, 170) with total circumference `2π × Σr = 3525 mm`, plus 20 sector wires from the outer bull to the outer double, `20 × (170 − 15.9) = 3082 mm`. Total length `L ≈ 6607 mm`. A uniform shift `δ` of every boundary misclassifies about `L × δ` (corner overlaps are second order). Then

`δ ≈ 90.8 / 6607 ≈ 0.014 mm`.

Dropping the miss circle at 170 mm (scoring area only) gives `L ≈ 5539 mm` and `δ ≈ 0.016 mm`. Both are an order of magnitude inside the WDF ±0.2 mm tolerance and inside the wire thickness. An area percentage this tight is a statement about the integral of the boundary error. A 4.6 mm error on a short arc of the far double moves little area and still flips every dart in that arc’s double bed. Area-99.9% does not constrain the place the double is actually scored from a foreshortened camera.

**(b) Radial scale error of 0.1%.** `0.001 × r`:

| Ring | 0.1% of radius |
|---|---:|
| Inner bull 6.35 | 0.006 mm |
| Outer bull 15.9 | 0.016 mm |
| Treble inner 99.4 | 0.099 mm |
| Treble outer 107.4 | 0.107 mm |
| Double inner 162 | 0.162 mm |
| Outer double 170 | 0.170 mm |

0.17 mm is 2.1% of the 8 mm bed and is the same order as the WDF’s ±0.2 mm on the outer double (0.12% of 170). A pure scale error does not rotate sector wires. It does move every ring. It is smaller than wire thickness, so it does not by itself decide a dart sitting in the middle of a wire, and it is much smaller than a 1 mm tip error.

**(c) Residual as a fraction of the bed.** 0.1% of the 8 mm bed is **0.008 mm** RMS. That reading is tighter than (a) and is not a quantity any system cited here reports. The operational fractions already in Madu’s gates:

| Residual | Fraction of the 8 mm bed | Fraction of the 4 mm centre-to-wire gap |
|---|---:|---:|
| 0.17 mm (0.1% of 170) | 2.1% | 4.3% |
| 0.7 mm (low end of the map’s accept RMS note) | 9% | 18% |
| 1.5 mm (`PASS_RMS_MM`, inliers only) | 19% | 38% |
| 3.0 mm (`WARN_RMS_MM`) | 38% | 75% |
| 4.6 mm (map: cam0 far-double RMS on one capture) | 58% | 115% |
| 5.5 mm (Accept fail line for far-double RMS) | 69% | 138% |

A far-double RMS of 4.6 mm is larger than the distance from the middle of the bed to the wire. With a perfect tip, the model wire and the physical wire are on opposite sides of the bed centre. Inlier RMS of 0.7–1.5 mm can coexist with that, because `evaluate_fit` drops samples beyond the RANSAC threshold and the spider is drawn from the ideal circles.

### Which reading protects >99% Hits once the tip is wrong

Model, not a measured Hit rate. Put a dart uniformly in an 8 mm bed and add a zero-mean Gaussian radial error of standard deviation `σ` (spider plus tip, one axis). The dart is assigned to the wrong ring when the error crosses either edge. Integrating that tail across the bed:

| `σ` (mm) | Fraction of uniform-in-bed darts that cross a ring wire | Still correct |
|---:|---:|---:|
| 0.10 | ~1.0% | ~99.0% |
| 0.20 | 2.0% | 98.0% |
| 0.50 | 5.0% | 95.0% |
| 1.00 | 10.0% | 90.0% |
| 1.50 | 15.0% | 85.0% |
| 2.00 | 19.9% | 80.0% |
| 3.76 | 36.9% | 63.1% |
| 4.60 | 44.0% | 56.0% |

The 3.76 mm and 4.6 mm rows are the map’s replay median and the cam0 far-double RMS, used here only as scales. A uniform double is a harsh population: real Turns include singles whose nearest wire is tens of millimetres away, and those Hits stay correct under a much looser spider. The product’s >99% is an average over that mix. The average stays high while the wire Hits fail, which is why a loose spider dominates the errors people see and still leaves most of the disk green.

Once a tip error of about 1 mm exists, the uniform-bed table says the ring call on doubles and trebles is already near 90% with a perfect spider. Spending the spider budget on a 0.014 mm area-band does not recover that. A 0.1% scale error (0.17 mm) is a small addend next to a 1 mm tip in the middle of a bed, and it is the whole decision when the dart is already within a few tenths of a millimetre of the wire — a region the wire thickness (1.3–1.9 mm) has already made ambiguous under rule 3.03. A systematic 4 mm radial bias is different: it moves the model wire across the centre of the true bed, so the miss is not a tail. That is the failure mode of a foreshortened double whose residual exceeds half the bed, and of a radius model that is off by a millimetre on every camera at once (the outside-edge versus inside-face reading, or 107.0 versus 107.4).

## Well-known automatic systems

Detection algorithms for the commercial camera scorers below are unpublished. Accuracy percentages on their pages are product claims. They are not a description of a fit, a residual, or a spider model.

### Autodarts

Official UX, fetched 2026-11-03: the setup wizard locates the 20 and highlights it; arrow buttons move that highlight by a segment when the automatic locate is wrong ([Setup](https://autodarts.diy/Autodarts-Desktop/Setup/), [Overview](https://autodarts.diy/Autodarts-Desktop/Overview/)). From software 0.24.0 the docs say lens distortion is handled in software and the separate manual distortion step is not required. The older Board Manager distortion tab (explicitly “earlier versions only”, unsupported from version 2) is a printed 25×25 chessboard moved inside a blue ellipse until coverage reaches 95%, per camera ([Distortion](https://autodarts.diy/getting-started/distortion/)). Camera guidance asks for roughly 80–110° field of view and says higher than 1280×720 “seem[s] to have no effect on accuracy”, without defining the accuracy ([Cameras](https://autodarts.diy/getting-started/cameras/)). The Vision Calibration tab, warped board plus rings, is described in the Desktop docs and in [research-autodarts-behaviour.md](research-autodarts-behaviour.md).

The local ellipse resource is an observable result, not a method. On the 2.1.0 board probed 2026-11-01, `GET /api/config/calibration/ellipses` returns per camera a bull point and `doubleInner` / `doubleOuter` / `trebleInner` / `trebleOuter` ellipses (`angle`, `x`, `y`, `width`, `height`) plus 20-point rings. Older 1.0.7 captures also stored a distortion object with K, d, and an error field. Both are cited from that behaviour note and its protocol sources. The detection binary is Emscripten on the legacy UI; the CV steps are not published. Motion knobs observed there (`scale`, `kernel`, `threshold`, `stableNumFrames`) are the numbers Madu’s motion defaults copy. They do not disclose how the tip or the spider is estimated.

### Scolia

Pages opened: [FAQ](https://scoliadarts.com/faq/), [Home 2](https://scoliadarts.com/scolia-home2/), [Pro](https://scoliadarts.com/scolia-pro/), [Home](https://scoliadarts.com/scolia-home/), and the Home user-manual extract at [Scolia-Home-User-Manual.pdf](https://scoliadarts.com/wp-content/uploads/2024/02/Scolia-Home-User-Manual.pdf). The product site that resolved is `scoliadarts.com`.

Published facts: a set of USB cameras and a processing unit; calibration is automatic, on the order of seconds at startup, and needs a clear board; a Calibrate control exists for a moved board (~10 seconds on Pro). The image processing “expects the dartboard to have standard dimensions, traditional colouring and to be equipped with the traditional metal number ring.” The Home manual tells the operator to get the board image close to green ellipses on the camera views. Home cameras sit on the light surround; Pro camera legs are described as wall-mounted. Home 2 uses fixed legs and says everyday use needs no manual calibration. Claims: Home and Home 2 “roughly 99.5%”, Pro “over 99.8%” on “10.000.000+ throws”, FAQ “well above 99%” for competitive players and “as high as 99.9%” for recreational players, plus “millimeter accuracy” for coordinates. No residual, no camera count, and no fit equations are on these pages. The algorithm is unpublished.

### Dartsee

[Venue specifics](https://www.dartsee.com/dartsee-venues/specifics), fetched 2026-11-03: steel-tip, “cameras and advanced algorithms”, “contractual warranties about scoring accuracy” with no percentage on that page. The Core package lists “4 Scoring cameras, pre-calibrated”, one instant-replay camera, an LED halo, and a Winmau Blade 5. “Installing and calibrating the Core Ring itself is a 20-minute process.” [Masterlist](https://www.dartsee.com/masterlist) points at a board-calibration video and a camera-identify video, available as video during their install session; those videos were not opened, so the procedure is unpublished here. No CV steps.

### Target OMNI

[targetdarts.com/omni](https://www.targetdarts.com/omni) and the [instructions](https://www.targetdarts.com/omni-instructions), plus the [user manual PDF](https://www.target-darts.co.uk/media/pdf/OMNI-User-Manual.pdf): four HD cameras, four magnetic legs, scores sent through the DartCounter app, bounce-outs included in the claim. Marketing figure on the product page: 99.7%. Calibration is automatic and “usually takes 40–60 seconds”, on re-mount, after a dart hits the unit or the ring light is disturbed, and again if miscounts rise. The manual says board vibration leads to inaccurate scoring. Compatible boards are listed (Target, Winmau Blade 5/6, Unicorn Eclipse, and others). The fit is unpublished.

### GRAN EYE (camera). Granboard matrix boards are a different sensor.

[gran-darts.com/graneye](https://www.gran-darts.com/graneye): two cameras beside a steel-tip board the player already owns, “AI” scoring, a zoom when the dart is close to the wire, Wi-Fi or USB, no special light required on that page. No residual and no calibration procedure on the page opened. The manufacturer’s [G2 video-review notes](https://www.gran-darts.com/topics/g2-video-review-instructions) add an Echo sound sensor that triggers the cameras, and they say scoring uses “previously calibrated cameras”. That is still not an algorithm. GRANBOARD soft-tip and steel-size electronic boards on the same site are segment-matrix boards, not this camera path.

Unicorn, as searched 2026-11-03, shows up as a dartboard brand on the OMNI compatibility list (Eclipse Ultra). No first-party Unicorn camera scorer was opened.

## Open-source calibration and detection

Default-branch raw files, fetched 2026-11-03. SHAs are the ones the GitHub contents API returned that day where a listing was opened.

### ARU-DART (`geziefer/arudart`)

[`board_geometry.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/board_geometry.py) (`b3e8ab4` on `main`): labelled “Winmau Blade 6”, millimetres, bull 6.35 / 15.9, triple **99.0 / 107.0**, double **162 / 170**. Control points for the manual click are the bull plus inner-triple and outer-double wire crossings at eight sector boundaries (17 points). `generate_spiderweb` projects those radii through the inverse homography; the overlay is the model, as in Madu.

[`homography_calculator.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/homography_calculator.py) (`2b4aaf1`): `cv2.findHomography` RANSAC, default `ransac_threshold_px=5.0` passed through as `ransacReprojThreshold` with **board millimetres as the destination**, plus `max_reprojection_error_mm=5.0`. `verify` returns the **mean** millimetre error, not an RMS. [`intrinsic_calibrator.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/intrinsic_calibrator.py) (`191079b`): separate chessboard `cv2.calibrateCamera`, default 9×6 inner corners, 25 mm squares, reprojection in pixels, warning above 1.0 px. Intrinsics are a different file from the homography. [`ring_detector.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/fusion/ring_detector.py) classifies radius with the same 99/107 defaults (`triple_inner ≤ r < triple_outer`, `double_inner ≤ r < double_outer`). The 0.4 mm treble shift versus WDF 107.4 / 99.4 is in the constants, on every camera, before any pixel noise.

### `lksmlr/autodarts`

[`extrinsic_calibration.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/extrinsic_calibration/extrinsic_calibration.py): load per-camera `intrinsic_matrix` and `distortion_coef`, click five world points — outer double at the four cardinals, `z=0`, radius 170 mm, plus the bull — `cv2.solvePnP`, Rodrigues to `R`, reprojection error as mean L2 in **pixels**. [`triangulate.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/triangulation/triangulate.py): `undistortPoints` then pairwise `triangulatePoints`, mean of the 3D points, then polar score. Geometry dict: outer double 170, inner double 162, triple **107 / 99**, outer bull **16.0**, inner bull 6.35. Sector index `(angle_deg + 9) / 18`, same half-open idea as Madu. This path estimates intrinsics, distortion, and extrinsics, and it does not fit a homography. The outer-bull constant is 0.1 mm off 15.9; the treble constants are 0.4 mm off the WDF outside edge. No far-ring residual is computed in these two files.

### Dart Vader (`j0j0i996/dart-vader-detection`)

[`boardClass.py`](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/src/boardClass.py) on `master`: `auto_calibration` needs five ellipses from HSV red/green masks and `fitEllipse`, then `HoughLinesP` sector lines, then `findHomography` onto a standard board (`STD_CENTER=(400,400)`, `PX_PER_MM=2`). Ring radii in that fit: 99, 107, 162, 170. `closest_field` rolls the correspondence so the camera’s nearby segment matches the 20-clock. `manual_calibration` uses four JSON clicks on the outer double. `pol2score` uses 6.35 and 15.9 for the bulls and the same 99/107/162/170 rings, with strict inequalities, so a radius exactly equal to 99, 107, 162, or 170 falls through to the miss branch. No distortion coefficients and no millimetre RMS in this file. Scoring is the homography into the standard image, then polar.

### opencv-steel-darts (`hanneshoettinger/opencv-steel-darts`)

Author’s [README](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/README.md): two webcams; find the outer ellipse and Hough segment lines; build an affine map that stretches the ellipse to a circle (`M = T2·R2·D·R1·T1`); intersect lines with that circle; `findHomography` from those points to a “perfect” dartboard. The repo says it is not ready to run as-is. In [`Calibration.py`](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/Calibration.py) the stored ring list is `ring_radius = [7, 16, 97, 107, 160, 170]` millimetres, encoded as twice that because the normalized image uses 2 px/mm (`7 * 2` … `170 * 2`, with circles drawn at `170 * 2` and `107 * 2`). Those are not the WDF set: bull 7 vs 6.35, 25-ring 16 vs 15.9, treble inner 97 vs 99.4, double inner 160 vs 162. [`GetDart.py`](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/GetDart.py) maps one point with `cv2.perspectiveTransform` and classifies `magnitude` against that list. Detection, per the README, is a frame diff plus `goodFeaturesToTrack`, then a merge of the two cameras. No published RMS.

### OpenDartboard

README on `main` (`a80ccb7`), fetched 2026-11-03: three cameras, “Basic Auto-calibration via OpenCV” marked done, “Scoring via OpenCV (`geometry_detector`)” marked WIP, “Improved accuracy & self-calibration” not scheduled. [`docs/api.md`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md) marks `POST /calibrate/start` as WIP; `GET /calibrate/status` is listed. Score messages carry a pixel `position`, not millimetres.

The geometry detector source is past a README claim. [`ellipse_processing.hpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/calibration/ellipse_processing.hpp): double ring from ray casts (3° step, outlier cuts on ring width in **pixels**), triple and bull from contours, each as a `RotatedRect`. [`perspective_processing.hpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/calibration/perspective_processing.hpp) holds a `DartboardSpec` in millimetres — bull 6.35 / 15.9, triple **99 / 107**, double 162 / 170 — and a `rectifyBoard(rvec, tvec, cameraMatrix)` helper. The scorer that was opened, [`score_processing.cpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/detection/score_processing.cpp) `getScoreAtPoint`, does not use that spec. It tests the tip pixel against the fitted ellipses and the angles of the detected wire endpoints, then takes a consensus of the segment **strings** across cameras (two or more agreeing, otherwise the first camera). `dartboard_position` is assigned the pixel tip with an explicit TODO to convert to board coordinates. So a metric spider exists beside an image-space vote, and neither file reports a millimetre residual.

### A-Dartment (Chase Bonfiglio)

First-party write-up, no repository, [chasebonfiglio.com/dart](https://chasebonfiglio.com/dart/), fetched 2026-11-03. Three OV9732 cameras, 1280×720. Calibration: no checkerboard; project twenty sector wires and five ring radii; snap samples to the strongest edge along the curve normal; joint least squares of `k1`, `k2` and the homography. He writes that a pure homography cannot bend, so its residual on those points is the lens. Table, his words: calibration RMS per camera **0.46 / 0.71 / 0.56 mm**, “reprojection residual on the fit’s own ~1,200 snapped edge points”, “in-sample, so it shows the plane fit is consistent with the wires it was fitted to and says nothing about the error on a dart tip.” Segment check on 71 throws, before the learned tip was on the Pi: **53/71 (75%)**, 50/64 when all three cameras saw the dart, 14/57 on an earlier run with one camera out of focus. Tip error in millimetres: “not yet measured.” Radii “measured to the centre of the wire” on a “WDF/BDO regulation” board (451 mm face, 340 mm playing surface). Fusion: cluster tips within 15 mm and average the largest cluster; line intersection on the plane when the dart is a streak. Diffs are masked beyond about 180 mm.

That RMS is the closest published number to a sub-millimetre spider, and it is the residual of the points the fit was built on. His own segment rate on the same rig was 75%.

### Academic: DeepDarts

William McNally, Pascale Walters, Kanav Vats, Alexander Wong, John McPhee, “DeepDarts: Modeling Keypoints as Objects for Automatic Scorekeeping in Darts using a Single Camera”, CVPR Workshops 2021. PDF opened 2026-11-03: [CVF open-access](https://openaccess.thecvf.com/content/CVPR2021W/CVSports/papers/McNally_DeepDarts_Modeling_Keypoints_as_Objects_for_Automatic_Scorekeeping_in_Darts_CVPRW_2021_paper.pdf).

Single steel-tip camera. A YOLOv4-tiny detector finds up to three dart tips and four calibration points on the outer double edge (wire crossings 5/20, 13/6, 17/3, 8/11). Homography is a direct linear transform from those four correspondences. The board centre is the mean of the transformed calibration points; the outer-double radius is the mean distance of those points from the centre; the other rings come from “the ratios between the radii of all circles”. The numeric ratio table was not in the text extraction (it is referenced as footnote 3). Score is polar. They report Percent Correct Score on the **image total**, not per-dart segment accuracy: 94.7% test on the face-on phone set, 84.0% on the angled set. Hand labels matched recorded scores for 97.6% of 1,200 darts. The failure modes they name are missed darts under occlusion, and darts on the edge of a section scored in the wrong section. No multi-view fusion and no separate distortion residual.

No other peer-reviewed steel-tip calibration paper was opened for this note.

## Error budget: what has to be true for >99% Hits

Terms, and who estimates them in code that was opened:

| Term | What it does near a wire | Who estimates it |
|---|---|---|
| Wire thickness and which face is zero | A 1.3–1.9 mm band. Outside-edge, wire-centre, and inside-face models disagree by that much on every camera, independent of the photos. | WDF 4.01 states the thickness and the inside-to-inside width. Madu, ARU-DART, lksmlr, Dart Vader, opencv-steel-darts, and OpenDartboard’s `DartboardSpec` each hard-code one radius set. A-Dartment says wire centres. None of the opened OSS fits the radii from the image. |
| Intrinsics / `k1`,`k2` | A homography cannot represent radial bend. The leftover shows up at the foreshortened ring, which is where doubles are thin in the image. | ARU-DART and lksmlr: chessboard `calibrateCamera`, stored separately. Autodarts docs: software from 0.24.0, chessboard only on older Board Manager. A-Dartment: joint `k1`,`k2` with `H`, in-sample RMS 0.46–0.71 mm. Madu: no term. OpenDartboard scoring path opened here: ellipses in the image, so some bend is absorbed into the ellipse rather than modelled. |
| Plane fit (homography or PnP) | Residual of the correspondences, in millimetres only if the destination is millimetres and outliers are kept. | Madu `H` + inlier RMS vs far-double RMS. ARU-DART `H`, mean error, 5 mm warning. Dart Vader and opencv-steel-darts `H`, no mm RMS in the files read. lksmlr `solvePnP`, pixel reprojection, then triangulation. DeepDarts four-point DLT. |
| Sector rotation (the 20) | An 18° miss is one whole neighbour. A 0.5° miss is ~1 mm at the treble outer wire and ~1.5 mm at the outer double. | Madu: colour suggestion of the warm wedge, then `rotate_offset` in whole sectors, plus a sub-sector image nudge. Autodarts docs: arrows by one field. Dart Vader: `closest_field` roll. OpenDartboard: `wedge20WireIndex`. DeepDarts: the four calibration points carry the orientation. |
| Tip pixel error | Mapped through the local mm-per-pixel, which is worst on the far side of a tilted camera. | Madu: Huber axis, mean of 4 extreme inliers. A-Dartment: classical tip or ResNet-18 heatmap; mm tip error “not yet measured”. lksmlr: detector keypoints then triangulation. opencv-steel-darts: `goodFeaturesToTrack` (README). DeepDarts: keypoint boxes. Commercial systems: unpublished. |
| Multi-view fusion | Disagreement of several millimetres becomes one point. A mean across a wire assigns the empty side of the bed. | Madu: mean within 15 mm, drop the off-board or off-treble side, drop weak and occluded cams. A-Dartment: 15 mm cluster. OpenDartboard scorer opened here: vote the segment string, no mm point. lksmlr: mean of pairwise triangulations. |
| Motion / settle false triggers | A Hit committed on the hand, a bounce, or the previous dart’s footprint is a wrong Segment with a fine spider. | Madu: `stable_num_frames=3`, takeout pixel gates, occlusion radius 8 mm. Autodarts: the same motion knob names, algorithm unpublished. GRAN EYE’s first-party G2 notes: a sound trigger. Scolia: unpublished, with a clear-board requirement at calibration. |

For a Hit rate above 99% on a mix of singles and wire shots, the geometry that has to hold is local, not an area percentage:

- On a double or treble, radial spider error plus radial tip error stays inside the dart’s true distance to the ring wire. The bed centre only has 4 mm of room. Madu’s Accept rule still allows a far-double RMS up to 5.5 mm and a max up to 12 mm, and it allows a `WARN` inlier RMS of 3 mm. Those gates are wider than the bed.
- The radius constants match the faces the point actually scores against (WDF 3.03 and 4.01), or the bias is measured and removed. A 0.4 mm treble-constant difference (107.0 vs 107.4) is already four times a 0.1% scale error at that ring. A 1.5 mm outside-edge versus inside-face bias is larger than A-Dartment’s reported fit RMS.
- Angular error at the treble stays well under the ~0.5–1° already occupied by the wire. Whole-sector rotate-20 fixes 18° mistakes. It does not fix a half-degree twist.
- Distortion is either small in the lens or fitted. Madu’s far-double session notes are the symptom a pure homography leaves on a tilted camera; the inlier RMS does not show it.
- Fusion does not average across a wire. Madu’s outer-double and treble straddles are that rule, with an 8 mm treble window that is exactly one bed width.
- False settles are rare compared with 1% of darts. That term is independent of the spider and is not measured in the calibration RMS.

## Gaps (evidence only)

These are absences and mismatches in the sources above. They are not a build list.

- Madu’s live mapping is a homography and a sector offset. The tree contains no `k1`/`k2` estimate. The far-double residual exists because a projective map was scored on the compressed ring, and the Accept thresholds (5.5 mm RMS, 12 mm max) are larger than half of an 8 mm bed.
- The badge number and the spider graphic are the inlier fit and the ideal circles. `summarize_residuals` is the quantity that keeps the far-double outliers. Residual drawing is off by default. A nudge clears both RMS and the residual field and still leaves the cam Acceptable at `WARN`.
- Madu’s radii are outside edge minus 8.0 mm. WDF 4.01 measures inside-to-inside 8.0 mm and outside edges at 170.0 and 107.4, and it allows wire stock 1.27–1.85 mm ± 0.2 mm. Those sentences do not place the scoring faces on `[162, 170]` and `[99.4, 107.4]`. Ticket [21](issues/21-geometry-radii-from-labels.md) records a hypothesis that Autodarts labels sit nearer 97 mm and 167 mm; that ticket is a pointer, and this pass did not remeasure the labels.
- Open-source radius tables that were opened disagree with each other and with the WDF outside edge by tenths of a millimetre up to several millimetres (opencv-steel-darts 97 / 160 / 7 / 16; lksmlr outer bull 16.0; ARU-DART, Dart Vader, and OpenDartboard’s spec use treble 99 / 107). A homography RMS against the wrong circle reports consistency with the model.
- A-Dartment is the only opened first-party source that states a sub-millimetre board residual and, in the same table, a segment rate of 75% with tip millimetres unmeasured. Commercial pages state 99.5–99.9% class figures and do not state a residual, a radius convention, or a fit.
- DeepDarts’ published score is the total on the image (94.7% / 84.0%), and the authors name section edges as a failure mode. It does not report a millimetre spider RMS.
- No opened commercial source separates calibration error from tip error. Copying a 99.x% claim onto a spider tolerance is not supported by those pages.

## Sources

Fetched 2026-11-03 unless noted.

Madu (this repo): [`src/madu_darts/board/geometry.py`](../../src/madu_darts/board/geometry.py), [`tests/test_board_geometry.py`](../../tests/test_board_geometry.py), [`src/madu_darts/calibration/`](../../src/madu_darts/calibration/) (`autofit.py`, `refine.py`, `homography.py`, `model.py`, `residuals.py`, `overlay.py`, `session.py`, `mount.py`), [`src/madu_darts/hits/`](../../src/madu_darts/hits/) (`detector.py`, `tip.py`, `fusion.py`, `claiming.py`, `config.py`), [`src/madu_darts/motion/`](../../src/madu_darts/motion/), [`src/madu_darts/server/service.py`](../../src/madu_darts/server/service.py), [`src/madu_darts/turn/controller.py`](../../src/madu_darts/turn/controller.py), [GLOSSARY.md](../../GLOSSARY.md), [ADR 0001](../../docs/adr/0001-no-autodarts-cloud.md), [ADR 0002](../../docs/adr/0002-calibration-every-startup.md), [ADR 0004](../../docs/adr/0004-autodarts-shaped-local-stream.md). Session notes: [map.md](map.md). Prior probes: [research-autodarts-behaviour.md](research-autodarts-behaviour.md) (Autodarts ellipse payload and motion knobs; not re-probed).

Rules: [WDF Playing and Tournament Rules rev 20 (2018-02-28) PDF](https://dartswdf.com/storage/uploads/fb05b306-c92c-4f08-b512-affb092a1b3d/2018-02-28_WDF_Playing_and_Tournament_Rules_rev20.pdf), still the playing-rules document named from the [WDF rules index](https://dartswdf.com/rules) in search results the same day. [WDF World Cup Rules rev 28 (2025-08-12) PDF](https://dartswdf.com/storage/uploads/637e0855-6dcb-4e8d-95aa-6f4f54ee4e5e/2025-08-12_WDF_World_Cup_Rules_rev_28.pdf) does not restate section 4 dimensions.

Commercial, first-party pages opened: [Autodarts Setup](https://autodarts.diy/Autodarts-Desktop/Setup/), [Overview](https://autodarts.diy/Autodarts-Desktop/Overview/), [Distortion](https://autodarts.diy/getting-started/distortion/), [Cameras](https://autodarts.diy/getting-started/cameras/); [Scolia FAQ](https://scoliadarts.com/faq/), [Home 2](https://scoliadarts.com/scolia-home2/), [Pro](https://scoliadarts.com/scolia-pro/), [Home](https://scoliadarts.com/scolia-home/), [Home manual PDF](https://scoliadarts.com/wp-content/uploads/2024/02/Scolia-Home-User-Manual.pdf); [Dartsee venue specifics](https://www.dartsee.com/dartsee-venues/specifics), [Dartsee masterlist](https://www.dartsee.com/masterlist); [Target OMNI](https://www.targetdarts.com/omni), [OMNI instructions](https://www.targetdarts.com/omni-instructions), [OMNI user manual PDF](https://www.target-darts.co.uk/media/pdf/OMNI-User-Manual.pdf); [GRAN EYE](https://www.gran-darts.com/graneye), [G2 video-review notes](https://www.gran-darts.com/topics/g2-video-review-instructions).

Open source, raw files opened: [arudart `board_geometry.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/board_geometry.py), [`homography_calculator.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/homography_calculator.py), [`intrinsic_calibrator.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/intrinsic_calibrator.py), [`ring_detector.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/fusion/ring_detector.py); [lksmlr `extrinsic_calibration.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/extrinsic_calibration/extrinsic_calibration.py), [`triangulate.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/triangulation/triangulate.py); [Dart Vader `boardClass.py`](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/src/boardClass.py); [opencv-steel-darts README](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/README.md), [`Calibration.py`](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/Calibration.py), [`GetDart.py`](https://github.com/hanneshoettinger/opencv-steel-darts/blob/master/GetDart.py); [OpenDartboard README](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/README.md), [`docs/api.md`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md), [`ellipse_processing.hpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/calibration/ellipse_processing.hpp), [`perspective_processing.hpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/calibration/perspective_processing.hpp), [`score_processing.cpp`](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/src/detector/geometry/detection/score_processing.cpp). Tree listing SHA `c919ef85998f77789ee99b0a57253d6dbd82b4bb`.

First-party write-up, no repo: [A-Dartment](https://chasebonfiglio.com/dart/).

Paper opened: McNally et al., DeepDarts, CVPRW 2021, [PDF](https://openaccess.thecvf.com/content/CVPR2021W/CVSports/papers/McNally_DeepDarts_Modeling_Keypoints_as_Objects_for_Automatic_Scorekeeping_in_Darts_CVPRW_2021_paper.pdf).
