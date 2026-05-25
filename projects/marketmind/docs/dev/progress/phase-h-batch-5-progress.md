# Phase H Batch 5 — Progress

**Updated**: 2026-05-19 03:20 UTC

## Completed

### Bug Fixes
- [x] Flash JSON trailing comma fix (`_parse_json_response` — added `re.sub(r',\s*([}\]])', r'\1', content)`)
- [x] Flash reasoning fix (`chat_flash` reasoning_effort: max → minimal — fixes empty content)
- [x] Red Team JSON trailing comma fix (`_parse_red_team_response` — same pattern)
- [x] Layer 3 NoneType fix (`float(d.get(k, 0))` → `float(d.get(k) or 0)` — handles LLM JSON null)
- [x] Shadow DB cleanup: 31→24 visible shadows (7 stale entries retired)
- [x] pre_gate1.py comment: 15→16 experts

### Fixture System
- [x] Red Team audit: 2C+2H+2M+2L findings — all fixed in plan
- [x] Fixture plan: `.claude/plans/pipeline-test-fixtures-plan.md` — Red Team fixes applied
- [x] Fixture infrastructure: `test_fixtures/__init__.py` (load/save/scrub/hash/staleness/force-guard)
- [x] Fixture conftest: `test_fixtures/conftest.py`
- [x] Synthetic fixtures: 3 JSON files (stage1_scout, stage2_flash_normal, stage2_flash_empty)
- [x] Fixture tests: 7 tests in 0.20s

### E2E Verification
- [x] Pipeline runs 10/10 stages end-to-end
- [x] Flash: 25 scored, 3 Pro browse (was 0/0)
- [x] Shadows: 24 initialized (was 31)
- [x] PICA-Regression: 1295 passed, 0 regressions

### PICA Artifacts (10 new/updated)
```
.claude/audits/phase-h/
  pica-unit-flash_triage.json
  pica-unit-red_team.json
  pica-unit-async_client.json
  pica-unit-layer3_technical.json
  pica-security-flash_triage.json
  pica-security-red_team.json
  pica-security-async_client.json
  pica-security-layer3_technical.json
  pica-integration-async_client.json (pending)
  pica-regression.json (updated — 1295/0)
```

## Remaining (Not Critical)

| Issue | Severity | Root Cause | Action |
|------|:---:|------|------|
| HVR 0 hypotheses | MEDIUM | Pre-Act planner expects direction/confidence/event_type but TriageResult doesn't have these — FLASH_TRIAGE_SYSTEM_PROMPT output schema mismatch | Design discussion needed — add fields to Flash output OR change Pre-Act to use classification+scores |
| Layer 3 0 green tickers | LOW | No market data provided (mock mode) | Expected — needs real market data feed |
| Regime text garbled | LOW | Terminal encoding for Chinese chars | Cosmetic only |
| Token budget exhaustion (last batch) | LOW | Transient — API rate limiting for last batch of 348 headlines | Monitor; increase budget if recurring |

## Files Modified
```
pipeline/flash_triage.py — trailing comma + debug logging + import re
pipeline/red_team.py — trailing comma + debug logging + import re
pipeline/layer3_technical.py — None-safe float conversion
pipeline/pre_gate1.py — comment fix (15→16)
gateway/async_client.py — chat_flash reasoning_effort: max→minimal
test_fixtures/__init__.py — created
test_fixtures/conftest.py — created
test_fixtures/stage1_scout_normal.json — created
test_fixtures/stage2_flash_normal.json — created
test_fixtures/stage2_flash_empty.json — created
tests/test_fixtures/test_pipeline_with_fixtures.py — created (7 tests)
.claude/plans/pipeline-test-fixtures-plan.md — created + Red Team fixes
```

## Shadow DB State
```
Before: 17E + 13D + 1 catfish = 31 visible
After:  16E + 8D = 24 visible
```
