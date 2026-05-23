"""FastAPI route definitions — thin handlers, all logic in data_providers."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path

from marketmind.api.data_providers import (
    add_log_entry,
    get_cost,
    get_decision_history,
    get_health,
    get_log_entries,
    get_portfolio,
    get_shadow_detail,
    get_shadow_overview,
    get_shadow_rankings,
)
from marketmind.api.websocket import ws_endpoint

app = FastAPI(title="MarketMind", version="2.0")
app.websocket("/ws")(ws_endpoint)

DASHBOARD_PATH = Path(__file__).parent.parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_PATH.read_text(encoding="utf-8")


@app.get("/api/portfolio")
async def portfolio():
    try:
        return JSONResponse(get_portfolio())
    except Exception:
        return JSONResponse({"positions": [], "total_value": 0, "cash_pct": 100, "patrol_status": "db_unavailable"})


@app.get("/api/cost")
async def cost():
    try:
        return JSONResponse(get_cost())
    except Exception:
        return JSONResponse({"status": "error"})


@app.get("/api/log")
async def system_log():
    return JSONResponse({"entries": get_log_entries()})


@app.get("/api/shadows/overview")
async def shadow_overview():
    try:
        return JSONResponse(get_shadow_overview())
    except Exception:
        return JSONResponse({"tiers": {}, "total": 0, "graduates": 0})


@app.get("/api/shadows/rankings")
async def shadow_rankings():
    try:
        return JSONResponse(get_shadow_rankings())
    except Exception:
        return JSONResponse({"top5": []})


@app.get("/api/shadows/{shadow_id}")
async def shadow_detail(shadow_id: str):
    try:
        return JSONResponse(get_shadow_detail(shadow_id))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/history/decisions")
async def decision_history():
    try:
        return JSONResponse(get_decision_history())
    except Exception:
        return JSONResponse({"decisions": []})


@app.post("/api/info/inject")
async def info_inject(request: dict):
    from marketmind.pipeline.info_injector import inject_user_info
    text = request.get("text", "")
    files = request.get("files", [])
    result = await inject_user_info(text=text, files=files)
    add_log_entry("info", f"Info injected: {len(result.items)} items, {result.total_chars} chars")
    return JSONResponse({
        "status": "ok",
        "items": len(result.items),
        "chars": result.total_chars,
    })


@app.get("/api/health")
async def health():
    return JSONResponse(get_health())
