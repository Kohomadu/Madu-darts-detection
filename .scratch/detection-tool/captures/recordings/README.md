# Visit recordings

Dev-only Autodarts-labelled sessions for offline Madu pipeline work (ticket 07).

## `2026-11-02T07-45-16Z`

- Board: `http://100.118.240.5:3180` (Autodarts 2.1.0)
- 10 visits / 28 darts (incl. D16, T4, outer bull `25`, misses)
- `calibration.json`: Autodarts `/api/config/calibration/ellipses`
- Frames: **none** (recorded from Windows while Autodarts held the USB cams). Re-record on the Board with `madu-darts record --frames local` (or `--frames madu`) before tickets 08–09 need pixels.
- Replay: `madu-darts replay .scratch/detection-tool/captures/recordings/2026-11-02T07-45-16Z`
