# Plan: Phase E — Infrastructure Fixes (5 Known Limitations)

## WHY + SCOPE

Phase D left 5 known infrastructure limitations documented in `PHASE_D_COMPLETION.md`. These are real gaps that, if unfixed, will accumulate technical debt and block Phase F (shadow ecology / knowledge accumulation / multi-modal input). Each fix is minimal and targeted — no new frameworks or dependencies.

**IN SCOPE (5 work items):**

1. **Schema Version Tracking** — Add `metadata` table with `schema_version` so future migrations are ordered and idempotent
2. **Prompt Hot-Reload** — Add `reload` param and mtime-based staleness check to `load_shadow_prompts()`
3. **Calibration Cold Start** — Wire `PaperLiveGapManager` into production (`shadow_mother.py`), add Bayesian peer prior for cold start
4. **Quota-Pool-Aware Key Rotation** — Parse `x-ratelimit-remaining` response headers, track per-key health, warn on shared quota pool
5. **Backtest Coverage Reporting** — Report coverage percentage and flag date ranges with no vote data

**OUT OF SCOPE:**
- Shadow ecology / knowledge accumulation (Phase F)
- External information input + multi-modal (Phase F)
- Expert shadow conversation participation (Phase G)
- Background async task scheduling overhaul (Phase F)
- Gemini Flash multi-modal adapter (Phase F)
- Migration rollback/downgrade
- File watcher / watchdog dependency
- Vote estimation from trade history
- `--reload-prompts` CLI flag

**Success Criteria:**
- [ ] DB has `metadata.schema_version` checked on each `init_schema()`
- [ ] `load_shadow_prompts(reload=True)` re-reads from disk; `stale_after_seconds` works
- [ ] `PaperLiveGapManager` is called during daily orchestration (not just tests)
- [ ] Cold start uses domain peer data as prior when < 10 own trades
- [ ] Key rotation uses `x-ratelimit-remaining` header; missing-header edge case handled
- [ ] Budget report includes per-key status
- [ ] Backtest report shows `coverage_pct` and missing-date warning
- [ ] 339 existing tests still pass; new tests for each area

## Existing Solutions

### Codebase-internal patterns referenced
- `_migrate_add_column()` in `shadow_state.py:309-317` — existing safe migration pattern
- `_prompt_cache` module-level singleton in `config/__init__.py:12-35` — existing cache pattern
- `PaperLiveGapManager` in `shadows/paper_live_gap.py:38-405` — already implemented, needs wiring
- `KeyRotator` in `gateway/async_client.py:24-43` — existing rotation pattern
- `BacktestRunner.run()` in `backtest_runner.py:20-96` — existing backtest loop
- `RateLimitError` in `gateway/async_client.py:18-21` — captures `retry_after` but not remaining quota

### External libraries considered and rejected
- `fastmigrate` / `yoyo-migrations` — overkill for current scale (1 migration, ~40 lines)
- `watchdog` — overkill for file mtime check (~25 line approach sufficient)
- `pydantic-settings` — already used in config, no change needed

### Research references (Phase F/G foundation)
- **FinMem** (AAAI 2024): Layered memory + character self-evolution → shadows learning from experience
- **FinCon CVRF** (NeurIPS 2024): Conceptual Verbal Reinforcement → belief propagation between agents
- **QuantAgent** (2024): Two-layer loop (knowledge base refinement + real-world testing) → methodology optimization
- **Nurture-First Development** (2026): Conversational Knowledge Crystallization → human-AI knowledge capture
- **AHCE** (2026): Learned expert intervention policy → when shadows interject in conversation
- **DynTaskMAS** (AAAI 2025): DAG task graph + async parallel engine → background shadow scheduling

## Minimal Path

### Implementation order (dependency-aware)

```
1. Schema Version Tracking     ──┐
2. Prompt Hot-Reload            ─┤ can be done in any order
5. Backtest Coverage            ─┘
        │
3. Calibration Cold Start       ── depends on nothing, independent
4. Quota-Pool Key Rotation      ── depends on nothing, independent
```

Items 1, 2, 5 can be done in parallel (no dependencies between them).
Items 3 and 4 are independent of each other and of 1/2/5.

### Critical path
1. Schema version tracking (enables future migrations)
2. Calibration cold start (has the most cross-file changes)
3. All others are independent leaves

## Files to Create/Modify

| File | Change | Lines (est.) |
|------|--------|-------------|
| `projects/marketmind/shadows/shadow_state.py` | Add `metadata` table to `_SCHEMA_SQL`, `CODE_VERSION` constant, version check in `init_schema()`, migration registry in init order | ~40 |
| `projects/marketmind/config/__init__.py` | Add `reload: bool=False` and `stale_after_seconds: int=0` params to `load_shadow_prompts()`, cached mtime tracking | ~25 |
| `projects/marketmind/shadows/shadow_mother.py` | Import and instantiate `PaperLiveGapManager`, call `update_discount_rate()` per shadow after ranking computation (between step 5 and step 6 in `orchestrate_daily_cycle`) | ~35 |
| `projects/marketmind/shadows/paper_live_gap.py` | In `_calibrate_per_asset()`, use domain peer PnL CV as Bayesian prior when < 10 own trades (only if peer data exists) | ~20 |
| `projects/marketmind/gateway/async_client.py` | Parse `x-ratelimit-remaining` header in `_call_with_retry()`, add `_key_remaining` dict to `KeyRotator`, preemptive rotation on low remaining, shared-pool warning | ~60 |
| `projects/marketmind/backtest_runner.py` | Track `days_with_votes / total_days` in `run()`, add `coverage_pct` + `empty_dates` + `warning` fields to report dict | ~30 |
| Tests (3-4 files) | `test_shadow_state.py`, `test_async_client.py`, `test_paper_live_gap.py`, `test_backtest_runner.py` (new) | ~150 |

**Total: 6 production files modified, ~210 lines production code, ~150 lines test code.**

## Risks and Unknowns

| Risk | Mitigation |
|------|------------|
| `X-RateLimit-Remaining` header counts RPM not tokens — preemptive rotation is a heuristic | Accept at ~60 lines; full token tracking deferred to Phase F |
| `db_version > CODE_VERSION` edge case (user opened DB with newer code then reverted) | Log warning, skip migration — no destructive action |
| No existing tests for `BacktestRunner` or cold-start Bayesian path | Allocate time for new test coverage (included in estimate) |
| `PaperLiveGapManager` wired at wrong orchestration point could block shadow analysis | Wire AFTER ranking (step 5), BEFORE state save (step 6) — read-only calibration pass |
| Missing `x-ratelimit-remaining` header on some deployments | Preserve previous known value, don't zero out |

## Critique History

| Round | Verdict | Composite | Assumption | Scope | Existing | Minimalism | Uncertainty |
|-------|---------|-----------|------------|-------|----------|------------|-------------|
| 1 | REVISE | 2.0 | 2 | 2 | 2 | 2 | 2 |
| 2 | REVISE | 2.6 | 2 | 3 | 3 | 3 | 2 |
| 3 | PROCEED | 3.4 | 3 | 4 | 3 | 4 | 3 |

**Key issues resolved:**
- Round 1 → 2: Dropped `BackfillRunner` (no archive data source), dropped full migration framework (YAGNI), switched from heuristic per-key tracking to response-header-based
- Round 2 → 3: Dropped vote estimation from trades, dropped `--reload-prompts` CLI flag, added missing-header edge case handling, added downgrade edge case handling

## Linked Issues

Issues not created — gh CLI not available in this environment. Run `/plan-to-issues` after plan creation to create issues manually.

**Issue decomposition (5 independent work items):**

| # | Title | Files | Depends on |
|---|-------|-------|------------|
| 1 | Schema version tracking with metadata table | `shadow_state.py` | nothing |
| 2 | Prompt cache invalidation (reload + staleness) | `config/__init__.py` | nothing |
| 3 | Wire PaperLiveGapManager into production + Bayesian cold start | `shadow_mother.py`, `paper_live_gap.py` | nothing |
| 4 | Quota-pool-aware key rotation via response headers | `async_client.py`, `token_budget.py` | nothing |
| 5 | Backtest coverage reporting for pre-Phase-D dates | `backtest_runner.py` | nothing |
