"""Data providers for API endpoints — isolates data access from route handlers.

Each function returns a dict ready for JSONResponse. Exceptions are caught
at the route level, not here — providers raise on real failures.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.api.data_providers")

# ── In-memory log (shared across providers and routes) ──────────────
_log_entries: list[dict] = []
_start_time = datetime.now(timezone.utc)


def add_log_entry(level: str, message: str) -> None:
    """Append to in-memory log and broadcast via WebSocket (if available)."""
    _log_entries.append({
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "level": level,
        "message": message,
    })
    if len(_log_entries) > 200:
        _log_entries[:] = _log_entries[-100:]
    # Fire-and-forget WebSocket broadcast (safe in sync or async contexts)
    try:
        from marketmind.api.websocket import broadcast_log as _bl
        loop = asyncio.get_running_loop()
        loop.create_task(_bl(level, message))
    except (RuntimeError, ImportError):
        pass  # No running loop (tests, early startup) — silently skip


# Public alias — call this from pipeline code for WS broadcast
ws_log = add_log_entry


def get_log_entries(count: int = 50) -> list[dict]:
    return _log_entries[-count:]


def get_uptime() -> str:
    return str(datetime.now(timezone.utc) - _start_time).split(".")[0]


# ── Shadow DB ───────────────────────────────────────────────────────

def _get_shadow_db():
    from marketmind.shadows.shadow_state import ShadowStateDB
    db_path = os.environ.get("SHADOW_DB", "data/shadows/shadows.db")
    db = ShadowStateDB(db_path)
    try:
        db.init_schema()
    except Exception:
        pass
    return db


# ── Providers ───────────────────────────────────────────────────────

def get_portfolio() -> dict:
    db = _get_shadow_db()
    trades = []
    if hasattr(db, 'get_all_open_trades'):
        trades = db.get_all_open_trades()
    total_val = sum(t.get("market_value", 0) for t in trades) if trades else 0
    return {
        "positions": trades,
        "total_value": total_val,
        "cash_pct": 100.0 if not total_val else round((1 - total_val / 100000) * 100),
        "patrol_status": "idle",
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def get_cost() -> dict:
    try:
        from marketmind.gateway.async_client import get_budget_report
        budget = get_budget_report()
    except Exception:
        budget = {"status": "error"}
    return {
        "pro_calls": budget.get("pro_calls_today", 0),
        "pro_limit": budget.get("pro_call_limit", 50),
        "flash_calls": budget.get("flash_calls_today", 0),
        "flash_limit": budget.get("flash_call_limit", 100),
        "tokens_used": budget.get("tokens_used_today", 0),
        "token_budget": budget.get("daily_token_budget", 2_000_000),
        "monthly_est": budget.get("estimated_monthly_cost", 0.0),
        "circuit_breaker": budget.get("circuit_breaker_state", "unknown"),
    }


def get_source_status() -> list[dict]:
    """Return source health from config/source_authority when available."""
    sources = []
    try:
        from marketmind.config.source_authority import SOURCE_AUTHORITY
        for name, cfg in SOURCE_AUTHORITY.items():
            sources.append({
                "name": name,
                "ok": cfg.get("status", "active") == "active",
                "tier": cfg.get("tier", 3),
            })
    except Exception:
        pass
    # Fallback: hardcoded list from config
    if not sources:
        for name, url, has_key in [
            ("FRED", "api.stlouisfed.org", bool(os.environ.get("FRED_KEY"))),
            ("CBOE CSV", "cboe.com", True),
            ("DefiLlama", "api.llama.fi", True),
            ("Crypto F&G", "alternative.me", True),
            ("Blockchain", "blockchain.info", True),
            ("EIA", "eia.gov", bool(os.environ.get("EIA_KEY"))),
            ("BLS", "bls.gov", True),
            ("CFTC COT", "cftc.gov", True),
            ("World Bank", "worldbank.org", True),
            ("SEC EDGAR", "sec.gov", True),
        ]:
            sources.append({"name": name, "ok": has_key if name in ("FRED", "EIA") else True})
    return sources


def get_health() -> dict:
    srcs = get_source_status()
    ok = sum(1 for s in srcs if s["ok"])
    return {
        "status": "ok" if ok == len(srcs) else "degraded",
        "uptime": get_uptime(),
        "sources_ok": ok,
        "sources_total": len(srcs),
    }


def get_shadow_overview() -> dict:
    db = _get_shadow_db()
    shadows = db.get_visible_shadows()
    tiers: dict[str, int] = {"elite": 0, "excellent": 0, "normal": 0, "watch": 0, "endangered": 0}
    for s in shadows:
        snap = db.get_latest_snapshot(s.shadow_id)
        tier = snap.achievement_tier if snap and snap.achievement_tier else "normal"
        tiers[tier] = tiers.get(tier, 0) + 1
    graduates = sum(1 for s in shadows if getattr(s, "status", "") == "graduated")
    return {
        "tiers": tiers,
        "total": len(shadows),
        "evolutions_today": 0,
        "challenger_trials": 0,
        "graduates": graduates,
        "diversity": "normal",
    }


def get_shadow_rankings() -> dict:
    db = _get_shadow_db()
    shadows = db.get_visible_shadows()
    top5 = []
    for s in shadows[:5]:
        snap = db.get_latest_snapshot(s.shadow_id)
        top5.append({
            "name": s.display_name,
            "tier": snap.achievement_tier if snap and snap.achievement_tier else "normal",
            "score": round(snap.composite_score, 2) if snap and snap.composite_score else 0.0,
        })
    return {"top5": top5}


def get_decision_history(limit: int = 10) -> dict:
    from marketmind.storage.archivist import get_archivist
    arch = get_archivist()
    results = arch.search("decision", limit=limit)
    decisions = [
        {
            "date": r.get("date", ""),
            "ticker": r.get("ticker", "--"),
            "direction": r.get("direction", ""),
            "confidence": r.get("confidence", 0),
            "result": r.get("result"),
        }
        for r in results
    ]
    return {"decisions": decisions}
