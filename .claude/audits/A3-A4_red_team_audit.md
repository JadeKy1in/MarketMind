# RED_TEAM_AUDIT — Phase A.3 + A.4

**Date:** 2026-05-11
**Agent:** Red Team (Haiku 1M, agentId: a48d028f)
**Status:** All Critical resolved (commit 1c5eeaa)

## Critical (blocks deployment)

1. **M2 amount regex drops comma-separated thousands** — `watchdog.py:51`
   - Pattern `\d+` fails on "1,234 billion" → captures "234"
   - **Resolved**: Changed to `[\d,]+` + `_normalize_value()` strip commas

2. **60-day protection period is prompt-only** — `position_patrol.py:56,97-113`
   - LLM trusted with enforcement of safety constraint
   - **Resolved**: Code-level `_apply_protection_veto()` with configurable `position_protection_days`

3. **PositionStatus ground-truth from LLM output** — `position_patrol.py:97-103`
   - entry_price, current_price, pnl_pct, days_held populated from LLM response JSON
   - **Resolved**: Input join via `pos_lookup`, ground-truth fields excluded from LLM output schema

## Warnings (all resolved)

- W4: `__init__.py` files empty → Exported public symbols
- W5: `_verify_price` silent exception → Replaced with structured logging
- W6: `patrol_positions` masks failures with `[]` → Returns (result, error) tuple
- W7: No `test_fact_checker.py` → Created 7 tests
- W8: `list_sessions()` sorts alphabetically → Sorts by mtime
- W9: Fence-stripping non-standard → Uses shared response_parser.extract_json()
- W10: M3 Track A missing for ratios/amounts → Added yfinance verification

## Architect Review

All 3 Criticals: FIX. Four additional findings (AF-1 through AF-4): FIX.
No DEFER or IGNORE items.
