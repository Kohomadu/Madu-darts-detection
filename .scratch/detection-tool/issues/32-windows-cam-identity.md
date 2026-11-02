Status: needs-triage
Type: task
Model: auto
Blocked by: 03

# Stable Windows USB → cam slot binding

Linux Board uses USB location `7.2/7.3/7.4`. Windows ingest still relies on index overrides; reboot/replug can swap cams and silently invalidate Calibration mounts / rotate offsets.

## Scope

1. Survey stable Windows identifiers (device instance path, USB hub port, Media Foundation, OpenCV index drift).
2. Persist slot↔device map (alongside `calibration_offsets.json`); warn on Calibration if binding changed.
3. Keep `location_index_overrides` as escape hatch.

Out of scope: macOS; rewriting the whole ingest stack.

## Done when

- Replug/reboot procedure documented; slots stay stable or operator gets a clear rebind UX.
- Answer: chosen identity scheme + file format.
