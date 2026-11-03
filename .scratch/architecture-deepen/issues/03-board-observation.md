Status: needs-triage
Type: grilling
Model: auto
Blocked by:

# Board observation module

Architecture review **Worth exploring**. Turn imports MotionGate’s private helpers for empty / takeout / bounce-out pixel counts — leaky seam. DetectionService reaches into Turn’s private `_board_empty` for Recheck. `BoardModel` is shallow (frame dict); Turn separately owns `_empty_refs` and `_takeout_full_refs`. “Is the Board empty?” knowledge is split with no single interface.

## Problem

Ticket-16 soft takeout and Recheck empty gating cannot be tested or reasoned about in one place. Deletion of BoardModel barely concentrates complexity (Turn already holds the interesting refs).

## Direction

Deepen Board observation: empty capture, dart-background commits, `changed_pixels` / `is_empty` / `darts_removed` behind a public interface. MotionGate uses the same pixel prep or sits beside it. Turn and Recheck stop private imports / peeks.

## Involved areas

Turn controller; motion gate / board_model; DetectionService Recheck empty gate.

## Done when (after grill + `/to-spec`)

- Spec with Board observation as the seam for empty / cleared / changed-pixel questions.
- Soft takeout and Recheck empty gate tested without spinning the full Turn machine.
- No new private peeks from DetectionService into Turn.

## Out of scope here

Hit claiming fusion policy; Calibration; ScoringRuntime extraction (may consume this module later).
