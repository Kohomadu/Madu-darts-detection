# Kanban — detection-tool

Generated 2026-11-03 08:33 UTC from ticket `Status:` / `Blocked by:` lines. Refresh with `madu-darts kanban`.

| Column | Meaning |
| --- | --- |
| To do | Unblocked, not started (`ready-for-agent`, `ready-for-human`, `needs-triage`, …) |
| Blocked | Open, but a listed blocker is not `resolved` |
| Doing | `claimed` |
| In testing | `in-testing` — code in; live Board check pending |
| Done | `resolved` (or `wontfix`) |

## To do (2)

- [11: Detection view + Madu-owned event stream](11-detection-view-event-stream.md) `ready-for-human`
- [32: Stable Windows USB → cam slot binding](32-windows-cam-identity.md) `needs-triage`

## Blocked (13)

- [12: Decide the tip only after the spider is honest](12-learned-tip-detector.md) `ready-for-agent` — waiting on 26, 35
- [17: Vision Recheck — mid-Turn classical re-detect (Autodarts AI Referee analogue)](17-vision-recheck.md) `ready-for-human` — waiting on 11, 15
- [18: Manual Hit override — Autodarts free-tier score correction](18-manual-hit-override.md) `ready-for-human` — waiting on 17
- [20: Drag the spider onto the wires](20-calib-wire-nudge.md) `ready-for-agent` — waiting on 35, 22
- [21: Scoring-face spider](21-geometry-radii-from-labels.md) `ready-for-agent` — waiting on 33
- [22: Joint radial distortion and homography](22-calib-distortion-k1k2.md) `ready-for-agent` — waiting on 21, 33
- [26: Labelled corpus — ring misses separated from tip misses](26-labelled-corpus-100.md) `ready-for-human` — waiting on 33
- [27: Learned tip on the settled crop](27-onnx-tip-in-crop.md) `ready-for-agent` — waiting on 12
- [28: Detection UI: Recheck / Hit confidence and “kept prior”](28-recheck-confidence-ui.md) `ready-for-agent` — waiting on 17, 18
- [29: Override sealed history visits (v2)](29-history-edit-sealed.md) `needs-triage` — waiting on 18
- [31: Live-tune takeout / standby on real hands](31-standby-takeout-live-tune.md) `needs-triage` — waiting on 10, 16, 11
- [35: Accept refuses a spider that can cross a ring](35-accept-half-bed.md) `ready-for-agent` — waiting on 22, 34
- [36: Fusion stays on one side of a ring wire](36-fusion-one-side-of-wire.md) `ready-for-agent` — waiting on 33, 21, 30

## Doing (0)

_empty_

## In testing (3)

- [30: Camera overlays — tip votes and which side of the wire](30-detection-cam-overlays.md) `in-testing`
- [33: Replay scorecard — ring miss vs neighbour](33-replay-ring-scorecard.md) `in-testing`
- [34: Calibration view shows the far-double residual](34-calib-honest-far-double.md) `in-testing`

## Done (18)

- [1: Research three-cam dart detection approaches](01-research-three-cam-approaches.md) `resolved`
- [2: Board geometry module](02-board-geometry-module.md) `resolved`
- [3: Camera ingest (3× USB)](03-camera-ingest.md) `resolved`
- [4: Calibration every startup](04-calibration-startup.md) `resolved`
- [5: Deep Autodarts Detection behavioural study](05-autodarts-behavioural-study.md) `resolved`
- [6: Confirm live throw schema on Autodarts 2.1.0](06-live-throw-schema-confirm.md) `resolved`
- [7: Visit recorder + shadow-compare harness](07-visit-recorder-shadow-compare.md) `resolved`
- [8: Background model, motion gate, settle (`stableNumFrames`)](08-motion-gate-settle.md) `resolved`
- [9: Tip localization + multi-view fusion → first Hit](09-tip-localization-fusion.md) `resolved`
- [10: Turn state machine: Hit commit, cap 3, bounce-out, takeout clear](10-turn-takeout-state-machine.md) `resolved`
- [13: Autofit suggested-20 is systematically wrong for the ring mounts](13-autofit-rotate20-mount-bias.md) `resolved`
- [14: Reject off-Board motion (arms / body) as Hits](14-reject-offboard-motion.md) `resolved`
- [15: Calibration quality: cam0 RMS / wire fit → doubles & trebles wrong](15-calibration-quality-cam0-dt.md) `resolved`
- [16: Takeout starts but never finishes (empty-Board gate)](16-takeout-finish-empty-gate.md) `resolved`
- [19: Calibration residual overlay — see where the spiderweb is soft](19-calib-residual-overlay.md) `resolved`
- [23: Accept quality gate v2 — refuse pretty-but-soft binds](23-calib-accept-quality-gate-v2.md) `resolved`
- [24: Fusion: drop occluded cam tips before the mean](24-fusion-occlusion-drop.md) `resolved`
- [25: Fusion: prefer inside-treble when cams straddle the treble wire](25-fusion-treble-wire-prefer.md) `resolved`
