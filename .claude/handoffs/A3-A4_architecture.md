# ARCHITECTURE_HANDOFF — MarketMind Phase A (A.3-A.4)

**Date:** 2026-05-11
**Architect:** Reviewed by Architect agent (af801262) after Red Team audit
**Status:** IMPLEMENTED + FIXED (commits 707d1f0, 1f0bfb2, 1c5eeaa)

## A.3 Integrity + Storage

### Modules
- `integrity/watchdog.py` — M1 (protocol injection), M2 (regex claim extraction, 5 types), M3 (Track A/B verification), M4 (agent scoring with 3-strike system)
- `integrity/fact_checker.py` — Claim extraction → Pro-based multi-source verification → synthesis report
- `storage/archivist.py` — JSON filesystem archive (year/month/day) + SQLite FTS5 with WAL mode
- `storage/session.py` — SessionState with 3-gate checkpoints, save/load/delete, mtime-sorted listing

### Key Decisions
- M2 regex MUST handle comma-separated thousands (fixed post-audit)
- M3 Track A: yfinance verification for prices, ratios, amounts; Track B forward-declaration for unverifiable
- M4: verified false → -15 score + 1 strike; 3 strikes = TERMINATED
- Archivist uses persistent connection + WAL mode (fixed from per-call connect/close)
- SessionManager sorts by modification time, not filename (fixed)

## A.4 Position Patrol

### Modules
- `pipeline/position_patrol.py` — Daily health check, green/yellow/red cards, buy-archive comparison

### Key Decisions (post-Architect review)
- **Data provenance partition**:
  - FROM INPUT (never LLM): ticker, entry_price, current_price, pnl_pct, days_held, protection_active
  - FROM LLM (analytical only): status, logic_valid, technical_breach, recommendation, etc.
  - FROM CODE (post-parse): recommendation_override, override_reason
- **60-day protection**: Code-enforced veto — if days_held < 60 and <2 exit conditions met, exit → hold override
- **Error reporting**: Returns `(list[PositionStatus], str | None)` tuple instead of silent `[]`
- **LLM prompt**: Output schema excludes ground-truth fields (entry_price, current_price, pnl_pct, days_held)

### Architecture Decisions (from Red Team audit)
- **AD-1**: M2 amount regex: FIX — comma support via `[\d,]+` + normalize_value()
- **AD-2**: 60-day protection: FIX — config.position_protection_days + _apply_protection_veto()
- **AD-3**: PositionStatus data provenance: FIX — input join for ground-truth, simplified LLM output schema
- **AF-1**: Error suppression in patrol_positions: FIX — returns (result, error) tuple
