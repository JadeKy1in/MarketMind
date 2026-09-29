"""Apple App Store top charts: daily archive and rank changes.

Source (keyless, verified reachable from Riyadh 2026-09-29): the legacy iTunes RSS
JSON feed, which (unlike the newer rss.marketingtools.apple.com v2 feed) still
supports genre filters and the top-grossing chart:
  https://itunes.apple.com/<cc>/rss/<chart>/limit=100[/genre=<id>]/json
  chart = topfreeapplications | topgrossingapplications
  feed.entry[i] (rank = i + 1): im:name.label, im:artist.label,
  id.attributes["im:id" | "im:bundleId"], category.attributes.label; feed.updated.label.
Apple publishes only the current ranking, so history exists only if we archive it:
`archive_daily()` writes one atomic JSON snapshot per day under
<data dir>/altdata/app_charts/<YYYY-MM-DD>.json. Rank changes need >= 2 archived days.

Developer -> ticker matches are a fixed, hand-written prefix list (DEVELOPER_TICKERS);
an unmatched developer is simply not attributed to a company.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from marketmind.gateway.altdata_store import altdata_dir, write_json_atomic

logger = logging.getLogger("marketmind.gateway.app_charts")

FEED_URL = "https://itunes.apple.com/{cc}/rss/{chart}/limit={limit}{genre}/json"
CHARTS = {"free": "topfreeapplications", "grossing": "topgrossingapplications"}
GENRES = {"all": None, "finance": 6015, "shopping": 6024, "games": 6014}
COUNTRIES = ("us", "gb", "jp", "cn")
LIMIT = 100
HTTP_TIMEOUT_S = 30.0
CONCURRENCY = 4
SOURCE = "Apple App Store charts (itunes.apple.com legacy RSS JSON)"
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport

# lower-case developer-name prefix -> ticker (public companies only)
DEVELOPER_TICKERS: dict[str, str] = {
    "robinhood": "HOOD", "coinbase": "COIN", "paypal": "PYPL", "block, inc": "XYZ",
    "sofi ": "SOFI", "capital one": "COF", "chime financial": "CHYM", "affirm, inc": "AFRM",
    "webull": "BULL", "venmo": "PYPL", "shopify": "SHOP", "amazon": "AMZN", "amzn mobile": "AMZN",
    "walmart": "WMT", "target corporation": "TGT",
    "temu": "PDD", "ebay inc": "EBAY", "costco": "COST", "nike, inc": "NKE", "mcdonald": "MCD",
    "starbucks": "SBUX", "doordash": "DASH", "uber technologies": "UBER", "airbnb": "ABNB",
    "etsy": "ETSY", "wayfair": "W", "chewy": "CHWY", "roblox": "RBLX", "electronic arts": "EA",
    "take-two": "TTWO", "zynga": "TTWO", "rockstar games": "TTWO", "google": "GOOGL",
    "meta platforms": "META", "microsoft": "MSFT", "netflix": "NFLX", "spotify": "SPOT",
    "snap, inc": "SNAP", "snap inc": "SNAP", "pinterest": "PINS", "reddit": "RDDT",
    "duolingo": "DUOL", "tencent": "0700.HK", "shenzhen tencent": "0700.HK",
    "netease": "NTES", "alibaba": "BABA", "taobao": "BABA", "浙江淘宝": "BABA",
    "浙江阿里巴巴": "BABA", "jd.com": "JD", "beijing jingdong": "JD",
}


def chart_key(cc: str, genre: str, kind: str) -> str:
    return f"{cc}/{genre}/{kind}"


def chart_url(cc: str, genre: str, kind: str, limit: int = LIMIT) -> str:
    g = GENRES[genre]
    return FEED_URL.format(cc=cc, chart=CHARTS[kind], limit=limit,
                           genre=f"/genre={g}" if g else "")


def ticker_for(artist: str) -> str | None:
    a = (artist or "").strip().lower()
    for prefix, t in DEVELOPER_TICKERS.items():
        if a.startswith(prefix):
            return t
    return None


# ── parsers (pure) ──────────────────────────────────────────────────────────

def _label(x) -> str:
    return (x or {}).get("label", "") if isinstance(x, dict) else ""


def parse_feed(payload: dict) -> dict:
    """{"updated": str, "apps": [{rank, id, name, artist, bundle, category}]}."""
    feed = (payload or {}).get("feed")
    if not isinstance(feed, dict):
        raise ValueError("unexpected App Store feed payload")
    entries = feed.get("entry") or []
    if isinstance(entries, dict):              # a one-entry feed is not a list
        entries = [entries]
    apps = []
    for i, e in enumerate(entries, 1):
        attrs = ((e.get("id") or {}).get("attributes") or {})
        app_id = attrs.get("im:id")
        if not app_id:
            continue
        apps.append({"rank": i, "id": app_id, "name": _label(e.get("im:name")),
                     "artist": _label(e.get("im:artist")), "bundle": attrs.get("im:bundleId", ""),
                     "category": ((e.get("category") or {}).get("attributes") or {}).get("label", "")})
    return {"updated": _label(feed.get("updated")), "apps": apps}


def rank_changes(prev: list[dict], cur: list[dict], top: int = 25, n: int = 3) -> dict:
    """Entrants into the top `top`, and the biggest risers / fallers among apps ranked
    in both snapshots (moves within the first 2 * top ranks)."""
    p = {a["id"]: a["rank"] for a in prev}
    c = {a["id"]: a["rank"] for a in cur}
    names = {a["id"]: a for a in (*prev, *cur)}
    entrants = [dict(names[i], prev_rank=p.get(i)) for i, r in sorted(c.items(), key=lambda kv: kv[1])
                if r <= top and (i not in p or p[i] > top)]
    moves = [(p[i] - c[i], i) for i in c if i in p and p[i] != c[i]
             and min(p[i], c[i]) <= 2 * top]
    risers = [dict(names[i], prev_rank=p[i], move=m) for m, i in sorted(moves, reverse=True) if m > 0][:n]
    fallers = [dict(names[i], prev_rank=p[i], move=m) for m, i in sorted(moves) if m < 0][:n]
    dropped = [dict(names[i]) for i, r in sorted(p.items(), key=lambda kv: kv[1])
               if r <= top and i not in c]
    return {"entrants": entrants, "risers": risers, "fallers": fallers, "dropped": dropped}


def company_ranks(snapshot: dict) -> dict[str, list[dict]]:
    """ticker -> [{chart, rank, name}] across every chart in a snapshot."""
    out: dict[str, list[dict]] = {}
    for key, ch in (snapshot.get("charts") or {}).items():
        for a in ch.get("apps") or []:
            t = ticker_for(a.get("artist", ""))
            if t:
                out.setdefault(t, []).append({"chart": key, "rank": a["rank"], "name": a["name"],
                                              "id": a["id"]})
    for rows in out.values():
        rows.sort(key=lambda r: r["rank"])
    return out


# ── network ─────────────────────────────────────────────────────────────────

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                             headers={"User-Agent": "MarketMind/0.1 (research)",
                                      "Accept": "application/json"},
                             transport=_TRANSPORT)


async def fetch_snapshot(today: str | None = None, countries=COUNTRIES, genres=tuple(GENRES),
                         kinds=tuple(CHARTS)) -> dict:
    """Every chart now; a chart that fails is recorded as {"error": ...}, never dropped."""
    sem = asyncio.Semaphore(CONCURRENCY)
    keys = [(cc, g, k) for cc in countries for g in genres for k in kinds]

    async with _client() as client:
        async def one(cc, g, k):
            async with sem:
                try:
                    r = await client.get(chart_url(cc, g, k))
                    r.raise_for_status()
                    return parse_feed(r.json())
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning("App Store chart %s failed: %s", chart_key(cc, g, k), e)
                    return {"error": type(e).__name__}
        results = await asyncio.gather(*(one(*k) for k in keys))
    return {"date": today or date.today().isoformat(),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": SOURCE, "limit": LIMIT,
            "charts": {chart_key(*k): r for k, r in zip(keys, results)}}


def _ok_count(snapshot: dict) -> int:
    return sum(1 for c in (snapshot.get("charts") or {}).values() if "error" not in c)


# ── archive ─────────────────────────────────────────────────────────────────

def archive_path(day: str, data_dir: Path | None = None) -> Path:
    return altdata_dir("app_charts", data_dir) / f"{day}.json"


def archived_days(data_dir: Path | None = None) -> list[str]:
    folder = altdata_dir("app_charts", data_dir)
    days = []
    for p in folder.glob("*.json"):
        try:
            date.fromisoformat(p.stem)
            days.append(p.stem)
        except ValueError:
            continue
    return sorted(days)


def load_day(day: str, data_dir: Path | None = None) -> dict | None:
    try:
        return json.loads(archive_path(day, data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def archive_daily(today: str | None = None, data_dir: Path | None = None,
                        force: bool = False) -> dict:
    """Orchestration hook: archive today's App Store charts (idempotent per day).

    Skips when today's file already has every chart (unless `force`); otherwise
    refetches and replaces the file only if the new snapshot has at least as many
    good charts. Raises RuntimeError when no chart could be fetched (nothing written).
    Returns {"path", "day", "written", "skipped", "charts_ok", "charts_failed"}.
    """
    day = today or date.today().isoformat()
    path = archive_path(day, data_dir)
    existing = load_day(day, data_dir)
    total = len(COUNTRIES) * len(GENRES) * len(CHARTS)
    if existing and not force and _ok_count(existing) >= total:
        return {"path": str(path), "day": day, "written": False, "skipped": True,
                "charts_ok": _ok_count(existing), "charts_failed": 0}
    snap = await fetch_snapshot(day)
    ok = _ok_count(snap)
    if ok == 0:
        raise RuntimeError("App Store charts: every chart failed; nothing archived")
    written = force or existing is None or ok >= _ok_count(existing)
    if written:
        write_json_atomic(path, snap)
    return {"path": str(path), "day": day, "written": written, "skipped": False,
            "charts_ok": ok, "charts_failed": len(snap["charts"]) - ok}
