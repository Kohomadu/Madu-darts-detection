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
- Calibration every startup ([04](issues/04-calibration-startup.md) resolved): LAN Calibration view on `:3181` — auto-suggest / rotate-20 / warped-board PASS+RMS / Accept gate; live Board accepted all three cams (RMS ~0.7–1.3 mm). Orange-aware autofit on `main`.
- Live throw schema ([06](issues/06-live-throw-schema-confirm.md) resolved): Autodarts 2.1.0 still exposes stuck-dart `throws[]` on local `/api/state` + WS `state` events (flat fields: `coordsX/Y`, `segmentName`, `method: UnanimousCam`). inventwo “cloud-only throws” is wrong here. Capture under `captures/06-live-throw-2026-11-02/`.
- **Detection pipeline plan (2026-11-02)**: checklist §4–14 sliced into grouped, live-testable tickets, each gated on the one before:
  [07](issues/07-visit-recorder-shadow-compare.md) recorder + shadow-compare (auto) →
  [08](issues/08-motion-gate-settle.md) background/motion/settle (auto) →
  [09](issues/09-tip-localization-fusion.md) tip + fusion → first Hit (premium; classical first, accuracy gate ≥90 % singles / ≥80 % doubles-trebles, ≤4 mm median) →
  [10](issues/10-turn-takeout-state-machine.md) Turn/takeout state machine (auto) →
  [11](issues/11-detection-view-event-stream.md) Detection view + Madu stream (auto).
  Decisions: real labelled data first (Autodarts local `throws[]` as reference); classical tip before learned; Autodarts-2.1-shaped local stream ([ADR 0004](../../docs/adr/0004-autodarts-shaped-local-stream.md)); Detection view in the same `:3181` app.

## Fog

- Homography-only vs later PnP/triangulation if doubles are noisy.
- Learned tip detector only if 09’s classical gate is missed (decided classical-first).
- Autodarts `coordsX/Y` normalisation scale — derive from 07 recordings.
- Windows USB device identity stability for the three cams (Linux board uses USB location `7.2/7.3/7.4`) — ingest supports `location_index_overrides` until a stable Windows enumerator exists.
