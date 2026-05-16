# Red Team Audit — Phase D

**Date**: 2026-05-12
**Status**: COMPLETE — all findings resolved
**Tests**: 339 passed, 0 warnings

## Findings

| ID | Severity | Issue | File | Status |
|----|----------|-------|------|--------|
| W-1 | WARNING | No date validation on `--start`/`--end` — malformed dates crash with unhandled ValueError | `backtest_runner.py:22` | FIXED |
| W-2 | WARNING | `start > end` silently produces empty backtest report | `backtest_runner.py:20` | FIXED |
| W-3 | WARNING | Accessing private `_connect()` method from backtest runner | `backtest_runner.py:189` | FIXED |
| I-1 | INFO | Accessing private `_idx` attribute in key rotation logging | `async_client.py:209` | FIXED |
| I-2 | INFO | Path traversal possible via `--output` flag | `app.py` | ACCEPTED — CLI tool, user controls output |
| I-3 | INFO | `json_extract` relies on SQLite JSON1 extension | `shadow_state.py:921` | ACCEPTED — try/except fallback handles missing extension |
| I-4 | INFO | `_run_backtest` doesn't catch backtest exceptions | `app.py` | FIXED |

## Resolution Summary

- **W-1/W-2**: Added `ValueError` with descriptive message for malformed dates and `start > end`
- **W-3**: Added `get_next_day_return_sign()` public method to `ShadowStateDB`
- **I-1**: Replaced `gw.key_rotator._idx` with `len(gw.key_rotator)` in log message
- **I-4**: Added try/except in `_run_backtest()` for graceful error handling

## SQL Injection Check

All new SQL queries in `shadow_state.py` use parameterized queries (`?` placeholders with tuple bindings). No string concatenation or f-string SQL construction found.

- `save_votes()` — executemany with parameterized INSERT
- `get_votes_by_date_range()` — parameterized SELECT
- `get_pnl_by_domain()` — parameterized SELECT with `json_extract` (JSON path hardcoded, domain value parameterized)
- `get_next_day_return_sign()` — parameterized SELECT
