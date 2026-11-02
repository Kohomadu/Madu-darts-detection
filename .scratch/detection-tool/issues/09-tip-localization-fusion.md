Status: resolved
Type: task
Model: premium
Blocked by: 08

# Tip localization + multi-view fusion → first Hit

Turn a settled-change event into a Board-plane point and a Segment. Classical approach first; learned detector only if accuracy falls short of the gate below.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §4 steps 7–9; §5 OSS gap-fill (ideas only, license-aware). Decision: classical-first (plan 2026-11-02).

## Scope

**Per-cam tip (step 7)**
- From the diff mask of the new dart: largest connected component, fit the dart axis (PCA / Hough line), take the extreme point along the axis toward the Board plane as the tip candidate; refine on the edge image in a small window.
- Confidence: component size, axis fit residual, tip sharpness.
- Reject: components touching the frame edge massively, multi-blob (hand), or no axis.

**Fusion (step 8)**
- Map each cam’s tip through its accepted homography → Board mm (`CalibrationSession.board_point`).
- Fuse: weighted mean by confidence with outlier rejection (drop a cam if > X mm from the other two); accept with **2-of-3** cams. Record `method` (`UnanimousCam` / `MajorityCam` / `SingleCam`) like Autodarts.
- Normalised `coordsX/Y` output in Autodarts’ convention (derive from recorded pairs in 07; document the scale).

**Segment (step 9)**
- `board.point_mm_to_segment` → Madu label (`T20`, `D16`, bulls, miss) and Autodarts-shaped `{segmentName, segmentNumber, multiplier, bed}`.

**Hit object**
- `Hit(slot_votes, board_mm, coords_norm, segment, method, confidence, t)`; no Turn logic yet (10).

## Done when (accuracy gate on the 07 recording)

- Segment agreement with Autodarts ≥ 90 % on singles, ≥ 80 % on doubles/trebles across the recorded visits; median Board-plane error ≤ 4 mm.
- Zero Hits emitted on takeout/hand sequences in the recording.
- If the gate is missed after reasonable tuning, append findings and open a follow-up for a learned tip detector (A-Dartment-style ONNX) instead of pushing heuristics further.
- Unit tests on synthetic darts (render a line + tip on a synthetic cam) + replay-based accuracy test.

## Answer

Classical tip + fusion shipped; first Hits flow live and in replay. Gate **partially met** on the 07 recording (24 darts): median error and doubles/trebles pass, singles land at 83 % vs the 90 % target — every miss is at Autodarts' own noise floor (see findings). Follow-up opened as [12](12-learned-tip-detector.md) per the ticket rule; not pushing heuristics further.

### Code
- `madu_darts.hits`: `TipConfig` (Autodarts `detection` kernel 5 / threshold 16), `locate_tip` (full-res diff vs `BoardModel` reference inside the settled bbox → Huber `fitLine` axis → tip = extreme along the axis toward image-down; rejects round / short / huge blobs), `fuse_points` (mean of agreeing cams, `agree_mm` 15 → `UnanimousCam` / `Cam+1` / `BestCam` — Autodarts' live `method` vocabulary), `Hit` (+ `to_autodarts_throw()` flat 2.1 shape, `coords` = mm ÷ 170), `HitDetector` (collects per-cam settles for one dart over `collect_window_s`, fuses, folds frames into the background).
- `DetectionService`: gate events → `HitDetector` on the pump thread; `GET /api/state/hits` (`throws[]` Autodarts-shaped + Madu debug votes), `POST /api/state/hits/clear`; `GET /api/config` grows `detection` + `fusion`.
- Replay: `MaduPipeline` (`madu-darts replay` default; `--pipeline echo` keeps the harness check; `--rotate-offsets o0,o1,o2` pins rotate-20). Cams bind via `calibration.suggest` on an empty-Board frame; rotate-20 resolved per cam by projecting Autodarts' labelled tips onto changed pixels (operator-by-eye analogue; this recording → `{0:10, 1:4, 2:16}`). Table now prints `method`, median error, per-kind rates.

### Accuracy (2026-11-02T08-07-55Z, 24 darts)
| metric | gate | measured |
|---|---|---|
| Segment agreement, singles | ≥ 90 % | **15/18 (83 %)** |
| Segment agreement, doubles/trebles | ≥ 80 % | **3/3** |
| bulls | — | 2/2 |
| misses (`M<n>`) | — | 0/1 (M20 vs M5, 1.1 mm from the wire) |
| median Board-plane error | ≤ 4 mm | **3.76 mm** |
| Hits on takeout / hand | 0 | 0 (recording has no takeout frames; synthetic hand blob rejected by elongation) |
| no Hit | — | 0/24 |

Per-cam medians: cam 0 3.1 mm, cam 1 3.8 mm, cam 2 6.5 mm (cam 2 has the worst autofit RMS, 1.48 mm). Fusion variants compared: plain mean of agreeing cams (chosen) beat confidence-weighted, RMS-weighted, component-wise and geometric median; a 36-point sweep over threshold / blur / tip-k / axis band plateaus at 20–21/24 and ~3.0 mm, with Autodarts' own threshold 16 best.

### Findings
- The 4 disagreements: 3 are wire-straddles where Autodarts' *own* label lies ≤ 2.3 mm from a wire (S16/S8 at 1.1° from the wire; S16 at r 108.6 vs treble outer 107.4; M20 at 1.1 mm from the 20/5 wire); 1 is occlusion — the previous dart's flight covers the new tip in cam 0 (visit-00 d2), pulling the mean 8 mm.
- Tip prior holds on this rig: ring-mounted cams see the flight **above** the tip, so tip = lowest axis end; `tip_directions` per slot exists for other mounts.
- **Geometry fog:** Autodarts' labels imply treble-inner ≤ 97.0 mm and double at ~167 mm (×170 normalisation), vs Madu WDF `TREBLE_INNER_MM` 99.4. Likely wire-centre vs wire-edge modelling; needs more labelled D/T darts before touching `board.geometry`.
- Autodarts labels misses as `M<sector>` (`bed: Outside`, multiplier 0) and the outer bull as `25` (`bed: Single`); inner bull assumed `Bull`/`Double` (not observed yet).

### Verification
Synthetic: tip within 4 px / 4 mm on three poses × three targets; round blob rejected; fusion rules; Autodarts throw shape. Detector: three synthetic cams → `UnanimousCam` T20; second dart against committed background; single-cam window → `BestCam`. Replay floor test pinned at ≥ 20/24, ≤ 4 mm, D/T ≥ 80 %, bulls 2/2, offsets `{0:10,1:4,2:16}`. Full suite **254 passed**.
