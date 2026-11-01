Status: resolved
Type: task
Model: auto
Blocked by:

# Board geometry module

Implement WDF radii + clockwise sector clock + `point_mm → Segment` (`T20`, `D16`, bulls, miss). Unit-test polar edges (wires, ring boundaries). Constants cited from WDF rules per research notes.

Primary: [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) checklist §9 (Autodarts `{name,number,multiplier,bed}` + Madu `T20`/`D16`). Geometry detail: [research-three-cam-approaches.md](../research-three-cam-approaches.md) § Segment mapping.

## Answer

Shipped `madu_darts.board.geometry`: WDF radii (IB 6.35 / OB 15.9 / treble 99.4–107.4 / double 162–170 mm), clockwise sector clock from 20, and `point_mm_to_segment(x, y) → Segment` with Madu `name` (`T20`/`D16`/`S5`/`IB`/`OB`/`MISS`) plus Autodarts-shaped `number`/`multiplier`/`bed`. Board plane: +y toward 20, +x right; sector wires owned by the clockwise-next wedge; outer ring wires inclusive, treble/double inner wires exclusive. Package scaffold under `src/madu_darts/`; 42 polar-edge unit tests in `tests/test_board_geometry.py` (includes scaled Autodarts S2 capture coords).
