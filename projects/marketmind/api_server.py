"""MarketMind API Server — FastAPI + embedded HTML dashboard.

Start: python api_server.py
Then open: http://localhost:8520
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("marketmind.api_server")

app = FastAPI(title="MarketMind", version="2.0")

# ---------------------------------------------------------------------------
# HTML Dashboard (embedded — no frontend build tool needed)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _DASHBOARD_HTML


# ---------------------------------------------------------------------------
# API Routes — Layer 1: What you always see
# ---------------------------------------------------------------------------

@app.get("/api/portfolio")
async def portfolio():
    """Current positions, P&L, patrol status."""
    return JSONResponse({
        "positions": [],
        "total_value": 0.0,
        "cash_pct": 100.0,
        "patrol_status": "idle",
        "updated": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/gates")
async def gates():
    """Gate 1/2/3 status and pending decisions."""
    return JSONResponse({
        "gate1": {"status": "idle"},
        "gate2": {"status": "idle", "ticker": None, "elite_available": 0},
        "gate3": {"status": "idle", "ticker": None},
        "injected_items": 0,
    })


@app.get("/api/progress")
async def progress():
    """Pipeline stage progress."""
    return JSONResponse({
        "stages": [
            {"name": "Scout", "status": "pending"},
            {"name": "Flash", "status": "pending"},
            {"name": "HVR", "status": "pending"},
            {"name": "L1", "status": "pending"},
            {"name": "L2/L3", "status": "pending"},
            {"name": "Shadows", "status": "pending"},
            {"name": "Red Team", "status": "pending"},
            {"name": "Decision", "status": "pending"},
        ],
        "overall_pct": 0,
        "elapsed": "0:00",
        "running": False,
    })


@app.get("/api/cost")
async def cost():
    """Token usage and API cost."""
    return JSONResponse({
        "pro_calls": 0, "pro_limit": 50,
        "flash_calls": 0, "flash_limit": 100,
        "tokens_used": 0, "token_budget": 2_000_000,
        "monthly_est": 0.0,
        "circuit_breaker": "closed",
    })


# ---------------------------------------------------------------------------
# API Routes — Layer 2: System log
# ---------------------------------------------------------------------------

_log_entries: list[dict] = []


@app.get("/api/log")
async def system_log():
    return JSONResponse({"entries": _log_entries[-50:]})


def api_log(level: str, message: str):
    _log_entries.append({
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "level": level,
        "message": message,
    })
    if len(_log_entries) > 200:
        _log_entries[:] = _log_entries[-100:]


# ---------------------------------------------------------------------------
# API Routes — Layer 3: Shadow ecosystem
# ---------------------------------------------------------------------------

@app.get("/api/shadows/overview")
async def shadow_overview():
    return JSONResponse({
        "tiers": {"elite": 0, "excellent": 0, "normal": 0, "watch": 0, "endangered": 0},
        "evolutions_today": 0,
        "challenger_trials": 0,
        "graduates": 0,
        "diversity": "normal",
    })


@app.get("/api/shadows/rankings")
async def shadow_rankings():
    return JSONResponse({"top5": []})


# ---------------------------------------------------------------------------
# API Routes — Layer 4: History
# ---------------------------------------------------------------------------

@app.get("/api/history/decisions")
async def decision_history():
    return JSONResponse({"decisions": []})


@app.get("/api/history/evolution")
async def evolution_timeline():
    return JSONResponse({"events": []})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "uptime": "0:00",
        "sources_ok": 0, "sources_total": 0,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    api_log("info", "MarketMind API server starting")
    uvicorn.run(app, host="0.0.0.0", port=8520, log_level="info")
