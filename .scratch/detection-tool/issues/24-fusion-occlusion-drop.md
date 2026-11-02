Status: ready-for-agent
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
