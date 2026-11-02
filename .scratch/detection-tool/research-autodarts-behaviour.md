# Autodarts Detection behavioural study (Madu planning)

**Stance:** Autodarts Detection is Madu’s **quality north star**. Study and reimplement observable behaviour. Do **not** depend at runtime on Autodarts cloud, account, or proprietary binary ([ADR 0001](../../docs/adr/0001-no-autodarts-cloud.md)). Open-source peers are **secondary** gap-fillers where algorithms aren’t published.

**Live board:** `http://100.118.240.5:3180` — Autodarts client **2.1.0**, Vision **3.0.0**, OpenCV **5.0.0** (`GET /api/version`, `GET /api/host`). Probed 2026-11-01. Board was idle in takeout (`throws: []`); throw object shapes below are from primary protocol captures + adapters when live throws weren’t present.

---

## 1. Official docs (Calibration, Vision, cams)

| Topic | What Autodarts documents | URL |
|-------|--------------------------|-----|
| Desktop = companion that runs Detection; multi-cam required; count fixed by hardware | Setup wizard: sign-in → board name → cams (device, resolution, FPS, standby) → calibrate → test throws | https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/ |
| Calibration UX | Auto-locate **20** (red highlight); arrow buttons rotate Segment overlay until it sits on physical 20 | Same + DIY Setup |
| Distortion | From software ≥0.24.0, lens distortion handled in software — no separate manual distortion step | https://autodarts.diy/Autodarts-Desktop/Setup/ · Overview |
| Vision diagnostics | Advanced/DIY mode → eye button. Tabs: **Motion**, **Movement**, **Detection**, **Calibration** | Desktop docs Vision section |
| Motion tile | Yellow = current movement (impact or still settling) before classification | Desktop docs |
| Movement colours | **Green** = current; **Yellow** = same spot as previous; **Red** = motion gone (fell out / shifted); **Gray** = last dart unchanged | Desktop docs |
| Calibration Vision tab | Each cam warped onto board with fitted rings — pass/fail check | Desktop docs |
| Home / board states | Home shows Throw / Takeout / Takeout detection + recognized darts; Restart / Stop / Reset | https://autodarts.diy/Autodarts-Desktop/Overview/ |
| Config per cam | Resolution, FPS, standby; 180° flip; magic-wand calibrate; left/right rotate-20; optional auto-calibrate-all | Overview Configuration |
| Board Manager ≤0.x | Served at `http://localhost:3180`; **not supported from v2**; Desktop/Headless sign-in replaces board ID/API key paste | Desktop docs |
| DIY kit framing | 3 USB cams, LED ring, local compute; claimed high accuracy; game modes on play site | https://autodarts.diy/ |

**Implication for Madu:** Mirror this UX semantics (rotate-20, spiderweb/warp check, Motion yellow settle, Movement green/yellow/red/gray footprints, takeout clear) without shipping their UI binary.

---

## 2. Live local HTTP / WS surface (2.1.0)

### Working GET endpoints (this board)

| Path | Role | Observed shape (summary) |
|------|------|--------------------------|
| `GET /api/version` | Detection/client version | plain `2.1.0` |
| `GET /api/config` | Full knobs | see §2.1 |
| `GET /api/state` | Board lifecycle + throws array | see §2.2 |
| `GET /api/host` | OS / CPU / OpenCV / visionVersion | `clientVersion`, `visionVersion: "3.0.0"`, `openCVVersion: "5.0.0"`, hostname, etc. |
| `GET /api/devices` | Enumerate USB cams + formats | 3× `USB Camera`, bus `USB 7.2/7.3/7.4`, id includes `location=…-usb-0:7.N:1.0`, MJPG resolutions |
| `GET /api/cams/state` | Cam pipeline | `{isOpened, isRunning}` |
| `GET /api/cams/stats` | Per-cam FPS | `{fps:[30,31,30], resolution:{width:1280,height:720}}` |
| `GET /api/state/stats` | Process load | `{cpuPercent, fps, width, height, memoryBytes}` |
| `GET /api/config/cam/resolution` | Active res | `{width:1280,height:720}` |
| `GET /api/config/calibration/ellipses` | Fitted ring geometry per cam | cams `"0"|"1"|"2"`: `bull[x,y]`, `doubleInner/Outer`, `trebleInner/Outer` each `{angle,x,y,width,height}`, plus 20-point rings `*Points` |
| `GET /api/cams/controls/{0\|1\|2}` | UVC controls | brightness, contrast, hue, saturation, sharpness, gamma, backlight, powerLineFrequency, WB, exposure… |
| `GET /api/streams/live?cam={0\|1\|2}` | Live cam MJPEG | `multipart/x-mixed-replace; boundary=advisionmjpg` (Board Manager cameras page). Optional `&warp=true`, `&update=onDart`. |
| `GET /` | Legacy Board Manager shell | HTML loads `autodarts-web.js` + `autodarts-web.wasm` (Emscripten UI, not a REST route map) |
| `GET /autodarts-web.js` / `.wasm` | WASM UI | ~8.5 MB wasm; algorithms not readable as source |

### WebSocket

| Endpoint | 2.1.0 observation |
|----------|-------------------|
| `ws://HOST:3180/api/events` | **Connects** (HTTP GET → 404). Idle listen produced no snapshot — matches Board Manager 1.0.7 evidence: **push deltas only**; client must HTTP-GET first then merge. |
| Other `/ws`, `/api/ws` | Fail to connect |

**Historical envelope** (Board Manager **1.0.7** capture corpus, primary evidence — not guessed):  
`{"type":"<name>","data":{…}}` with types `state`, `motion_state`, `stats`, `cam_stats`, (`cam_state`, `calibration_state` documented as subscribed by shipped client).  
Source: https://github.com/jonaswre/autodarts-nixos/blob/main/protocol/EVIDENCE.md

### 404 / gone on this 2.1.0 build (GET)

`/api/throws`, `/api/numThrows`, `/api/state/motion`, `/api/config/calibration` (GET), `/api/config/distortion`, image snapshot paths tried, `/api/start|stop|reset` as GET.

### Mutating routes (documented / captured — **not exercised** on the live board this study)

From Board Manager 1.0.7 client extract (`protocol/actions.json`) and inventwo:

| Method | Path | Effect |
|--------|------|--------|
| `PUT` | `/api/start`, `/api/stop` | start/stop detection |
| `POST` | `/api/reset` | reset current visit |
| `POST` | `/api/restart` | restart Board Manager |
| `PATCH` | `/api/config` | patch config |
| `POST` | `/api/config/calibration/auto` | auto-calibrate all cams |
| `POST` | `/api/config/calibration/auto/{camera}` | one cam |
| `POST` | `/api/config/calibration/auto/{camera}/rotate-left` | **rotate-20** (and likely rotate-right sibling in UI) |
| `PUT` | `/api/config/calibration` | replace calibration |
| `PUT` | `/api/config/distortion…` | distortion model |
| `PATCH` | `/api/cams/controls/{camera}` | UVC controls |

OPTIONS on `/api/config`, `/api/state`, `/api/config/calibration/auto` advertise `GET, PUT, POST, PATCH, OPTIONS` on 2.1.0 — consistent with routes still existing even when GET of some paths 404s.

**Madu constraint:** do not call these as a product dependency; they are evidence of Autodarts’ control surface and Calibration UX (especially **rotate-left**).

### 2.1 Config shape (live)

```json
{
  "auth": { "apiKey": "", "boardId": "<uuid>" },
  "cam": {
    "autoCalibrateOnStart": false,
    "autoDistortion": false,
    "cams": [
      "vid=0bda&pid=5844&serial=…&location=…-usb-0:7.2:1.0",
      "…:7.3:1.0",
      "…:7.4:1.0"
    ],
    "fps": 30, "fpsMax": 30, "width": 1280, "height": 720,
    "syncControls": false
  },
  "detection": { "kernel": 5, "threshold": 16 },
  "host": { "port": "3180", "tls…": "…" },
  "linkServer": { "enabled": false, "interfaces": [], "name": "" },
  "motion": {
    "kernel": 3,
    "scale": 4.0,
    "stableNumFrames": 3,
    "standbyMinutes": 60,
    "threshold": 16
  }
}
```

**Cam identity:** same VID/PID/serial on all three; **USB location** (`7.2/7.3/7.4`) is the stable discriminator — Madu should prefer path/location over index.

**Older 1.0.7 config** (snake_case, richer): also exposed `board_rois`, per-cam `calibration` quads, full `dartboard` ellipse point clouds, `distortion` K/d/error, `rotate_180`, `stable_num_frames`. Live 2.1 camelCase config is thinner via `/api/config`, but **ellipse geometry remains** at `/api/config/calibration/ellipses`.  
Source: https://raw.githubusercontent.com/jonaswre/autodarts-nixos/main/protocol/testdata/captures/board-1.0.7-post-calibration/http/config.json

### Interpreting motion / detection knobs (behavioural)

Autodarts does not publish algorithm source. Observable + Vision docs imply:

| Knob | Likely meaning for Madu to match |
|------|----------------------------------|
| `motion.scale: 4` | Downscale factor before motion (1.0.7 `stats` streams often show **320×180** while cams are 1280×720 → 4×) |
| `motion.kernel: 3` | Small morphology / blur kernel on motion mask |
| `motion.threshold: 16` | Pixel/diff threshold for “moving” |
| `motion.stableNumFrames: 3` | Consecutive quiet frames required before **settle / commit** (Vision: yellow until settled) |
| `motion.standbyMinutes` | Cam standby after idle |
| `detection.kernel: 5` | Larger kernel for dart/tip mask vs motion |
| `detection.threshold: 16` | Threshold for dart-vs-background classification |

---

## 2.2 `/api/state` lifecycle

### Live 2.1.0 (idle takeout)

```json
{
  "connected": true,
  "event": "takeoutStarted",
  "running": true,
  "status": "takeoutInProgress",
  "throws": []
}
```

Notes:

- Event/status strings are **camelCase** on 2.1 (`takeoutStarted` / `takeoutInProgress`).
- Board Manager **1.0.7** used spaced Title Case: `"Takeout started"`, `"Takeout in progress"`, `"Throw"`, `"Throw detected"`, `"Calibration finished"`, `"Starting"`/`"Started"`, `"Stopping"`/`"Stopped"`.
- inventwo maps both eras: status `Throw` → green traffic light; `Takeout` / `Takeout in progress` → yellow.  
  Source: https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/main.js

### Throw object schema (when populated — 1.0.7 capture; Madu should emit equivalent locally)

From https://raw.githubusercontent.com/jonaswre/autodarts-nixos/main/protocol/testdata/captures/board-1.0.7-three-darts/http/state.json:

```json
{
  "connected": true,
  "event": "Throw detected",
  "numThrows": 3,
  "running": true,
  "status": "Takeout",
  "throws": [
    {
      "coords": { "x": 0.295…, "y": -0.458… },
      "segment": {
        "bed": "SingleInner",
        "multiplier": 1,
        "name": "S2",
        "number": 2
      }
    }
  ]
}
```

Evidence notes ([EVIDENCE.md](https://github.com/jonaswre/autodarts-nixos/blob/main/protocol/EVIDENCE.md)):

- `coords` are **normalized board-plane floats** (may be negative).
- Segment beds include at least `SingleInner` (expect Double/Treble/Bull beds in richer sessions).
- `name` is Autodarts label (`S2`, `T20`, …); Madu glossary prefers `T20`/`D16`/bulls — map 1:1.
- Every state update carries the **full visit-so-far**, not only the newest dart.
- Takeout **started** retained the three throws; takeout **finished** → `numThrows: 0`, throws omitted; status back to `Throw`.
- Zero-dart false takeout possible while cams stabilize; `POST /api/reset` recovers without restart.

### Live 2.1 throw plumbing (confirmed 2026-11-02)

- `GET /api/throws` / `/api/numThrows` → **404** (still).
- **Stuck-dart `throws[]` still populates locally** on `GET /api/state` and on `ws://…/api/events` `{type:"state", data}` — inventwo’s “v2+ cloud-only throws” claim is **false for this 2.1.0 Board**.
- Live visit: S18 → S20 → S14; after 3rd dart `status:"takeout"`, `event:"throwDetected"`. `numThrows` absent/null.
- 2.1 throw objects are **flat** (`coordsX`/`coordsY`, `segmentName`/`segmentNumber`/`bed`/`multiplier`, plus `method` e.g. `UnanimousCam`, `bouncer`, `failed`) — not the nested 1.0.7 `{coords:{x,y}, segment:{…}}` shape.
- **`coordsX/Y` normalisation:** Board-plane mm ÷ outer-double radius **170 mm** (`DOUBLE_OUTER_MM`). Live S18/S20/S14 radii land in the matching beds via `point_mm_to_segment` after `* 170`. See ticket [07](issues/07-visit-recorder-shadow-compare.md) / `madu_darts.record.meta.COORDS_NORM_RADIUS_MM`.
- Capture: [captures/06-live-throw-2026-11-02/](captures/06-live-throw-2026-11-02/).  
  Source: https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/README.md

**Madu must own its own Hit stream** — matching Autodarts *behaviour*, not their cloud bus.

---

## 2.3 `motion_state` (internal pipeline — gold for Madu)

From 1.0.7 takeout WebSocket capture (primary). Fields Madu should reproduce as internal state (not necessarily expose identically):

```json
{
  "type": "motion_state",
  "data": {
    "camStates": [
      {
        "backgroundPixels": 0,
        "boardPixels": 0,
        "dartBackgroundPixels": 0,
        "dartPixels": 0,
        "isDart": false,
        "isHand": false,
        "isStable": true,
        "isTakeout": false,
        "takeoutBackgroundPixels": 0,
        "takeoutPixels": 0
      }
    ],
    "class": 0,
    "darts": 3,
    "frameCounts": { "dart": 0, "hand": 0, "stable": 0, "takeout": 0, "wait": 0 },
    "frameFlags": { "dart": false, "hand": false, "takeout": false },
    "isDart": false,
    "isHand": false,
    "isStable": false,
    "isTakeoutFull": false,
    "isTakeoutPartial": false,
    "isWaiting": false,
    "timings": { "copy": …, "diff": …, "takeout": …, "total": … }
  }
}
```

Behavioural reading aligned with Vision docs:

1. Per-cam **diff / pixel budgets** (`*Pixels`) drive masks.
2. Classification flags: dart vs hand vs takeout vs stable.
3. **`frameCounts.stable`** increments toward settle; ties to `stableNumFrames`.
4. Hand-in-view → takeout partial/full → board empty → clear visit (`Takeout finished` → status Throw).
5. Processing runs a **diff-heavy** loop (`timings.diff` dominates).

---

## 3. Adapters: what still works locally on v2

| Adapter | Local still useful | Needs cloud for throws |
|---------|--------------------|-------------------------|
| **inventwo ioBroker.autodarts** | Poll `/api/state` for connection + board status; `/api/host`, `/api/config`; `POST …/calibration/auto` for calibrate button | **Yes** on v2 (`CloudClient` → `api.autodarts.com` auth + `play.ws.autodarts.com` channels `autodarts.boards` / `.matches`) |
| inventwo traffic light | `Throw` → green; Takeout* → yellow; offline → red | — |
| inventwo throw score | `(segment.number ‖ 0) * (segment.multiplier ‖ 0)` | Same shape expected from cloud-normalized state |
| **Mastershort/ha-autodarts-local** | Claims local `:3180` status + throws (best on pre-v2; verify against your build) | — |
| **jonaswre/autodarts-nixos protocol** | Best **primary** schema corpus for 1.0.7 Board Manager HTTP+WS | Play match checkout is cloud `gs/v0` / `autodarts.matches` — out of Madu scope |

Cloud auth endpoints (document only — Madu must **not** integrate):  
`https://api.autodarts.com/auth/v1/login`, refresh; WS `wss://play.ws.autodarts.com/ms/v0/subscribe` with board topics `{boardId}.events|.state|.matches`.  
Source: https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/lib/cloud.js

---

## 4. Madu pipeline checklist (match Autodarts behaviour first)

Ordered steps Madu’s detection tool should implement. Each line is an Autodarts-shaped requirement; OSS notes are **fillers only**.

1. **Three USB cams, fixed geometry**  
   - Autodarts: hardware-fixed cam count; 1280×720@30 typical; standby minutes.  
   - Identity by USB **location** (not serial alone).  
   - OSS filler: Dart Vader / ARU-DART OpenCV capture patterns.

2. **Cam image controls**  
   - Lock exposure/WB where possible (Autodarts exposes full UVC control panel).  
   - Optional 180° flip per cam (docs).  
   - OSS filler: V4L2/DirectShow property setters.

3. **Calibration gate every startup** ([ADR 0002](../../docs/adr/0002-calibration-every-startup.md))  
   - Auto-suggest board rings / **20** highlight.  
   - Operator **rotate-20** (left/right) until overlay matches physical 20.  
   - Show **warped board + fitted rings** (Vision Calibration tab analogue) → **Accept**.  
   - Autodarts stores ellipse/ROI geometry (`/api/config/calibration/ellipses`; older full dartboard point clouds).  
   - OSS filler: ARU-DART wire-intersection clicks + spiderweb; Dart Vader ellipse/Hough auto; A-Dartment edge-snap ideas; `lksmlr` PnP if plane fit fails later.

4. **Background / board model**  
   - Maintain empty-board reference; fold scored darts into background after commit (A-Dartment/ARU-DART idea; Autodarts Movement gray/yellow implies footprint memory).

5. **Motion gate (Motion tile = yellow)**  
   - Downscale by ~`scale` (4), kernel 3, threshold 16 — start from Autodarts defaults, tune on hardware.  
   - OSS filler: frame-diff + morphology (Dart Vader, ARU-DART).

6. **Settle via `stableNumFrames`**  
   - Do **not** emit a Hit on first motion frame.  
   - Require N consecutive stable frames (config default **3**) after motion drops — matches Vision “settling” and `motion_state.isStable` / `frameCounts.stable`.  
   - OSS filler: ARU-DART `settled_timeout`; A-Dartment ~1.5 s still — prefer **frame-count** to match Autodarts knobs.

7. **Tip / dart localization (Detection tile)**  
   - Proprietary algorithm unpublished.  
   - OSS filler: classical tip-from-diff (ARU-DART / Dart Vader line); optional later ONNX tip (A-Dartment).

8. **Multi-view fusion → board plane**  
   - Autodarts emits normalized `coords.x/y` then Segment.  
   - Prefer per-cam homography (or H + light undistort) → fuse cluster / weighted average; reject outliers; allow 2-of-3.  
   - OSS filler: Dart Vader line intersection; ARU-DART angular fusion; `lksmlr` triangulation optional.

9. **Segment labels**  
   - Map `(r,θ)` with WDF radii + clockwise 20-sector clock.  
   - Emit Madu Segments (`T20`, `D16`, …) while remaining able to speak Autodarts-like `{name, number, multiplier, bed}` for interoperability tests.  
   - OSS filler: ARU-DART / `lksmlr` / opencv-steel-darts polar code (license-aware).

10. **Hit commit + Turn strip**  
    - Cap 3 Hits; full visit retained until clear.  
    - Bounce-out / fall: Movement **red** semantics — retract Hit, do not score as stuck.  
    - Glossary: bounce-out ≠ Hit.

11. **Takeout / empty-Board clear**  
    - Detect hand (`isHand`) → takeout partial/full → board empty → clear strip; status back to “may throw”.  
    - Autodarts Home: Throw vs Takeout vs Takeout detection.  
    - OSS filler: ARU-DART PullOutStarted; Dart Vader hand + empty match.

12. **Operator Detection view**  
    - Virtual Board + up to 3 Segment slots; Calibrate / Reset / Stop (glossary + Autodarts Home controls).

13. **Local event stream (Madu-owned)**  
    - Prefer Autodarts-shaped visit updates (full throws array + status/event) **produced by Madu**, e.g. local WS — never Autodarts cloud.  
    - Optional internal debug stream mirroring `motion_state` for a Vision-like diagnostic UI.

14. **Standby / start-stop**  
    - Match standbyMinutes behaviour and explicit Start/Stop/Reset semantics for operator control.

---

## 5. OSS gap-fill map (only where Autodarts source missing)

| Autodarts-shaped step | Best OSS filler | License caution |
|-----------------------|-----------------|-----------------|
| Cam ingest + diff motion | Dart Vader, ARU-DART ideas | MIT / no-license (ideas only) |
| Settle SM | ARU-DART state machine ideas | No LICENSE → don’t copy code |
| Tip classical | Dart Vader line; ARU-DART tip heuristic | MIT / ideas |
| Homography calib UX | ARU-DART clicks; Dart Vader auto ellipse | as above |
| Rotate-20 UX | **Autodarts docs + local API** (primary) | — |
| PnP / triangulation fallback | `lksmlr/autodarts` | Apache-2.0 |
| Polar Segment | WDF + any Apache/MIT scorer | Prefer non-GPL |
| Local WS API shape | OpenDartboard ideas | GPL-3 — don’t derive unless intentional |
| Learned tip | A-Dartment writeup ideas | No repo |

---

## 6. Explicit non-goals

- No Autodarts account, cloud WebSocket, or embedding `autodarts-web.wasm` / Detection binary in Madu product path.
- No pretending inventwo cloud mode is a Madu dependency.
- Studying Autodarts (docs, live `:3180`, Vision semantics, protocol captures) **is** desired and recorded here.

---

## Sources (primary)

1. Live Board HTTP/WS probes — `100.118.240.5:3180` (2026-11-01).  
2. https://autodarts-docs.pages.dev/getting-started/detection/autodarts-desktop/  
3. https://autodarts.diy/Autodarts-Desktop/Setup/ · https://autodarts.diy/Autodarts-Desktop/Overview/ · https://autodarts.diy/  
4. https://raw.githubusercontent.com/inventwo/ioBroker.autodarts/main/README.md · `main.js` · `lib/cloud.js` · `lib/trafficLight.js`  
5. https://github.com/jonaswre/autodarts-nixos/tree/main/protocol (`EVIDENCE.md`, `actions.json`, capture fixtures)  
6. Madu `GLOSSARY.md`, `docs/adr/0001`, `docs/adr/0002`

*Research date: 2026-11-01.*
