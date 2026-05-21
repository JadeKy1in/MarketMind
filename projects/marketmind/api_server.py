"""MarketMind API Server — FastAPI + embedded HTML dashboard.

Start: python api_server.py
Then open: http://localhost:8520
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger("marketmind.api_server")

app = FastAPI(title="MarketMind", version="2.0")

# ── Shared state for log streaming ──────────────────────────────────
_log_entries: list[dict] = []
_start_time = datetime.now(timezone.utc)

def api_log(level: str, message: str):
    _log_entries.append({
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "level": level, "message": message,
    })
    if len(_log_entries) > 200:
        _log_entries[:] = _log_entries[-100:]

# ── Lazy helpers (avoid import errors when DB/files not yet set up) ──

def _get_shadow_db():
    from marketmind.shadows.shadow_state import ShadowStateDB
    db_path = os.environ.get("SHADOW_DB", "data/shadows/shadows.db")
    db = ShadowStateDB(db_path)
    try: db.init_schema()
    except Exception: pass
    return db

def _get_budget():
    try:
        from marketmind.gateway.async_client import get_budget_report
        return get_budget_report()
    except Exception:
        return {"status": "not_initialized"}

def _get_source_status():
    sources = []
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
        sources.append({"name": name, "ok": has_key if name in ("FRED","EIA") else True})
    return sources


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# API Routes — Layer 1: What you always see
# ---------------------------------------------------------------------------

@app.get("/api/portfolio")
async def portfolio():
    try:
        db = _get_shadow_db()
        trades = db.get_trade_history("__all__", limit=20) if hasattr(db, 'get_all_open_trades') else []
        total_val = sum(t.get("market_value", 0) for t in trades) if trades else 0
        return JSONResponse({
            "positions": trades if trades else [],
            "total_value": total_val,
            "cash_pct": 100.0 if not total_val else round((1 - total_val/100000) * 100),
            "patrol_status": "idle",
            "updated": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        return JSONResponse({"positions": [], "total_value": 0, "cash_pct": 100, "patrol_status": "db_unavailable"})


@app.get("/api/cost")
async def cost():
    try:
        budget = _get_budget()
    except Exception:
        budget = {"status": "error"}
    return JSONResponse({
        "pro_calls": budget.get("pro_calls_today", 0),
        "pro_limit": budget.get("pro_call_limit", 50),
        "flash_calls": budget.get("flash_calls_today", 0),
        "flash_limit": budget.get("flash_call_limit", 100),
        "tokens_used": budget.get("tokens_used_today", 0),
        "token_budget": budget.get("daily_token_budget", 2_000_000),
        "monthly_est": budget.get("estimated_monthly_cost", 0.0),
        "circuit_breaker": budget.get("circuit_breaker_state", "unknown"),
    })


@app.get("/api/log")
async def system_log():
    return JSONResponse({"entries": _log_entries[-50:]})


@app.get("/api/shadows/overview")
async def shadow_overview():
    try:
        db = _get_shadow_db()
        shadows = db.get_visible_shadows()
        tiers = {"elite": 0, "excellent": 0, "normal": 0, "watch": 0, "endangered": 0}
        for s in shadows:
            tier = getattr(s, "achievement_tier", "normal") or "normal"
            tiers[tier] = tiers.get(tier, 0) + 1
        graduates = sum(1 for s in shadows if getattr(s, "status", "") == "graduated")
        return JSONResponse({
            "tiers": tiers,
            "total": len(shadows),
            "evolutions_today": 0,
            "challenger_trials": 0,
            "graduates": graduates,
            "diversity": "normal",
        })
    except Exception:
        return JSONResponse({"tiers": {}, "total": 0, "graduates": 0})


@app.get("/api/shadows/rankings")
async def shadow_rankings():
    try:
        db = _get_shadow_db()
        shadows = db.get_visible_shadows()
        top5 = []
        for s in shadows[:5]:
            top5.append({
                "name": s.display_name,
                "tier": getattr(s, "achievement_tier", "normal") or "normal",
                "score": round(getattr(s, "composite_score", 0), 2),
            })
        return JSONResponse({"top5": top5})
    except Exception:
        return JSONResponse({"top5": []})


@app.get("/api/history/decisions")
async def decision_history():
    try:
        from marketmind.storage.archivist import get_archivist
        arch = get_archivist()
        results = arch.search("decision", limit=10)
        decisions = []
        for r in results:
            decisions.append({
                "date": r.get("date", ""),
                "ticker": r.get("ticker", "--"),
                "direction": r.get("direction", ""),
                "confidence": r.get("confidence", 0),
                "result": r.get("result"),
            })
        return JSONResponse({"decisions": decisions})
    except Exception:
        return JSONResponse({"decisions": []})


@app.post("/api/info/inject")
async def info_inject(request: dict):
    """Inject user-provided information into the pipeline."""
    from marketmind.pipeline.info_injector import inject_user_info
    text = request.get("text", "")
    files = request.get("files", [])
    result = await inject_user_info(text=text, files=files)
    api_log("info", f"Info injected: {len(result.items)} items, {result.total_chars} chars")
    return JSONResponse({
        "status": "ok",
        "items": len(result.items),
        "chars": result.total_chars,
    })


@app.get("/api/health")
async def health():
    sources = _get_source_status()
    ok = sum(1 for s in sources if s["ok"])
    return JSONResponse({
        "status": "ok" if ok == len(sources) else "degraded",
        "uptime": str(datetime.now(timezone.utc) - _start_time).split(".")[0],
        "sources_ok": ok,
        "sources_total": len(sources),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    api_log("info", "MarketMind API server starting")
    uvicorn.run(app, host="0.0.0.0", port=8520, log_level="info")
