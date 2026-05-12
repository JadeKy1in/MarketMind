# Phase B Shadow Ecosystem -- Full Security, Correctness, and Compliance Audit

**Date:** 2026-05-11
**Auditor:** Red Team (Automated)
**Scope:** 14 shadow modules + 2 UI widgets + 4 existing Phase A file modifications
**Test Suite:** 147/147 PASSED (12.39s)

---

## Executive Summary

The Phase B Shadow Ecosystem demonstrates strong architecture with well-isolated subsystems. The ranking engine, achievement ladder, challenger pipeline, and collusion detector are all structurally sound with good test coverage. However, **three CRITICAL issues** and several WARNING-level items must be resolved before production deployment: (1) an unguarded emergency quota bypass in `ShadowAgent` that defeats the entire penalty state machine, (2) a Priority enum value mismatch that would starve shadow tasks, and (3) the `save_daily_snapshot` method does not propagate computed metrics from the ranking engine, rendering snapshots incomplete.

**Overall Verdict: FAIL** (3 CRITICAL issues must be resolved before Phase B completion)

---

## Item-by-Item Findings

### 1. Token Budget Fairness: Does SHADOW priority correctly sit below NORMAL?

**Severity: CRITICAL**

**Evidence:**
- `projects/marketmind/gateway/token_budget.py:8-14`
- Priority enum defined as: `CRITICAL=1, HIGH=2, NORMAL=3, SHADOW=5, LOW=4`
- Comment at line 12: "Shadow ecosystem -- below NORMAL, above LOW"

**Analysis:** `IntEnum` compares by integer value. The ordering is `1 < 2 < 3 < 4 < 5`, which means `LOW=4 < SHADOW=5`, making SHADOW the *lowest* priority (below even LOW). The comment says "below NORMAL, above LOW" implying `NORMAL < SHADOW < LOW`, which would require `SHADOW=4` and `LOW=5`. This contradicts both the defined values and the existing test at `test_token_budget.py:60` which asserts `CRITICAL < HIGH < NORMAL < LOW` (omitting SHADOW entirely).

**Impact:** Any priority-based dispatch using this enum will place shadow tasks below LOW priority. Since SHADOW=5 makes it the lowest, this does *not* starve the main pipeline -- it starves *shadows*. However, the enum definition is self-contradictory and will cause confusion.

**Remediation:** Either (a) swap values: `SHADOW=4, LOW=5` to match the comment, or (b) update the comment to "below LOW" if shadows truly should have lowest priority, and add SHADOW to the test assertion. Additionally, `Priority` is imported in `gateway/__init__.py:6` but never used for actual dispatch anywhere in the codebase -- this enum is defined but not wired into any scheduler.

---

### 2. Shadow Isolation: Can one shadow's output influence another's analysis?

**Severity: PASS**

**Evidence:**
- Each ShadowAgent subclass calls `_analyze()` independently (`shadow_agent.py:93-98`)
- Expert shadows filter news by domain keywords only (`expert_shadows.py:108-136`); no shadow reads another shadow's analysis output
- `ShadowVote` objects have no cross-references between shadows (`shadow_agent.py:17-27`)
- The `ShadowAnalysisOutput` dataclass is per-shadow only (`shadow_agent.py:42-51`)
- Collusion detection reads *aggregated votes* post-hoc, not during analysis (`collusion_detector.py:149-220`)
- Catfish reads pre-computed trigger data, not raw shadow analyses (`catfish_agent.py:57-98`)

**Analysis:** Each shadow's `_analyze()` method receives only `news_items` and `market_data` -- raw inputs, never peer output. Inter-shadow comparison happens only in post-analysis aggregation (ranking, collusion). No shadow can read or influence another shadow's analysis during generation.

---

### 3. Challenger Opacity: Is challenger data truly invisible?

**Severity: PASS**

**Evidence:**
- `shadow_state.py:342-350` -- `get_visible_shadows()` explicitly excludes `shadow_type != 'challenger'`
- `shadow_state.py:764-778` -- `get_all_active_votes()` also excludes challengers
- `challenger_engine.py:181-183` -- Docstring confirms opacity design
- `shadow_mother.py:259,292` -- Status cards and orchestration use `get_visible_shadows()`
- `test_shadow_state.py:80-93` -- `test_get_visible_shadows_excludes_challengers` verified
- `test_challenger_engine.py:118-132` -- `test_challenger_not_visible_in_rankings` verified

**Analysis:** Challengers are excluded from all visibility queries at the DB layer. The UI ranking panel only renders visible shadows (`shadow_panel.py` uses `get_visible_shadows()`). Target shadow and user cannot see challenger performance data until after the trial completes and a verdict is returned.

---

### 4. Law 7 Compliance: Do all shadow prompts include M1 protocol?

**Severity: WARNING**

**Evidence:**
- `gateway/async_client.py:148-153` -- `chat_with_integrity()` injects `[DATA_INTEGRITY_PROTOCOL v1.0]` header into **all** calls routed through it
- `catfish_agent.py:25` -- Catfish system prompt references Law 7 explicitly
- Expert shadow methodology prompts (`expert_shadows.py:18-94`) do NOT mention Law 7 or M1 protocol in their text

**Analysis:** The M1 integrity protocol is injected at the gateway level, not embedded in each shadow's methodology prompt. This is a valid defense-in-depth approach -- all LLM calls route through `chat_with_integrity()` which adds the protocol header. However, if any shadow ever calls `chat_flash()` or `chat_pro()` directly (bypassing `chat_with_integrity()`), the protocol would be missing. The codebase currently does NOT have such bypasses, but there is no enforcement mechanism.

**Recommendation:** Add a comment in `async_client.py` marking `chat_flash()` and `chat_pro()` as internal/do-not-use for shadow agents. Or add an assertion/lint rule.

---

### 5. Emergency Quota Gaming: Can a shadow spam emergency quotas?

**Severity: CRITICAL**

**Evidence:**
- `shadow_agent.py:174-185` -- `ShadowAgent.request_emergency_quota()` performs ONLY a confidence threshold check (`>= 8`) and writes directly to the DB via `self.state_db.record_emergency_quota()`. It has **zero** state machine checks -- no blocked-in-penalized check, no pending state check, no audit state check.
- `emergency_quota.py:51-87` -- `EmergencyQuotaAuditor.request_quota()` has the proper state machine: checks `penalized/pending/audit` states, tracks consecutive failures, enforces penalties.
- The `ShadowAgent` method `request_emergency_quota` is **never called** anywhere in the codebase (verified via grep). It is dead code but remains an active attack surface if any future code invokes it.

**Impact:** A malicious or buggy shadow that calls `agent.request_emergency_quota(opportunity="critical event", confidence=10)` bypasses the entire EmergencyQuotaAuditor state machine. The quota is written directly to the DB with `result="pending"` and no penalty tracking. Repeated calls would accumulate unlimited emergency quotas with no penalty enforcement.

**Remediation:** (a) Remove or deprecate `ShadowAgent.request_emergency_quota()` entirely -- all emergency quota requests must route through `EmergencyQuotaAuditor.request_quota()`. (b) If the method must remain, have it delegate to the auditor: `auditor.request_quota(self.shadow_id, opportunity, confidence)`.

---

### 6. Collusion False Positives: Tested with known-market-regime scenarios?

**Severity: INFO**

**Evidence:**
- `collusion_detector.py:123-147` -- `discriminate_convergence_vs_herding()` uses `market_signal_strength > 0.70` threshold to distinguish market-driven convergence from behavioral herding
- `test_collusion_detector.py:82-88` -- Tests only `agreement_pct=85%` with `market_signal=0.75` -> `convergence`
- `test_collusion_detector.py:94-101` -- Tests only `agreement_pct=88%` with `market_signal=0.45` -> `herding`

**Analysis:** The discrimination logic is sound in principle: high market signal suggests convergence, low market signal suggests herding. However, the test suite only tests binary extremes (0.75 vs 0.45). No tests verify behavior at the exact boundary (`market_signal=0.70`) or with mixed-market-regime scenarios (e.g., strong price trend but weak volume confirmation). The `borderline` case (`agreement_pct < 80%`) returns `"pending_review"` at line 142, which is correct but not tested.

**Recommendation:** Add tests for boundary cases: (a) market_signal_strength exactly 0.70, (b) agreement_pct exactly 80.0%, (c) mixed signals (price_trend=0.9, volume=0.1, news=0.5).

---

### 7. Ranking Stability: Discontinuities in hybrid percentile transition at N=30?

**Severity: PASS**

**Evidence:**
- `ranking_engine.py:148-168` -- Hybrid percentile computation with smooth interpolation:
  - `n >= parametric_threshold_n (30)`: purely empirical
  - `n <= 15`: purely parametric (logistic-normal)
  - `15 < n < 30`: linear blend `alpha * empirical + (1-alpha) * parametric` where `alpha = n / 30`
- `test_ranking_engine.py:140-143` -- Verifies percentiles sum to approximately expected value

**Analysis:** The transition uses a continuous linear blend (`alpha = n/30`), which is mathematically smooth. At `n=15, alpha=0.5` (0% empirical), at `n=30, alpha=1.0` (100% empirical). There is no discontinuity because the blend ratio is continuous. The epsilon `(count_le - 0.5) / n` in empirical provides continuity correction. The parametric logistic `1/(1+exp(-2*(p-0.5)*sqrt(n)))` is also continuous. **No discontinuity at N=30.**

---

### 8. Achievement Ladder Hysteresis: Correct consecutive-day transitions?

**Severity: PASS**

**Evidence:**
- `ranking_engine.py:201-245` -- `determine_achievement_tier()`:
  - Checks in priority order: ELITE first, then EXCELLENT, then ENDANGERED, then WATCH, defaulting to NORMAL
  - `_count_consecutive_above`: counts from most recent backwards, stops at first below-threshold (line 248-259)
  - `_count_consecutive_below`: counts from most recent backwards, stops at first above-threshold (line 262-275)
- Settings: elite=30 days, excellent=10 days, watch=10 days, endangered=20 days
- `test_ranking_engine.py:146-165` -- Elite (30 days at p85+ with deflated sharpe > 0.8), Endangered (20 days below p15), and Normal default tested

**Analysis:** The ENTIRE logic is correct. Both `_count_consecutive_above` and `_count_consecutive_below` break at the first non-matching day when iterating from most-recent backward. A single day improvement resets the ENDANGERED counter, requiring 20 fresh consecutive days to re-enter. Similarly, a single day drop resets ELITE counter, requiring 30 new consecutive days. **Hysteresis is correctly implemented.**

---

### 9. Cash Reframing Isolation: Does treatment shadow know it's in A/B test?

**Severity: PASS**

**Evidence:**
- `cash_reframing.py:47-53` -- `CASH_REFRAMING_PROTOCOL` constant is the "would you buy?" question, makes no mention of an A/B test
- `cash_reframing.py:64-100` -- `allocate_cohorts()` assigns treatment/control based on MD5 hash of shadow_id (deterministic, not configurable by shadow)
- `cash_reframing.py:116-143` -- `run_exit_check_treatment()` does not expose cohort membership to the shadow
- `gateway/async_client.py:130-136` -- `CASH_REFRAMING_PROTOCOL` in gateway also contains no A/B test references
- `test_cash_reframing.py:187-217` -- Injection test verifies protocol content but confirms no test-metadata leakage

**Analysis:** The treatment protocol is injected at the gateway level as a mental framing prompt. Shadows are not informed they are in the A/B test. Cohort assignment is deterministic from shadow_id hash, invisible to the shadow at runtime. **Isolation is maintained.**

---

### 10. Missed Path Survivorship: Does report include required bias warning?

**Severity: PASS**

**Evidence:**
- `missed_path.py:73-79` -- `_SURVIVORSHIP_WARNING` constant is a complete, well-written survivorship bias warning
- `missed_path.py:48-56` -- `generate_report()` includes `survivorship_bias_warning=_SURVIVORSHIP_WARNING` even when there's no data (`days_tracked=0`)
- `missed_path.py:69` -- Report with data also includes warning
- `test_missed_path.py:54-56` -- `test_report_includes_survivorship_warning` verifies warning in both cases

**Analysis:** The survivorship bias warning is hardcoded into the `MissedPathReport` return and is returned unconditionally -- even for empty reports with 0 days tracked. The warning content explicitly acknowledges the limitation. **Compliant.**

---

### 11. Knowledge Filter ACE: Does multi-generation inheritance detect cascade risk?

**Severity: PASS**

**Evidence:**
- `knowledge_filter.py:170-216` -- `detect_ace_risk()`:
  - Returns 0.0 if ALL items are verified and have no false positives (line 202-203)
  - Computes `unverified_ratio` and `fp_ratio` as fraction of total items
  - `cascade_depth = len(source_ids) / max(n, 1)` -- captures multi-generation risk
  - Final score = `0.50 * unverified_ratio + 0.30 * fp_ratio + 0.20 * cascade_depth * max(unverified_ratio, fp_ratio)`
  - The cascade term amplifies risk ONLY when unverified or FP items exist
- `test_knowledge_filter.py:139-175` -- Multiple ACE tests cover zero-risk (all verified), high-risk (all unverified), and increasing-risk-with-cascade-depth scenarios

**Analysis:** The ACE risk formula correctly gates cascade depth behind the existence of unverified/false-positive items. A chain of perfectly verified knowledge across many generations has zero ACE risk (line 202-203). This prevents false alarms on well-tested methodology while accurately flagging risky inheritance chains. **Correct implementation.**

---

### 12. Paper-Live Gap Monotonicity: As gap closes, does discount decrease monotonically?

**Severity: PASS**

**Evidence:**
- `paper_live_gap.py:147-192` -- `update_discount_rate()`:
  - Computes `target_rate = max(floor, min(default, gap * default))` (line 183)
  - Applies smoothing: `new_rate = current_rate + factor * (target_rate - current_rate)` (line 186)
  - Clamps: `new_rate = max(floor, min(default, new_rate))` (line 187)
- `test_paper_live_gap.py:76-118` -- Test verifies discount decreases as gap closes
- `test_paper_live_gap.py:123-150` -- Floor test: discount never below 5% even after 20 updates

**Analysis:** The target rate is `gap * default` when `gap < 1.0` (linear decrease with gap) and `default` when `gap >= 1.0` (capped at max discount). Since the smoothing factor (0.75) moves current toward target, and the gap must decrease for the target to decrease, the discount rate moves monotonically downward as gap decreases. The function `max(floor, min(default, gap * default))` is monotonic in `gap`. **Monotonicity holds.**

---

### 13. Plateau Detection Edge Cases: New shadow (0 days), exactly at threshold

**Severity: WARNING**

**Evidence:**
- `ranking_engine.py:279-319` -- `detect_plateau()`:
  - Line 293-297: Stagnation score -- `no_elite = "elite" not in recent_tiers if recent_tiers else True`. If `recent_tiers` is empty (new shadow with no history), `no_elite = True`, contributing 0.5 to plateau score immediately.
  - Line 300-306: WR stability -- `len(recent_wr) < 2` returns 0.0 (benign)
  - Line 310-315: Insight drought -- `insight_dates` empty -> `drought = 1.0`, contributing `0.2 * 1.0 = 0.2`
  - Total: `0.5 + 0.0 + 0.2 = 0.7 >= 0.5` -> **New shadow is immediately plateaued!**

**Analysis:** A brand-new shadow with zero days of history would be flagged as plateaued because `recent_tiers` is empty and `insight_dates` is empty. The threshold check at line 319 returns `true` for a score of 0.7. This means every new shadow starts as "plateaued" until it generates at least one insight. This is a false positive.

**Recommendation:** Add a minimum-age guard: if a shadow has fewer than `plateau_no_elite_days` (126) snapshots, skip plateau detection and return `(False, 0.0)`.

---

### 14. Shadow Mother Overlap: Two events with same affected_assets

**Severity: INFO**

**Evidence:**
- `shadow_mother.py:64-72` -- `scan_events()` concatenates results from 4 detectors without deduplication
- `shadow_mother.py:168-196` -- `create_temp_shadows()` generates `temp_event:{type}:{ts}_{event_id[:8]}` -- the event_id is a SHA256 hash of event-specific data, and the timestamp ensures uniqueness
- `shadow_mother.py:193-194` -- Collision on `create_shadow()` raises `ValueError` which is caught and logged

**Analysis:** If two different detection methods fire for the same underlying news (e.g., a central bank shock that also triggers VIX spike detection), two separate events with overlapping `affected_assets` would be created. This creates two temp shadows analyzing the same event from different angles. The shadow_id includes both event_id hash (unique per event) and timestamp (unique per creation), preventing DB ID collisions. Whether duplicate analysis of the same event is desirable or wasteful depends on intent. No data corruption occurs due to the idempotent handling at line 193-195.

**Recommendation:** Consider adding a deduplication step based on affected_assets overlap (e.g., Jaccard similarity > 0.7) to avoid redundant temp shadows burning quotas.

---

### 15. Temp Shadow Cleanup: What if process crashes with active temp shadows?

**Severity: WARNING**

**Evidence:**
- `shadow_mother.py:199-218` -- `check_destruction_conditions()` tests: 30-day max lifespan OR active-but-no-trades for 5+ days
- `shadow_mother.py:267-295` -- `orchestrate_daily_cycle()` calls `check_destruction_conditions` during the daily cycle only
- No startup recovery logic -- no "on_init" scan for orphaned/stale temp shadows
- `shadow_state.py:363-378` -- `eliminate_shadow()` writes `eliminated_at` timestamp but cleanup of stale shadows requires the daily cycle

**Analysis:** If the process crashes and restarts, orphaned temp shadows remain in the DB with `status='active'`. They will eventually be detected and destroyed when the next daily cycle runs `check_destruction_conditions`, but not on startup. No orphans accumulate permanently since `check_destruction_conditions` is date-based (30 days from `created_at`). However, if the process is restarted frequently (e.g., during development), stale temp shadows persist until the daily cycle runs.

**Recommendation:** Add a `cleanup_stale_temp_shadows()` call to the startup path in `app.py` (or to ShadowMother init) that checks all existing temp_event shadows against `check_destruction_conditions()`.

---

### 16. Concurrent DB Access: 15 shadows writing simultaneously -- deadlocks?

**Severity: PASS**

**Evidence:**
- `shadow_state.py:254-265` -- `ShadowStateDB._connect()`:
  - `PRAGMA journal_mode=WAL` -- Write-Ahead Logging enables concurrent reads + single writer
  - `PRAGMA busy_timeout=5000` -- 5-second wait on lock before error
  - `PRAGMA synchronous=NORMAL` -- balances durability with performance
  - Every method opens a new connection, does work, and closes it in a `try/finally`
- `test_shadow_state.py:205-210` -- WAL mode verified in test

**Analysis:** With WAL mode, SQLite supports concurrent readers and a single writer. The 5-second busy timeout means transient lock contention (which is unlikely with per-operation connections) will retry rather than fail. However, the *current implementation* in the test suite and app.py runs shadows sequentially (single coroutine), not concurrently, so deadlocks are not a practical concern in the present architecture. If shadows were ever run in parallel with `asyncio.gather()`, SQLite serializes writes via WAL without deadlocks.

**Limitation:** The current architecture opens and closes a new `sqlite3.Connection` per method call. This is thread-safe but slow. For 15 shadows each calling 5+ DB methods per cycle, that is 75+ open/close operations. Consider using a connection pool or single persistent connection with threading.Lock if performance becomes an issue.

---

### 17. Catfish Integrity: Does Catfish ever fabricate counter-arguments?

**Severity: PASS**

**Evidence:**
- `catfish_agent.py:15-26` -- `CATFISH_SYSTEM_PROMPT`:
  - Line 20: "ONLY activate when given the trigger signal"
  - Line 23: "Your counter-argument MUST cite verifiable data. Use EST: prefix for estimates. Use DATA_UNAVAILABLE when data is missing."
  - Line 24: "If no legitimate counter-argument exists after thorough analysis, report 'NO_VALID_COUNTER' -- NEVER fabricate."
  - Line 26: "You are subject to Law 7 (Data Integrity). Fabrication = 3 strikes and termination."
- `test_catfish_agent.py:115-119` -- Test verifies both "NO_VALID_COUNTER" and "NEVER fabricate" are in the prompt
- `catfish_agent.py:57-98` -- Implementation only generates votes when `trigger_pct >= 0.80`, sets low confidence (0.5) with explicit risk note

**Analysis:** The Catfish system prompt contains explicit anti-fabrication instructions: M1 data integrity protocol, EST prefix requirement, DATA_UNAVAILABLE escape hatch, and a "NEVER fabricate" directive backed by a 3-strike termination threat. The Catfish is also subject to the gateway-level integrity protocol injection in `chat_with_integrity()`. **Integrity safeguards are present.**

---

### 18. Gateway M1 Injection: Is cash_reframing injected before or after integrity protocol?

**Severity: INFO**

**Evidence:**
- `gateway/async_client.py:148-162` -- `chat_with_integrity()`:
  ```python
  full_system = integrity_header           # M1 protocol first
  if cash_reframing_ticker:
      cr_protocol = CASH_REFRAMING_PROTOCOL.format(...)
      full_system = cr_protocol + "\n" + full_system  # CASH prepended BEFORE M1
  full_system += system_prompt             # shadow's method prompt appended last
  ```
- Final order: `[CASH_REFRAMING] [DATA_INTEGRITY v1.0] [shadow_methodology_prompt]`

**Analysis:** Cash reframing is injected BEFORE the M1 data integrity protocol. This means the LLM sees cash-reframing framing first, then the integrity rules, then its methodology. Since LLMs typically give more weight to later instructions, the integrity protocol at position 2 would override the cash reframing framing at position 1. This could potentially weaken the cash-reframing effect since the integrity protocol's emphasis on verifiable data might cause the shadow to ignore the "would you buy?" mental framing in favor of data-driven analysis. The current order is: M1 integrity has the "last word" over cash reframing.

Whether this is desirable depends on intent: (a) if cash reframing should dominate, it should go AFTER integrity, (b) if integrity always dominates, current order is correct. The A/B test design probably wants treatment shadows to fully experience the framing, so **recommend swapping to: `[M1 Integrity] [CASH_REFRAMING] [methodology]`**.

---

### 19. Config Validation: Does validate() catch all shadow config errors?

**Severity: WARNING**

**Evidence:**
- `config/settings.py:112-125` -- `MarketMindConfig.validate()`:
  - Checks: `DEEPSEEK_API_KEY` presence, `max_position_count >= 1`, `max_total_heat_pct in (0,1]`
  - Shadows: checks `max_concurrent_shadows >= 1`, `evaluation_window_days >= 30`
- `shadow_state.py:40-60` -- `ShadowConfig.__post_init__()`:
  - Checks: non-empty `shadow_id`, valid `shadow_type` (7 types), valid `status` (5 values), `virtual_capital >= 0`, `temperature in [0,2]`, etc.

**Missing validations:**
1. `collusion_agreement_threshold` is not validated to be in (0,1] -- a value of 0 would flag every day, 1.5 would never fire
2. `achievement_percentiles` order is not validated -- `endangered < watch < excellent < elite` must hold or the ladder produces wrong tiers
3. `virtual_slippage_atr_pct` is a float multiplier -- not validated to be >= 0
4. `confidence_discount_default` vs `confidence_discount_floor` -- floor should be less than default; if switched, discount would *increase* as gap closes
5. Individual ShadowConfig validation is in `__post_init__()` on the dataclass but `MarketMindConfig.validate()` only checks two shadow fields

**Recommendation:** Add cross-field constraint checks: `achievement_percentiles` ordering, `discount_floor < discount_default`, `collusion_agreement_threshold in (0,1)`, `virtual_slippage_atr_pct >= 0`.

---

### 20. Test Coverage: What % of lines are covered?

**Severity: INFO**

**Evidence:**
- Test suite results: **147 tests, 100% pass rate, 0 failures**
- Test modules (19 files):
  | Module | Tests | Lines (src) |
  |--------|-------|-------------|
  | test_shadow_state.py | 12 | shadow_state.py: 778 |
  | test_shadow_agent.py | 10 | shadow_agent.py: 197 |
  | test_shadow_mother.py | 9 | shadow_mother.py: 315 |
  | test_challenger_engine.py | 9 | challenger_engine.py: 442 |
  | test_ranking_engine.py | 17 | ranking_engine.py: 404 |
  | test_emergency_quota.py | 8 | emergency_quota.py: 206 |
  | test_collusion_detector.py | 9 | collusion_detector.py: 259 |
  | test_paper_live_gap.py | 8 | paper_live_gap.py: 323 |
  | test_expert_shadows.py | 6 | expert_shadows.py: 258 |
  | test_daredevil_shadows.py | 5 | daredevil_shadows.py: 130 |
  | test_catfish_agent.py | 9 | catfish_agent.py: 121 |
  | test_missed_path.py | 5 | missed_path.py: 91 |
  | test_knowledge_filter.py | 10 | knowledge_filter.py: 234 |
  | test_cash_reframing.py | 8 | cash_reframing.py: 488 |
  | test_shadow_panel.py | 4 | shadow_panel.py: 164 |
  | test_shadow_status_card.py | 4 | shadow_status_card.py: 179 |
  | test_e2e_shadow_ecosystem.py | 6 | (integration) |
  | test_token_budget.py | 8 | token_budget.py: 97 |

**Coverage estimate:** Based on code vs test volume, approximately **55-65% line coverage** across the 14 core modules. Key coverage gaps:
- **No coverage:** `close_virtual_position()` PnL calculation for uncovered entry trades (line 152-154 returns 0.0)
- **No coverage:** `eliminate_shadow()` auto-closing open trades (line 371-375)
- **No coverage:** `ShadowAgent.__init__()` reactivation of eliminated shadows (line 68-69)
- **No coverage:** `_compute_paired_ttest()` ties with <2 samples (line 382-383)
- **No coverage:** `_mann_whitney_u()` manual fallback path (lines 366-430, only tested via scipy)
- **No coverage:** `chat_with_integrity()` with `model='pro'` path (line 166)
- **No coverage:** `get_latest_snapshot()` for shadow with no snapshots (line 533)
- **No coverage:** EmergencyQuotaAuditor.audit_result() on already-resolved quota (line 112)

**Coverage by module:**
- shadow_state.py: ~75% (CRUD operations extensively tested)
- ranking_engine.py: ~70% (core metrics + ranking pipeline tested)
- challenger_engine.py: ~60% (stage detection + trial tested, edge cases partial)
- emergency_quota.py: ~65% (state machine tested, edge cases partial)
- paper_live_gap.py: ~55% (slippage + discount + gap + live-ready tested, PBO fallback not tested)
- cash_reframing.py: ~40% (cohort allocation + DE + stats tested; exit checks in mock mode not tested)
- collusion_detector.py: ~50% (agreement + classification tested; binomial test partial, market signal partial)

**Recommendation:** Add tests for the 8 coverage gaps listed above. Target minimum 70% line coverage per module before Phase B completion.

---

## Additional Findings (Beyond 20-Item Checklist)

### A.1 ShadowAgent.request_emergency_quota Bypasses Auditor State Machine

**Severity: CRITICAL** (same as Item 5, detailed above)

### A.2 ShadowAgent.save_daily_snapshot Writes Incomplete Metrics

**Severity: WARNING**

**Evidence:** `shadow_agent.py:189-196` -- `save_daily_snapshot()` creates a `DailySnapshot` with only `shadow_id`, `date`, and `virtual_capital`. All performance metrics (`daily_return_pct`, `cumulative_return_pct`, `sharpe_ratio`, `composite_score`, `percentile_rank`, etc.) are **None/null**. The RankingEngine computes these but never writes them back.

**Impact:** Snapshots saved by the agent do not contain ranking data. This means `get_latest_snapshot()` returns incomplete data for status cards and the ranking engine itself would need to recompute from raw returns. The database has the schema columns but they are never populated by the agent's save path.

**Recommendation:** Either have the ranking engine write back to snapshots after computation, or wire `save_daily_snapshot` to accept a `RankingResult` parameter.

### A.3 ShadowMother.generate_status_cards Creates New ShadowAgent Instances

**Severity: INFO**

**Evidence:** `shadow_mother.py:256-263` -- `generate_status_cards()` instantiates a new `ShadowAgent` for each visible shadow just to call `receive_status_card()`. This is wasteful but benign. Each agent initialization checks if the shadow exists in DB (line 65-69) which is a read operation. No state is modified.

### A.4 No Rate Limiting on Emergency Quota Requests

**Severity: INFO**

**Evidence:** `emergency_quota.py:51-87` -- `request_quota()` has state-based blocking (`penalized/pending/audit`) but no time-based rate limiting. A shadow could theoretically request quota every time its state resets to "normal" (after the 3-day or 7-day observation period expires). The emergency_extra_calls setting (3) is defined in settings but never enforced.

**Recommendation:** Add a per-period cap (e.g., max `emergency_extra_calls` per 90-day window) enforced in `request_quota()`.

---

## Summary Table

| # | Item | Severity | Key Files |
|---|------|----------|-----------|
| 1 | Token Budget Fairness | **CRITICAL** | `token_budget.py:8-14` |
| 2 | Shadow Isolation | PASS | `shadow_agent.py:93-98`, `expert_shadows.py:108-136` |
| 3 | Challenger Opacity | PASS | `shadow_state.py:342-350`, `test_challenger_engine.py:118-132` |
| 4 | Law 7 (M1) Compliance | WARNING | `async_client.py:148-153`, expert prompts lack explicit M1 |
| 5 | Emergency Quota Gaming | **CRITICAL** | `shadow_agent.py:174-185` vs `emergency_quota.py:51-87` |
| 6 | Collusion False Positives | INFO | `collusion_detector.py:123-147`, boundary tests missing |
| 7 | Ranking Stability at N=30 | PASS | `ranking_engine.py:148-168` (continuous blend) |
| 8 | Achievement Ladder Hysteresis | PASS | `ranking_engine.py:201-275` |
| 9 | Cash Reframing Isolation | PASS | `cash_reframing.py:47-53,64-100` |
| 10 | Missed Path Survivorship | PASS | `missed_path.py:73-79` |
| 11 | Knowledge Filter ACE | PASS | `knowledge_filter.py:170-216` |
| 12 | Paper-Live Gap Monotonicity | PASS | `paper_live_gap.py:147-192` |
| 13 | Plateau Edge Cases | WARNING | `ranking_engine.py:293-319` (new shadows flagged) |
| 14 | Shadow Mother Overlap | INFO | `shadow_mother.py:64-72` (no dedup) |
| 15 | Temp Shadow Crash Recovery | WARNING | `shadow_mother.py:199-218` (no startup cleanup) |
| 16 | Concurrent DB Access | PASS | WAL + busy_timeout=5000 |
| 17 | Catfish Integrity | PASS | `catfish_agent.py:23-26` |
| 18 | Gateway M1 Injection Order | INFO | `async_client.py:148-162` (cash before integrity) |
| 19 | Config Validation | WARNING | `settings.py:112-125` (gaps in cross-field checks) |
| 20 | Test Coverage | INFO | ~55-65% estimated, 147 tests, 8 uncovered paths |

---

## Overall Verdict: FAIL

Three CRITICAL issues must be resolved:

1. **CRITICAL** -- `ShadowAgent.request_emergency_quota()` bypasses the `EmergencyQuotaAuditor` state machine entirely (`shadow_agent.py:174-185`). Remove this method or redirect it through the auditor.

2. **CRITICAL** -- `Priority.SHADOW=5` is below `Priority.LOW=4`, contradicting the comment "below NORMAL, above LOW". Either swap values or update the comment. Furthermore, `Priority` is never wired into an actual scheduler -- the enum is imported but unused (`token_budget.py:8-14`).

3. **CRITICAL** -- `ShadowAgent.save_daily_snapshot()` writes snapshots with None/null for all computed metrics, rendering them incomplete for ranking and status display purposes (`shadow_agent.py:189-196`).

Additionally, 6 WARNING items and 4 INFO items should be addressed before production deployment. See remediation recommendations in each item above.
