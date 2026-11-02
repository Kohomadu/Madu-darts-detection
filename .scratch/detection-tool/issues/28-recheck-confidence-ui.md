Status: ready-for-agent
Type: task
Model: auto
Blocked by: 17, 18

# Detection UI: Recheck / Hit confidence and “kept prior”

After Recheck hardening, operators cannot see *why* a Hit stayed or changed (method, conf, kept-prior). Surface that on the Detection strip and optional meta line.

## Scope

1. Hit chips / meta: show `method`, confidence, and a flag when Recheck kept the previous Hit (`madu.keptPrior` or similar on API).
2. Recheck button: brief toast/status (“updated 1 Hit, kept 2”) from response state.
3. No change to scoring rules; read-only UX + small API field if missing.

## Done when

- Live Detection view makes weak BestCam / kept-prior obvious without opening captures.
- Smoke test or screenshot in Answer.
