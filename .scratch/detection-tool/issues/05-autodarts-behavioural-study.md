Status: resolved
Type: research
Model: premium
Blocked by:

# Deep Autodarts Detection behavioural study

Misunderstanding corrected: Autodarts Detection is the **primary** design target (superior quality). Open-source is secondary gap-fill. Goal is to reproduce Autodarts-class logic in Madu so a custom UI never needs Autodarts cloud/binary.

## Scope

Against the live Board (`http://100.118.240.5:3180` / local Autodarts Desktop):

1. Catalogue every still-working **local** HTTP/WS endpoint (config, calibrate, throws if any, vision/state).
2. Document Detection UX semantics: motion → settle → Hit commit; Movement tile colours; bounce-out/red; empty-Board / pull-out clear; Calibration (20-rotate, spiderweb, cam settings).
3. Capture Hit/turn event shapes if locally observable; note what moved to cloud-only on v2+.
4. Derive a Madu pipeline checklist that prioritises matching Autodarts behaviour over OSS defaults.
5. Update [research-three-cam-approaches.md](../research-three-cam-approaches.md) with an “Autodarts-first” section; keep OSS as implementation fillers where algorithms aren’t published.

## Constraints

- Do not make Madu call Autodarts cloud or ship their binary (ADR 0001).
- Studying/observing/reimplementing behaviour is explicitly desired.

## Answer

Primary write-up: **[research-autodarts-behaviour.md](../research-autodarts-behaviour.md)**. Three-cam survey amended with Autodarts-first section: [research-three-cam-approaches.md](../research-three-cam-approaches.md).

**Verdict:** Local Detection on 2.1.0 still exposes rich **config/state/cams/calibration ellipses** and a live **`ws://…/api/events`** channel. Takeout lifecycle is observable locally (`takeoutStarted` / `takeoutInProgress`). Dedicated `/api/throws` is gone; inventwo reports visit throw payloads moved to Autodarts **cloud** on v2 — Madu must emit its own Hit stream. Match Autodarts knobs/UX (`stableNumFrames`, rotate-20, Movement colours, motion_state-style settle/hand/takeout); use OSS only to implement unpublished CV steps.

## Comments
