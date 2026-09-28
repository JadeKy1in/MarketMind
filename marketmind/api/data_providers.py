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


# ── Legacy shadow ecosystem (removed) ───────────────────────────────
# /api/portfolio, /api/shadows/*, /api/history/decisions served the old
# ShadowStateDB. The ecosystem was deleted on 2026-09-28; these providers keep
# the old /legacy page from crashing and say plainly that there is no data.

LEGACY_REMOVED_REASON = "legacy shadow ecosystem removed 2026-09-28; see / (white box)"


def _legacy_removed(**payload) -> dict:
    return {"available": False, "reason": LEGACY_REMOVED_REASON, **payload}


# ── Providers ───────────────────────────────────────────────────────

def get_portfolio() -> dict:
    return _legacy_removed(positions=[], total_value=0, cash_pct=100.0,
                           patrol_status="removed",
                           updated=datetime.now(timezone.utc).isoformat())


def get_cost() -> dict:
    """Today's LLM usage from <data_dir>/token_usage.jsonl, written by each run.

    The server process makes no pipeline calls, so its own TokenBudget says
    nothing about the day; the old version read field names that TokenBudget
    never had and always showed 0.
    """
    from marketmind.api.whitebox import read_token_usage
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [r for r in read_token_usage(limit=50) if r.get("date") == today]
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for r in rows:
        for k in total:
            total[k] += (r.get("total") or {}).get(k, 0)
    return {
        "date": today,
        "runs": len(rows),
        "calls": total["calls"],
        "tokens_used": total["total_tokens"],
        "prompt_tokens": total["prompt_tokens"],
        "completion_tokens": total["completion_tokens"],
        "token_budget": 2_000_000,
        "source": "token_usage.jsonl" if rows else "no run recorded today",
    }


def get_source_status() -> list[dict]:
    """Return source health from config/source_authority when available."""
    sources = []
    try:
        from marketmind.config.source_authority import SOURCES
        for s in SOURCES:
            sources.append({
                "name": s.name,
                "ok": s.status.name.lower() in ("working", "active", "untested", "degraded"),
                "tier": int(s.tier) if hasattr(s, 'tier') else 3,
            })
    except Exception:
        logger.warning("SOURCES source status lookup failed", exc_info=True)
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
    return _legacy_removed(
        tiers={"elite": 0, "excellent": 0, "normal": 0, "endangered": 0},
        total=0, evolutions_today=0, challenger_trials=0, graduates=0,
        diversity="n/a",
    )


def get_shadow_rankings() -> dict:
    return _legacy_removed(rankings=[])


def get_shadow_detail(shadow_id: str) -> dict:
    """No per-shadow detail any more; the route turns this into a 404 with the reason."""
    raise ValueError(f"Shadow '{shadow_id}' not found: {LEGACY_REMOVED_REASON}")


def get_decision_history(limit: int = 10) -> dict:
    return _legacy_removed(decisions=[])


# ── Evolution Tracking Providers ────────────────────────────────────

def get_shadow_evolution() -> dict:
    import json
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    rows = store._conn.execute(
        "SELECT entity_id, week_start, metrics_json FROM snapshots "
        "WHERE scope='shadow' ORDER BY week_start DESC LIMIT 500"
    ).fetchall()
    shadows: dict[str, list] = {}
    for row in rows:
        sid, ws, mj = row[0], row[1], json.loads(row[2])
        if sid not in shadows:
            shadows[sid] = []
        shadows[sid].append({"week_start": ws, "metrics": mj})
    return {"shadows": shadows}


def get_pipeline_evolution() -> dict:
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    history = store.get_history("pipeline", "main_pipeline", limit=12)
    baseline = store.get_baseline("pipeline", "main_pipeline")
    return {"history": history, "baseline": baseline}


def get_main_pipeline_decision() -> dict:
    """Read today's main pipeline conclusion + full reasoning brief."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    calib_path = Path(__file__).resolve().parent.parent / ".claude" / "calibration" / f"{today}.json"
    brief_path = Path(__file__).resolve().parent.parent / ".claude" / "briefs" / f"{today}.json"

    if not calib_path.exists():
        return {"found": False, "message": "No pipeline run today yet"}

    try:
        with open(calib_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"found": False, "message": "Failed to read calibration data"}

    # Load reasoning brief
    brief = None
    if brief_path.exists():
        try:
            with open(brief_path, "r", encoding="utf-8") as f:
                brief = json.load(f)
        except Exception:
            pass

    # Also read latest pipeline metrics for stage-level detail
    metrics_path = Path(__file__).resolve().parent.parent / ".claude" / "metrics" / "pipeline_metrics.jsonl"
    latest_metrics = {}
    if metrics_path.exists():
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    m = json.loads(line)
                    if m.get("date") == today:
                        latest_metrics = m
        except Exception:
            pass

    decisions = data.get("decisions", [])
    has_no_trade = len(decisions) == 0

    return {
        "found": True,
        "date": data.get("date", today),
        "l1_grade": data.get("l1_grade", "?"),
        "l1_quadrant": data.get("l1_quadrant", "?"),
        "l1_direction": data.get("l1_direction", "?"),
        "ticker_candidates": data.get("ticker_candidates", []),
        "decisions": decisions,
        "has_no_trade": has_no_trade,
        "decision_count": len(decisions),
        # Stage-level metrics
        "flash_scored": latest_metrics.get("flash_total_scored", 0),
        "flash_high_impact": latest_metrics.get("flash_high_impact", 0),
        "l3_green": latest_metrics.get("l3_green_lights", 0),
        "l3_yellow": latest_metrics.get("l3_yellow_lights", 0),
        "l3_red": latest_metrics.get("l3_red_lights", 0),
        "red_team_challenges": latest_metrics.get("red_team_challenges", 0),
        "resonance_passed": latest_metrics.get("resonance_passed", False),
        "resonance_verdict": latest_metrics.get("resonance_verdict", ""),
        # Flash source-level detail
        "flash_high_impact_count": data.get("flash_high_impact_count", 0),
        "flash_avg_impact": data.get("flash_avg_impact", 0.0),
        # Full reasoning chain
        "brief": brief,
    }


def get_playground_data() -> dict:
    """Return Playground agent data: manifests, performance, audit status."""
    import json
    from pathlib import Path

    pg_dir = Path(__file__).resolve().parent.parent / "playground"
    agents_dir = pg_dir / "agents"
    data_dir = pg_dir / "data"

    agents: list[dict] = []
    if not agents_dir.exists():
        return {"agents": [], "total": 0, "status_counts": {}}

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        mf = agent_dir / "manifest.json"
        if not mf.exists():
            continue
        try:
            with open(mf, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue

        aid = manifest.get("agent_id", agent_dir.name)
        entry = {
            "agent_id": aid,
            "display_name": manifest.get("display_name", aid),
            "description": manifest.get("description", ""),
            "output_character": manifest.get("output_character", ""),
            "tags": manifest.get("tags", []),
            "version": manifest.get("version", "1.0.0"),
            "target_pipeline_node": manifest.get("target_pipeline_node", ""),
            "data_sources": manifest.get("public_data_sources", []),
            "status": "observing",
            "days_observing": 0,
            "total_decisions": 0,
            "settled_calls": 0,
            "correct_calls": 0,
            "direction_accuracy": None,
            "sharpe_ratio": None,
            "cumulative_pnl_bps": 0,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown_bps": None,
            "last_audit": None,
            "performance_history": [],
        }

        # Performance
        perf_path = data_dir / "playground_performance.jsonl"
        if perf_path.exists():
            try:
                ph: list[dict] = []
                with open(perf_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        p = json.loads(line)
                        if p.get("agent_id") == aid:
                            ph.append(p)
                if ph:
                    lp = ph[-1]
                    entry.update({
                        "direction_accuracy": lp.get("direction_accuracy"),
                        "sharpe_ratio": lp.get("sharpe_ratio"),
                        "cumulative_pnl_bps": lp.get("cumulative_pnl_bps", 0),
                        "total_decisions": lp.get("total_calls", 0),
                        "days_observing": lp.get("observation_days", 0),
                        "settled_calls": lp.get("settled_calls", 0),
                        "correct_calls": lp.get("correct_calls", 0),
                        "max_drawdown_bps": lp.get("max_drawdown_bps"),
                        "win_rate": lp.get("win_rate"),
                        "profit_factor": lp.get("profit_factor"),
                        "performance_history": [
                            {"date": p.get("computed_at", "")[:10],
                             "accuracy": p.get("direction_accuracy"),
                             "sharpe": p.get("sharpe_ratio"),
                             "pnl": p.get("cumulative_pnl_bps"),
                             "calls": p.get("total_calls", 0)}
                            for p in ph[-12:]
                        ],
                    })
            except Exception:
                pass

        # Audit
        audit_path = data_dir / "playground_audits.jsonl"
        if audit_path.exists():
            try:
                with open(audit_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        ad = json.loads(line)
                        if ad.get("agent_id") == aid:
                            entry["last_audit"] = ad
            except Exception:
                pass

        # Status from audit
        la = entry.get("last_audit")
        if la:
            rec = la.get("recommendation", "")
            if rec == "CANDIDATE_FOR_UPGRADE":
                entry["status"] = "candidate"
            elif rec == "MARK_STAGNANT":
                entry["status"] = "stagnant"
            elif entry["days_observing"] >= 60:
                entry["status"] = "evaluating"
        elif entry["days_observing"] >= 60:
            entry["status"] = "evaluating"

        agents.append(entry)

    # Sort: candidate > evaluating > observing > stagnant
    order = {"candidate": 0, "evaluating": 1, "observing": 2, "stagnant": 3}
    agents.sort(key=lambda a: order.get(a["status"], 5))

    counts: dict[str, int] = {}
    for a in agents:
        s = a["status"]
        counts[s] = counts.get(s, 0) + 1

    return {"agents": agents, "total": len(agents), "status_counts": counts}


def get_stagnation_report() -> dict:
    import json
    from marketmind.evolution.stagnation_detector import (
        compute_cusum, compute_psi, linear_trend_pvalue,
        composite_stagnation_score, stagnation_grade,
    )
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    results = {}
    rows = store._conn.execute(
        "SELECT entity_id, metrics_json FROM snapshots WHERE scope='shadow'"
    ).fetchall()
    # Group by shadow
    shadow_data: dict[str, list[dict]] = {}
    for row in rows:
        sid, mj = row[0], json.loads(row[1])
        if sid not in shadow_data:
            shadow_data[sid] = []
        shadow_data[sid].append(mj)
    for sid, metrics_list in shadow_data.items():
        sharpes = [m.get("sharpe", 0) for m in metrics_list if "sharpe" in m]
        if len(sharpes) >= 4:
            cusum = compute_cusum(sharpes)
            psi = compute_psi(sharpes[:len(sharpes)//2], sharpes[len(sharpes)//2:])
            pval = linear_trend_pvalue(sharpes)
            score = composite_stagnation_score(cusum, psi, pval)
            results[sid] = {
                "stagnation_score": round(score, 3),
                "grade": stagnation_grade(score),
                "cusum": round(cusum, 3),
                "psi": round(psi, 3),
                "trend_pvalue": round(pval, 3),
            }
    return {"stagnation": results}
