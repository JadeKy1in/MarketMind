"""White-box dashboard data (docs/S4_DESIGN.md): ledger, shadow arena, briefs, health.

Read-only. Every value comes from the ledger database or a file written by a
run; when something is missing the payload says so instead of filling in 0.
Paths resolve on each call so tests can point MARKETMIND_DATA_DIR elsewhere.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from marketmind.ledger.scoreboard import PROBATION_DAYS, benchmark_id_for, scoreboard
from marketmind.ledger.store import LedgerStore, default_ledger_path

logger = logging.getLogger("marketmind.api.whitebox")

BRIEF_DIR = Path(__file__).resolve().parent.parent / ".claude" / "briefs"
LEDGER_PAGE_MAX = 500


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def brief_dir() -> Path:
    return Path(os.getenv("MARKETMIND_BRIEF_DIR", str(BRIEF_DIR)))


def _store() -> LedgerStore | None:
    path = default_ledger_path()
    return LedgerStore(path) if path.exists() else None


def _latest_json(folder: Path) -> tuple[str | None, object | None]:
    """(date stem, parsed json) of the newest <YYYY-MM-DD>.json in folder."""
    if not folder.is_dir():
        return None, None
    files = sorted(p for p in folder.glob("????-??-??.json"))
    for p in reversed(files):
        try:
            return p.stem, json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("unreadable file %s", p)
    return None, None


# ── brief / reasoning chain ─────────────────────────────────────────────────

def get_brief(date: str | None = None) -> dict:
    folder = brief_dir()
    if date:
        p = folder / f"{date}.json"
        if not p.exists():
            return {"available": False, "reason": f"no brief for {date}"}
        return {"available": True, "date": date,
                "brief": json.loads(p.read_text(encoding="utf-8"))}
    day, brief = _latest_json(folder)
    if brief is None:
        return {"available": False, "reason": "no decision brief has been written yet"}
    return {"available": True, "date": day, "brief": brief,
            "dates": [p.stem for p in sorted(folder.glob("????-??-??.json"))]}


# ── ledger ──────────────────────────────────────────────────────────────────

def get_ledger(status: str | None = None, source_type: str | None = None,
               source_id: str | None = None, ticker: str | None = None,
               limit: int = 200, offset: int = 0) -> dict:
    store = _store()
    if store is None:
        return {"available": False, "reason": "ledger database not found", "entries": []}
    rows = store.list(status=status or None, source_type=source_type or None)
    if source_id:
        rows = [e for e in rows if e.source_id == source_id]
    if ticker:
        rows = [e for e in rows if e.ticker.upper() == ticker.upper()]
    rows.reverse()                                   # newest first
    limit = max(1, min(int(limit), LEDGER_PAGE_MAX))
    page = rows[offset: offset + limit]
    counts: dict[str, int] = {}
    for e in rows:
        counts[e.status] = counts.get(e.status, 0) + 1
    return {"available": True, "total": len(rows), "offset": offset, "limit": limit,
            "status_counts": counts, "entries": [asdict(e) for e in page]}


def get_entry(entry_id: str) -> dict:
    store = _store()
    e = store.get(entry_id) if store else None
    if e is None:
        return {"available": False, "reason": f"no ledger record {entry_id}"}
    snap = store.snapshot(e.snapshot_id) if e.snapshot_id else {}
    return {"available": True, "entry": asdict(e),
            "snapshot": snap.get(e.ticker.upper()) or snap.get(e.ticker)}


# ── shadow arena / promotion log ────────────────────────────────────────────

def _latest_run() -> tuple[str | None, list[dict]]:
    day, runs = _latest_json(data_dir() / "shadows" / "v3_runs")
    if not runs:
        return day, []
    # a date file holds a list of runs; later runs only cover shadows still missing
    merged: dict[str, dict] = {}
    for run in runs if isinstance(runs, list) else [runs]:
        for r in run.get("results", []):
            if r.get("status") != "skipped" or r.get("shadow_id") not in merged:
                merged[r.get("shadow_id")] = r
    return day, list(merged.values())


def get_arena() -> dict:
    from marketmind.shadows.v3 import roster as roster_mod
    store = _store()
    entries = store.list() if store else []
    scores = {(s.source_type, s.source_id): s for s in scoreboard(entries)}
    run_day, run_results = _latest_run()
    run_by_id = {r.get("shadow_id"): r for r in run_results}
    rows = []
    for r in roster_mod.ROSTER:
        s = scores.get(("shadow", r.shadow_id))
        b = scores.get(("benchmark", benchmark_id_for(r.shadow_id)))
        last = run_by_id.get(r.shadow_id)
        rows.append({
            "shadow_id": r.shadow_id, "name": r.name, "display_name": r.display_name,
            "group": r.group, "domain": r.domain, "roster_status": r.status,
            "notes": r.notes, "domain_benchmark": r.domain_benchmark,
            "score": s.to_dict() if s else None,
            "random_benchmark": b.to_dict() if b else None,
            "last_run": {"date": run_day, "status": last.get("status"),
                         "errors": last.get("errors", []),
                         "warnings": last.get("warnings", [])} if last else None,
        })
    others = [s.to_dict() for k, s in scores.items() if k[0] not in ("shadow", "benchmark")]
    return {"available": store is not None, "run_date": run_day, "shadows": rows,
            "other_sources": others}


def get_promotion_log() -> dict:
    """S7 not built yet: every shadow is on probation; show progress honestly."""
    arena = get_arena()
    rows = []
    for r in arena["shadows"]:
        s = r["score"] or {}
        if r["roster_status"] != "active":
            stage, note = "暂缓", r["notes"] or r["roster_status"]
        else:
            stage, note = "见习", "未评审（晋升评审在 S7 实现）"
        rows.append({"shadow_id": r["shadow_id"], "display_name": r["display_name"],
                     "stage": stage, "active_days": s.get("active_days", 0),
                     "probation_days": PROBATION_DAYS, "settled": s.get("settled", 0),
                     "first_date": s.get("first_date"), "note": note})
    return {"review_implemented": False, "rows": rows, "events": []}


# ── health ──────────────────────────────────────────────────────────────────

def read_token_usage(limit: int = 10) -> list[dict]:
    p = data_dir() / "token_usage.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def get_health() -> dict:
    store = _store()
    entries = store.list() if store else []
    counts: dict[str, int] = {}
    sources: dict[str, int] = {}
    last_settled = None
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
        if e.price_source:
            sources[e.price_source] = sources.get(e.price_source, 0) + 1
        if e.settled_at and (last_settled is None or e.settled_at > last_settled):
            last_settled = e.settled_at
    brief_day, _ = _latest_json(brief_dir())
    run_day, run_results = _latest_run()
    submitted = sum(1 for r in run_results if r.get("status") in ("submitted", "skipped"))
    return {
        "ledger": {"available": store is not None, "records": len(entries),
                   "status_counts": counts, "last_settled_at": last_settled,
                   "price_sources": sources},
        "latest_brief": brief_day,
        "shadow_run": {"date": run_day, "submitted": submitted, "total": len(run_results)},
        "token_usage": read_token_usage(),
    }


# ── evidence layer (S5) ─────────────────────────────────────────────────────

def get_evidence(date: str | None = None) -> dict:
    folder = data_dir() / "evidence"
    if date:
        p = folder / f"{date}.json"
        if not p.exists():
            return {"available": False, "reason": f"no evidence report for {date}"}
        day, report = date, json.loads(p.read_text(encoding="utf-8"))
    else:
        day, report = _latest_json(folder)
    if report is None:
        return {"available": False, "reason": "证据层尚未运行（每日运行或 --mode evidence 后生成）"}
    items = report.get("items", [])
    # divergences first, then support, then unverifiable
    order = {"contradict": 0, "support": 1, "unverifiable": 2}
    items = sorted(items, key=lambda i: order.get(i.get("verdict"), 3))
    return {"available": True, "date": day, "status": report.get("status"),
            "divergences": report.get("divergences", 0), "items": items,
            "dropped": report.get("dropped", []), "news_considered": report.get("news_considered")}


# ── owner holdings (S6) ─────────────────────────────────────────────────────

def get_holdings() -> dict:
    day, report = _latest_json(data_dir() / "holdings_reports")
    if report is None:
        from marketmind.holdings.store import load
        n = len(load())
        reason = ("未录入持仓：python -m marketmind.holdings add <代码> <数量> <成本>" if not n
                  else f"已录入 {n} 个持仓，尚未巡检：python -m marketmind.holdings inspect")
        return {"available": False, "reason": reason}
    items = report.get("items", [])
    return {"available": True, "date": day, "items": items,
            "note": "结论由代码规则给出（docs/S6_DESIGN.md），系统不下单；持仓只存在本机 data/holdings.json"}
