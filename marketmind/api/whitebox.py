"""White-box dashboard data (docs/S4_DESIGN.md): ledger, shadow arena, briefs, health.

Read-only. Every value comes from the ledger database or a file written by a
run; when something is missing the payload says so instead of filling in 0.
Paths resolve on each call so tests can point MARKETMIND_DATA_DIR elsewhere.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from marketmind.runtime_paths import claude_dir

from marketmind.ledger.scoreboard import PROBATION_DAYS, benchmark_id_for, score, scoreboard
from marketmind.ledger.store import LedgerStore, default_ledger_path

logger = logging.getLogger("marketmind.api.whitebox")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BRIEF_DIR = None                     # resolved at call time (claude_dir / MARKETMIND_BRIEF_DIR)
LEDGER_PAGE_MAX = 500


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def brief_dir() -> Path:
    return Path(os.getenv("MARKETMIND_BRIEF_DIR") or (claude_dir() / "briefs"))


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
        if not _DATE_RE.match(date):
            return {"available": False, "reason": "date must be YYYY-MM-DD"}
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
    retired = roster_mod.retired_ids(data_dir())
    rows = []
    # the fixed roster plus approved successors; retired shadows stay listed (history)
    for r in roster_mod.all_entries(data_dir()):
        s = scores.get(("shadow", r.shadow_id))
        b = scores.get(("benchmark", benchmark_id_for(r.shadow_id)))
        last = run_by_id.get(r.shadow_id)
        rows.append({
            "shadow_id": r.shadow_id, "name": r.name, "display_name": r.display_name,
            "group": r.group, "domain": r.domain,
            "roster_status": "retired" if r.shadow_id in retired else r.status,
            "successor_of": r.successor_of or None,
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


STAGE_CN = {"probation": "见习", "formal": "正式", "advisor": "顾问", "paused": "暂停",
            "blocked": "暂缓", "retired": "退役"}


def get_retirements(names: dict[str, str] | None = None) -> dict:
    """Pending retirement proposals (reason, proposed successor and donor) and retired
    shadows, from promotion/retirement.summary() (data/promotion/retirements.json; the
    ids also appear in state.json `retirements`). docs/S7_DESIGN.md §一 退役."""
    from marketmind.promotion import retirement
    names = names or {}
    summ = retirement.summary(data_dir())
    pending = []
    for p in summ.get("pending", []):
        reason, succ = p.get("reason") or {}, p.get("successor") or {}
        donor = succ.get("donor_id")
        pending.append({
            "shadow_id": p.get("shadow_id"),
            "display_name": names.get(p.get("shadow_id"), p.get("shadow_id")),
            "proposed_at": p.get("proposed_at"),
            "stage": STAGE_CN.get(p.get("stage"), p.get("stage")),
            "rule": reason.get("rule"), "challengers": reason.get("challengers") or [],
            "excess_domain_mean": reason.get("excess_domain_mean"),
            "excess_n": reason.get("excess_n"), "window": reason.get("window"),
            "domain_benchmark": reason.get("domain_benchmark"),
            "successor_id": succ.get("shadow_id"), "donor_id": donor,
            "donor_name": names.get(donor, donor) if donor else None,
            "donor_match": succ.get("donor_match"), "method": succ.get("method"),
            "command": f"python -m marketmind.promotion retire approve {p.get('shadow_id')}"})
    retired = [{**r, "display_name": names.get(r.get("shadow_id"), r.get("shadow_id"))}
               for r in summ.get("retired", [])]
    return {"pending": pending, "retired": retired, "error": summ.get("error")}


def get_promotion_log() -> dict:
    """Promotion ladder state written by marketmind/promotion (docs/S7_DESIGN.md)."""
    from marketmind.promotion import config as pconf
    root = data_dir() / "promotion"
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    events = []
    ev_path = root / "events.jsonl"
    if ev_path.exists():
        for line in ev_path.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    events.reverse()
    arena = get_arena()
    names = {r["shadow_id"]: r["display_name"] for r in arena["shadows"]}
    retirements = get_retirements(names)
    successor_by_id = {r["shadow_id"]: r.get("successor") for r in retirements["retired"]}
    recs = (state or {}).get("shadows", {})
    rows = []
    for r in arena["shadows"]:
        rec = recs.get(r["shadow_id"], {})
        m = rec.get("metrics") or {}
        s = r["score"] or {}
        if r["roster_status"] == "retired":
            stage = "retired"
        else:
            stage = rec.get("stage") or ("probation" if r["roster_status"] == "active"
                                         else "blocked")
        if stage == "retired":
            succ = successor_by_id.get(r["shadow_id"])
            note = f"已退役，接任者 {names.get(succ, succ)}" if succ else "已退役"
        elif r.get("successor_of"):
            note = f"接任 {names.get(r['successor_of'], r['successor_of'])}"
        else:
            note = r["notes"] if stage == "blocked" else ""
        rows.append({"shadow_id": r["shadow_id"], "display_name": r["display_name"],
                     "stage": STAGE_CN.get(stage, stage), "stage_code": stage,
                     "active_days": m.get("record_days", s.get("active_days", 0)),
                     "probation_days": PROBATION_DAYS, "settled": s.get("settled", 0),
                     "n_eff": m.get("n_eff"), "min_trl": m.get("min_trl"),
                     "score": rec.get("score"), "tier": rec.get("tier"),
                     "first_date": s.get("first_date"), "note": note})
    for sid, rec in recs.items():                      # Playground candidates (S8)
        if not sid.startswith("playground:"):
            continue
        m = rec.get("metrics") or {}
        rows.append({"shadow_id": sid, "display_name": sid, "stage": STAGE_CN.get(rec.get("stage"), rec.get("stage")),
                     "stage_code": rec.get("stage"), "active_days": m.get("record_days", 0),
                     "probation_days": PROBATION_DAYS, "settled": m.get("settled", 0),
                     "n_eff": m.get("n_eff"), "min_trl": m.get("min_trl"),
                     "score": rec.get("score"), "tier": rec.get("tier"), "first_date": None,
                     "note": "Playground 候选"})
    return {"review_implemented": True, "reviewed_on": (state or {}).get("updated_at"),
            "pbo": (state or {}).get("pbo"), "rows": rows, "events": events[:100],
            "retirements": retirements,
            "thresholds": pconf.thresholds()}


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
        "alerts": get_alerts(limit=15)["alerts"],
        "scheduler": read_scheduler(),
    }


def read_scheduler(limit: int = 10, skip_limit: int = 3) -> list[dict]:
    """Recent automatic runs (marketmind/scripts/scheduled_run.py), newest first.

    A finished-with-failures run has status "degraded" and lists the failed steps
    in ``degraded_steps``; ``skips`` holds the last ``skip_limit`` skipped triggers
    ({"t", "reason"}) of that day, oldest first. A day with only skipped triggers
    has status None and sorts by its latest skip."""
    p = data_dir() / "scheduler" / "state.json"
    try:
        runs = json.loads(p.read_text(encoding="utf-8")).get("runs", {})
    except (OSError, ValueError, AttributeError):
        return []
    if not isinstance(runs, dict):
        return []
    rows = []
    for k, v in runs.items():
        if not isinstance(v, dict):
            continue
        row = {"key": k, **{f: v.get(f) for f in ("mode", "status", "started", "ended",
                                                    "attempts", "reason")}}
        steps = v.get("degraded_steps")
        row["degraded_steps"] = ([str(x) for x in steps if x] if isinstance(steps, list)
                                 else [])
        skips = v.get("skips") if isinstance(v.get("skips"), list) else []
        row["skips"] = [{"t": str(x.get("t") or ""), "reason": str(x.get("reason") or "")}
                        for x in skips if isinstance(x, dict)][-skip_limit:] if skip_limit > 0 else []
        rows.append(row)

    def when(r: dict) -> str:
        return r["started"] or (r["skips"][-1]["t"] if r["skips"] else "") or ""
    return sorted(rows, key=when, reverse=True)[:limit]


# ── evidence layer (S5) ─────────────────────────────────────────────────────

def get_evidence(date: str | None = None) -> dict:
    folder = data_dir() / "evidence"
    if date:
        if not _DATE_RE.match(date):
            return {"available": False, "reason": "date must be YYYY-MM-DD"}
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


# ── cold-data discovery and watchlist (S10) ─────────────────────────────────

def origin_label(meta: dict | None) -> str:
    o = (meta or {}).get("origin") or {}
    kind = o.get("kind")
    if not kind:
        return "unrecorded"
    series = ",".join(o.get("series") or [])
    return f"{kind}:{series}" if series else kind


def get_discovery(date: str | None = None) -> dict:
    """Latest discovery report, the watchlist, and ledger results by data origin."""
    from dataclasses import replace
    folder = data_dir() / "discovery"
    if date:
        if not _DATE_RE.match(date):
            return {"available": False, "reason": "date must be YYYY-MM-DD"}
        p = folder / f"{date}.json"
        day, report = (date, json.loads(p.read_text(encoding="utf-8"))) if p.exists() else (date, None)
    else:
        day, report = _latest_json(folder)
    watch = []
    if (data_dir() / "watchlist.db").exists():
        from marketmind.watchlist import dashboard_items
        from marketmind.watchlist.store import WatchlistStore
        watch = dashboard_items(WatchlistStore(data_dir() / "watchlist.db"))
    store = _store()
    rows = [replace(e, source_type="origin", source_id=origin_label(e.meta))
            for e in (store.list() if store else [])
            if (e.meta or {}).get("origin")]
    by_origin = [s.to_dict() for s in scoreboard(rows)]
    return {"available": report is not None or bool(watch), "date": day,
            "counts": (report or {}).get("counts"), "anomalies": (report or {}).get("anomalies", []),
            "unavailable": (report or {}).get("unavailable", []), "watchlist": watch,
            "by_origin": by_origin,
            "reason": None if report is not None else "冷门数据扫描尚未运行（每日运行后生成）"}


# ── trend state machine (docs/TREND_DESIGN.md §9) ───────────────────────────

_TREND_ORDER = {"TREND": 0, "EXIT": 1, "WATCH": 2, "CASH": 3, "UNAVAILABLE": 4}


def get_trend(date: str | None = None) -> dict:
    """Latest (or given) data/trend/<date>.json. A weekend file holds crypto only; the
    other instruments are carried from their most recent earlier file and flagged."""
    from marketmind.trend.daily import load, previous_states, trend_dir
    if date and not _DATE_RE.match(date):
        return {"available": False, "reason": "date must be YYYY-MM-DD"}
    day, doc = load(data_dir(), date)
    if doc is None:
        return {"available": False, "date": day,
                "reason": "趋势状态尚未运行（每日运行后生成 data/trend/）"}
    full = dict(doc.get("full") or {})
    carried = set()
    for t, s in previous_states(trend_dir(data_dir()), day, "full").items():
        if t not in full:
            full[t] = s
            carried.add(t)
    lean = doc.get("lean") or {}
    groups = lean.get("groups") or {}
    rows = []
    for t, s in full.items():
        r12, h = s.get("ret_12m"), s.get("hurdle")
        rows.append({k: s.get(k) for k in ("state", "event", "as_of", "close", "ret_12m", "hurdle",
                                          "sma200", "high_55", "stop_level", "entry_signal_date",
                                          "reason")}
                    | {"ticker": t, "excess_12m": None if r12 is None or h is None else r12 - h,
                       "lean_group": groups.get(t), "carried": t in carried})
    rows.sort(key=lambda r: (_TREND_ORDER.get(r["state"], 9), r["ticker"]))
    counts = {k: sum(r["state"] == k for r in rows) for k in _TREND_ORDER}
    return {"available": True, "date": day, "mode": doc.get("mode"),
            "written_at": doc.get("written_at"), "hurdle": doc.get("hurdle"),
            "hurdle_source": doc.get("hurdle_source"), "counts": counts,
            "changes": doc.get("changes"), "lean": lean, "rows": rows}


# ── owner holdings (S6) ─────────────────────────────────────────────────────

def get_holdings() -> dict:
    from dataclasses import asdict as _asdict
    from marketmind.holdings.store import load
    holdings = [_asdict(h) for h in load()]
    current = {h["ticker"] for h in holdings}
    day, report = _latest_json(data_dir() / "holdings_reports")
    items = [i for i in (report or {}).get("items", []) if i.get("ticker") in current]
    return {"available": True, "holdings": holdings,
            "report": {"date": day, "items": items} if report else None,
            "alerts": get_alerts(source="holdings", limit=20)["alerts"],
            "note": "结论由代码规则给出（docs/S6_DESIGN.md），系统不下单；持仓只存在本机 data/holdings.json"}


# ── alerts (persisted by notification/alert_log in the process that raised them) ──

def get_alerts(source: str | None = None, limit: int = 50) -> dict:
    path = data_dir() / "alerts.db"
    if not path.exists():
        return {"available": False, "alerts": []}
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        sql, args = "SELECT * FROM alerts", []
        if source:
            sql += " WHERE source = ?"
            args.append(source)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args.append(int(limit))
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
    except sqlite3.Error:
        logger.warning("alerts.db unreadable", exc_info=True)
        return {"available": False, "alerts": []}
    return {"available": True, "alerts": rows}


# ── big-move alerts (S8) ────────────────────────────────────────────────────

_ALERT_STATUS_CN = {"supported": "顾问支持", "vetoed": "顾问反对（否决标记）",
                    "weak": "支持不足", "no_votes": "无顾问意见"}


def _alert_row(r: dict) -> dict:
    """One report row (alerts/runner.py::_row) as trunk / annotation / evidence."""
    t = r.get("trend") or {}
    kind = r.get("kind")
    state = t.get("state")
    move = {"entry": f"→{state or 'TREND'}", "exit": f"TREND→{state or '?'}"}.get(
        kind, f"{state or '?'}（只差 55 日突破）" if kind == "watch" else (state or "?"))
    status = r.get("status") or "no_votes"
    vf, va = r.get("votes_for") or [], r.get("votes_against") or []
    ev_for, ev_against = r.get("evidence") or [], r.get("evidence_against") or []
    claim = lambda e: {"entry_id": e.get("entry_id"), "ticker": e.get("ticker"),
                       "claim": e.get("claim", ""), "type": e.get("type")}
    return {
        "ticker": r.get("ticker"), "kind": kind, "direction": r.get("direction"),
        "asset_group": r.get("asset_group"), "key": r.get("key"),
        "trunk": {"move": move, "state": state, "as_of": t.get("as_of"),
                  "close": t.get("close"), "stop_level": t.get("stop_level"),
                  "entry_signal_date": t.get("entry_signal_date")},
        "annotation": {"status": status,
                       "status_cn": r.get("status_cn") or _ALERT_STATUS_CN.get(status, status),
                       "veto": bool(r.get("veto", status == "vetoed")),
                       "votes_for": len(vf), "votes_against": len(va),
                       "groups_for": sorted({v.get("group") for v in vf if v.get("group")}),
                       "groups_against": sorted({v.get("group") for v in va if v.get("group")})},
        "evidence": {"for": [claim(e) for e in ev_for], "against": [claim(e) for e in ev_against]},
        "entry_id": r.get("entry_id"), "note": r.get("note", ""),
        "notified": len(r.get("notified") or []),
    }


def alert_report_view(report: dict | None) -> dict | None:
    """The alert report JSON (alerts/runner.py::run_alerts) reshaped for the dashboard:
    trend trunk per alert, advisor annotation, evidence notes, near misses (WATCH), mode."""
    if not report:
        return None
    src = report.get("trend_source") or {}
    return {
        "date": report.get("date"), "written_at": report.get("written_at"),
        "mode": report.get("mode") or "observe", "live_switch": bool(report.get("live_switch")),
        "crypto_only": bool(report.get("crypto_only")),
        "trend_source": {"name": src.get("source"), "universe": src.get("universe"),
                         "available": src.get("available"), "reason": src.get("reason"),
                         "date": src.get("date")},
        "voter_basis": report.get("voter_basis"), "voters": report.get("advisors"),
        "alerts": [_alert_row(r) for r in report.get("fired") or []],
        "near_misses": [_alert_row(r) for r in report.get("near_misses") or []],
        "duplicates": [_alert_row(r) for r in report.get("duplicates") or []],
        "skipped": list(report.get("skipped") or []),
        "pushed": len(report.get("pushed") or []),
    }


def get_big_alerts() -> dict:
    from marketmind.alerts.runner import load_responses
    day, report = _latest_json(data_dir() / "alerts")
    store = _store()
    responses = load_responses()
    history = []
    for e in (store.list(source_type="alert") if store else []):
        r = responses.get(e.entry_id, {})
        history.append({"entry_id": e.entry_id, "created_at": e.created_at, "mode": e.source_id,
                        "ticker": e.ticker, "status": e.status, "net_return": e.net_return,
                        "response": r.get("decision"), "note": r.get("note", "")})
    history.reverse()
    if report is None and not history:
        return {"available": False,
                "reason": "警报尚未运行（每日运行最后一步，或 python -m marketmind.alerts run）"}
    return {"available": True, "date": day, "report": report,
            "view": alert_report_view(report if isinstance(report, dict) else None),
            "history": history}


# ── temporary shadows (S7) ──────────────────────────────────────────────────

def get_temp_shadows() -> dict:
    from marketmind.shadows.v3 import temp_event, trials
    store = _store()
    rows = store.list(source_type="temp_shadow") if store else []
    scores = {s.source_id: s.to_dict() for s in scoreboard(rows)}
    events = []
    by_type: dict[str, list] = {}
    for e in temp_event.load():
        sid = f"temp_event:{e.event_id}"
        sc = scores.get(sid)
        events.append({**e.__dict__, "shadow_id": sid, "score": sc})
        by_type.setdefault(e.type, []).extend(r for r in rows if r.source_id == sid)
    type_scores = {}
    for t, rs in by_type.items():
        d = score(rs).to_dict() if rs else {"records": 0}
        d["name"] = temp_event.TYPES[t][0]
        type_scores[t] = d
    trial_rows = [{**t.__dict__, "score": scores.get(f"trial:{t.trial_id}")} for t in trials.load()]
    return {"events": sorted(events, key=lambda e: (e["status"] != "active", e["spawned"]), reverse=False),
            "event_types": type_scores, "trials": trial_rows,
            "missed_path": scores.get("missed_path:main"),
            "limits": {"events": temp_event.MAX_ACTIVE, "trials": trials.MAX_RUNNING}}


# ── daily report (owner request 2026-09-28) ────────────────────────────────

def get_daily_report() -> dict:
    from marketmind.reports.daily import latest
    r = latest()
    if not r:
        return {"available": False, "reason": "还没有今日汇报（每个工作日自动运行后生成）"}
    return {"available": True, "date": r.get("date"), "source": r.get("source"),
            "markdown": r.get("markdown", ""), "written_at": r.get("written_at")}


# ── shadow-ecosystem health (docs/ECOSYSTEM_DESIGN.md) ─────────────────────

def _tail(rows: list | None, n: int = 12) -> list:
    return list(rows or [])[-n:]


def _diversity_view(d: dict | None) -> dict:
    d = d or {}
    clusters = d.get("clusters") or []
    return {**{k: d.get(k) for k in ("eligible", "actors", "n_eff", "mean_abs_rho", "note")},
            "pairs_high": d.get("pairs_high") or [], "clusters": clusters,
            "unexpected_clusters": [c for c in clusters if not c.get("expected")]}


def get_ecosystem(date: str | None = None) -> dict:
    """The latest (or given) data/ecosystem/<date>.json reshaped for the dashboard:
    herding flags with their market-driven / behavioural verdict, N_eff and duplicate
    clusters, source / model homogenisation, stagnation, zombies / orphans, degradation
    trends and the one-line summary. Measures without enough data keep None + `note`."""
    from marketmind.ecosystem import read_report
    if date and not _DATE_RE.match(date):
        return {"available": False, "reason": "date must be YYYY-MM-DD"}
    doc = read_report(date, root=data_dir())
    if not doc:
        return {"available": False, "date": date,
                "reason": "生态健康尚未运行（每日运行或 python -m marketmind.ecosystem 后生成 data/ecosystem/）"}
    herd = doc.get("herding") or {}
    div = doc.get("diversity") or {}
    hom = doc.get("homogenisation") or {}
    stag = doc.get("stagnation") or {}
    integ = doc.get("integrity") or {}
    deg = doc.get("degradation") or {}
    ent = [r for r in deg.get("entropy") or [] if r.get("records")]
    return {
        "available": True, "date": doc.get("date"), "written_at": doc.get("written_at"),
        "summary": doc.get("summary"), "population": doc.get("population") or {},
        "herding": {"flags": herd.get("flags") or [], "today": herd.get("today") or [],
                    "episodes": len(herd.get("episodes") or []),
                    "long_share": _tail(herd.get("ecosystem_long_share"))},
        "diversity": {"pnl": _diversity_view(div.get("pnl")),
                      "direction": _diversity_view(div.get("direction"))},
        "homogenisation": {k: hom.get(k) for k in ("window_days", "dominant_group", "dominant_ticker",
                                                   "llm", "mean_ticker_jaccard", "news_source")},
        "stagnation": {"flags": stag.get("flags") or [],
                       "insufficient": len(stag.get("insufficient") or {}), "note": stag.get("note")},
        "integrity": {"zombies": integ.get("zombies") or [], "orphans": integ.get("orphans") or [],
                      "retired_submitting": integ.get("retired_submitting") or [],
                      "active": integ.get("active"), "run_days_checked": integ.get("run_days_checked")},
        "degradation": {"direction_entropy_trend": deg.get("direction_entropy_trend"),
                        "spread_trend": deg.get("spread_trend"),
                        "beat_random_trend": deg.get("beat_random_trend"),
                        "entropy_latest": ent[-1] if ent else None,
                        "beat_random": _tail(deg.get("beat_random")), "note": deg.get("note")},
        "notes": doc.get("notes") or [], "thresholds": doc.get("thresholds") or {},
    }


# ── promotion diagnostics: factor regression + paper-to-live (S7 §三 / §四) ──

def _factor_view(f: dict | None) -> dict:
    f = f or {}
    if f.get("status") != "ok":
        return {"status": f.get("status") or "missing", "reason": f.get("reason"),
                "obs": f.get("obs"), "window": f.get("window")}
    betas = f.get("betas") or {}
    main = sorted(betas.items(), key=lambda kv: -abs(kv[1].get("t") or 0))[:3]
    drift = f.get("drift") or {}
    return {"status": "ok", "source": f.get("source"), "window": f.get("window"), "obs": f.get("obs"),
            "alpha_annual": f.get("alpha_annual"), "alpha_t": f.get("alpha_t"),
            "alpha_p": f.get("alpha_p"),
            "main_betas": [{"factor": k, "beta": v.get("beta"), "t": v.get("t")} for k, v in main],
            "r2": f.get("r2"), "adj_r2": f.get("adj_r2"), "meaningful": f.get("meaningful"),
            "drift": {"status": drift.get("status"), "reason": drift.get("reason"),
                      "flags": drift.get("flags") or [], "flags_family": drift.get("flags_family") or []},
            "notes": f.get("notes") or []}


def _paper_live_view(p: dict | None) -> dict:
    if not p:
        return {"status": "missing", "live_ready": False}
    cap = p.get("capacity") or {}
    mean = p.get("extra_cost_mean")
    return {"status": p.get("status"), "trades": p.get("trades", 0),
            "record_days": p.get("record_days"),
            "extra_cost_median_bps": p.get("extra_cost_median_bps"),
            "extra_cost_mean_bps": None if mean is None else mean * 1e4,
            "paper_mean_excess_domain": p.get("paper_mean_excess_domain"),
            "live_mean_excess_domain": p.get("live_mean_excess_domain"),
            "capacity_breaches": cap.get("breaches"), "capacity_priced": cap.get("priced"),
            "capacity_usd_p10": cap.get("capacity_usd_p10"), "unknown_cost": p.get("unknown_cost"),
            "live_ready": bool(p.get("live_ready")), "checks": p.get("live_ready_checks") or {}}


def get_diagnostics() -> dict:
    """Per-shadow factor alpha / main betas / R² / style drift and the paper-to-live gap,
    from promotion.runner.read_diagnostics (state.json "diagnostics"). Reporting only."""
    from marketmind.promotion.runner import read_diagnostics
    d = read_diagnostics(data_dir())
    shadows = d.get("shadows") or {}
    if not shadows:
        return {"available": False, "updated_at": d.get("updated_at"), "meta": d.get("meta"),
                "rows": [], "reason": "因子诊断尚未计算（晋升评审时写入 data/promotion/state.json）"}
    rows = [{"shadow_id": sid, "factors": _factor_view(v.get("factors")),
             "paper_live": _paper_live_view(v.get("paper_live"))}
            for sid, v in sorted(shadows.items())]
    return {"available": True, "updated_at": d.get("updated_at"), "meta": d.get("meta"), "rows": rows}


# ── Playground agents (docs/PLAYGROUND_AGENTS.md; S8 "Playground 接回") ──────

PLAYGROUND_DIR = Path(__file__).resolve().parent.parent / "playground"
CONTROL_SUFFIX = "_control"


def get_playground(latest: int = 5) -> dict:
    """Every Playground agent from its manifest, with its ledger counts by status, latest
    calls and promotion stage. A `<x>_control` agent is paired with `<x>` and listed next to it."""
    from marketmind.playground.agent_manifest import discover_agents
    from marketmind.playground.ledger_bridge import source_id as pg_sid
    manifests = discover_agents(PLAYGROUND_DIR)
    store = _store()
    rows_by_sid: dict[str, list] = {}
    for e in (store.list(source_type="playground") if store else []):
        rows_by_sid.setdefault(e.source_id, []).append(e)
    scores = {s.source_id: s.to_dict()
              for s in scoreboard([e for v in rows_by_sid.values() for e in v])}
    state_path = data_dir() / "promotion" / "state.json"
    try:
        recs = (json.loads(state_path.read_text(encoding="utf-8")).get("shadows") or {}
                if state_path.exists() else {})
    except (OSError, ValueError):
        recs = {}
    ids = {m.agent_id for m in manifests}
    agents = []
    for m in manifests:
        sid = pg_sid(m.agent_id)
        rows = rows_by_sid.get(sid, [])
        counts: dict[str, int] = {}
        for e in rows:
            counts[e.status] = counts.get(e.status, 0) + 1
        rec = recs.get(sid) or {}
        stage = rec.get("stage")
        base = m.agent_id[:-len(CONTROL_SUFFIX)] if m.agent_id.endswith(CONTROL_SUFFIX) else None
        is_control = base in ids
        pair = base if is_control else (m.agent_id + CONTROL_SUFFIX
                                        if m.agent_id + CONTROL_SUFFIX in ids else None)
        agents.append({
            "agent_id": m.agent_id, "source_id": sid, "display_name": m.display_name,
            "description": m.description, "author": m.author, "version": m.version,
            "domain_benchmark": m.domain_benchmark, "primary_metric": m.primary_metric,
            "tags": m.tags, "records": len(rows), "status_counts": counts, "score": scores.get(sid),
            "latest": [{"entry_id": e.entry_id, "created_at": e.created_at, "ticker": e.ticker,
                        "direction": e.direction, "confidence": e.confidence, "status": e.status,
                        "net_return": e.net_return}
                       for e in sorted(rows, key=lambda e: e.created_at, reverse=True)[:latest]],
            "stage_code": stage, "stage": STAGE_CN.get(stage, stage) if stage else None,
            "tier": rec.get("tier"), "promotion_score": rec.get("score"),
            "pair_with": pair, "is_control": is_control})
    order = {a["agent_id"]: i for i, a in enumerate(agents)}
    agents.sort(key=lambda a: (order[a["pair_with"]] if a["is_control"] else order[a["agent_id"]],
                               a["is_control"]))
    pairs = [[a["pair_with"], a["agent_id"]] for a in agents if a["is_control"]]
    known = {a["source_id"] for a in agents}
    unknown = [{"source_id": sid, "records": len(v)} for sid, v in sorted(rows_by_sid.items())
               if sid not in known]
    return {"available": bool(manifests), "ledger": store is not None, "agents": agents,
            "pairs": pairs, "unknown_sources": unknown}
