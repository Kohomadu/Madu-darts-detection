# Madu Darts

Local automatic dart scoring: cameras observe a fixed Board and produce scored Hits. Near-term work is a local detection tool; match UI and game modes come later. Winmau Autodarts Detection is the quality north star for detection behaviour; Madu reimplements that class of logic locally so a custom UI never depends on Autodarts’ cloud API or proprietary binary.

## Language

**Board**:
The physical steel-tip dartboard the system is calibrated to, including standard WDF scoring segments (1–20 with single/double/treble rings, outer bull 25, inner bull 50).
_Avoid_: Target, face

**Hit**:
One dart that has stuck in the Board and been assigned a scoring segment (and thus a score value). Emitted per dart, not per visit. A bounce-out or fall is not a Hit.
_Avoid_: Throw, dart event, detection, miss

**Turn**:
The span from the first stuck dart of a player's throw until those darts are removed from the Board. Removal ends the Turn and clears the Detection view’s Hit strip. Game-mode rules (who throws next, 501 math) are outside this definition.
_Avoid_: Visit, round, leg

**Segment**:
A named scoring region on the Board (e.g. T20, S5, D16, outer bull, inner bull) that a Hit is assigned to.
_Avoid_: Slice, bed, field, zone

**Calibration**:
The operator step that binds the three cameras to the Board’s geometry and Segment map so Hits can be assigned. Every detection-process startup runs Calibration before Hits are claimed. Success must be visible in the Calibration view (camera feeds + Segment overlay). Operator accepts the suggested alignment.
_Avoid_: Setup, mapping, alignment (as synonyms for this gate)

**Detection view**:
The operator surface that shows a virtual Board with detected dart positions and a top Hit strip of up to three Segment labels for the current Turn. Controls: Calibrate, Reset, Stop.
_Avoid_: Match UI, scoreboard, game screen

**Calibration view**:
The operator surface for camera device/resolution/fps settings and live feeds with Segment overlay used to complete Calibration.
_Avoid_: Cameras page (except as casual shorthand)

**Recording**:
A saved visit from the live Board used for offline development: the three cameras’ frames around each stuck dart plus Autodarts’ local throw list as reference labels. A dev-time artefact only; the product never reads Autodarts at runtime.
_Avoid_: Dataset (too generic), capture (reserve for raw API dumps)
