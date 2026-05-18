# Phase H — investigation_loop.py Extraction

**Updated**: 2026-05-18 — Extraction complete, 243 tests pass, investigation_loop.py at 486 lines

## Extraction Summary

Architecture CRITICAL #1 fixed: `investigation_loop.py` (was 918 lines) extracted to 5-module structure.

### Extracted Modules

| Module | Lines | Type | Description |
|--------|-------|------|-------------|
| `investigation_loop.py` | **486** | Glue | Orchestration + remaining phases |
| `investigation_types.py` | 81 | Data | HypothesisResult, InvestigationConfig |
| `investigation_prompts.py` | 94 | Data | _PRE_ACT_SYSTEM, _EXPECTATION_GAP_SYSTEM, _BEAR_CASE_SYSTEM, _NARRATIVE_PROMPT |
| `hvr_cycle.py` | 328 | Behavioral | run_hvr_cycle() + _refine_hypothesis() + H-SEC-2 cap checks |
| `investigation_direction.py` | 107 | Helper | extract_direction, estimate_risk_level, estimate_time_window |

### Import DAG (glue → modules → data)
- `investigation_loop.py` imports from `hvr_cycle`, `investigation_prompts`, `investigation_direction`, `investigation_types`
- `hvr_cycle.py` imports from `investigation_types` only (no glue back-imports)
- All modules import from `investigation_types` as needed
- Data modules have no behavioral imports

### Backward Compatibility
- `investigation_loop.HypothesisResult` — re-exported from `investigation_types`
- `investigation_loop.InvestigationConfig` — re-exported from `investigation_types`
- `investigation_loop._classify_layer_interpretation` — re-exported from `hvr_cycle`
- `investigation_loop.run_investigation_loop()` — signature unchanged
- `investigation_loop.TriageResult` — unchanged alias

### Verification
- [x] Syntax check: all 5 files pass
- [x] Line count: investigation_loop.py = 486 (under 500 hard ceiling)
- [x] Test suite: 243/243 pipeline tests pass
- [x] investigation_loop tests: 18/18 pass
- [x] Public API unchanged: run_investigation_loop signature preserved
- [x] H-SEC-2 pro_calls_counter preserved in all extracted functions
