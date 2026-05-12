# Operation Scout Audit — Phase D

**Date**: 2026-05-12
**Status**: COMPLETE — HIGH issues resolved, MEDIUM issues documented
**Tests**: 339 passed, 0 warnings

## Findings

| # | Severity | Issue | File | Status |
|---|----------|-------|------|--------|
| 1 | HIGH | No ALTER TABLE migration for `discount_rate` column — existing databases never get the column | `shadow_state.py` | FIXED |
| 2 | HIGH | `_evaluate_day_from_snapshots()` passes `shadow_id` as `ticker` — produces autocorrelation, not predictive signal | `backtest_runner.py:171` | FIXED |
| 3 | MEDIUM | Module-level `_prompt_cache` global — no invalidation, no thread safety, no reload | `config/__init__.py` | ACCEPTED |
| 4 | MEDIUM | `budget_exhausted` indistinguishable from LLM failure in shadow agent | `async_client.py` / `shadow_agent.py` | ACCEPTED |
| 5 | MEDIUM | `_calibrate_per_asset()` dead zone — requires 10+ trades, never called with ticker in production | `paper_live_gap.py:231` | ACCEPTED |
| 6 | LOW | `KeyRotator.__len__` without `__iter__`/`__getitem__` — incomplete container protocol | `async_client.py:42` | ACCEPTED |
| 7 | LOW | `_load_charts_for_shadow()` state_db None-safety | `shadow_panel.py:135` | CORRECT — already guarded |

## Resolution Detail

### HIGH-1: Schema Migration (FIXED)

Added `_migrate_add_column()` static method to `ShadowStateDB` that runs `ALTER TABLE ADD COLUMN` for the `discount_rate` column. Uses try/except to silently skip if column already exists. Called from `init_schema()` after the main CREATE TABLE scripts.

```python
@staticmethod
def _migrate_add_column(conn, table, column, col_type):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass  # Column already exists
```

### HIGH-2: Backtest Fallback (FIXED)

Removed `_evaluate_day_from_snapshots()` entirely. The snapshot-based fallback path passed `snap.shadow_id` (e.g., `"expert:gold:arthur"`) as the ticker parameter to `get_next_day_return_sign()`, which would:
1. Never match any ticker in `virtual_trades` (produces `None`)
2. Fall through to `daily_snapshots WHERE shadow_id = ?` — producing autocorrelation, not predictive signal

The backtest now returns empty results for dates without vote data, which is the correct behavior.

### MEDIUM-3: Calibration Dead Zone (ACCEPTED)

`_calibrate_per_asset()` requires 10+ trades for calibration. For new shadows, the discount rate stays at the 20% default until trade history accumulates. The aggregate path (`update_discount_rate` without ticker) can still adjust rates via inter-shadow gap. `_calibrate_per_asset` is exposed as a public API for future use when explicit per-asset calibration is needed.

### MEDIUM-1: Prompt Cache (ACCEPTED)

Module-level cache is appropriate for a single-process CLI/GUI application. Adding thread safety (RLock) or file watching (inotify/polling) would be over-engineering for the current deployment model. If multi-process deployment is needed in the future, the cache should be moved to an explicit `PromptConfig` class with `reload()` method.

### MEDIUM-2: Budget Error Indistinguishability (ACCEPTED)

The plan explicitly designs this behavior: when budget is exhausted, shadows receive empty output and produce zero votes, which is the correct fail-closed behavior. The `quota_used` counter correctly stays at 0 for budget-exhausted calls. Adding a separate error code would require changes to the `ShadowAnalysisOutput` dataclass and all callers — out of scope for Phase D.

## Architecture Observations

1. **Schema version tracking**: The database has no `schema_version` table. Future phases should add one to enable safe incremental migrations.
2. **JSON config pattern**: The `load_shadow_prompts()` pattern (cached singleton loader) is a good precedent for future config externalization.
3. **Chart lifecycle**: Lazy canvas creation (`_ensure_canvas()`) is the correct pattern for headless-safe UI components.
4. **Backtest data dependency**: The backtest is cleanly separated from the live pipeline — it reads historical data without side effects.
