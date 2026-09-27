"""First-hand regulatory / official-calendar sources (free, no API key) turned into NewsItems.

- SEC EDGAR full-text search (efts.sec.gov): recent 8-K / 10-Q / 10-K filings that mention a
  watchlist of red-flag / catalyst phrases ("going concern", "material weakness", ...).
- Federal Reserve Board calendar (federalreserve.gov/json/calendar.json): FOMC, Board member
  speeches, testimony and Beige Book in the next 7 days.
- BLS release calendar (bls.gov .ics): market-moving BLS releases (CPI, jobs, PPI, JOLTS, ECI ...)
  in the next 7 days. Parsed with the stdlib only.

SEC XBRL "frames" (aggregated financial facts) are intentionally NOT implemented: they are
numeric datasets, not events, and would either flood the news feed or produce nothing useful
as NewsItems. They belong in a data-mining tool, not in scout.

Every fetcher raises on non-200 responses (resp.raise_for_status) so that
scout.fetch_source() applies its usual failure tracking (DEGRADED -> DEAD).
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("marketmind.pipeline.sources_regulatory")

HTTP_TIMEOUT = 30.0
_ET = ZoneInfo("America/New_York")
_BOT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketMind/0.1; Financial Research Bot)"}

# ── SEC EDGAR full-text search ──────────────────────────────────────────────
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EFTS_FORMS = "8-K,10-Q,10-K"
EFTS_LOOKBACK_DAYS = 3
# SEC requires "Org contact@email"; same string as scout._fetch_sec_edgar / insider_sources.
SEC_HEADERS = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)", "Accept": "application/json"}
# SEC fair-access limit is 10 req/s; phrases are queried sequentially with this pause.
EFTS_REQUEST_PAUSE_S = 0.15
# Watchlist in priority order: when the total cap is hit, later phrases are dropped first.
# (phrase, forms). Phrases that are boilerplate in 10-K risk factors / Item 1C (cyber, export
# control, tariff, chapter 11 history) are limited to 8-Ks, where they signal a current event.
EFTS_PHRASES: tuple[tuple[str, str], ...] = (
    ("going concern", EFTS_FORMS),
    ("material weakness", EFTS_FORMS),
    ("should no longer be relied upon", "8-K"),   # Item 4.02 non-reliance on prior financials
    ("restatement", "8-K"),
    ("delisting", "8-K"),
    ("chapter 11", "8-K"),
    ("cybersecurity incident", "8-K"),            # Item 1.05 material cybersecurity incident
    ("export control", "8-K"),
    ("Section 232", EFTS_FORMS),
    ("tariff", "8-K"),
)
EFTS_MAX_PER_PHRASE = 3
EFTS_MAX_FILINGS = 30

# ── Federal Reserve Board calendar ──────────────────────────────────────────
FED_CALENDAR_URL = "https://www.federalreserve.gov/json/calendar.json"
FED_CALENDAR_PAGE = "https://www.federalreserve.gov/newsevents/calendar.htm"
# Kept event types. Skipped: "Stat" (daily H.x/G.x statistical releases), "Other" (holidays),
# "events"/"Conferences" (low-signal outreach events).
FED_EVENT_TYPES = frozenset({"FOMC", "Speeches", "Testimony", "Beige", "Board"})
FED_MAX_EVENTS = 20

# ── BLS release calendar ────────────────────────────────────────────────────
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE_PAGE = "https://www.bls.gov/schedule/news_release/"
# Market-moving releases only (exact SUMMARY match, case-insensitive). Regional, annual and
# niche releases (State JOLTS, Employee Tenure, ...) are dropped to keep output compact.
BLS_MAJOR_RELEASES = frozenset(s.lower() for s in (
    "Employment Situation",
    "Consumer Price Index",
    "Producer Price Index",
    "Job Openings and Labor Turnover Survey",
    "Employment Cost Index",
    "Real Earnings",
    "U.S. Import and Export Price Indexes",
    "Productivity and Costs",
    "Current Employment Statistics Preliminary Benchmark (National)",
))
CALENDAR_WINDOW_DAYS = 7


def _client_kwargs(config: Any) -> dict:
    kwargs: dict = {"timeout": HTTP_TIMEOUT, "follow_redirects": True}
    proxy = getattr(config, "proxy_url", "") if config is not None else ""
    if isinstance(proxy, str) and proxy:
        kwargs["proxy"] = proxy
    return kwargs


def _reliability(source: Any, default: float) -> float:
    try:
        return float(source.reliability)
    except (TypeError, ValueError, AttributeError):
        return default


def _sid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _clean_text(text: Any) -> str:
    """Unescape (the Fed calendar is double-escaped), strip tags, collapse whitespace."""
    s = str(text or "")
    for _ in range(2):
        s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _in_window(d: date, today: date, days: int = CALENDAR_WINDOW_DAYS) -> bool:
    return today <= d <= today + timedelta(days=days)


# ════════════════════════════════════════════════════════════════════════════
# SEC EDGAR full-text search
# ════════════════════════════════════════════════════════════════════════════

def _efts_company(src: dict) -> str:
    names = src.get("display_names") or []
    name = str(names[0]) if names else "Unknown filer"
    name = re.sub(r"\(CIK \d+\)", "", name)
    return re.sub(r"\s+", " ", name).strip() or "Unknown filer"


def _efts_url(hit: dict) -> str:
    src = hit.get("_source", {})
    adsh = str(src.get("adsh", ""))
    ciks = src.get("ciks") or []
    filename = str(hit.get("_id", "")).split(":", 1)[1] if ":" in str(hit.get("_id", "")) else ""
    try:
        cik = int(ciks[0])
    except (IndexError, TypeError, ValueError):
        cik = None
    if cik is None or not adsh:
        return "https://efts.sec.gov/LATEST/search-index"  # should not happen for real hits
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/"
    return base + filename if filename else base


def _is_signal_document(src: dict) -> bool:
    """Main filing document or EX-99 press release. Other exhibits (credit agreements, charters,
    clawback policies, underwriting agreements) match phrases in boilerplate and are dropped."""
    file_type = str(src.get("file_type") or "").upper()
    roots = [str(r).upper() for r in (src.get("root_forms") or [src.get("form") or ""])]
    return file_type.startswith("EX-99") or any(r and file_type.startswith(r) for r in roots)


def collect_efts_hits(results: list[tuple[str, dict]],
                      max_per_phrase: int = EFTS_MAX_PER_PHRASE,
                      max_total: int = EFTS_MAX_FILINGS) -> list[dict]:
    """Merge per-phrase EFTS responses into unique filings (deduped by accession number).

    `results` is [(phrase, efts_json), ...] in watchlist priority order. Within a phrase the
    newest filings win. A filing matching several phrases is kept once, listing every phrase.
    """
    filings: dict[str, dict] = {}
    for phrase, payload in results:
        hits = (payload or {}).get("hits", {}).get("hits", []) or []
        hits = sorted(hits, key=lambda h: str(h.get("_source", {}).get("file_date", "")), reverse=True)
        taken = 0
        for hit in hits:
            src = hit.get("_source", {}) or {}
            adsh = str(src.get("adsh", ""))
            if not adsh or not _is_signal_document(src):
                continue
            if adsh in filings:
                if phrase not in filings[adsh]["phrases"]:
                    filings[adsh]["phrases"].append(phrase)
                continue
            if taken >= max_per_phrase or len(filings) >= max_total:
                continue
            filings[adsh] = {"adsh": adsh, "hit": hit, "phrases": [phrase]}
            taken += 1
    return list(filings.values())


def efts_filing_to_newsitem(filing: dict, source: Any) -> Any:
    from marketmind.pipeline.scout import NewsItem

    src = filing["hit"].get("_source", {}) or {}
    company = _efts_company(src)
    form = str(src.get("form") or src.get("file_type") or "filing")
    file_date = str(src.get("file_date", ""))
    phrases = filing["phrases"]
    # Keep shared boilerplate minimal: scout.deduplicate drops titles with >80% word overlap.
    title = f'{company} {form}: "{phrases[0]}"'
    if len(phrases) > 1:
        title += f" +{len(phrases) - 1}"
    parts = [f"{form} filed {file_date} by {company}",
             "matched: " + ", ".join(f'"{p}"' for p in phrases)]
    if src.get("items"):
        parts.append("8-K items " + ", ".join(str(i) for i in src["items"]))
    if src.get("period_ending"):
        parts.append(f"period ending {src['period_ending']}")
    if src.get("biz_locations"):
        parts.append(str(src["biz_locations"][0]))
    if src.get("sics"):
        parts.append(f"SIC {src['sics'][0]}")
    parts.append(f"accession {filing['adsh']}")
    return NewsItem(
        id=_sid(f"efts:{filing['adsh']}"),
        title=title,
        url=_efts_url(filing["hit"]),
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=file_date,
        summary=("; ".join(parts))[:500],
        source_reliability=_reliability(source, 0.90),
    )


async def fetch_sec_fulltext_flags(source: Any, config: Any = None,
                                   today: date | None = None) -> list[Any]:
    """Recent SEC filings mentioning watchlist phrases (one NewsItem per filing, capped)."""
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=EFTS_LOOKBACK_DAYS)
    results: list[tuple[str, dict]] = []
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        for i, (phrase, forms) in enumerate(EFTS_PHRASES):
            if i and EFTS_REQUEST_PAUSE_S:
                await asyncio.sleep(EFTS_REQUEST_PAUSE_S)
            params = {"q": f'"{phrase}"', "forms": forms, "dateRange": "custom",
                      "startdt": start.isoformat(), "enddt": today.isoformat()}
            resp = await client.get(EFTS_URL, params=params, headers=SEC_HEADERS)
            resp.raise_for_status()
            results.append((phrase, resp.json()))
    return [efts_filing_to_newsitem(f, source) for f in collect_efts_hits(results)]


# ════════════════════════════════════════════════════════════════════════════
# Federal Reserve Board calendar
# ════════════════════════════════════════════════════════════════════════════

def _parse_fed_time(text: str) -> tuple[int, int] | None:
    """'3:30 p.m.' -> (15, 30); '' / unparseable -> None."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?", str(text or ""), re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).lower() == "p":
        hour += 12
    return hour, minute


def fed_events_in_window(events: list[dict], today: date,
                         days: int = CALENDAR_WINDOW_DAYS) -> list[tuple[datetime | date, dict]]:
    """Kept-type events with a day in today..today+days, sorted by first in-window day.

    `days` may be a comma list ("1, 2"); such an entry yields ONE item at its first in-window
    day, with the other in-window days in ev["_also_days"] (separate items with near-identical
    titles would be collapsed by scout.deduplicate anyway).
    """
    out: list[tuple[datetime | date, dict]] = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") not in FED_EVENT_TYPES:
            continue
        try:
            year, month = (int(x) for x in str(ev.get("month", "")).split("-"))
        except ValueError:
            continue
        in_window: list[date] = []
        for day_txt in str(ev.get("days", "")).split(","):
            try:
                d = date(year, month, int(day_txt.strip()))
            except ValueError:
                continue
            if _in_window(d, today, days):
                in_window.append(d)
        if not in_window:
            continue
        in_window.sort()
        d = in_window[0]
        hm = _parse_fed_time(ev.get("time", ""))
        when: datetime | date = datetime(d.year, d.month, d.day, *hm, tzinfo=_ET) if hm else d
        out.append((when, {**ev, "_also_days": [x.isoformat() for x in in_window[1:]]}))
    out.sort(key=lambda t: (t[0] if isinstance(t[0], datetime)
                            else datetime(t[0].year, t[0].month, t[0].day, tzinfo=_ET)))
    return out


def fed_event_to_newsitem(when: datetime | date, ev: dict, source: Any) -> Any:
    from marketmind.pipeline.scout import NewsItem

    title_txt = _clean_text(ev.get("title")) or "Federal Reserve event"
    desc = _clean_text(ev.get("description"))
    if isinstance(when, datetime):
        stamp = when.strftime("%Y-%m-%d %H:%M ET")
        day = when.date().isoformat()
    else:
        stamp = day = when.isoformat()
    if ev.get("_also_days"):
        stamp += " (also " + ", ".join(ev["_also_days"]) + ")"
    title = f"Fed {stamp}: {title_txt}" + (f" - {desc}" if desc else "")
    parts = [f"Federal Reserve calendar ({ev.get('type')}) {stamp}: {title_txt}"]
    if desc:
        parts.append(desc)
    loc = _clean_text(ev.get("location"))
    if loc:
        parts.append(loc)
    item_id = _sid(f"fedcal:{day}:{ev.get('time', '')}:{title_txt}")
    return NewsItem(
        id=item_id,
        title=title[:300],
        # scout.deduplicate drops exact-URL repeats, so each event gets its own URL.
        url=f"{ev.get('link') or FED_CALENDAR_PAGE}#{item_id}",
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=when.isoformat(),
        summary=("; ".join(parts))[:500],
        source_reliability=_reliability(source, 0.97),
    )


async def fetch_fed_calendar(source: Any, config: Any = None,
                             today: date | None = None) -> list[Any]:
    """Fed Board calendar events (FOMC, speeches, testimony, Beige Book) in the next 7 days."""
    today = today or datetime.now(_ET).date()
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(FED_CALENDAR_URL, headers={**_BOT_HEADERS, "Accept": "application/json"})
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8-sig"))  # the file starts with a UTF-8 BOM
    events = data.get("events", []) if isinstance(data, dict) else []
    selected = fed_events_in_window(events, today)[:FED_MAX_EVENTS]
    return [fed_event_to_newsitem(when, ev, source) for when, ev in selected]


# ════════════════════════════════════════════════════════════════════════════
# BLS release calendar (.ics, stdlib parser)
# ════════════════════════════════════════════════════════════════════════════

def _ics_unescape(value: str) -> str:
    return (value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\")).strip()


def parse_ics_events(text: str) -> list[dict]:
    """Minimal RFC 5545 VEVENT parser: unfolds lines, returns [{'UID', 'SUMMARY', 'DTSTART', ...}].

    DTSTART is returned as a datetime (US Eastern for TZID times, UTC for 'Z' times) or a date.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events: list[dict] = []
    cur: dict | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *params = head.split(";")
        name = name.upper()
        if name == "DTSTART":
            cur[name] = _parse_ics_dt(value.strip(), params)
        else:
            cur[name] = _ics_unescape(value)
    return events


def _parse_ics_dt(value: str, params: list[str]) -> datetime | date | None:
    try:
        if "T" not in value or any(p.upper() == "VALUE=DATE" for p in params):
            return datetime.strptime(value[:8], "%Y%m%d").date()
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        # BLS uses TZID=US-Eastern (a custom VTIMEZONE); floating times are also treated as ET.
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=_ET)
    except ValueError:
        return None


def bls_releases_in_window(events: list[dict], today: date,
                           days: int = CALENDAR_WINDOW_DAYS) -> list[dict]:
    out = []
    for ev in events:
        start = ev.get("DTSTART")
        name = str(ev.get("SUMMARY", "")).strip()
        if start is None or name.lower() not in BLS_MAJOR_RELEASES:
            continue
        d = start.astimezone(_ET).date() if isinstance(start, datetime) else start
        if _in_window(d, today, days):
            out.append(ev)
    out.sort(key=lambda e: e["DTSTART"] if isinstance(e["DTSTART"], datetime)
             else datetime(e["DTSTART"].year, e["DTSTART"].month, e["DTSTART"].day, tzinfo=_ET))
    return out


def bls_event_to_newsitem(ev: dict, source: Any) -> Any:
    from marketmind.pipeline.scout import NewsItem

    start = ev["DTSTART"]
    name = str(ev.get("SUMMARY", "")).strip()
    if isinstance(start, datetime):
        start = start.astimezone(_ET)
        stamp = start.strftime("%Y-%m-%d %H:%M ET")
    else:
        stamp = start.isoformat()
    uid = str(ev.get("UID") or f"{name}:{stamp}")
    return NewsItem(
        id=_sid(f"bls:{uid}:{stamp}"),
        title=f"BLS {stamp}: {name}",
        url=f"{BLS_SCHEDULE_PAGE}?release={quote(name)}&date={stamp[:10]}",  # unique per release
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=start.isoformat(),
        summary=f"Scheduled BLS release: {name} at {stamp} (official BLS release calendar)."[:500],
        source_reliability=_reliability(source, 0.97),
    )


async def fetch_bls_calendar(source: Any, config: Any = None,
                             today: date | None = None) -> list[Any]:
    """Market-moving BLS releases scheduled in the next 7 days."""
    today = today or datetime.now(_ET).date()
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(BLS_ICS_URL, headers={**_BOT_HEADERS, "Accept": "text/calendar"})
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")
    events = parse_ics_events(text)
    return [bls_event_to_newsitem(ev, source) for ev in bls_releases_in_window(events, today)]
