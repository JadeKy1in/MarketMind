# OPTIMIZATION_REPORT -- Phase B Team Monitor

**Date:** 2026-05-11
**Scout:** Optimization Scout (DeepSeek Flash, agentId: current)
**Status:** 79 tests pass, 1 CRITICAL bug found, 3 HIGH issues, 4 MEDIUM warnings

## Test Execution Summary

```
79 passed, 0 failed, 0 skipped — 8 committed shadow modules
8/8 modules compile OK (py_compile verified)
1 ImportError: test_emergency_quota.py → emergency_quota module not committed yet
```

Complete test results: `projects/marketmind/tests/test_shadows/` — all 79 committed tests pass in 2.98s.

---

## CRITICAL: Runtime Bug in ShadowMother.scan_events

**File:** `projects/marketmind/shadows/shadow_mother.py`, lines 64-69 + 96

**Problem:** `scan_events()` passes `news_items` (a `list[dict]`) to `detect_vol_shock()`, but `detect_vol_shock` expects `market_data: dict[str, float] | None = None`. Since `news_items` is not None, the guard `if market_data is None: return []` does NOT trigger, and the function proceeds to call `market_data.items()` on a list -- raising `AttributeError: 'list' object has no attribute 'items'` at runtime.

**Impact:** Any call to `scan_events()` with non-empty news_items crashes. The vol_shock detector is completely broken.

**Fix:**
- Option A: Change line 69 to `self.detect_vol_shock(None)` and add a separate call site that passes actual market_data when available.
- Option B: Rename the parameter to `news_items` and rewrite `detect_vol_shock` to extract z-scores from news headlines (like the other detectors do).
- Option C: Make `detect_vol_shock` accept `news_items` as a fallback and guard with `isinstance(market_data, dict)`.

**Found during static analysis; not caught by tests because `test_shadow_mother.py` does NOT test `scan_events()` end-to-end -- it only tests individual detector methods.**

---

## HIGH: `close_virtual_position` Trade Lookup Logic Bug

**File:** `projects/marketmind/shadows/shadow_agent.py`, lines 135-145

**Problem:** The method searches for a trade by `trade_id` using:
```python
trades = self.state_db.get_trade_history(self.shadow_id, limit=1)
```
This returns only the single most recent *closed* trade, which almost never matches the `trade_id` being closed. The fallback to `get_open_trades()` does find the correct trade, but the first path is dead code that wastes a DB query on every close.

**Fix:** Replace with a single DB method `get_trade_by_id(trade_id)` or search `get_open_trades()` directly.

---

## HIGH: B.6 Test Uses Non-Existent `.id` Attribute on EmergencyQuotaRequest

**File:** `projects/marketmind/tests/test_shadows/test_emergency_quota.py`, lines 73, 94, 110, 127, 145

**Problem:** The test accesses `pending[0].id` but `EmergencyQuotaRequest` (defined in `shadow_state.py`) is a dataclass without an `id` field. The `record_emergency_quota()` method returns `cur.lastrowid` (an int), not an object with `.id`. The test expects an interface that differs from the existing DB schema.

**Impact:** When Agent 2 commits `emergency_quota.py`, the test will fail unless the agent also modifies `EmergencyQuotaRequest` to include `id` or the test is corrected. This is a specification mismatch between the test (already committed) and the expected module (not yet committed).

**Recommendation:** Agent 2 should be alerted to this mismatch before writing implementation code.

---

## HIGH: `save_daily_snapshot` Produces Incomplete Snapshots

**File:** `projects/marketmind/shadows/shadow_agent.py`, line 189-196

**Problem:** `ShadowAgent.save_daily_snapshot()` only populates `shadow_id`, `date`, and `virtual_capital` -- all 13 metric fields (daily_return_pct, cumulative_return_pct, max_drawdown_pct, sharpe_ratio, etc.) are left as None. This means:
1. Snapshots saved by individual agents are useless for ranking (ranking engine needs filled snapshots).
2. The actual metric computation must happen in a separate pipeline step (B.9 integration).
3. If B.9 doesn't re-save snapshots, ranking will produce garbage results.

**Recommendation:** Add a TODO comment explicitly noting that `save_daily_snapshot()` is a placeholder and B.9 integration must fill metrics. Or move this to a method on the RankingEngine.

---

## MEDIUM: Missing `max_concurrent_shadows` Enforcement

**File:** `projects/marketmind/config/settings.py`, line 15

**Problem:** `ShadowSettings.max_concurrent_shadows = 5` is defined but never enforced anywhere. With 15 experts + 5 daredevils + 1 catfish + N temp shadows, the daily cycle could fire 21+ concurrent LLM calls, potentially exceeding API rate limits.

**Recommendation:** B.9 Gateway integration should add a semaphore or queue to limit concurrent shadow LLM calls to `max_concurrent_shadows`. Not a bug in current code, but a performance footgun for B.9.

---

## MEDIUM: ExpertShadow._filter_news_by_domain Keyword Overlap

**File:** `projects/marketmind/shadows/expert_shadows.py`, lines 108-136

**Problem:** The domain keyword filter has some inaccuracies:
- "volatility" domain has "vol" as a keyword -- this substring matches "volume", "voluntary", etc., causing false positives in unrelated news.
- "fx" domain has "dollar" -- typical macro news mentions USD, so this overlaps with the macro domain.
- No keyword for "agriculture" domain exists in the mapping, but conftest.py references it. There are only 15 domains mapped but the conftest includes "agriculture".

**Recommendation:** Review keyword specificity. Use word-boundary regex (`\b`) for short keywords like "vol" and "gas".

---

## MEDIUM: Test Gaps for Integration-Critical Methods

Several methods that B.9 Gateway+Integration will depend on have zero or minimal test coverage:

| Method | Test Coverage | Risk |
|--------|--------------|------|
| `ShadowAgent.run_daily_analysis()` | Only tests that `_analyze` raises NotImplemented | MEDIUM -- happy path untested |
| `ShadowMother.orchestrate_daily_cycle()` | Not tested at all | HIGH -- main entry point for daily cycle |
| `ShadowMother.create_missed_path_shadows()` | Not tested | LOW |
| `RankingEngine.rank_shadows()` | Tested (well!) | LOW |
| `ExpertShadow._parse_votes()` | Well tested | LOW |

---

## MEDIUM: `_DOMAIN_PROMPTS` and `EXPERT_SHADOW_CONFIGS` Duplication

**File:** `projects/marketmind/shadows/expert_shadows.py`

**Problem:** Both `_DOMAIN_PROMPTS` and `EXPERT_SHADOW_CONFIGS` list 15 domains independently. Adding a 16th domain requires changes in two places (dict + list). If the methodology prompt key differs from the config domain (e.g., `"volatility"` in prompts vs `"volatility"` in config), the shadow silently gets the wrong methodology.

**Recommendation:** Generate `EXPERT_SHADOW_CONFIGS` programmatically from `_DOMAIN_PROMPTS` + a config mapping dict. Eliminates the duplication risk.

---

## Parallel Agent Dispatch Analysis

### Agent Status

| Agent | Sub-Phase | Test Stub | Source Module | Risk |
|-------|-----------|-----------|---------------|------|
| 1 (a6b1cb09) | B.5 Challenger + Knowledge Filter | test_challenger_engine.py (313 lines, 11 tests) | Not committed | LOW |
| 2 (adc87268) | B.6 Emergency Quota + Collusion | test_emergency_quota.py (179 lines, 9 tests) | Not committed | MEDIUM |
| 3 (ae083e90) | B.7 Paper-Live Gap + Cash Reframing | NO TEST STUB | Not committed | HIGH |
| 4 (a559c68c) | B.8 UI Shadow Panel + Status Card | test_shadow_panel.py + test_shadow_status_card.py (224 lines, 7 tests) | Not committed | LOWEST |

### Hidden Dependencies and Conflicts

**1. B.6 depends on EmergencyQuotaRequest.id (missing field)**
The test expects `EmergencyQuotaRequest` objects with an `.id` attribute, but the existing dataclass in `shadow_state.py` has no `id` field. The `record_emergency_quota()` returns `cur.lastrowid` (an int), not an object. Agent 2 must either:
- Add `id: int | None = None` to the `EmergencyQuotaRequest` dataclass (modifying B.0 code), or
- Restructure the test to use the returned integer ID.

**2. B.3 has NO test specifications** -- highest integration risk
Agent 3 (Paper-Live Gap + Cash Reframing) has no test stubs committed. The B.7 specification is only documented in `.claude/methodology/B_analysis_framework.md` (sections 5 and 6). Without test-first specifications, there is no clear acceptance criteria and B.9 integration will be delayed by debugging B.7 modules.

**3. B.5's ChallengerEngine test references `temp_shadow_db` fixture**
This fixture is defined in `conftest.py` and should work. But the test also calls `engine.create_challenger()` which needs to create shadows in the DB. The existing `ShadowConfig` validates `virtual_capital > 0` for all types except `missed_path` -- does `challenger` type need an exception too? Currently: yes, challengers have non-zero virtual capital in tests.

**4. Cross-agent merge conflicts on `shadow_state.py`**
If both Agent 2 (EmergencyQuotaAuditor) and Agent 5 (B.9 integration) add methods to `ShadowStateDB`, there will be merge conflicts. The DB class is 776 lines and growing -- consider splitting into separate CRUD classes per table before B.9.

**5. B.8 UI modules need `mock_ctk` fixture duplicated in two files**
`test_shadow_panel.py` and `test_shadow_status_card.py` both define nearly identical `mock_ctk` fixtures. This duplication should be extracted to `conftest.py` during or after B.8 completion.

### Is the Parallel Dispatch Strategy Sound?

**Assessment: Partially sound with one concern.**

The agents are well-isolated by file boundaries -- B.5 writes `challenger_engine.py`, B.6 writes `emergency_quota.py`, B.7 writes `paper_live_gap.py`/`cash_reframing.py`, B.8 writes UI files. No two agents write the same file.

**However**, the B.6 test references API that requires modifying `shadow_state.py` (EmergencyQuotaRequest needs an `id` field). This is a hidden cross-cutting dependency that wasn't captured in the sub-phase definition. If Agent 2 modifies `shadow_state.py`, the change may conflict with Agent 1's work if Agent 1 also needs schema changes.

**Recommendation:** Freeze `shadow_state.py` as read-only for B.5-B.8 agents. Any schema extensions needed by individual sub-phases should be deferred to B.9 (Gateway integration) which has explicit authority to modify existing files.

---

## Integration Readiness for B.9/B.10

### What's Ready

| Capability | Status |
|-----------|--------|
| Persistent shadow storage (7 tables, WAL mode, FK constraints) | READY |
| Pure-math ranking (MPPM, Calmar, Omega, composite, haircut, ladder) | READY |
| 15 expert shadow configs + domain filtering | READY |
| 5 daredevil configs | READY |
| Catfish consensus detection | READY |
| Missed path counterfactual tracking | READY |
| Event detection (CB, geopolitical, personnel) | PARTIAL (vol_shock broken) |
| Temp shadow lifecycle | READY |

### What's Missing for B.9

| Capability | Owning Agent | Criticality |
|-----------|-------------|-------------|
| Emergency quota state machine | B.6 | HIGH -- needed for daily cycle quotas |
| Collusion detector | B.6 | MEDIUM -- needed for vote aggregation |
| Challenger engine (3-stage elimination) | B.5 | HIGH -- needed for shadow lifecycle |
| Paper-live gap computation | B.7 | MEDIUM -- needed for live-readiness |
| Cash reframing A/B test | B.7 | LOW -- deferrable to Phase C |
| Shadow panel UI | B.8 | HIGH -- needed for dashboard |
| Shadow status card UI | B.8 | HIGH -- needed for detail drill-down |
| LLM gateway wiring (all _analyze methods are stubs) | B.9 | CRITICAL -- NO shadow currently calls an LLM |
| Vote aggregation and signal synthesis | B.9 | CRITICAL -- no module exists |
| Daily orchestration pipeline (end-to-end) | B.9 | CRITICAL -- `orchestrate_daily_cycle` never calls ranking or agents |

---

## Pattern Consistency with Phase A

**Consistent:**
- All modules use `from __future__ import annotations` 
- Dataclass-heavy design (matching Phase A pattern)
- SQLite with WAL mode and row_factory (matches Phase A archivist)
- Structured logging with module-level loggers
- Settings loaded from environment/dataclass defaults
- Same test structure: conftest.py + per-module test files

**Inconsistent:**
- Phase A used `projects/robinhood/src/` flat layout; Phase B uses nested `shadows/` subdirectory (better organization, but different convention)
- Phase A's `deepseek_client.py` is the single LLM gateway; Phase B shadow `_analyze` methods are stubs that would call `httpx` directly if implemented naively. The B.9 integration must route all shadow LLM calls through `deepseek_client.py` (per system rules).
- Phase A modules log with `logger = logging.getLogger(__name__)`; Phase B uses explicit dotted names like `"marketmind.shadows.shadow_state"` -- functionally equivalent but inconsistent style.

---

## Action Items (Priority-Ordered)

### Immediate (before B.5-B.8 agents finish)

1. **Fix `scan_events` crash** -- change line 69 to `self.detect_vol_shock(None)` or separate market_data parameter.
2. **Alert Agent 2** about `EmergencyQuotaRequest.id` mismatch between test and schema.
3. **Create test stubs for B.7** (paper_live_gap, cash_reframing) or accept the risk of untestified implementation.

### Before B.9 integration

4. **Add `get_trade_by_id()` to ShadowStateDB** and fix `close_virtual_position` to use it.
5. **Enforce `max_concurrent_shadows`** with a semaphore in B.9 gateway.
6. **De-duplicate mock_ctk fixtures** into conftest.py.
7. **Generate EXPERT_SHADOW_CONFIGS programmatically** from `_DOMAIN_PROMPTS` to eliminate duplicate domain lists.
8. **Fix `_filter_news_by_domain` keyword specificity** (word boundaries for "vol", "gas").
9. **Document that `save_daily_snapshot` is a placeholder** pending B.9 metric computation.

### Deferrable

10. **Consider splitting `ShadowStateDB`** into per-table repository classes before it exceeds 1000 lines.
11. **Add `scan_events` integration test** covering all 4 detector types end-to-end.
12. **Extract shared keyword-detection logic** between `_detect_by_keywords` and `_filter_news_by_domain` (both do case-insensitive keyword matching on news headlines).

---

## Summary

**Overall Phase B code quality: GOOD.** The 8 committed modules are well-structured, well-tested (79 tests, 0 failures), and follow consistent patterns. The ranking engine is mathematically rigorous with proper edge-case handling (NaN/inf guards, cap-at-10 for Omega, log-sigmoid normalization).

**One CRITICAL bug** (scan_events crash) needs fixing before B.9 integration. **Three HIGH issues** (trade lookup logic, test-schema mismatch, incomplete snapshots) represent correctness problems but won't block B.5-B.8. **Four MEDIUM issues** are code quality improvements.

**The parallel dispatch is sound overall** -- agents work on separate files with minimal cross-dependencies. The main concern is Agent 3 (B.7) lacking test stubs and Agent 2's test referencing a schema field that doesn't exist yet.

**B.9 readiness assessment: 6/10.** Core storage and ranking are ready. The biggest gap is that NO shadow currently makes LLM calls -- all `_analyze` methods are stubs. B.9 will need to wire all shadows through the LLM gateway, implement vote aggregation, and build the daily orchestration pipeline.
