# 30: Camera overlays — tip votes and which side of the wire

**What to build:** On the Detection view, each camera shows its tip, whether that vote was kept, which side of the nearest ring wire it fell on, and the fused Hit projected back. The overlay is off unless the operator turns it on.

**Blocked by:** None (can start immediately).

**Status:** in-testing

Type: task
Model: auto

- [x] With three stuck darts, the operator can see which camera was dropped and which side of the ring each kept vote is on
- [x] Turning the overlay off leaves the stream as it is today
- [x] It works on the live view or on the last capture preview

## Answer

- `draw_hit_debug` draws keep (green) / drop (orange) tip votes and a blue fused cross; labels include Segment and ring side (`inside` / `outside` / `on`).
- Detection Vision has a Tip / Hit overlay checkbox; streams use `/stream/{slot}.mjpg?hitDebug=1`. Default streams stay unchanged when the toggle is off.
- `SlotVote.to_api` includes `ringSide` for the motion-tile text and for 36 later.
- `PATCH /api/calibration/display` accepts `showHitDebug`.
