# Three-camera steel-tip dart scoring: approaches Madu can reuse

## Summary

> **Correction (2026-11-01):** Autodarts Detection is Madu’s **quality north star**, not a casual UX skim. We want as much of its detection *logic/behaviour* as observation allows. Open-source peers are **gap fillers** where algorithms aren’t published. The only hard no is **runtime dependence** on Autodarts cloud/account/binary (custom-UI lock-in risk) — see ADR 0001.

Autodarts-class scorers share one geometry story: bind each camera to a millimetre Board plane (homography and/or multi-view extrinsics), wait for stick-and-settle after motion, localize the tip (or dart axis), fuse views, then map `(r, θ)` to a Segment via WDF radii and the clockwise 20-sector clock. Autodarts Detection remains proprietary (no published CV source); v2+ product path uses cloud for some throw plumbing, but the **local Board process still exposes useful config/state** (see live probe below). OSS peers (ARU-DART ideas; Apache-2.0 `lksmlr/autodarts`; MIT Dart Vader) implement similar pipelines when we need concrete code. Madu should match Autodarts behaviour first, borrow OSS only where needed, and ship its own local Hit stream for custom UIs.

## Autodarts-first (quality north star)

Full behavioural study: **[research-autodarts-behaviour.md](research-autodarts-behaviour.md)** (issue [05](issues/05-autodarts-behavioural-study.md)).

Design order for Madu:

1. Match Autodarts **observable** behaviour: Calibration rotate-20 + warp/rings check; motion knobs (`scale`/`kernel`/`threshold`/`stableNumFrames`); Vision Motion/Movement colours; settle-then-Hit; takeout clear; Segment labels; local visit state machine.
2. Use live `:3180` + official docs + protocol captures as the spec.
3. Only then borrow OSS implementations for unpublished CV steps (tip, fusion, etc.).
4. Never runtime-depend on Autodarts cloud/account/binary ([ADR 0001](../../docs/adr/0001-no-autodarts-cloud.md)).

### Live Board probe (Autodarts 2.1.0 @ Tailscale `:3180`)

- `GET /api/version` → `2.1.0`; `GET /api/host` → `visionVersion: 3.0.0`, OpenCV `5.0.0`
- `GET /api/config` → cams by USB **location** `…-usb-0:7.2/7.3/7.4`, `1280×720@30`; **motion** `{kernel:3, scale:4, stableNumFrames:3, threshold:16, standbyMinutes:60}`; **detection** `{kernel:5, threshold:16}`; `autoCalibrateOnStart:false`; `linkServer.enabled:false`
- `GET /api/state` → e.g. `{event:"takeoutStarted", status:"takeoutInProgress", throws:[]}` — takeout is first-class locally
- Still local: `/api/devices`, `/api/cams/state|stats`, `/api/state/stats`, `/api/config/calibration/ellipses` (bull + double/treble ellipses + 20-point rings), `/api/cams/controls/{0,1,2}`
- `ws://HOST:3180/api/events` **connects** (delta push; no initial snapshot) — HTTP GET of that path is 404
- `GET /api/throws`, `/api/numThrows` → **404**; inventwo: v2 throw payloads moved to **cloud** WS — Madu must emit its own Hits
- UI at `/` is Emscripten (`autodarts-web.js` + `.wasm`), not a REST map

Throw object schema (from Board Manager 1.0.7 primary captures when visit scored):  
`throws[].coords.{x,y}` normalized plane floats + `segment.{name,number,multiplier,bed}` (e.g. `S2` / `SingleInner`). Madu should match this *behaviour* on a local stream.

## Systems / sources reviewed

| System | Role for Madu | URL |
|--------|---------------|-----|
| Autodarts Desktop / DIY docs | UX & Calibration UX reference; proprietary Detection; account + cloud path | https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/ · https://autodarts.diy/ · https://autodarts.diy/Autodarts-Desktop/Setup/ |
| inventwo ioBroker.autodarts README | Documents Autodarts local `:3180` vs cloud throw events | https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/README.md |
| OpenDartboard | Local 3-cam FOSS; WS/REST API; detector plugin interface | https://github.com/OpenDartboard/OpenDartboard · https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md |
| ARU-DART (`geziefer/arudart`) | Closest Python 3-cam pipeline (calib, tip, fusion, Segment, settle/pull-out) | https://github.com/geziefer/arudart |
| TH Nürnberg `lksmlr/autodarts` | Python YOLO + PnP extrinsics + triangulation + polar score | https://github.com/lksmlr/autodarts |
| Dart Vader (`j0j0i996/dart-vader-detection`) | Python OpenCV 3-cam; line→homography→intersection; SocketIO | https://github.com/j0j0i996/dart-vader-detection |
| A-Dartment (Chase Bonfiglio) | First-party writeup of Autodarts-inspired 3-cam; **no public repo** | https://chasebonfiglio.com/dart/ |
| opencv-steel-darts | 2-cam OpenCV; ellipse→homography; clarifies Segment mapping | https://github.com/hanneshoettinger/opencv-steel-darts |
| WDF Playing & Tournament Rules | Authoritative Board radii / segment clock | https://dartswdf.com/storage/uploads/fb05b306-c92c-4f08-b512-affb092a1b3d/2018-02-28_WDF_Playing_and_Tournament_Rules_rev20.pdf |
| Madu ADRs / glossary | Local-only constraint; Calibration every startup; Hit/Segment language | `docs/adr/0001-no-autodarts-cloud.md` · `docs/adr/0002-calibration-every-startup.md` · `GLOSSARY.md` |

## Calibration approaches

### Autodarts (reference UX; closed Detection)

- Multi-camera required; count is fixed by hardware, not a user choice. Operator picks device, resolution, FPS, standby per cam; optional 180° flip. ([Autodarts Desktop docs](https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/))
- Calibration: auto-locate the **20** field (red highlight); arrows rotate the Segment overlay until it sits on physical 20. From software ≥0.24.0, lens distortion is handled in software—no separate manual distortion step. ([Setup](https://autodarts.diy/Autodarts-Desktop/Setup/), [Overview](https://autodarts.diy/Autodarts-Desktop/Overview/))
- Vision → Calibration tab: each camera view **warped onto the board** with fitted rings—fast pass/fail check. ([Vision section](https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/))
- Older Board Manager (≤0.x): `http://localhost:3180`; drag markers / Auto; v2 Board Manager **not supported**—signin in Desktop/Headless connects the board. ([Board Manager note](https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/))
- Local calibrate trigger still documented by third-party adapters: `POST http://<board-ip>:3180/api/config/calibration/auto` ([ioBroker.autodarts](https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/README.md)). **Detection algorithms are not published.**

### Homography / plane mapping (dominant open approach)

**Idea:** Board face ≈ plane. Per camera, map image pixels ↔ board millimetres with `cv2.findHomography`, then tip_board = H · tip_pixel. Overlay “spiderweb” (rings + sector wires) for human confirm—matches Madu Calibration view.

- **ARU-DART**: Manual click of **wire–wire intersections** (bull + inner-triple / outer-double boundaries at N/E/S/W). ≥4 points → RANSAC homography; live 4× zoom; spiderweb overlay for confirmation. Chessboard **intrinsic** calibration is separate (`--calibrate-intrinsic`). ([`manual_calibrator.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/manual_calibrator.py), [`board_geometry.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/calibration/board_geometry.py), [README](https://raw.githubusercontent.com/geziefer/arudart/main/README.md))
- **Dart Vader**: Auto-cal via HSV color masks → ellipses → Hough sector lines → `findHomography` to a standardized board image; `closest_field` rotates correspondence so camera pose (e.g. near 18/2/11) aligns Segment order. Manual fallback from JSON click points. Overlay warped board for check. ([`boardClass.py`](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/src/boardClass.py), [readme](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/readme.md))
- **A-Dartment** (ideas only; no repo): No checkerboard. Project known sector wires + five ring radii into the image, snap samples to edges along curve normals, jointly LS-fit **k1,k2 distortion + homography**. Reports ~0.5–0.7 mm RMS on fit points. ([chasebonfiglio.com/dart](https://chasebonfiglio.com/dart/))
- **opencv-steel-darts** (2-cam, Segment math clarity): Fit ellipse of outer ring; affine-stretch ellipse→circle; map segment-line intersections to a “perfect” board via homography. ([README](https://raw.githubusercontent.com/hanneshoettinger/opencv-steel-darts/master/README.md))

### Multi-view extrinsics + triangulation

**`lksmlr/autodarts`**: Chessboard intrinsics per camera; click 5 world points (12/3/6/9 o’clock at outer double 170 mm + bull); `cv2.solvePnP` → R,t; build projection matrices; tip detections triangulated with `cv2.triangulatePoints` (pairwise, then mean). ([`extrinsic_calibration.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/extrinsic_calibration/extrinsic_calibration.py), [`triangulate.py`](https://raw.githubusercontent.com/lksmlr/autodarts/main/triangulation/triangulate.py))

### OpenDartboard

README claims MVP “Basic Auto-calibration via OpenCV” done; geometry scoring still WIP. Calibration HTTP endpoints are marked **[WIP]** in the API doc. ([README](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/README.md), [api.md](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md))

### Madu fit

Prefer **per-camera homography (or H + light distortion)** with **startup Calibration** and **operator Accept** on spiderweb overlay ([ADR 0002](../../docs/adr/0002-calibration-every-startup.md), [GLOSSARY](../../GLOSSARY.md)). Autodarts’ “rotate until 20 matches” is a good UX pattern; open peers’ wire-intersection clicks are the implementable path. Full 3D PnP/triangulation is optional later if plane fusion is noisy at the double ring.

## Dart / Hit detection approaches

Madu definition: **Hit** = stuck dart assigned a Segment; bounce-out is not a Hit; commit after stick-and-settle; empty board clears the 3-slot strip ([GLOSSARY](../../GLOSSARY.md)).

### Autodarts Vision (behavioural, not source)

- **Motion** tab: yellow = current movement (impact or still settling).
- **Movement** tiles: green = current; yellow = same spot as previous; **red = motion gone** (fell out / shifted); gray = last dart unchanged.
- Implies: detect motion → wait settle → classify landed tip → track previous dart footprints → removal / fall detection. Algorithms unpublished. ([Vision](https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/))

### Motion → settle → tip (open peers)

| Project | Trigger | Tip localization | Multi-view fusion | Empty / pull-out |
|---------|---------|------------------|-------------------|------------------|
| ARU-DART | Persistent frame change; state `idle → motion_detected → dart_detected` | Diff + morphology; tip = higher image-Y end (flight sticks out); shape score `area × aspect × (1−circularity)` | Homography to mm; confidence + angular-weight fusion; outlier reject | State machine: WaitForThrow → ThrowDetected (**settled_timeout ~500 ms**) → WaitForThrow / ThrowFinished; HAND motion → PullOutStarted; clears tracker when board empty ([`throw_state_machine.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/state_machine/throw_state_machine.py), [`motion_classifier.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/state_machine/motion_classifier.py), [DEVELOPMENT_KNOWLEDGE](https://raw.githubusercontent.com/geziefer/arudart/main/DEVELOPMENT_KNOWLEDGE.md)) |
| Dart Vader | Diff consecutive frames → B/W dart blob | Fit line through dart axis per cam | Lines → std board coords; **intersection** of 2–3 lines; 1-cam tip backup | Hand + >1 s continuous motion + board matches last empty state ([readme](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/readme.md)) |
| A-Dartment | Diff inside board ROI; mask beyond ~180 mm | Classical tip or ResNet-18 heatmap ONNX; streak → LS line intersection on plane | Cluster tips within 15 mm; average largest cluster | Hand in view then still ~1.5 s ends visit; scored dart folded into background ([writeup](https://chasebonfiglio.com/dart/)) |
| `lksmlr/autodarts` | YOLO keypoint detect (batch/script style) | Model keypoints | Undistort + triangulate ≥2 cams | Not a full Turn lifecycle in published scripts ([`detect.py` / `triangulate.py`](https://github.com/lksmlr/autodarts/tree/main/triangulation)) |
| OpenDartboard | Detector plugin `process(frames)` → `DetectorResult` | Geometry (default) / AI / custom `.so` | Left to detector | Score strings include `"MISS"`, `"END"` ([detectors.md](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/detectors.md), [api.md](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md)) |

**Bounce-out:** ARU-DART models `DartBounceOutEvent` and periodic checks; Autodarts Movement “red = missing” is the UX analogue. Mid-flight tracking is **not** required by open peers for scoring; Madu correctly scopes it research-only.

**Commit rule that matches peers + Madu:** wait until motion drops for a settle window, then score; do not emit a Hit on the first motion frame.

## Segment mapping

All serious systems convert a board-plane point to polar `(r, θ)` then:

1. **Ring** from `r` (WDF radii).
2. **Sector** from `θ` (20 wedges of 18°, sector **20** at top).

### WDF radii (authoritative)

From WDF Playing & Tournament Rules (rev 20): bull inside diameter **12.7 mm** → radius **6.35 mm**; “25” ring inside diameter **31.8 mm** → radius **15.9 mm**; outside edge of treble to centre **107.4 mm**; outside edge of double to centre **170.0 mm**; double/treble band **8.0 mm** inside-to-inside (wire boards). ([WDF PDF](https://dartswdf.com/storage/uploads/fb05b306-c92c-4f08-b512-affb092a1b3d/2018-02-28_WDF_Playing_and_Tournament_Rules_rev20.pdf))

Open code commonly uses: inner bull ≤6.35; outer bull ≤15.9; triple ≈99–107; double ≈162–170 mm (inner edges ≈ outer − 8). ([ARU-DART `ring_detector.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/fusion/ring_detector.py), [Dart Vader `pol2score`](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/src/boardClass.py), [`lksmlr` `_setup_dartboard_geometry`](https://raw.githubusercontent.com/lksmlr/autodarts/main/triangulation/triangulate.py))

### Sector order

Clockwise from top:  
`20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5`  
([ARU-DART `SectorDetector`](https://raw.githubusercontent.com/geziefer/arudart/main/src/fusion/sector_detector.py), [`lksmlr` segments list](https://raw.githubusercontent.com/lksmlr/autodarts/main/triangulation/triangulate.py))

### Labels Madu wants

Map ring + sector → Segment strings: `T20`, `D16`, `S5`, outer/inner bull (open APIs also use `BULL`/`OUTER`, or structured `{base, multiplier, ring, sector}`). ARU-DART’s `DartHitEvent` / `Score` is a clean local schema ([`dart_hit_event.py`](https://raw.githubusercontent.com/geziefer/arudart/main/src/fusion/dart_hit_event.py)). OpenDartboard streams `"score": "D20"` etc. ([api.md](https://raw.githubusercontent.com/OpenDartboard/OpenDartboard/main/docs/api.md)).

## Local APIs / event streams

| Source | Local? | Shape | Cloud / account? |
|--------|--------|-------|------------------|
| **Autodarts Desktop v2+** | Detection runs on device but product path signs into Autodarts; play via cloud site | Throw data for v2: **cloud WebSocket** (account + board ID). Local `:3180` may still answer connection/cams/status/calibrate; **throws / numThrows no longer provided** on v2 per ioBroker docs | **Yes — account required to use Desktop** ([Desktop docs](https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/), [ioBroker README](https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/README.md)) |
| **OpenDartboard** | Fully local | `ws://<ip>:13520/scores` JSON: `score`, `position`, `confidence`, `camera`, `processing_time`, `timestamp`; HTTP `/health`, WIP `/config`, `/calibrate/*` | No |
| **Dart Vader** | Fully local | Flask-SocketIO on port 3000: `start_dect` / `end_dect` / detection loop emits; REST `PATCH /calibration`, image GETs | No (optional Dropbox helper exists in tree; not required) |
| **ARU-DART** | Local process | In-process `DartHitEvent` / pull-out / bounce-out / miss events; `src/api/` present—treat as evolving; primary interface today is CLI + OpenCV windows | No |
| **A-Dartment** | Local Pi service | “One message type” feed → scoreboard reducer; tuning UI on LAN | No published protocol |
| **`lksmlr/autodarts`** | Local scripts | Function return dict: `success`, `position`, `base_score`, `multiplier` | No |

**Madu should not call Autodarts cloud or embed Autodarts Detection** ([ADR 0001](../../docs/adr/0001-no-autodarts-cloud.md)). A local WebSocket (OpenDartboard-style) or SocketIO (Dart Vader-style) plus Calibration / Detection operator views is enough.

## License & reuse guidance for Madu

| Project | License | Reuse for Madu |
|---------|---------|----------------|
| Autodarts Detection / Desktop | Proprietary (binary + account; source not published) | **UX/ideas only.** No binary dependency, no cloud API. |
| OpenDartboard | **GPL-3.0** ([LICENSE](https://github.com/OpenDartboard/OpenDartboard/blob/main/LICENSE)) | Ideas freely. Copying/deriving code forces Madu GPL. Prefer implement-your-own API shaped similarly. |
| `lksmlr/autodarts` | **Apache-2.0** ([LICENSE](https://raw.githubusercontent.com/lksmlr/autodarts/main/LICENSE)) | **Strongest code-reuse candidate** for PnP, triangulation, polar scoring (retain notices). |
| Dart Vader | **MIT** ([LICENSE](https://raw.githubusercontent.com/j0j0i996/dart-vader-detection/master/LICENSE)) | Code reuse OK with attribution; good for diff→line→homography→intersection and SocketIO patterns. |
| ARU-DART | **No LICENSE file** in repo (default all-rights-reserved) | **Do not copy source.** Treat as the best *design* reference (settle SM, fusion, Segment, Calibration UI). Ask author for a license if Madu wants to fork. |
| opencv-steel-darts | **GPL-3.0** ([README](https://raw.githubusercontent.com/hanneshoettinger/opencv-steel-darts/master/README.md)) | Ideas / Segment math; avoid shipping derived GPL unless intentional. |
| A-Dartment | No public source | Ideas only (edge-snap calibration, cluster fusion, settle/pull-out). |
| WDF rules PDF | Spec document | Use dimensions; not software. |

**Practical Madu stance:** reuse **algorithms and UX patterns** from Autodarts/ARU-DART/A-Dartment; reuse **code** preferentially from **Apache-2.0 / MIT** peers; keep Madu’s license free of accidental GPL unless you choose OpenDartboard as a base.

## Recommended next implementation steps for a Python local tool

Ordered to **match Autodarts** first (detail checklist in [research-autodarts-behaviour.md](research-autodarts-behaviour.md) §4). OSS named only as gap-fill:

1. **Board geometry module** — WDF radii + clockwise sector list + `point → Segment` (`T20`/`D16`/bulls/miss). Prefer emitting Autodarts-compatible `{name,number,multiplier,bed}` alongside Madu labels.
2. **Camera ingest** — 3× USB MJPEG @ Autodarts-like 1280×720@30; lock exposure/WB; identity by USB **location** (live board: `7.2/7.3/7.4`).
3. **Calibration (every startup)** — Autodarts UX: auto-suggest + **rotate-20** + warped rings Accept ([ADR 0002](../../docs/adr/0002-calibration-every-startup.md)). OSS filler for math: ARU-DART clicks / Dart Vader ellipses / optional undistort.
4. **Detection loop** — Motion defaults from Autodarts config (`scale:4`, `kernel:3`, `threshold:16`) → settle via **`stableNumFrames` (3)** → tip → `H` fuse → Segment. Tip/fusion algorithms unpublished → Dart Vader / ARU-DART / `lksmlr` as fillers.
5. **Turn / Hit strip** — Cap 3; Movement red = bounce-out/shift ≠ Hit; takeout/hand → empty-Board clear (Autodarts Home + `motion_state` semantics).
6. **Operator UI** — Calibration + Detection views per glossary; optional Vision-like Motion/Movement debug tiles.
7. **Local events** — Madu-owned stream shaped like Autodarts visit state (`throws[]` + status/event). **No** Autodarts cloud/binary.
8. **Optional later** — PnP/triangulation (`lksmlr`) if plane fusion fails at doubles; learned tip after labelled data.

---

*Research date: 2026-11-01. Claims above are tied to the linked first-party docs/source; Autodarts Detection internals remain unpublished.*
