"""Daily / weekend trend step (docs/TREND_DESIGN.md §9): states only - no ledger, no push.

Computes today's states for the full merged universe and the lean variant from one
fetch, compares them with the most recent earlier file for each instrument, and
writes <data dir>/trend/<New York date>.json atomically. The weekend run covers the
crypto instruments only.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Sequence
from zoneinfo import ZoneInfo

from marketmind.gateway.price_history import is_crypto_ticker
from marketmind.trend.lean import LeanConfig, lean_states
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import (
    CASH, EVENT_ENTRY, EVENT_EXIT, EXIT, TREND, UNAVAILABLE, WATCH, compute_states, fetch_inputs,
)
from marketmind.trend.universe import TREND_UNIVERSE

logger = logging.getLogger("marketmind.trend.daily")

NEW_YORK = ZoneInfo("America/New_York")
LOOKBACK_FILES = 14            # how far back to look for an instrument's previous state
FLAT = (CASH, WATCH, EXIT)


def ny_date(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(NEW_YORK).date().isoformat()


def trend_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "trend"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable trend file %s", path)
        return None


def previous_states(folder: Path, before: str, section: str) -> dict[str, dict]:
    """Each instrument's state in the most recent file dated before `before` that has it."""
    files = sorted((p for p in folder.glob("????-??-??.json") if p.stem < before), reverse=True)
    out: dict[str, dict] = {}
    for p in files[:LOOKBACK_FILES]:
        doc = _read(p) or {}
        states = doc.get("full", {}) if section == "full" else (doc.get("lean") or {}).get("states", {})
        for t, s in states.items():
            out.setdefault(t, s)
    return out


def changes(prev: dict[str, dict], cur: dict[str, dict]) -> dict[str, list[str]]:
    """Entries / exits = state changes vs the previous record. With no previous record
    only today's ENTRY / EXIT events count; UNAVAILABLE is neither."""
    entries, exits = [], []
    for t, s in cur.items():
        p = prev.get(t)
        now_in, was_in = s["state"] == TREND, p is not None and p.get("state") == TREND
        same = was_in and now_in and p.get("entry_signal_date") == s.get("entry_signal_date")
        known = p is not None and p.get("state") != UNAVAILABLE
        if now_in and not same and (known or s.get("event") == EVENT_ENTRY):
            entries.append(t)
        if (was_in and (s["state"] in FLAT or (now_in and not same))) or \
                (not was_in and not known and s.get("event") == EVENT_EXIT):
            exits.append(t)
    return {"entries": sorted(entries), "exits": sorted(exits)}


def build_snapshot(histories: dict, sources: dict, hurdle: float, hurdle_source: str, *,
                   today: str, mode: str, prev_full: dict, prev_lean: dict,
                   cfg: TrendConfig | None = None, lean: LeanConfig = LeanConfig(),
                   now: datetime | None = None) -> dict:
    from datetime import date
    cfg = cfg or TrendConfig()
    day = date.fromisoformat(today)
    full = {t: s.to_dict() for t, s in compute_states(
        histories, hurdle, cfg, hurdle_source=hurdle_source, today=day, sources=sources).items()}
    lv = lean_states(histories, hurdle, cfg, lean, hurdle_source=hurdle_source, today=day,
                     sources=sources)
    lean_doc = {"strongest_sector": lv["strongest_sector"], "top_n": lv["top_n"],
                "groups": lv["groups"], "states": {t: s.to_dict() for t, s in lv["states"].items()}}
    counts = {"TREND": sum(s["state"] == TREND for s in full.values()),
              "CASH": sum(s["state"] in FLAT for s in full.values()),
              "UNAVAILABLE": sum(s["state"] == UNAVAILABLE for s in full.values())}
    return {"date": today, "mode": mode,
            "written_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            .isoformat(timespec="seconds"),
            "hurdle": hurdle, "hurdle_source": hurdle_source, "counts": counts,
            "full": full, "lean": lean_doc,
            "changes": {"full": changes(prev_full, full), "lean": changes(prev_lean, lean_doc["states"])}}


def write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


Fetcher = Callable[[Sequence[str]], Awaitable[tuple[dict, dict, float, str]]]


async def run_trend_step(data_dir: Path, mode: str = "daily", now: datetime | None = None,
                         fetch: Fetcher = fetch_inputs,
                         universe: Sequence[str] = TREND_UNIVERSE) -> dict:
    """Fetch, compute, diff and write today's file; returns the snapshot. Raises on failure
    (the orchestration step records it as degraded)."""
    tickers = [t for t in universe if is_crypto_ticker(t)] if mode == "weekend" else list(universe)
    histories, sources, hurdle, src = await fetch(tickers)
    if not any(histories.values()):
        raise RuntimeError(f"no price history for any of {len(tickers)} trend instruments")
    today = ny_date(now)
    folder = trend_dir(data_dir)
    snap = build_snapshot(histories, sources, hurdle, src, today=today, mode=mode,
                          prev_full=previous_states(folder, today, "full"),
                          prev_lean=previous_states(folder, today, "lean"), now=now)
    write_atomic(folder / f"{today}.json", snap)
    return snap


def summary_line(snap: dict) -> str:
    """`[trend] n TREND, m CASH, k unavailable; entries: ...; exits: ...` (full universe;
    lean changes in parentheses)."""
    c, ch = snap["counts"], snap["changes"]

    def names(kind: str) -> str:
        full, lean = ch["full"][kind], ch["lean"][kind]
        text = ", ".join(full) or "none"
        return text + (f" (lean: {', '.join(lean)})" if lean else "")
    return (f"[trend] {c['TREND']} TREND, {c['CASH']} CASH, {c['UNAVAILABLE']} unavailable; "
            f"entries: {names('entries')}; exits: {names('exits')}")


def load(data_dir: Path, day: str | None = None) -> tuple[str | None, dict | None]:
    folder = trend_dir(data_dir)
    if day:
        p = folder / f"{day}.json"
        return day, (_read(p) if p.exists() else None)
    files = sorted(folder.glob("????-??-??.json")) if folder.is_dir() else []
    for p in reversed(files):
        doc = _read(p)
        if doc is not None:
            return p.stem, doc
    return None, None


def report_facts(data_dir: Path, day: str) -> dict | None:
    """The daily report's "趋势状态" facts: today's entries/exits, the TREND list with
    stop levels, the unavailable list (full universe) and the lean view."""
    doc = load(data_dir, day)[1]
    if doc is None:                  # report date (UTC) may be a day off the NY file date
        from datetime import date, timedelta
        stem, doc = load(data_dir)
        if doc is None or stem < (date.fromisoformat(day) - timedelta(days=3)).isoformat():
            return None
    full = doc.get("full", {})
    lean = doc.get("lean") or {}
    return {
        "as_of_file": doc.get("date"), "mode": doc.get("mode"),
        "entries_today": doc.get("changes", {}).get("full", {}).get("entries", []),
        "exits_today": doc.get("changes", {}).get("full", {}).get("exits", []),
        "trend": [{"ticker": t, "stop_level": s.get("stop_level"), "close": s.get("close"),
                   "entry_signal_date": s.get("entry_signal_date"), "as_of": s.get("as_of")}
                  for t, s in sorted(full.items()) if s.get("state") == TREND],
        "unavailable": [{"ticker": t, "reason": s.get("reason")}
                        for t, s in sorted(full.items()) if s.get("state") == UNAVAILABLE],
        "lean": {"strongest_sector": lean.get("strongest_sector"),
                 "entries_today": doc.get("changes", {}).get("lean", {}).get("entries", []),
                 "exits_today": doc.get("changes", {}).get("lean", {}).get("exits", []),
                 "trend": [t for t, s in sorted((lean.get("states") or {}).items())
                           if s.get("state") == TREND]},
        "note": "趋势状态机只是代码确认的趋势状态，尚未接入警报；不是交易指令。",
    }
