# 20: Drag the spider onto the wires

**What to build:** When the spider is a fraction off, the operator drags a ring or two wire crossings, Calibration re-solves and remeasures, and Accept uses the new residual. Undo returns to the last Auto. Pan and fine-rotate already exist; this is the wire-level correction, and it cannot leave a stale pass.

**Blocked by:** 35, 22

**Status:** ready-for-agent

Type: task
Model: auto

- [ ] Dragging a visibly off ring moves the spider and replaces the residual
- [ ] Accept stays blocked until the new residual is in
- [ ] Undo restores the pre-drag fit
- [ ] A drag that pushes the far double past the 35 gate cannot be Accepted
