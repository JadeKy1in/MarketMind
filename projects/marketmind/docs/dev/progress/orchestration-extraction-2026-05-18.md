# orchestration.py Extraction — 2026-05-18

## Summary
Extracted `_run_stages_0_3()` and `_run_stages_4_10()` from `orchestration.py` (516 lines) to comply with 300-line glue/orchestration hard ceiling.

## Files changed

| File | Lines | Status |
|------|:-----:|--------|
| `pipeline/orchestration.py` | 172 → 172 | Thin coordinator, under 250 target |
| `pipeline/pre_gate1.py` | NEW — 187 | Stages 0-3 + `_StageTracker` |
| `pipeline/post_gate1.py` | NEW — 195 | Stages 4-10 |

## Exports

- `pre_gate1.run_pre_gate1(config, mock, verbose, shadow_count) -> dict`
- `post_gate1.run_post_gate1(config, state, mock, verbose, gate1_decision=None) -> int`
- `orchestration.run_daily`, `.run_full`, `.run_gate1_mode`, `.run_interactive` — unchanged signatures

## Test results
- 965 passed, 0 failed, 6 warnings
- All 4 import smoke tests pass
- `app.py` imports unchanged — backward compatible

## PICA
- PICA-Unit: 965/965 pass (full suite)
- PICA-Regression: 0 regressions from base (was 913, now 965 from Phase H additions)
- PICA-Security/Integration: N/A — pure extraction, no new logic or API changes

**Updated**: 2026-05-18 — Extraction complete, 965 tests pass
