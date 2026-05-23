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
        logger.warning("shadow DB schema init failed", exc_info=True)
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
        logger.warning("budget report fetch failed", exc_info=True)
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
        logger.warning("SOURCE_AUTHORITY source status lookup failed", exc_info=True)
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
            "shadow_id": s.shadow_id,
            "name": s.display_name,
            "tier": snap.achievement_tier if snap and snap.achievement_tier else "normal",
            "score": round(snap.composite_score, 2) if snap and snap.composite_score else 0.0,
        })
    return {"top5": top5}


def get_shadow_detail(shadow_id: str) -> dict:
    """Return full detail for a single shadow: config, recent analyses,
    snapshot history, tier history, and open positions."""
    db = _get_shadow_db()
    config = db.get_shadow(shadow_id)
    if not config:
        raise ValueError(f"Shadow '{shadow_id}' not found")

    # Recent analyses (last 10 with direction)
    recent_analyses = db.get_analyses_with_direction(shadow_id, days=90)[:10]

    # Full snapshot history (last 60 days)
    snapshots = db.get_snapshot_history(shadow_id, days=60)

    # Tier history (last 120 days)
    tier_history = db.get_tier_history(shadow_id, days=120)

    # Open positions
    open_trades = db.get_open_trades(shadow_id)

    # Latest snapshot for summary stats
    latest = db.get_latest_snapshot(shadow_id)

    return {
        "shadow_id": config.shadow_id,
        "display_name": config.display_name,
        "shadow_type": config.shadow_type,
        "domain": config.domain,
        "methodology_prompt": config.methodology_prompt,
        "virtual_capital": config.virtual_capital,
        "status": config.status,
        "generation": config.generation,
        "model": config.model,
        "max_positions": config.max_positions,
        "created_at": config.created_at,
        "latest_snapshot": {
            "date": latest.date,
            "virtual_capital": latest.virtual_capital,
            "daily_return_pct": latest.daily_return_pct,
            "cumulative_return_pct": latest.cumulative_return_pct,
            "max_drawdown_pct": latest.max_drawdown_pct,
            "win_rate_pct": latest.win_rate_pct,
            "sharpe_ratio": latest.sharpe_ratio,
            "composite_score": latest.composite_score,
            "achievement_tier": latest.achievement_tier,
            "insights_generated": latest.insights_generated,
        } if latest else None,
        "recent_analyses": recent_analyses,
        "snapshots": [
            {
                "date": s.date,
                "virtual_capital": round(s.virtual_capital, 2) if s.virtual_capital else None,
                "daily_return_pct": s.daily_return_pct,
                "cumulative_return_pct": s.cumulative_return_pct,
                "max_drawdown_pct": s.max_drawdown_pct,
                "win_rate_pct": s.win_rate_pct,
                "sharpe_ratio": s.sharpe_ratio,
                "composite_score": round(s.composite_score, 2) if s.composite_score else None,
                "achievement_tier": s.achievement_tier,
            }
            for s in snapshots
        ],
        "tier_history": [{"date": d, "tier": t} for d, t in tier_history],
        "open_trades": [
            {
                "trade_id": t.trade_id,
                "ticker": t.ticker,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "entry_date": t.entry_date,
                "position_size_pct": t.position_size_pct,
                "pnl_pct": t.pnl_pct,
            }
            for t in open_trades
        ],
    }


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
