"""FastAPI route definitions — thin handlers, all logic in data_providers."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path

logger = logging.getLogger("marketmind.api.routes")

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
from marketmind.notification.alert_manager import get_alert_manager
from marketmind.api.websocket import broadcast_alert

app = FastAPI(title="MarketMind", version="2.0")
app.websocket("/ws")(ws_endpoint)

_alm = get_alert_manager()
_alm.set_broadcast_fn(broadcast_alert)

DASHBOARD_PATH = Path(__file__).parent.parent / "dashboard.html"
EVOLUTION_PATH = Path(__file__).parent.parent / "evolution.html"


_CACHE_PREVENT_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Vary": "*",
}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    headers = dict(_CACHE_PREVENT_HEADERS)
    headers["ETag"] = f'"{int(DASHBOARD_PATH.stat().st_mtime)}"'
    return HTMLResponse(content=content, headers=headers)


@app.get("/evolution", response_class=HTMLResponse)
async def evolution():
    content = EVOLUTION_PATH.read_text(encoding="utf-8")
    headers = dict(_CACHE_PREVENT_HEADERS)
    headers["ETag"] = f'"{int(EVOLUTION_PATH.stat().st_mtime)}"'
    return HTMLResponse(content=content, headers=headers)


@app.get("/api/portfolio")
async def portfolio():
    try:
        return JSONResponse(get_portfolio())
    except Exception:
        logger.warning("portfolio endpoint failed", exc_info=True)
        return JSONResponse({"positions": [], "total_value": 0, "cash_pct": 100, "patrol_status": "db_unavailable"})


@app.get("/api/cost")
async def cost():
    try:
        return JSONResponse(get_cost())
    except Exception:
        logger.warning("cost endpoint failed", exc_info=True)
        return JSONResponse({"status": "error"})


@app.get("/api/log")
async def system_log():
    return JSONResponse({"entries": get_log_entries()})


@app.get("/api/shadows/overview")
async def shadow_overview():
    try:
        return JSONResponse(get_shadow_overview())
    except Exception:
        logger.warning("shadow_overview endpoint failed", exc_info=True)
        return JSONResponse({"tiers": {}, "total": 0, "graduates": 0})


@app.get("/api/shadows/rankings")
async def shadow_rankings():
    try:
        return JSONResponse(get_shadow_rankings())
    except Exception:
        logger.warning("shadow_rankings endpoint failed", exc_info=True)
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
        logger.warning("decision_history endpoint failed", exc_info=True)
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


@app.get("/api/alerts")
async def alerts():
    return JSONResponse({"alerts": get_alert_manager().recent(50)})


@app.get("/api/alerts/health")
async def alerts_health():
    return JSONResponse(get_alert_manager().health())


@app.get("/api/evolution/shadows")
async def evolution_shadows():
    try:
        from marketmind.api.data_providers import get_shadow_evolution
        return JSONResponse(get_shadow_evolution())
    except Exception:
        return JSONResponse({"shadows": {}})


@app.get("/api/evolution/pipeline")
async def evolution_pipeline():
    try:
        from marketmind.api.data_providers import get_pipeline_evolution
        return JSONResponse(get_pipeline_evolution())
    except Exception:
        return JSONResponse({"history": [], "baseline": None})


@app.get("/api/evolution/stagnation")
async def evolution_stagnation():
    try:
        from marketmind.api.data_providers import get_stagnation_report
        return JSONResponse(get_stagnation_report())
    except Exception:
        return JSONResponse({"stagnation": {}})


@app.get("/api/health")
async def health():
    return JSONResponse(get_health())


@app.post("/api/pipeline/run")
async def pipeline_run(request: dict):
    """Trigger a daily pipeline run with optional --mock flag. Runs asynchronously."""
    import asyncio
    import subprocess
    import sys
    from pathlib import Path
    from marketmind.api.data_providers import add_log_entry

    mock = request.get("mock", True) if request else True
    project_dir = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "app.py", "--mode", "daily"]
    if mock:
        cmd.append("--mock")
    cmd.append("-v")

    add_log_entry("info", f"Pipeline started: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(project_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        # Non-blocking: fire and forget, pipeline broadcasts progress via WS
        return JSONResponse({
            "status": "started",
            "pid": proc.pid,
            "mock": mock,
        })
    except Exception as e:
        add_log_entry("error", f"Pipeline failed to start: {e}")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
