# MarketMind Restart Guide — Development Continuation

**Last updated**: 2026-05-13 | **Branch**: master | **Last push**: `2fbba82`
**All pushed to GitHub**: ✅

---

## Restart Command

Type this exactly:

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。按顺序实施 P2-2 → P2-4 → P3-1 → P3-3 → P3-4 → P3-2。

---

## Current State

### ✅ Completed: 7 Implementation Phases (17 features) + P0-P2 Core (10/15)
218/218 tests pass. All pushed to GitHub.

### ⏸️ Remaining: 6 items (P2-2, P2-4, P3-1, P3-2, P3-3, P3-4)
All externally researched, Red Team audited, ready to implement.

---

## Implementation Order & Specs

**Development rule for EVERY item**: Search external research first → Red Team audit → implement → commit.

---

### 1. P2-2: Walk-Forward Validation (~150 lines, 1 day)

**VERDICT**: APPROVED | **Dependencies**: None

**Why**: Detects overfitting. Current system evaluates all historical data in one window — no out-of-sample test. Based on AlgoXpert IS-WFA-OOS protocol (Pham, Mar 2026) and HypoDriven framework (Deep et al., Dec 2025).

**What to build**:
- `RankingEngine.WalkForwardValidator` class in `shadows/ranking_engine.py` (+120 lines)
- Integration in `shadow_mother.py` after ranking step (+30 lines)
- 90-day train / 2-day purge / 20-day test windows
- WFE gate: `mean(OOS_deflated) / mean(IS_deflated) < 0.5` = overfit flag
- Skip check if IS_deflated <= 0.001
- Min 120 career days required
- Binomial sign test on OOS directional accuracy
- No new DB tables — uses existing `daily_snapshots`

**Tests needed** (5): WFE passing, WFE flagging, insufficient data early-exit, near-zero IS handling, binomial test

---

### 2. P2-4: External Market Anchor (~170 lines, 1 day)

**VERDICT**: MODIFIED (3 corrections applied) | **Dependencies**: `yfinance` (already in requirements.txt)

**Why**: Breaks virtual PnL circularity. Shadows are currently ranked against system-calculated PnL. Market accuracy < random (0.50) must block ELITE tier. Based on S&P Totem consensus validation and AlgoXpert defense-in-depth.

**Corrections applied**:
- Threshold raised: `market_accuracy < 0.50` → demote to NORMAL (not 0.45)
- Accuracy defined as: `count(shadow_direction == sign(next_day_return)) / total_predictions`
- Integration point: between step 4 (analyses) and step 5 (rankings) in daily cycle

**What to build**:
- NEW `shadows/market_data_fetcher.py` (+60 lines): `MarketDataFetcher` using `yfinance.history()`
- MODIFY `shadows/shadow_state.py` (+40 lines): `market_prices` table + CODE_VERSION=3 migration
- MODIFY `shadows/ranking_engine.py` (+25 lines): `accuracy_gate` param in `determine_achievement_tier()`
- MODIFY `shadows/shadow_mother.py` (+45 lines): fetch→compute→gate integration

**Tests needed** (6): OHLCV fetch, accuracy computation, ELITE demotion, tier retention, holiday skip, migration

---

### 3. P3-1: Challenger Learns from Predecessor Failures (~50 lines, 0.5 day)

**VERDICT**: APPROVED | **Dependencies**: Soft dep on AEL (works without it)

**Why**: Challenger currently inherits target's methodology VERBATIM — including the same biases. Based on Mistake Notebook Learning (ACL 2026) and Hindsight Hint Distillation (May 2026): training-free, predecessor failures → structured "what not to do" for successor.

**What to build**:
- MODIFY `shadows/challenger_engine.py` (+50 lines): in `create_challenger()`, query AEL debriefs (last 3 months) + crystallization retirements, call `MethodologyInjector.inject_failure_patterns()` (already built in P1-1)
- Primary source: AEL debrief failure_patterns
- Secondary source: crystallization retired insights from methodology_changes table
- Cap at 5 total patterns to avoid prompt bloat
- Graceful degradation if AEL data unavailable

**Tests needed** (5): patterns injected, no AEL data ok, deduplication, crystallization retirements, cap at 5

---

### 4. P3-3: LLM Gateway Redundancy (~200 lines, 1.5 days)

**VERDICT**: MODIFIED (2 corrections) | **Dependencies**: None

**Why**: Single DeepSeek outage = all 22 shadows dead simultaneously. Based on circuit breaker pattern (llm-circuit, 2026) and ADR-021 Fallback Chain.

**Corrections applied**:
- HALF_OPEN probe interval depends on error type (429→Retry-After, 5xx→30s, quota→skip HALF_OPEN)
- Fallback provider must be configurable: `fallback_provider_url` + `fallback_model` in settings

**What to build**:
- MODIFY `gateway/async_client.py` (+180 lines): `CircuitBreaker` class (CLOSED→OPEN→HALF_OPEN state machine), integration with existing `_call_with_retry()`, exponential backoff with jitter
- MODIFY `config/settings.py` (+15 lines): `fallback_provider_url`, `fallback_model`, `circuit_breaker_threshold=3`, `circuit_breaker_timeout_s=30`

**Tests needed** (8): CLOSED→OPEN transition, fallback routing, HALF_OPEN probe success, HALF_OPEN probe failure, 429 Retry-After, jitter, fallback output, config ordering

---

### 5. P3-4: Partial-State Recovery (~200 lines, 1.5 days)

**VERDICT**: APPROVED (per-shadow granularity) | **Dependencies**: None

**Why**: Crash during step 4 (most expensive — all LLM calls) loses 22 completed analyses. Based on Kitaru checkpoint pattern (ZenML, 2026).

**Corrections applied**:
- Per-shadow checkpoint after each individual analysis (not just after entire step 4)
- Resume: skip completed shadows, re-run only incomplete ones

**What to build**:
- MODIFY `shadows/shadow_mother.py` (+140 lines): per-shadow checkpoint after each analysis in `_run_one`, resume detection on cycle start, cached replay logic
- MODIFY `shadows/shadow_state.py` (+60 lines): `cycle_checkpoints` table + CODE_VERSION=4 migration + CRUD methods
- Schema: `cycle_checkpoints(date TEXT PK, status TEXT, step_completed INT, shadow_states JSON, ...)`

**Tests needed** (7): incomplete cycle resume, completed skip, incomplete re-run, per-shadow checkpoint, crash safety, two incomplete cycles, cleanup

---

### 6. P3-2: Main AI Gate Iteration — SHARP (~750 lines, 3-4 days)

**VERDICT**: MODIFIED (split into P3-2a + P3-2b) | **Dependencies**: MissedPathReport (exists)

**Why**: Main AI currently has ZERO self-improvement while shadows have 5+ mechanisms. SHARP bridges this by decomposing static DECISION_SYSTEM_PROMPT into auditable rules with the same pattern shadows already use (ID→decay→validation→audit).

**Correction: Split into two sub-phases** (original 500-line estimate was too low):

#### P3-2a: Rule Framework + Attribution (~350 lines, 1-2 days)
- NEW `pipeline/methodology_rules.py`: `MainAIRule` dataclass, rule decomposition from DECISION_SYSTEM_PROMPT, `AttributionAgent` (Flash LLM → hypothesis only, NOT verdict), backtest gate makes final keep/retire decision
- MODIFY `storage/archivist.py` (+20 lines): rule audit methods
- Key: AttributionAgent output is `RuleImpactHypothesis` (rule_id, suspected_impact, confidence). Walk-forward backtest is the actual verdict. LLM is NOT the judge.

#### P3-2b: Evolution + Dynamic Assembly (~400 lines, 2 days)
- MODIFY `pipeline/methodology_rules.py`: `RuleValidator` with walk-forward gate, `RuleEvolver` (atomic edits: tune threshold, add/remove rule), dynamic prompt assembly from active rules
- MODIFY `pipeline/decision.py` (+30 lines): replace static DECISION_SYSTEM_PROMPT with dynamic assembly

**Tests needed** (6): rule decomposition, attribution hypothesis, dynamic assembly, backtest retirement, audit trail, error handling

---

## Dependency Graph

```
P3-3 (unblocks reliability)           P3-1 (quick win)
    ↓                                       ↓
P2-2 + P2-4 (validation gates)         [independent]
    ↓
P3-4 (recovery)
    ↓
P3-2a → P3-2b (largest, last)
```

P3-3, P3-1, and P2-2+P2-4 can all run in parallel (different files).

---

## After All 6 Items Complete

### Start AEL Controlled Experiment
1. Set `ael_experiment_enabled = True` in `config/settings.py`
2. Create replica shadows for 4 treatment shadows
3. Run 2-3 months, compare treatment vs control with z-test
4. If significant: expand AEL to all shadows

### Run Full Test Suite
```bash
python -m pytest projects/marketmind/tests/ -v --tb=short
```

---

## Key Design Decisions (DO NOT CHANGE WITHOUT REVIEW)

1. All shadows default to Pro model. Flash: queries, preprocessing, one-line comments.
2. Challengers inherit ORIGINAL methodology prompts, not AEL-evolved ones.
3. Daredevils are ENVIRONMENT-LOCKED (7+1). Each trades its own environment.
4. Catfish → EcosystemAuditor (mechanism, not shadow).
5. Temp Events = Form C milestone-triggered (3-5 Pro calls/30 days).
6. Emergency quota triggers on exhaustion, not confidence.
7. Tier quotas: ELITE=7, EXCELLENT=6, NORMAL=5, WATCH=3, ENDANGERED=1.
8. Dynamic win-rate line: early boost WR, mature allow WR-for-profitability trade.
9. Negative profitability = largest penalty regardless of win rate.
10. ELITE Gate 2 participation: domain-triggered, no decision authority, once/session.
11. SHARP rules apply the PATTERN to main AI, NOT shadow data.

---

## Key Files

| File | Purpose |
|------|---------|
| `projects/marketmind/shadows/ranking_engine.py` | Composite scoring, haircut, dynamic WR, walk-forward (P2-2) |
| `projects/marketmind/shadows/shadow_mother.py` | Daily orchestration, all wiring, recovery (P3-4) |
| `projects/marketmind/shadows/shadow_state.py` | SQLite schema, methodology_changes, market_prices (P2-4) |
| `projects/marketmind/shadows/challenger_engine.py` | 3-stage elimination, Wilcoxon, failure patterns (P3-1) |
| `projects/marketmind/shadows/methodology_evolver.py` | MethodologyInjector (P1-1) |
| `projects/marketmind/gateway/async_client.py` | LLM calls, circuit breaker (P3-3) |
| `projects/marketmind/pipeline/decision.py` | Main AI prompts, SHARP dynamic assembly (P3-2) |
| `projects/marketmind/config/settings.py` | All configuration, AEL flag, fallback (P3-3) |
| `.claude/phase_b_ideation_notes.md` | Full Grill Me ideation notes |
| `.claude/forensics/phase-b-fdr.md` | Phase B forensic design reconstruction |
| `.claude/audits/` | All Red Team audit reports |
| `docs/superpowers/specs/2026-05-10-marketmind-design.md` | Original design doc v1.2 |

---

---

## Pending / Deferred Items (Not in Current Sprint)

These were identified during research/audit but deferred or deprioritized. Documented so nothing is lost.

### Deferred from 3-Proposal Review (You.com, SAC)
- **You.com Recursive Improvement**: Deferred. Key insight (plateau→environment change) incorporated into SHARP. Standalone Judge Agent not needed. If SHARP plateaus → revisit.
- **SAC Credit-Assigned Penalty**: Deferred to Phase 2 (after SHARP stabilizes 2+ weeks). Apply to shadow ecosystem first (daily votes), then main AI.

### From Original Design Doc v1.2 (Possibly Not Built)
These were in the May 2026 design spec but may not have been implemented:
- **不交易信号生成器 (NoTrade Signal Generator)**: Design doc 4.0.1 — symmetric "why NOT to trade" analysis presented alongside buy/sell at Gate 3. Check if implemented in `pipeline/decision.py`.
- **人类决策镜像 (Human Decision Mirror)**: Design doc 8.4 — track user decisions vs AI recommendations, identify patterns (bias toward over-trading, VIX-correlated decisions). Check `shadows/` or `pipeline/`.
- **信号追踪器 (Signal Tracker)**: Design doc 8.2 — per-signal-type lying history, false signal context annotation. Check `shadows/` or `pipeline/`.
- **三层复盘 (3-Tier Review)**: Design doc 8.1 — daily tactical + monthly strategic + quarterly systemic. Some daily review exists in AEL/crystallization. Monthly and quarterly may not be built.
- **Phase C 复盘进化**: Original roadmap Phase C. Some components built (crystallization, methodology evolver). Full pipeline may be incomplete.
- **Phase D 打磨**: Original roadmap Phase D — performance optimization, cost optimization, stability testing. Not started.

### From Unified Improvement Plan
- **P2-2, P2-4**: In current sprint (above).
- **P3-1 through P3-4**: In current sprint (above).

### Operational Items
- **AEL Controlled Experiment**: Code ready (`ael_experiment_enabled=False`). Start after P2-4 done (needs external market data).
- **Full End-to-End Test Run**: After all 6 items done, run complete test suite.
- **Grill Me Round 5 closing questions** (optional): (1) What makes MarketMind indispensable in 1 year? (2) Anything we should STOP doing?

---

## Grill Me Status

Rounds 1-4 complete. Round 5 two closing questions (optional — see Pending Items above).
