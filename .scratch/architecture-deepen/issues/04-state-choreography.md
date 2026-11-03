Status: needs-triage
Type: grilling
Model: auto
Blocked by:

# Collapse DetectionService state choreography

Architecture review **Speculative**. Almost every Calibration HTTP handler must remember `sync_motion_with_calibration` + `publish_state`. Easy to miss; the interface of “mutate Calibration” is larger than any one route’s body. `api_state` merges Turn snapshot, session snapshot, cameras, madu debug, LiveStore — shallow assembly with many facts callers must keep consistent (ADR 0004).

## Problem

Pain is real but smaller than Hit claiming / Binder. Drift risk on Autodarts-shaped WS updates when Calibration changes.

## Direction

Session mutations go through DetectionService methods that always park/arm Turn and append state; or a small state publisher owned by service so app never dual-calls. Deeper `api_state` builder next to TurnSnapshot projection.

## Involved areas

DetectionService, HTTP app, LiveStore, Turn snapshot / types.

## Done when (after grill + `/to-spec`)

- Spec: one place emits state after Calibration mutate; app does not dual-call sync + publish.
- Locality for “Calibration changed ⇒ detection parked ⇒ WS updated.”
- Reinforces ADR 0004; no conflict with ADR 0003 LAN UI.

## Out of scope here

Hit claiming; Binder internals; redesigning Detection / Calibration views.
