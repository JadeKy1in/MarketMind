"""Temporary event shadows (docs/S7_DESIGN.md §二, SPEC_v3 §6.3 temp_event).

E1 central-bank surprise, E2 geopolitics, E4 key personnel: keyword pre-filter,
then one Flash call groups articles into events; code validates the article ids
and requires >= 2 independent sources. E3 volatility shock: pure code over the
long-term shadows' watchlists. At most MAX_ACTIVE event shadows live at once,
each for LIFE_DAYS; they trade through the normal v3 runner as temp_shadow.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import pstdev

from marketmind.config.source_independence import count_independent_sources
from marketmind.pipeline.defang import defang_text
from marketmind.shadows.v3.roster import PROMPT_DIR, RosterEntry

logger = logging.getLogger("marketmind.shadows.v3.temp_event")

MAX_ACTIVE = 5                   # owner decision 2026-09-28: 5 event + 5 trial shadows
LIFE_DAYS = 30
MAX_NEWS = 60
MIN_SOURCES = 2
VOL_Z = 4.0
VOL_LOOKBACK = 60
OVERLAP = 0.5

# (name, base impact, keyword groups: an article must hit >= 2 groups) — legacy E1-E4
TYPES = {
    "E1": ("央行意外", 0.6, [
        r"\b(?:Fed|Federal Reserve|FOMC|ECB|BOJ|BOE|PBOC|RBA|RBNZ|BOC|SNB|central bank)\b",
        r"\b(?:rate|rates|hike|cut|ease|easing|tighten|basis points?|bps?|QE|QT)\b",
        r"\b(?:surprise|unexpected|shock|emergency|unscheduled|than expected)\b"]),
    "E2": ("地缘政治", 0.5, [
        r"\b(?:war|conflict|sanctions?|tensions?|missile|invasion|military|coup|strike)\b",
        r"\b(?:geopolitical|crisis|escalat\w*|attack|embargo|blockade|ceasefire)\b"]),
    "E3": ("波动率冲击", 0.7, []),
    "E4": ("关键人事", 0.4, [
        r"\b(?:Treasury Secretary|Fed Chair|SEC Chair|CFTC|OCC|FDIC|Fed Governor|finance minister)\b",
        r"\b(?:resign\w*|fired|ousted|replaced|appointed|nominated|confirmed|steps down)\b"]),
}
DEFAULT_WATCHLIST = {
    "E1": ("SPY", "TLT", "SHY", "UUP", "GLD", "EURUSD=X", "JPY=X"),
    "E2": ("SPY", "GLD", "USO", "XLE", "ITA", "VXX", "TLT"),
    "E4": ("SPY", "TLT", "UUP", "XLF", "GLD"),
}
BENCHMARK = {"E1": "TLT", "E2": "SPY", "E3": "SPY", "E4": "SPY"}

SYSTEM_PROMPT = """你是事件归并员。下面每条新闻都已被关键词初筛为可能的"央行意外(E1)"、"地缘政治(E2)"或"关键人事变动(E4)"。
把报道同一件事的新闻归并成一个事件，只保留真正重大的、会影响市场的事件（评论、预告、旧闻不算）。
每个事件给出：type（E1/E2/E4）、title（中文，一句话）、summary（中文，两三句，只用新闻里的事实）、
news_ids（报道该事件的新闻编号，必须来自输入）、watchlist（最直接受影响、真实可交易的代码，Yahoo 格式，
如 SPY、TLT、GLD、USO、CL=F、EURUSD=X、0700.HK，最多 8 个）。最多 8 个事件；没有就返回空列表。
只输出 JSON：{"events": [{"type": "E1", "title": "...", "summary": "...", "news_ids": ["..."], "watchlist": ["..."]}]}"""


@dataclass
class Event:
    event_id: str
    type: str
    title: str
    summary: str
    watchlist: list[str]
    impact: float
    spawned: str                      # YYYY-MM-DD
    expires: str
    news_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    status: str = "active"            # active | retired

    def days_left(self, today: str) -> int:
        return max(0, (date.fromisoformat(self.expires) - date.fromisoformat(today)).days)


def state_path() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "temp_shadows" / "events.json"


def load_state(path: Path | None = None) -> tuple[str | None, list[Event]]:
    """(date of the last detection run, events)."""
    path = path or state_path()
    if not path.exists():
        return None, []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("last_run"), [Event(**r) for r in data.get("events", [])]


def load(path: Path | None = None) -> list[Event]:
    return load_state(path)[1]


def save(events: list[Event], path: Path | None = None, last_run: str | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_run": last_run, "events": [asdict(e) for e in events]},
                               ensure_ascii=False, indent=1), encoding="utf-8")


def _id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:10]


def prefilter(items: list) -> list:
    out = []
    for n in items:
        text = f"{n.title} {getattr(n, 'summary', '') or ''}"
        for code, (_, _, groups) in TYPES.items():
            if groups and sum(1 for g in groups if re.search(g, text, re.I)) >= 2:
                out.append(n)
                break
    return sorted(out, key=lambda n: -(getattr(n, "priority_score", 0) or 0))[:MAX_NEWS]


def parse_events(text: str, by_id: dict, today: str, tradable) -> tuple[list[Event], list[str]]:
    from marketmind.shadows.v3.decision import extract_json
    try:
        payload = extract_json(text)
    except ValueError as e:
        return [], [f"no JSON: {e}"]
    rows = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [], ["events is not a list"]
    events, dropped = [], []
    for i, r in enumerate(rows[:8]):
        if not isinstance(r, dict):
            continue
        t = str(r.get("type") or "").strip().upper()
        ids = [str(x) for x in (r.get("news_ids") or []) if str(x) in by_id]
        sources = sorted({getattr(by_id[x], "source_name", "") or "unknown" for x in ids})
        indep = count_independent_sources(sources)
        title = str(r.get("title") or "").strip()
        if t not in ("E1", "E2", "E4"):
            dropped.append(f"#{i}: bad type {t!r}")
        elif not title or not ids:
            dropped.append(f"#{i}: missing title or valid news ids")
        elif indep < MIN_SOURCES:
            dropped.append(f"#{i}: {indep} independent source(s) < {MIN_SOURCES}")
        else:
            wl = [str(x).strip().upper() for x in (r.get("watchlist") or [])]
            wl = [x for x in dict.fromkeys(wl) if x and tradable(x)][:8] or list(DEFAULT_WATCHLIST[t])
            base = TYPES[t][1]
            events.append(Event(
                event_id=_id(today, t, title), type=t, title=title[:120],
                summary=str(r.get("summary") or "")[:600], watchlist=wl,
                impact=round(min(1.0, base + 0.1 * min(indep, 3)), 3), spawned=today,
                expires=(date.fromisoformat(today) + timedelta(days=LIFE_DAYS)).isoformat(),
                news_ids=ids, sources=sources))
    return events, dropped


def vol_shocks(histories: dict, today: str) -> list[Event]:
    """E3: last daily return >= VOL_Z standard deviations of the prior 60 returns."""
    out = []
    for ticker, hist in histories.items():
        bars = getattr(hist, "daily", None) or []
        if len(bars) < VOL_LOOKBACK + 2:
            continue
        closes = [b.close for b in bars[-(VOL_LOOKBACK + 2):]]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        sd = pstdev(rets[:-1])
        if sd <= 0:
            continue
        z = rets[-1] / sd
        if abs(z) >= VOL_Z:
            title = f"{ticker} 单日{'暴涨' if z > 0 else '暴跌'} {rets[-1]:+.1%}（{abs(z):.1f} 倍标准差）"
            out.append(Event(
                event_id=_id(today, "E3", ticker), type="E3", title=title,
                summary=f"{ticker} 最近一个交易日（{bars[-1].date}）收益 {rets[-1]:+.2%}，"
                        f"为过去 {VOL_LOOKBACK} 日日收益标准差的 {abs(z):.1f} 倍。",
                watchlist=[ticker, "SPY"] if ticker != "SPY" else ["SPY", "QQQ", "TLT"],
                impact=round(min(1.0, TYPES["E3"][1] + (abs(z) - VOL_Z) * 0.05), 3),
                spawned=today,
                expires=(date.fromisoformat(today) + timedelta(days=LIFE_DAYS)).isoformat()))
    return out


def _similar(a: Event, b: Event) -> bool:
    if a.type != b.type:
        return False
    if a.type == "E3":
        return a.watchlist[0] == b.watchlist[0]

    def jac(x: set, y: set) -> float:
        return len(x & y) / len(x | y) if x | y else 0.0
    # Chinese titles have no spaces: compare character bigrams
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}
    return (jac(grams(a.title), grams(b.title)) >= OVERLAP
            or jac(set(a.watchlist), set(b.watchlist)) >= 0.8)


def refresh(events: list[Event], candidates: list[Event], today: str) -> tuple[list[Event], list[Event]]:
    """Retire expired events, then fill free slots by impact. Returns (all, spawned today)."""
    for e in events:
        if e.status == "active" and e.expires <= today:
            e.status = "retired"
    active = [e for e in events if e.status == "active"]
    spawned = []
    for c in sorted(candidates, key=lambda c: -c.impact):
        if len(active) >= MAX_ACTIVE:
            break
        if any(c.event_id == e.event_id or _similar(c, e) for e in active):
            continue
        active.append(c)
        events.append(c)
        spawned.append(c)
    return events, spawned


# shadow_id -> the event's LLM-written title/summary. They are untrusted text, so they
# never go into the shadow's SYSTEM prompt; context.build_context puts them in the
# user message inside a delimited untrusted-data block (red-team 2026-09-29).
_BRIEFS: dict[str, dict[str, str]] = {}


def event_brief(shadow_id: str) -> dict[str, str] | None:
    """Title/type/summary of an event shadow built by roster_entries in this process."""
    return _BRIEFS.get(shadow_id)


def roster_entries(events: list[Event], today: str) -> list[RosterEntry]:
    template = (PROMPT_DIR / "_temp_event.md").read_text(encoding="utf-8")
    out = []
    for e in events:
        if e.status != "active":
            continue
        type_name = f"{e.type} {TYPES[e.type][0]}"
        prompt = template.format(type_name=type_name, spawned=e.spawned,
                                 watchlist=", ".join(e.watchlist), days_left=e.days_left(today))
        _BRIEFS[f"temp_event:{e.event_id}"] = {"title": e.title, "type": type_name,
                                               "summary": e.summary or e.title}
        out.append(RosterEntry(
            shadow_id=f"temp_event:{e.event_id}", name=f"temp_{e.type}_{e.event_id[:6]}",
            display_name=e.title, group="temp_event", domain=f"{e.type} {TYPES[e.type][0]}",
            watchlist=tuple(e.watchlist), domain_benchmark=BENCHMARK[e.type],
            source_type="temp_shadow", prompt_text=prompt))
    return out


async def _call_llm(system: str, user: str) -> str:
    import asyncio
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_flash
    token = usage_tracker.set_stage("temp_event")
    try:
        result = await asyncio.wait_for(chat_flash(system, user, temperature=0.1, max_tokens=8192),
                                        timeout=240)
    finally:
        usage_tracker.reset_stage(token)
    if result.get("error"):
        raise RuntimeError(f"LLM error: {result.get('error')}")
    return result.get("content") or ""


async def daily_events(news_items: list, histories: dict, *, today: str | None = None,
                       call=_call_llm, tradable=None, path: Path | None = None) -> dict:
    """Detect, dedupe, spawn and retire; returns a summary. Failures never raise."""
    from marketmind.markets import is_shadow_tradable
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tradable = tradable or is_shadow_tradable
    last_run, events = load_state(path)
    if last_run == today:                            # one detection (one LLM call) per day
        return {"date": today, "skipped": True, "active": sum(e.status == "active" for e in events)}
    candidates, dropped = vol_shocks(histories, today), []
    news = prefilter(news_items)
    if news:
        by_id = {n.id: n for n in news}
        user = "\n".join(f"[{n.id}] ({defang_text(getattr(n, 'source_name', '') or '')}) "
                         f"{defang_text(n.title)}\n    "
                         f"{defang_text((getattr(n, 'summary', '') or '')[:240])}" for n in news)
        try:
            found, dropped = parse_events(await call(SYSTEM_PROMPT, user), by_id, today, tradable)
            candidates += found
        except Exception as e:
            logger.warning("event grouping failed: %s", e)
            dropped.append(f"LLM failed: {type(e).__name__}")
    events, spawned = refresh(events, candidates, today)
    save(events, path, last_run=today)
    return {"date": today, "candidates": len(candidates), "spawned": [e.title for e in spawned],
            "active": sum(e.status == "active" for e in events), "dropped": dropped}
