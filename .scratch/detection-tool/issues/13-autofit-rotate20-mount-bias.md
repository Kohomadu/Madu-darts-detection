Status: resolved
Type: task
Model: auto

# Autofit suggested-20 is systematically wrong for the ring mounts

Live Board observation (2026-11-02, Madu on `100.118.240.5:3181` after `suggest` / auto-calibrate, all cams at `rotateOffset: 0`).

Autofit finds the Board plane (ellipses / wires bind; RMS ~1.3–2.3 mm) but the **colour / screen-up “suggested 20”** does not match the physical 20 for this three-cam ring. The operator must rotate-20 every startup; the corrections are stable and match the 07-recording offsets from ticket 09 (`{0:10, 1:4, 2:16}`).

## Live notes (operator)

| Cam | Physical mount | What autofit marks as 20 (offset 0) | Correction needed | Implied `rotateOffset` |
|-----|----------------|-------------------------------------|-------------------|-------------------------|
| 0 | Right above the physical **20** | Opposite side → physical **3** | Flip 180° (10 sectors) | **10** |
| 1 | Near physical **16** | Top-of-view wedge is physical **13** | **4 sectors left** | **4** |
| 2 | Near physical **15** | Marks physical **14** as 20 | **4 sectors right** (= 16 left) | **16** |

API snapshot at observation: `accepted=false`, `canAccept=true`, offsets all `0`, cam0/2 `warn`, cam1 `pass`.

## Why this happens (current design)

[`src/madu_darts/calibration/autofit.py`](../../../src/madu_darts/calibration/autofit.py) picks the warm-banded wedge closest to **screen-up** as sector 20 and leaves `rotate_offset=0`. Ring-mounted cams do not look “from the 20 side” in image space the way a fronto synthetic cam does, so screen-up ≠ physical 20. ADR 0002 already requires an operator rotate-20 step; this ticket is about **removing or shrinking that step** for the known mount geometry.

## Improvement directions (pick in triage)

1. **Per-slot default offset** in ingest/config (e.g. `location → rotate_offset` for USB `7.2/7.3/7.4`) applied after `suggest`, still overridable by the Calibration arrows.
2. **Mount-aware suggest**: given known cam azimuth on the ring (above 20 / near 16 / near 15), bias the suggested-20 away from pure screen-up.
3. **Remember last Accepted offsets** per slot across process restarts (local file) and re-apply after autofit.
4. Keep manual rotate-20 only, but surface a clearer “expected offset for this Board” hint in the Calibration UI.

## Done when

- After `POST /api/calibration/auto` on this Board (empty), the red 20 wedge lands on physical 20 for all three cams with **zero** arrow presses, or at most ±1 sector of fine-tune.
- Synthetic / unit autofit tests still pass; document the mount defaults in Calibration help text.

## Answer

Resolved 2026-11-02. Implemented **per-slot defaults + last-Accepted persistence** (triage options 1 + 3).

### Code
- `src/madu_darts/calibration/mount.py` — `DEFAULT_ROTATE_OFFSETS = {0:10, 1:4, 2:16}`, `captures/calibration_offsets.json` load/save.
- `CalibrationSession(default_rotate_offsets=…, offset_store=…)` applies the offset after every successful `suggest`; `accept()` writes current offsets to the store so the next autofit reuses operator fine-tunes.
- `DetectionService` / `ServiceConfig` wire Board defaults + store by default; `madu-darts serve --rotate-offsets 10,4,16` overrides. Tests that need synthetic offset-0 pass `rotate_offsets={}`.
- Calibration page help text mentions the mount defaults.

### Live use
After pull/restart: **Auto-calibrate all** (or startup suggest) should land the red 20 on physical 20 for cams 0/1/2 with no arrows. Fine-tune if needed, then Accept — those offsets stick across restarts via `captures/calibration_offsets.json` (gitignored).
