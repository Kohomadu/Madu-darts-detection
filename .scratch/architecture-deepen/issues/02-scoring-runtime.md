Status: needs-triage
Type: grilling
Model: auto
Blocked by: hit-claiming

# ScoringRuntime seam (live + Recording replay)

Architecture review **Worth exploring**. Live DetectionService and Recording replay both hand-wire BoardModel + MotionGate + HitDetector + TurnController (+ Calibration bind). That is a real second adapter, but the shared behaviour has no deep module — only duplicated construction. DetectionService is a shallow god-orchestrator (cameras, Calibration, Turn, Recheck, override, LiveStore, Autodarts state).

## Problem

Replay cannot reuse DetectionService without cameras/HTTP. Takeout / Hit / Recheck interactions lack one interface both paths exercise. Pays off **after** Hit claiming is one seam.

## Direction

Deepen a ScoringRuntime: Accept/bind projection + process frame batch + recheck + override + snapshot. Live = cameras/pump/CalibrationSession + ScoringRuntime + LiveStore/state stream. Replay = Recording frames + bind + same ScoringRuntime. Two adapters justify the seam (live cams vs Recording frames).

## Involved areas

DetectionService; replay madu_pipeline; Turn controller; Hits detector / claiming; motion stack.

## Done when (after grill + `/to-spec`)

- Spec with one ScoringRuntime interface; live and replay are adapters.
- Recording regressions exercise the same Turn/Hit path as LAN Detection.
- Autodarts-shaped state stays one projection (ADR 0004); no Autodarts runtime (ADR 0001).

## Out of scope here

Calibration Binder; Board observation (may compose inside runtime later); changing throw schema.
