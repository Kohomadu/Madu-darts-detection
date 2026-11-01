# Detection tool

## Notes

First milestone: local Python three-cam detection process + Calibration / Detection operator views. Autodarts behaviour is the quality target; Madu owns the Hit stream (no Autodarts cloud/binary).

**Model routing** (finite premium tokens; Auto unlimited): each issue has `Model: auto | premium | human+auto`. Prefer Auto for well-spec’d plumbing; premium for Autodarts-matching CV/Calibration and hard vision debug.

## Decisions-so-far

- Domain + ADRs: see `GLOSSARY.md`, `docs/adr/0001`–`0003`, grill session closed.
- **Autodarts is the detection quality north star.** We copy behaviour/logic as faithfully as observation allows. Open-source peers are gap-fillers only. What we avoid is *runtime* dependency on Autodarts cloud/account/binary (custom UI lock-in risk) — see ADR 0001 (corrected).
- Research ([01](issues/01-research-three-cam-approaches.md)): useful geometry/API survey, but undersold Autodarts as primary design target. Notes: [research-three-cam-approaches.md](research-three-cam-approaches.md).
- Autodarts behavioural study ([05](issues/05-autodarts-behavioural-study.md) resolved): live 2.1.0 still has local config/state/cams/ellipses + `ws://…/api/events`; takeout local; throws endpoints 404 / v2 throw data reported cloud-only. Pipeline checklist + schemas: [research-autodarts-behaviour.md](research-autodarts-behaviour.md). Madu settles via Autodarts-like `stableNumFrames`, Calibration rotate-20, and a Madu-owned Autodarts-shaped visit stream.
- Board geometry ([02](issues/02-board-geometry-module.md) resolved): `point_mm_to_segment` in `src/madu_darts/board/geometry.py` — WDF radii + clockwise clock; Madu labels + Autodarts `{number,multiplier,bed}`; +y→20 plane.
- Camera ingest ([03](issues/03-camera-ingest.md) resolved): `CameraIngest` in `src/madu_darts/cameras/` — USB location identity (7.2/7.3/7.4), 1280×720@30, exposure/WB lock; by-path on Linux, index overrides on Windows.

## Fog

- Whether stuck-dart `throws[]` still appears in local `/api/state` on 2.1.0 during an active visit (board was idle takeout when probed) — confirm with a live throw session if needed for schema parity tests only.
- Homography-only vs later PnP/triangulation if doubles are noisy.
- Classical tip vs learned tip (after labelled data).
- Exact Madu wire format for Hits (Autodarts-shaped visit vs thinner hit events) — prefer Autodarts visit shape unless UI needs otherwise.
- Windows USB device identity stability for the three cams (Linux board uses USB location `7.2/7.3/7.4`) — ingest supports `location_index_overrides` until a stable Windows enumerator exists.
