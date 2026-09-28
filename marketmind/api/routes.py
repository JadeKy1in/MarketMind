"""FastAPI route definitions — thin handlers, all logic in data_providers."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path

logger = logging.getLogger("marketmind.api.routes")

from marketmind.api.chat_handler import chat_response, get_chat_manager
from marketmind.api.data_providers import (
    add_log_entry,
    get_cost,
    get_decision_history,
    get_health,
    get_log_entries,
    get_main_pipeline_decision,
    get_playground_data,
    get_portfolio,
    get_shadow_detail,
    get_shadow_overview,
    get_shadow_rankings,
)
from marketmind.api.websocket import broadcast_alert, broadcast_stage, ws_endpoint
from marketmind.notification.alert_manager import get_alert_manager

app = FastAPI(title="MarketMind", version="2.0")
app.websocket("/ws")(ws_endpoint)

_alm = get_alert_manager()
_alm.set_broadcast_fn(broadcast_alert)

WHITEBOX_PATH = Path(__file__).parent.parent / "whitebox.html"
DASHBOARD_PATH = Path(__file__).parent.parent / "dashboard.html"   # legacy page, at /legacy
EVOLUTION_PATH = Path(__file__).parent.parent / "evolution.html"
PLAYGROUND_PATH = Path(__file__).parent.parent / "playground.html"


_CACHE_PREVENT_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Vary": "*",
}


def _html(path: Path) -> HTMLResponse:
    headers = dict(_CACHE_PREVENT_HEADERS)
    headers["ETag"] = f'"{int(path.stat().st_mtime)}"'
    return HTMLResponse(content=path.read_text(encoding="utf-8"), headers=headers)


@app.get("/", response_class=HTMLResponse)
async def whitebox_page():
    return _html(WHITEBOX_PATH)


@app.get("/legacy", response_class=HTMLResponse)
async def dashboard():
    return _html(DASHBOARD_PATH)


# ── White box v1 (docs/S4_DESIGN.md) ────────────────────────────────────────

def _wb(fn, *args, **kwargs) -> JSONResponse:
    try:
        return JSONResponse(fn(*args, **kwargs))
    except Exception:
        logger.warning("white-box provider %s failed", fn.__name__, exc_info=True)
        return JSONResponse({"available": False, "reason": "provider error (see server log)"},
                            status_code=500)


@app.get("/api/wb/brief")
async def wb_brief(date: str = ""):
    from marketmind.api import whitebox
    return _wb(whitebox.get_brief, date or None)


@app.get("/api/wb/ledger")
async def wb_ledger(status: str = "", source_type: str = "", source_id: str = "",
                    ticker: str = "", limit: int = 200, offset: int = 0):
    from marketmind.api import whitebox
    return _wb(whitebox.get_ledger, status or None, source_type or None, source_id or None,
               ticker or None, limit, max(0, offset))


@app.get("/api/wb/ledger/{entry_id}")
async def wb_entry(entry_id: str):
    from marketmind.api import whitebox
    return _wb(whitebox.get_entry, entry_id)


@app.get("/api/wb/arena")
async def wb_arena():
    from marketmind.api import whitebox
    return _wb(whitebox.get_arena)


@app.get("/api/wb/promotion")
async def wb_promotion():
    from marketmind.api import whitebox
    return _wb(whitebox.get_promotion_log)


@app.get("/api/wb/health")
async def wb_health():
    from marketmind.api import whitebox
    return _wb(whitebox.get_health)


@app.get("/api/wb/evidence")
async def wb_evidence(date: str = ""):
    from marketmind.api import whitebox
    return _wb(whitebox.get_evidence, date or None)


@app.get("/api/wb/holdings")
async def wb_holdings():
    from marketmind.api import whitebox
    return _wb(whitebox.get_holdings)


@app.get("/api/wb/big_alerts")
async def wb_big_alerts():
    from marketmind.api import whitebox
    return _wb(whitebox.get_big_alerts)


@app.get("/api/wb/temp_shadows")
async def wb_temp_shadows():
    from marketmind.api import whitebox
    return _wb(whitebox.get_temp_shadows)


@app.post("/api/reporter")
async def reporter_endpoint(request: dict):
    from marketmind.api import reporter
    try:
        result = await reporter.ask(str(request.get("question", "")), request.get("history"))
    except Exception:
        logger.warning("reporter failed", exc_info=True)
        return JSONResponse({"error": "reporter failed"}, status_code=500)
    return JSONResponse(result, status_code=400 if result.get("error") == "question is required"
                        else 200)


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


@app.post("/api/chat")
async def chat_endpoint(request: dict):
    """Chat with the MarketMind AI analyst. Returns AI response with session tracking."""
    try:
        message = request.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)
        session_id = request.get("session_id", "default")
        lang = request.get("lang", "")
        result = await chat_response(session_id=session_id, message=message, lang=lang)
        return JSONResponse(result)
    except Exception:
        logger.warning("chat endpoint failed", exc_info=True)
        return JSONResponse({"error": "Chat service unavailable"}, status_code=500)


@app.get("/api/chat/history")
async def chat_history(session_id: str = "default"):
    """Get chat history for a session."""
    try:
        manager = get_chat_manager()
        history = manager.get_history(session_id)
        return JSONResponse({"session_id": session_id, "messages": history})
    except Exception:
        return JSONResponse({"session_id": session_id, "messages": []})


@app.delete("/api/chat/history")
async def clear_chat_history(session_id: str = "default"):
    """Clear chat history for a session."""
    try:
        manager = get_chat_manager()
        manager.clear(session_id)
        return JSONResponse({"status": "ok"})
    except Exception:
        return JSONResponse({"status": "error"}, status_code=500)


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


@app.get("/playground", response_class=HTMLResponse)
async def playground_page():
    content = PLAYGROUND_PATH.read_text(encoding="utf-8")
    headers = dict(_CACHE_PREVENT_HEADERS)
    headers["ETag"] = f'"{int(PLAYGROUND_PATH.stat().st_mtime)}"'
    return HTMLResponse(content=content, headers=headers)


@app.get("/api/pipeline/decision")
async def pipeline_decision():
    try:
        return JSONResponse(get_main_pipeline_decision())
    except Exception:
        return JSONResponse({"found": False, "message": "Error reading pipeline decision"})


@app.get("/api/playground")
async def playground_api():
    try:
        return JSONResponse(get_playground_data())
    except Exception:
        logger.warning("playground endpoint failed", exc_info=True)
        return JSONResponse({"agents": [], "total": 0, "status_counts": {}})


@app.post("/api/pipeline/progress")
async def pipeline_progress(request: dict):
    """Receive progress updates from pipeline subprocess and broadcast via WS."""
    await broadcast_stage(
        stage=request.get("stage", ""),
        pct=request.get("pct", 0),
        status=request.get("status", "running"),
        stage_num=request.get("stage_num", 0),
    )
    return JSONResponse({"ok": True})


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

    mock = request.get("mock", False) if request else False
    lang = request.get("lang", "zh") if request else "zh"
    project_dir = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "app.py", "--mode", "daily", "--lang", lang]
    if mock:
        cmd.append("--mock")
    cmd.append("-v")

    add_log_entry("info", f"Pipeline started: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(project_dir),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
