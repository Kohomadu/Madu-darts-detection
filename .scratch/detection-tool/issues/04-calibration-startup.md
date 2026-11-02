Status: resolved
Type: task
Model: premium
Blocked by: 02, 03

# Calibration every startup

Per-cam Board-plane bind. Match Autodarts Calibration UX: auto-suggest rings / **20** highlight, operator **rotate-20**, warped-board + fitted rings pass/fail, then **Accept**. No Accept → no Hits. Calibration view: three feeds + device/resolution/fps + overlay.

Primary: ADR 0002 + [research-autodarts-behaviour.md](../research-autodarts-behaviour.md) checklist §3.

## Answer

Shipped on Board LAN UI (`:3181`) and verified live 2026-11-01.

Checklist §3 / ADR 0002 covered:
- Auto-suggest rings + **20** highlight (✨ Auto / Auto-calibrate all)
- Operator **rotate-20** (◀ 20 / 20 ▶); live offsets applied per cam
- Warped-board inset + fitted rings with PASS/WARN/FAIL + RMS mm
- **Accept** gate — session shows `accepted: true`, banner “Hits may be claimed”
- Three feeds with USB location, 1280×720@30, overlay

Live accepted session (Board): cam0 PASS 1.27 mm (offset 0), cam1 PASS 1.10 mm (offset 4), cam2 PASS 0.74 mm (offset 16). Orange-aware autofit on `main` (`beda200`).

Residual: fresh Auto on a single noisy frame can still fail intermittently; Accept of a good fit remains the gate.
