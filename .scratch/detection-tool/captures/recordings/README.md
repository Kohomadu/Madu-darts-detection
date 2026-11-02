# Visit recordings

Dev-only Autodarts-labelled sessions for offline Madu pipeline work (ticket 07).

Cam JPEGs under `visit-*/cam*/*.jpg` are **gitignored** (large). Meta, session, and calibration JSON are tracked. Re-pull frames with:

```text
madu-darts record --board http://100.118.240.5:3180 --out .scratch/detection-tool/captures/recordings --frames autodarts
```

(`--frames autodarts` reads Autodarts MJPEG at `/api/streams/live?cam=0|1|2` — same feeds as `?page=cameras`.)

## `2026-11-02T08-07-55Z` (preferred — has pixels)

- Board: `http://100.118.240.5:3180` (Autodarts 2.1.0)
- 8 visits / 24 darts (incl. T19, D13, T20, outer bull `25`)
- Frames: Autodarts MJPEG (`--frames autodarts`), ~1239 JPEGs @ 1280×720 (~198 MB locally)
- `calibration.json`: Autodarts ellipses
- Replay: `madu-darts replay .scratch/detection-tool/captures/recordings/2026-11-02T08-07-55Z`

## `2026-11-02T07-45-16Z` (throws-only, superseded)

- 10 visits / 28 darts; empty `cam*` dirs (`--frames none`). Kept for label history only.
