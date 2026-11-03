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
- Visit recorder + shadow-compare ([07](issues/07-visit-recorder-shadow-compare.md) resolved): `madu-darts record` / `replay`; `coordsX/Y` = mm÷170; `--frames autodarts` via `/api/streams/live?cam=N` MJPEG. Preferred session [captures/recordings/2026-11-02T08-07-55Z/](captures/recordings/2026-11-02T08-07-55Z/) (8 visits / 24 darts + ~1239 JPEGs locally; meta in git, jpgs gitignored).
- Background / motion / settle ([08](issues/08-motion-gate-settle.md) resolved): `madu_darts.motion` — `BoardModel` + `MotionGate` (`idle→motion→settling→stable`, Autodarts knobs); Accept-gated in `DetectionService`; `GET /api/state/motion` + `/api/config`; Vision tiles on Calibration page. Replay of 07 session: 24×3 settled-change events within 0.5 s of Autodarts; takeout heuristic suppresses.
- Tip + fusion → first Hit ([09](issues/09-tip-localization-fusion.md) resolved, gate partially met): `madu_darts.hits` — `locate_tip` (diff → Huber axis → lowest end), `fuse_points` (mean of agreeing cams; `UnanimousCam`/`Cam+1`/`BestCam` = Autodarts' live vocab), `Hit.to_autodarts_throw()`, `HitDetector`; live `GET /api/state/hits`; `madu-darts replay` now runs the real chain. 07 recording: **20/24**, median **3.76 mm**, D/T 3/3, bulls 2/2, singles 15/18 (83 % vs 90 % gate — all misses ≤ 2.3 mm from a wire or occluded). Heuristics saturated → follow-up [12](issues/12-learned-tip-detector.md) (`needs-triage`: more data first, learned tip only if the gap persists).
- Turn / takeout state machine ([10](issues/10-turn-takeout-state-machine.md) resolved): `madu_darts.turn.TurnController` — Autodarts 2.1 `status`/`event` strings (`throw` → `throwDetected` ×3 → `takeout` → `takeoutInProgress`/`takeoutStarted` → `throw`/`takeoutFinished`), cap 3, bounce-out retraction via pre-commit reference snapshots (`bounceOut`, Madu extension), empty-Board test ≤ 60 px/cam at motion scale, zero-dart false-takeout recovery, standby. `PUT /api/start|stop`, `POST /api/reset`, `GET /api/state/turn`. Replay of 07: **8/8 visits** reproduce Autodarts' throws growth + status/event and clear on takeout (takeout exercised on the next visit's empty frames — recordings hold no hand frames). Next: Detection view + stream ([11](issues/11-detection-view-event-stream.md), auto).
- Takeout empty-Board finish ([16](issues/16-takeout-finish-empty-gate.md) resolved): live visits were sealing only via Reset because finish required ≤60 px vs Accept empty refs while post-visit boards sat ~1k vs dart bg. Now: snapshot full Board on `takeoutStarted`; finish on strict empty, or soft empty (≤500) + footprints gone (≥200 vs full), or soft held 4 s; `madu.emptyDiffPx`/`dartBgDiffPx`/`takeoutFullDiffPx` on `/api/state`.
- Detection view + Madu-owned stream ([11](issues/11-detection-view-event-stream.md) code complete, `ready-for-human` for the live `:3180` side-by-side): `GET /api/state` is now the Autodarts 2.1 shape + `calibration`/`cameras`/`madu` blocks; `ws://…:3181/api/events` pushes `{type:"state", data}` per transition (no coalescing — snapshot taken in `TurnController.on_transition`), `?motion=1` debug channel; `/detection` page (Board SVG, Hit strip, status pill, Start/Stop/Reset/Calibrate, Vision tiles, event log, WS with polling fallback). `serve --synthetic-throws` loops a scripted visit for hardware-free demos. Schema test against the 06 capture + end-to-end WS test through fake cams. **Start/Reset/Accept take the current Board as empty** — press them on an empty Board. Detection-pipeline plan (07–11) is now fully implemented; remaining: live validation, then [12](issues/12-learned-tip-detector.md) triage.
- **Detection pipeline plan (2026-11-02)**: checklist §4–14 sliced into grouped, live-testable tickets, each gated on the one before:
  [07](issues/07-visit-recorder-shadow-compare.md) recorder + shadow-compare (auto) →
  [08](issues/08-motion-gate-settle.md) background/motion/settle (auto) →
  [09](issues/09-tip-localization-fusion.md) tip + fusion → first Hit (premium; classical first, accuracy gate ≥90 % singles / ≥80 % doubles-trebles, ≤4 mm median) →
  [10](issues/10-turn-takeout-state-machine.md) Turn/takeout state machine (auto) →
  [11](issues/11-detection-view-event-stream.md) Detection view + Madu stream (auto).
  Decisions: real labelled data first (Autodarts local `throws[]` as reference); classical tip before learned; Autodarts-2.1-shaped local stream ([ADR 0004](../../docs/adr/0004-autodarts-shaped-local-stream.md)); Detection view in the same `:3181` app.
- Residual overlay ([19](issues/19-calib-residual-overlay.md) resolved): after Auto, measured wire/ring samples are drawn on the Calibration tile (green → red by Board-mm error, magenta arcs on the foreshortened double). `GET /api/calibration` adds `maxResidualMm` and `farDouble` (all samples, not inlier-only). Live empty Board capture `20261102T183706-8fded2`: badge RMS ~1.4 mm while cam0 far-double RMS is 4.6 mm (max 12.5).
- Accept gate v2 ([23](issues/23-calib-accept-quality-gate-v2.md) resolved): far-double RMS > 5.5 mm or max > 12 mm → FAIL + Accept blocked; WARN above 3.5 / 7. Retuned after first live Auto under 4/7 failed every cam while overall RMS was fine.
- Occlusion-aware fusion ([24](issues/24-fusion-occlusion-drop.md) resolved): drop cams whose tip sits in a prior Hit footprint (pad 24 px) or near a prior tip (8 mm) while peers moved on. 07 replay **21/24** (↑ from 20).
- Treble-wire prefer ([25](issues/25-fusion-treble-wire-prefer.md) resolved): keep on-treble vote(s) when peers straddle just inside/outside the treble wires (±8 mm). Twin of outer-double prefer-inside.

## Fog

### Overlay / Calibration backlog

Moved to the accuracy ladder below. PnP and triangulation stay deferred until 22’s far-double residual is still past a half-ring on a real Board.

### Product / reliability

- Recheck confidence UI ([28](issues/28-recheck-confidence-ui.md)); sealed history edit ([29](issues/29-history-edit-sealed.md)).
- Live takeout/standby tune ([31](issues/31-standby-takeout-live-tune.md)); Windows cam identity ([32](issues/32-windows-cam-identity.md)).

### Architecture deepen (2026-11-03 review)

- Hit claiming spec + tip-unify ticket: [../hit-claiming/spec.md](../hit-claiming/spec.md) (`ready-for-agent`).
- Remaining review candidates (needs grilling / `/to-spec`): [../architecture-deepen/map.md](../architecture-deepen/map.md) — Binder, ScoringRuntime, Board observation, state choreography.

### Still open from earlier

- Vision Recheck + Manual override ([17](issues/17-vision-recheck.md) / [18](issues/18-manual-hit-override.md), `ready-for-human`): shipped + Recheck stub hardening (`b57b116`); live human validation continues.
- Calibration / D–T quality ([15](issues/15-calibration-quality-cam0-dt.md), resolved): edge refine shipped. The next bar is the accuracy ladder, not a tighter inlier RMS.

## Kanban

Live board: [kanban.md](kanban.md). Refresh with `madu-darts kanban`. Columns: To do / Blocked / Doing / In testing / Done. Status `in-testing` means code is in and the live Board check is pending (22, 30, 34 right now).

## Accuracy ladder (2026-11-03)

Evidence: [research-spider-calibration-accuracy.md](research-spider-calibration-accuracy.md). An 8 mm double or treble ring leaves 4 mm from its centre to a wire. Inlier RMS and a 99.9% area figure do not protect those Hits. The spider has to be right in millimetres on the foreshortened double, and the tip is a separate error.

Frontier done 2026-11-03: [33](issues/33-replay-ring-scorecard.md) scorecard (07: 21/24, ring_miss 2, neighbour 1), [34](issues/34-calib-honest-far-double.md) far-double badge + nudge rescore, [30](issues/30-detection-cam-overlays.md) tip overlay toggle.

[21](issues/21-geometry-radii-from-labels.md) scoring-face radii **resolved** (WIRE 1.5 → D 168.5/160.5, T 105.9/97.9; 07 still 21/24 ring_miss 2).
[22](issues/22-calib-distortion-k1k2.md) joint radial+H **in-testing**: synthetic lens fixture clears 2/4 and beats H-only; empty `_ticket19/board` improves cam0 8.5→4.7 / cam1 3.8→2.0 but cam0 still above half-bed — ticket stays open. 07 still **21/24**. Next live: retune 22 on Board → [35](issues/35-accept-half-bed.md) → [20](issues/20-calib-wire-nudge.md).

Fusion: [36](issues/36-fusion-one-side-of-wire.md) (unblocked by 33+30; still needs 21).

Tip: [26](issues/26-labelled-corpus-100.md) (unblocked, human throws) → [12](issues/12-learned-tip-detector.md) → [27](issues/27-onnx-tip-in-crop.md).

[15](issues/15-calibration-quality-cam0-dt.md) is resolved. Its inlier-RMS pass is not this ladder’s gate.
