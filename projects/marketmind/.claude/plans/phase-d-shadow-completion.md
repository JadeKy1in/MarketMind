# Plan: Phase D — MarketMind Shadow System Completion

## WHY + SCOPE

Phase C completed with 339 tests and Red Team clearance. 5 known gaps remain from the Phase C completion report:

1. **GapRatio Calibration**: `update_discount_rate()` at `paper_live_gap.py:173` uses a hardcoded 20% baseline discount for all assets/strategies. The rate adjusts toward floor (5%) as inter-shadow gap converges, but the starting point and per-asset tier are arbitrary — no per-domain differentiation, no per-strategy tuning, no absolute return benchmark anchoring.

2. **Multi-day Backtest**: No validation that shadow consensus signals are predictive. ShadowVote objects are purely transient — created in-memory during `orchestrate_daily_cycle()`, used for ranking/collusion, then discarded. No vote persistence means no historical signal quality measurement is possible.

3. **Shadow Performance UI**: `shadow_panel.py` has a static ranking table. No historical trend visualization — no ranking trend charts, no discount rate evolution tracking. Users cannot see shadow performance over time.

4. **Methodology Prompts Inline**: `expert_shadows.py` (~80 lines across 15 domains) and `daredevil_shadows.py` (~40 lines across 5 variants) embed prompts as Python string constants. Prompt engineering requires code changes.

5. **Credential Management**: `TokenBudget` in `gateway/token_budget.py` is fully implemented (priority queue, daily limits, 429 backoff) but never wired into the call path. `daily_pro_limit:30` and `daily_flash_limit:100` are defined in settings but unenforced. Single API key with no rotation support.

**IN scope**: Dynamic GapRatio from PnL history per (domain, ticker); vote persistence + batch replay backtest from stored data; Canvas-based trend charts in UI (no matplotlib); JSON prompt configuration; TokenBudget wiring + API key rotation with `asyncio.Lock`.

**OUT of scope**: Brokerage APIs, live trading, new shadow types, full portfolio backtesting, OAuth, real-time streaming, matplotlib dependency.

**Success criteria**:
1. Discount rate calibrated from PnL dispersion per (domain, ticker), no hardcoded 20% used as starting point
2. `--backtest --start DATE --end DATE` produces hit_rate + Sharpe report from persisted vote history
3. Shadow Panel shows ranking trend chart + discount rate evolution chart
4. All methodology prompts loaded from `config/shadow_prompts.json`, Python code references by key
5. TokenBudget enforced on every LLM call; API key rotation on HTTP 429 with `asyncio.Lock`
6. 339+ tests pass, no regressions, test count only increases

## Existing Solutions

**Codebase research findings:**

- **TokenBudget** at `gateway/token_budget.py:16-96`: Priority queue (`CRITICAL` → `LOW`), `can_call_pro()`/`can_call_flash()`, `reserve_pro()`/`reserve_flash()`, `handle_429()` backoff, `report()`, daily auto-reset. Fully implemented. Zero callers — never wired into `async_client.py`.
- **Settings**: `daily_pro_limit:30`, `daily_flash_limit:100`, `daily_token_budget:2_000_000` — defined in `settings.py` but dormant. `confidence_discount_default:0.20`, `confidence_discount_floor:0.05`, `gap_closure_adjustment_factor:0.75` — the only discount-related config.
- **9 SQLite tables** in `shadow_state.py`: `daily_snapshots` (per-date per-shadow metrics including sharpe_ratio, composite_score, percentile_rank), `virtual_trades` (pnl_pct, ticker, entry/exit prices), `ranking_history` (rank, component_scores JSON), `paper_live_gap_state` (current discount_rate JSON blob — single-value, no time-series). **No vote persistence table exists.**
- **ShadowMother.orchestrate_daily_cycle()** at `shadow_mother.py:283`: 8-step single-day pipeline. Step 4 runs all shadow analyses in parallel and collects votes into `ShadowAnalysisOutput.votes` lists. These votes are used for ranking (step 5) and collusion detection (step 6), then discarded.
- **No backtest/simulator**: Zero CLI flags (`--backtest`, `--historical`, `--replay`), no multi-day loop, no time-override mechanism.
- **No charting libraries**: `customtkinter>=5.2.0` only. Canvas drawing available.
- **No YAML/JSON config loading**: All config is Python dataclasses + environment variables. JSON parsing used extensively for DB serialization elsewhere.

**Web search**: Not performed — this is internal project completion, no external libraries needed.

## Minimal Path

### Task 0: Vote Persistence (prerequisite for Tasks 1-2)
**Files**: `shadows/shadow_state.py`, `shadows/shadow_mother.py`

Small prerequisite: persist shadow votes so backtest calibration has data.

1. Add `shadow_votes` table to `_SCHEMA_SQL`:
```sql
CREATE TABLE IF NOT EXISTS shadow_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long','short','abstain')),
    confidence REAL NOT NULL,
    thesis TEXT,
    risk_note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_votes_date ON shadow_votes(date);
CREATE INDEX IF NOT EXISTS idx_shadow_votes_shadow_date ON shadow_votes(shadow_id, date);
```
2. Add `save_votes(shadow_id, date, votes: list[ShadowVote])` method
3. Add `get_votes_by_date_range(start_date, end_date) -> list` method
4. In `shadow_mother.py::orchestrate_daily_cycle()`: after step 4 (analyses complete), call `state_db.save_votes()` for each shadow's votes

### Task 1: GapRatio Calibration
**Files**: `shadows/paper_live_gap.py`, `shadows/shadow_state.py`, `shadows/shadow_mother.py`, `config/settings.py`

1. Add `discount_rate REAL DEFAULT 0.20` column to `daily_snapshots` schema — enables time-series charting (Task 3)
2. Add `get_pnl_by_domain(domain: str) -> list[float]` to `ShadowStateDB`:
   - Query `virtual_trades` JOIN `shadows` WHERE `json_extract(config_json, '$.domain') = ?`
   - Domain sourced from `ShadowConfig.domain` stored in `shadows.config_json` column
3. Add `absolute_return_benchmark: float = 0.04` to `ShadowSettings`
4. Modify `update_discount_rate(self, shadow_id: str, ticker: str | None = None) -> float`:
   - `ticker` given: compute CV of shadow's PnL for ticker vs. domain peers. CV > 1.0 → near ceiling. CV < 0.3 → near floor. Returns below benchmark → penalty.
   - `ticker` None: aggregate across all tickers (backward compatible)
   - Cold start: < 10 trades → fall back to `confidence_discount_default` (0.20)
5. Wiring: In `shadow_mother.py`, pass current `discount_rate` from `PaperLiveGapManager._get_discount_rate()` to `save_snapshot()` for storage in `discount_rate` column

### Task 2: Multi-day Backtest
**Files**: `backtest_runner.py` (new), `app.py`

1. New `backtest_runner.py` with `BacktestRunner`:
   - Constructor takes `ShadowStateDB`
   - `run(start_date, end_date)`: For each date, query `shadow_votes` for top-5 shadows by composite_score (from `ranking_history`). Compute consensus = majority direction (long/short) per ticker. Check against next-day return sign from `virtual_trades`.
   - For dates before vote persistence exists: use `daily_snapshots.daily_return_pct` sign as proxy for direction
   - Metrics: hit_rate, sharpe_of_consensus, by_ticker, by_shadow_type, confusion_matrix
   - Output JSON to `--output` path or stdout
2. Add CLI flags to `app.py`: `--backtest`, `--start DATE`, `--end DATE`, `--output PATH`

### Task 3: Shadow Performance UI
**Files**: `ui/shadow_charts.py` (new), `ui/shadow_panel.py`

1. New `ui/shadow_charts.py` with two Canvas-based widgets:
   - `RankingTrendChart(ctk.CTkFrame)`: Queries `get_snapshot_history()`, plots composite_score time-series. Multiple shadows = multiple colored lines. Manual Canvas axes with date labels.
   - `DiscountRateChart(ctk.CTkFrame)`: Queries `daily_snapshots.discount_rate` column via `get_snapshot_history()`. Single-shadow line chart. X=date, Y=rate (0.05-0.20 range).
   - Both use manual Canvas drawing (lines, axes, labels) — zero new dependencies
2. Modify `ui/shadow_panel.py`: Add chart container below scrollable ranking table. On row click → load trend data → render both charts.

### Task 4: Prompt Externalization
**Files**: `config/shadow_prompts.json` (new), `config/__init__.py`, `shadows/expert_shadows.py`, `shadows/daredevil_shadows.py`

1. Create `config/shadow_prompts.json` with structure: `{"expert": {gold: "...", crypto: "...", ...15 domains}, "daredevil": {scalper: "...", ...5 variants}}`
2. Add `load_shadow_prompts(path=None) -> dict` to `config/__init__.py` (cached singleton, parsed once)
3. Modify `expert_shadows.py`: Replace inline `_DOMAIN_PROMPTS` dict with `_load_prompts()` call at module level
4. Modify `daredevil_shadows.py`: Replace 5 inline prompt strings with JSON-loaded values
5. Test: round-trip JSON parseability validation

### Task 5: Credential Rotation + TokenBudget Wiring
**Files**: `gateway/async_client.py`, `config/settings.py`

1. Modify `settings.py`: Change `deepseek_api_key` to `deepseek_api_keys: list[str]`. Parse `DEEPSEEK_API_KEYS` (comma-separated), fall back to `DEEPSEEK_API_KEY` for backward compatibility.
2. Modify `gateway/async_client.py`:
   a. Add `KeyRotator` class inline (~15 lines): `__init__(keys)`, `current() -> str`, `async rotate() -> str` (under `asyncio.Lock`, cycles through keys)
   b. Make `TokenBudget.reserve_pro()`/`reserve_flash()` atomic with `asyncio.Lock` (add lock to class)
   c. In `init_gateway()`: create `TokenBudget` instance from settings, store globally
   d. In `chat_flash()`: `await budget.reserve_flash(estimated_tokens=4096)`. If exhausted: return error dict.
   e. In `chat_pro()`: same with `reserve_pro(estimated_tokens=8192)`. Release over-reserved tokens after actual call.
   f. In `_call()`: compute `Authorization` header per-request from `key_rotator.current()`. On HTTP 429: `budget.handle_429()` + `await key_rotator.rotate()` → retry once.
   g. `asyncio.Semaphore(max_concurrent_shadows=5)` in `shadow_mother.py` is primary throttle. TokenBudget is the safety net.

## Files to Create/Modify (15 files)

| # | File | Action | Depends On |
|---|------|--------|------------|
| 1 | `shadows/shadow_state.py` | MODIFY (shadow_votes table + methods, discount_rate column, get_pnl_by_domain) | None |
| 2 | `shadows/shadow_mother.py` | MODIFY (save votes after analysis, pass discount_rate to save_snapshot) | #1 |
| 3 | `config/settings.py` | MODIFY (api_keys list, benchmark field) | None |
| 4 | `shadows/paper_live_gap.py` | MODIFY (per-domain calibration, update_discount_rate API) | #1, #3 |
| 5 | `config/shadow_prompts.json` | CREATE | None |
| 6 | `config/__init__.py` | MODIFY (add prompt loader) | #5 |
| 7 | `shadows/expert_shadows.py` | MODIFY (load from JSON) | #5, #6 |
| 8 | `shadows/daredevil_shadows.py` | MODIFY (load from JSON) | #5, #6 |
| 9 | `gateway/async_client.py` | MODIFY (wire TokenBudget + KeyRotator inline) | #3 |
| 10 | `backtest_runner.py` | CREATE | #1, #2 |
| 11 | `app.py` | MODIFY (--backtest CLI flags) | #10 |
| 12 | `ui/shadow_charts.py` | CREATE | #1 |
| 13 | `ui/shadow_panel.py` | MODIFY (add chart widgets) | #12 |
| 14 | `tests/test_backtest_runner.py` | CREATE | #10 |
| 15 | `tests/test_shadows/test_paper_live_gap.py` | MODIFY (add calibration tests) | #4 |

## Dependency Graph

```
                    Task 4 (prompts) ── independent
Task 0 (votes) ──┐  Task 5 (gateway)  ── independent
                 ├── Task 1 (calib)    ── after Task 0
                 ├── Task 2 (backtest) ── after Task 0
                 │
                 └── Task 3 (UI)       ── after Task 1
```

**Execution order**: Task 0 first (unblocks 1+2). Then [1→3], [2], [4], [5] in parallel.

## Risks and Unknowns

1. **Vote persistence volume**: 20+ shadows × 3-5 votes/day ≈ 60-100 rows/day. After 1 year ≈ 30k rows — well within SQLite capacity.
2. **Backtest data window**: Vote persistence starts NOW. Historical backtest covers dates after deployment. Pre-existing snapshots provide partial signal (daily_return sign as proxy direction) for earlier dates.
3. **Canvas charting complexity**: Manual axis scaling, date formatting, multi-line rendering. Estimate ~150-200 lines per chart widget. Customtkinter Canvas primitives only — no auto-scaling or label libraries.
4. **Prompt JSON escaping**: Prompts contain double quotes and newlines. Must validate with round-trip test (load → compare all 20 prompts match expected strings).
5. **TokenBudget + Semaphore interaction**: Semaphore(5) limits concurrent calls. TokenBudget checks inside semaphore — if budget exhausted while 5 shadows mid-call, subsequent attempts get `budget_exhausted`. This is correct behavior.
6. **Key rotation under shared quota**: If all DeepSeek keys share a Tier quota pool, rotation after 429 may not help. Rotation provides resilience against single-key expiration/revocation, not quota expansion. Documented as known limitation.
7. **Calibration cold start**: New shadows/tickers with < 10 trades fall back to 20% default. Visible in discount_rate chart as flat line at 0.20 until enough trades accumulate.
8. **Schema migration**: Three schema additions: `shadow_votes` table (CREATE IF NOT EXISTS), `discount_rate` column (ALTER TABLE ADD COLUMN), `shadow_votes` indexes. All safe for existing databases — no data migration needed. Existing `daily_snapshots` rows get NULL discount_rate (interpreted as 0.20 default).

## Critique History

Three rounds of adversarial plan-critic review (Opus model):

| Round | Verdict | Composite | Key Findings |
|-------|---------|-----------|-------------|
| 1 | REVISE | 2.4 | Discount rate chart has no time-series data source (paper_live_gap_state stores only current value); ticker-to-group mapping undefined; file count too high (19); key rotation design unspecified; update_discount_rate API unchanged |
| 2 | REVISE | 2.8 | Vote data transient — no persistence for backtest (CRITICAL); TokenBudget check-then-reserve race; domain extraction strategy wrong (should use config_json, not shadow_id prefix); discount rate wiring to save_snapshot unspecified |
| 3 | PROCEED | 3.0 | All prior issues resolved. 7 minor findings documented in Implementation Notes — none blocking. Plan converged and ready for implementation. |

**Implementation Notes from final critique**:
- A. `save_votes()` should use `executemany()` for batch insert efficiency
- B. Domain extraction: `json_extract(config_json, '$.domain')` — verify SQLite JSON1 extension enabled
- C. TokenBudget `estimated_tokens` should be an over-estimate (release excess after), not an under-estimate
- D. Backtest `next-day return` for last date in range: exclude (no next day to compare)
- E. Canvas chart date formatting: use `datetime.strftime("%m/%d")` for X-axis labels to fit horizontally
- F. `config/__init__.py` loader: handle `FileNotFoundError` gracefully with descriptive error
- G. ShadowMother: vote save should happen inside the `_run_one()` wrapper for per-shadow error isolation

## Linked Issues

Issues not created — `gh` CLI not installed/authenticated. Run `/plan-to-issues` to create GitHub issues manually.
