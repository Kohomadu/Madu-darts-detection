Status: ready-for-agent
Type: task
Model: auto
Blocked by: 04, 06

# Visit recorder + shadow-compare harness

Record real labelled data from the live Board before writing detection: per visit, save the three cam frames around each stuck dart **plus** Autodarts’ local `throws[]` (confirmed working on 2.1.0, see [06](06-live-throw-schema-confirm.md)). Then a replay harness that feeds a recording through Madu’s pipeline and diffs Madu Hits vs Autodarts throws. This is the test bed for 08–11; development happens offline on Windows against real frames.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) §2.2 (live 2.1 throw schema), §4 step 13 (Madu-owned stream), capture in [captures/06-live-throw-2026-11-02/](../captures/06-live-throw-2026-11-02/).

## Scope

**Recorder (runs on the Board, in the `:3181` process or as a sibling CLI)**
- Subscribe to `ws://<board>:3180/api/events` (fallback: poll `/api/state` at ~5 Hz).
- Keep a ring buffer of the last ~2 s of frames per slot from the existing `FramePump` (reduced rate is fine, e.g. 10 fps).
- On each `throws[]` length increase: dump the ring buffer + the frame at detection + the new throw object. On takeout finish (`throws` → empty): close the visit.
- Also save the accepted Calibration snapshot (`/api/calibration` + homographies/rings) once per recording session so replay can reuse the same bind.
- Layout: `recordings/<session>/<visit-NN>/{meta.json, cam0/*.jpg, cam1/*.jpg, cam2/*.jpg}`; `meta.json` holds Autodarts throws (flat 2.1 shape), timestamps, calibration ref. JPEG q≈90.
- CLI: `madu-darts record --board http://100.118.240.5:3180 --out recordings/`.

**Replay / shadow-compare**
- `madu-darts replay <recording>` → runs the Madu pipeline (whatever exists at that point: motion → settle → tip → fusion → Segment) and prints a per-dart table: Autodarts Segment / coords vs Madu Segment / coords, mm error on the Board plane, agreement %.
- Pure-Python API `replay(recording) -> list[DartComparison]` so later tickets can use it in pytest.
- Autodarts `coordsX/Y` are normalised; derive the normalisation (likely ÷ outer-double radius 170 mm or board radius) from the recorded data and document it.

## Done when

- One recording session from the live Board with ≥ 5 visits (≥ 12 darts incl. at least one double/treble) is checked into `.scratch/detection-tool/captures/recordings/` (or referenced if too large).
- `replay` runs end-to-end on it (with a stub pipeline that just echoes Autodarts) and the comparison table renders.
- Unit tests for ring buffer, visit segmentation from `throws[]` deltas, and meta schema.

## Notes

- Do not depend on Autodarts at runtime in the product path (ADR 0001) — recorder/compare is a **dev tool** only.
- Beware frame/throw time skew: record monotonic timestamps on both sides and the WS receive time.
