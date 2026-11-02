Status: resolved
Type: task
Model: auto
Blocked by: 09, 10

# Fusion: drop occluded cam tips before the mean

Ticket 12 option 2: when a cam’s tip lands inside a previously committed dart’s footprint (or very near a stuck tip), that view is unreliable. Down-weight or drop it before `fuse_points` so clustered Turns stop pulling Hits toward occluders.

## Scope

1. Given committed Hits (Board mm + optional image footprints), mark per-cam tip votes as occluded when inside a footprint / within a mm radius of a prior tip.
2. Fusion: drop occluded cams if ≥1 other cam remains; if all occluded, keep BestCam among non-occluded motion or refuse.
3. Unit test with two synthetic stuck darts where cam X’s tip for dart 2 falls on dart 1’s shaft projection.
4. No API change to `throws[]` shape; optional `madu` debug flag `occludedSlots`.

Out of scope: learned tip (27); Recheck multi-blob association.

## Done when

- Synthetic / replay case: occlusion no longer shifts Segment across a wire vs classical mean.
- 07 replay does not regress overall floor.
- Answer notes radius / footprint rule chosen.

## Answer

A cam tip is **occluded** when (a) its tip pixel sits in that cam’s padded settled bbox from a prior Hit (`occlusion_bbox_pad_px=24`), or (b) its Board-mm tip is within `occlusion_tip_radius_mm=8` of a prior tip **and** at least one peer tip is farther — so peers moved on while this cam stayed on the stuck dart.

`fuse_points(..., occluded=…)` drops those slots only when ≥1 clear cam remains. If every cam is marked occluded (clustered real darts), the classical pool is kept. `TurnController` passes prior footprints + tip mm into `HitDetector.poll`. Debug: `madu.occludedSlots` on the Hit API.

Synthetic: cam0 on the S20 side of the 20|1 wire, cams 1+2 on S1 within `agree_mm` — classical mean → T20; with cam0 occluded → T1.

07 recording replay: **21/24** (was 20/24), median **3.24 mm**, D/T 3/3, bulls 2/2, visits 8/8.
