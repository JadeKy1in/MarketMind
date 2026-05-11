# MarketMind Phase C -- Completion Report

**Date**: 2026-05-11
**Status**: COMPLETE
**Tests**: 322 passed (from 299 baseline, +23 new)

## Summary

Phase C addressed 4 of 5 known limitations identified in Phase B:

| Limitation | Status |
|---|---|
| `_analyze()` stubs -- no real LLM | RESOLVED -- `chat_with_integrity()` wired |
| In-memory state lost on restart | RESOLVED -- `shadow_runtime_state` table |
| `orchestrate_daily_cycle()` incomplete | RESOLVED -- factory + `asyncio.gather` |
| Test coverage at ~60-65% | IMPROVED -- 322 tests, edge cases covered |
| GapRatio calibration (needs real trades) | DEFERRED to Phase D |

## Architecture Changes

### 1. Base `ShadowAgent._analyze()` -- Real LLM Integration

The base class `_analyze()` method was a stub in Phase B. Phase C wires it to the gateway's `chat_with_integrity()` function, making every shadow capable of real LLM-driven analysis.

The base implementation:
- Calls `chat_with_integrity(model=, system_prompt=, user_prompt=, caller_agent=, temperature=, reasoning_effort=)`
- Constructs `caller_agent` as `"shadow:{shadow_type}:{display_name}"` for traceability
- Parses LLM output into `ShadowVote` objects via `_parse_votes()` (regex on `VOTE_START`/`VOTE_END` blocks)
- Extracts insights via `_extract_insights()` (lines prefixed `INSIGHT:` or `OBSERVATION:`)
- Gracefully handles LLM failures -- returns empty content, zero votes, no crash
- Records `latency_ms` and `quota_used` in the output

Subclasses override `_build_user_prompt()` to customize what gets sent to the LLM:

| Subclass | `_build_user_prompt()` Behavior |
|---|---|
| `ShadowAgent` (base) | Generic: all headlines + market data + VOTE format instructions |
| `ExpertShadow` | Domain-filtered headlines, domain context prefix |
| `DaredevilShadow` | Variant constraints (`DANGER ZONE`, `CONTRARIAN MODE`, `TREND MODE`, `EVENT MODE`) |
| `CatfishAgent` | Consensus challenge prompt with trigger details and "construct best counter-argument" framing |
| `MissedPathAgent` | Counterfactual tracking, no trading votes |

### 2. Shadow Factory (`create_shadow_agent`)

A single factory function at the bottom of `shadow_agent.py` maps `ShadowConfig.shadow_type` to the correct subclass:

```python
def create_shadow_agent(config, state_db, settings) -> ShadowAgent:
    if shadow_type == "expert":      return ExpertShadow(...)
    elif shadow_type == "daredevil":  return DaredevilShadow(...)
    elif shadow_type == "catfish":    return CatfishAgent(...)
    elif shadow_type == "missed_path": return MissedPathAgent(...)
    elif shadow_type in ("temp_event", "challenger", "beta"):
        return ShadowAgent(...)  # base class
    else:
        return ShadowAgent(...)  # base class (fallback)
```

This is the single point of construction used by `orchestrate_daily_cycle()` and ensures every `ShadowConfig` row maps to the correct agent class with the right `_build_user_prompt()` override.

### 3. Parallel Orchestration (`orchestrate_daily_cycle`)

The orchestrator in `shadow_mother.py` was rewritten to use the factory and parallel execution:

- **Shadow instantiation**: Each visible shadow config goes through `create_shadow_agent()` -- no more manual type checks at the orchestration level
- **Concurrency**: All shadow analyses run concurrently via `asyncio.gather(*tasks)`
- **Throttle**: A `Semaphore(max_concurrent_shadows)` limits parallelism, preventing API rate limit exhaustion
- **Error isolation**: Each shadow is wrapped in `_run_one()` which catches exceptions per-shadow. One crashing shadow does not halt others
- **The full pipeline** runs 8 stages in sequence:
  1. Scan events -> create/destroy temp shadows
  2. Create missed_path shadows (Gate 1 rejected directions)
  3. Count active shadows
  4. Run all shadow analyses in parallel (collect votes)
  5. Compute rankings + backfill snapshots
  6. Detect collusion across all votes
  7. Check challenger conditions
  8. Audit emergency quotas

### 4. Position Exit Analysis (`analyze_position_exits`)

A new LLM-driven method on `ShadowAgent` that reviews open virtual positions and decides whether to hold or exit:

- **5-day gate**: Positions held fewer than 5 days are skipped (no LLM call needed)
- **Per-position LLM call**: Each qualifying position gets a dedicated LLM request with position context (direction, entry price, current PnL, days held, position size)
- **Cash reframing injection**: If `cash_reframing_ticker` is set, the `chat_with_integrity()` gateway prepends the `CASH_REFRAMING_PROTOCOL` to the system prompt, making the LLM treat virtual capital as real money for bias reduction
- **Structured output**: LLM returns `EXIT_DECISION: hold|exit`, `EXIT_REASON`, and `CONFIDENCE` fields parsed by `_extract_field()`
- **Safe default**: On LLM failure or unparseable output, `should_exit=False` (hold) -- never liquidate on error
- Returns a list of `PositionCheck` dataclass instances with `should_exit`, `exit_reason`, and `confidence`

### 5. State Persistence (`shadow_runtime_state`)

Phase B state was purely in-memory -- discount rates, emergency quota states, and cumulative slippage were lost on process restart. Phase C adds the 8th SQLite table:

```sql
CREATE TABLE IF NOT EXISTS shadow_runtime_state (
    shadow_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);
```

Two API methods on `ShadowStateDB`:

- `save_runtime_state(shadow_id, state_json)` -- UPSERT with `INSERT OR REPLACE`
- `load_runtime_state(shadow_id)` -- returns JSON string or `None`

**Read-merge-write pattern**: Both `EmergencyQuotaAuditor` and `PaperLiveGapManager` use the same pattern:
1. `load_runtime_state()` to get existing JSON blob
2. Parse into dict (handle `JSONDecodeError` gracefully)
3. Update only their own sub-key (`"emergency_quota"` or `"paper_live_gap"`)
4. `save_runtime_state()` the merged JSON -- preserves other modules' keys

**Rehydration on construction**: Both managers call `load_runtime_state()` in their getter methods (`_get_or_create_state()` for emergency quota, `_get_discount_rate()` for paper/live gap). If no DB state exists, they use defaults (20% discount rate, normal emergency state). If corrupted, they fall back to defaults without crashing.

Tests verify: state survives auditor/manager recreation, state is persisted after audit results, and corrupted JSON falls back gracefully.

## File Changes

| File | Change |
|---|---|
| `shadows/shadow_agent.py` | Base `_analyze()` with LLM call + `analyze_position_exits()` + `create_shadow_agent()` factory + `_build_user_prompt()`, `_parse_votes()`, `_extract_insights()` |
| `shadows/shadow_mother.py` | Parallel orchestration with `asyncio.gather` + `Semaphore` + factory-based agent creation |
| `shadows/expert_shadows.py` | `_build_user_prompt()` override with domain context + `ExpertShadow._analyze()` delegates to super with domain-filtered news |
| `shadows/daredevil_shadows.py` | `_build_user_prompt()` with variant constraints (scalper/fade/trend/news) |
| `shadows/catfish_agent.py` | Consensus-triggered LLM call + `_build_user_prompt()` override with `CONSENSUS DETECTED` framing |
| `shadows/shadow_state.py` | `shadow_runtime_state` table (8th table) + `save_runtime_state()` / `load_runtime_state()` methods |
| `shadows/emergency_quota.py` | DB-backed state rehydration in `_get_or_create_state()` + `_save_state()` with read-merge-write |
| `shadows/paper_live_gap.py` | DB-backed discount rate rehydration in `_get_discount_rate()` + `_save_state()` with read-merge-write |
| `tests/test_shadows/test_shadow_agent.py` | +6 tests: `test_analyze_returns_output_with_mock_llm`, `test_analyze_exit_llm_says_exit`, `test_analyze_exit_llm_says_hold`, `test_analyze_exit_skips_fresh_positions`, `test_analyze_exit_llm_failure_graceful`, `test_analyze_exit_unparseable_output` |
| `tests/test_shadows/test_catfish_agent.py` | Updated with `test_catfish_analyze_with_trigger` using mock LLM |
| `tests/test_shadows/test_expert_shadows.py` | +3 LLM integration tests: `test_expert_analyze_with_mock_llm_produces_votes`, `test_expert_domain_filtering_applied`, `test_expert_empty_llm_response_graceful` |
| `tests/test_shadows/test_daredevil_shadows.py` | +3 LLM integration tests: `test_daredevil_analyze_with_mock_llm`, `test_scalper_must_pick_direction`, `test_fade_master_contrarian_mode` |
| `tests/test_shadows/test_challenger_engine.py` | +1 test verifying `ShadowAgent` base class behavior in challenger context |
| `tests/test_shadows/test_shadow_state.py` | +3 runtime state tests: `test_runtime_state_save_and_load`, `test_runtime_state_overwrite`, `test_runtime_state_missing_returns_none` |
| `tests/test_shadows/test_emergency_quota.py` | +3 persistence tests: `test_state_survives_recreation`, `test_state_persisted_after_audit_result`, `test_corrupted_runtime_state_graceful` |
| `tests/test_shadows/test_paper_live_gap.py` | +2 persistence tests: `test_discount_rate_survives_recreation`, `test_discount_rate_default_when_no_state` |
| `tests/test_shadows/test_llm_integration.py` | NEW -- 3 cross-cutting tests: factory type dispatch, caller_agent parameter, all shadow types analyze without error |

## Known Limitations (Phase D)

1. **GapRatio calibration** still uses permanent 20% baseline -- needs real trade data to calibrate per-asset, per-strategy discount rates. The current `update_discount_rate()` moves toward the floor (5%) as inter-shadow gap converges, but the starting point is arbitrary.

2. **No OAuth/API key rotation** for the LLM gateway. All shadow calls share a single key. A production-ready system needs credential rotation and per-model rate limit tracking.

3. **Shadow methodology prompts are inline strings** in `expert_shadows.py` and `daredevil_shadows.py`. For maintainability they should move to external configuration files (YAML/JSON) that can be edited without touching application code.

4. **No shadow performance visualization**. The UI has `shadow_panel.py` and `shadow_status_card.py` from Phase B, but there is no dashboard for historical performance comparison, ranking trends, or discount rate evolution over time.

5. **No multi-day backtest** of shadow consensus signal quality. The orchestration runs daily cycles, but there is no batch replay mode to validate whether shadow voting consensus is predictive across historical periods.

## Verification

```bash
python -m pytest projects/marketmind/tests/ -q
# 322 passed in ~21s
```

Tests cover:
- LLM integration with mock `chat_with_integrity` across all shadow types
- Factory type dispatch for all 7 config types
- Position exit analysis (hold, exit, skip, failure, unparseable)
- Runtime state persistence (save, load, overwrite, missing, corrupted)
- Emergency quota state survival across auditor recreation
- Paper/live gap discount rate survival across manager recreation
- Domain filtering for expert shadows
- Daredevil variant constraint prompts
- Catfish consensus trigger and non-trigger paths

## Next: Phase D

Phase D scope (TBD):
- Real trade data integration for GapRatio calibration
- Multi-day backtesting of shadow consensus signal quality
- UI dashboard for shadow rankings and performance visualization
- External configuration files for methodology prompts
- Credential rotation and rate limit management for LLM gateway

---

## Post-Phase-C Fixes (2026-05-12)

Red Team C audit identified 1 CRITICAL + 5 WARNING items. All resolved before Phase D entry:

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| C-1 | CRITICAL | Read-merge-write race on shared `shadow_runtime_state` row | Split into `emergency_quota_state` + `paper_live_gap_state` tables |
| W-5 | WARNING | Two modules sharing one state_json blob (C-1 root cause) | Same fix as C-1 |
| W-3 | WARNING | `chat_batch_flash` single failure cancels entire batch | try/except per-item in `_one()` |
| W-4 | WARNING | `CASH_REFRAMING_PROTOCOL.format()` crash on `{}` in ticker | `.format()` → `.replace()` |
| W-2 | WARNING | `_extract_field()` unescaped parameter in regex | Added `re.escape(field)` |
| W-1 | WARNING | Headline prompt injection via control sequences | Zero-width-char defanging (preserves information) |
| Tests | — | 12 warnings (coroutine, feedparser, scipy) | Fixed mock patterns + filterwarnings |

**Final test count**: 339 passed, 0 warnings.

All 6 INFO items confirmed benign (parameterized SQL, fail-closed defaults, JSON corruption fallbacks complete).
