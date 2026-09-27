"""Attention / alternative data sources ("Group C") turned into a handful of NewsItems.

All three are free and key-free. Each fetcher emits only anomalies / top items, so a
normal run adds a few NewsItems at most (often zero):

- Wikipedia pageviews (Wikimedia REST): attention spikes on ~25 core assets / macro themes.
  Spike rule: latest day's views >= WIKI_SPIKE_RATIO (3.0x) the median of the trailing
  28 days AND >= WIKI_MIN_SPIKE_VIEWS (1,000) absolute views. At most WIKI_MAX_ITEMS items.
- GDELT 2.0 raw event exports (15-minute CSV zips, NOT the rate-limited DOC API): the last
  GDELT_FILES files (~1 hour) are streamed row by row and only high-impact conflict /
  coercion / sanctions events are kept, aggregated by (country, CAMEO root). Top GDELT_MAX_ITEMS.
- IMF PortWatch daily chokepoint transits (ArcGIS FeatureServer): per key chokepoint, the
  latest 7-day average of daily transits vs the trailing 90-day average before it. Item only
  when |deviation| >= PORTWATCH_DEVIATION (20%); prior-year same-window average is reported
  as context but does not trigger (structural YoY shifts, e.g. Red Sea diversions, would fire
  every run).

Fetchers raise on non-200 (resp.raise_for_status) so scout.fetch_source() applies its usual
failure tracking. Google Trends "trending now" is plain RSS and needs no fetcher here.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import statistics
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

import httpx

logger = logging.getLogger("marketmind.pipeline.sources_alternative")

HTTP_TIMEOUT = 30.0
# Wikimedia requires a descriptive User-Agent with contact info.
_UA = "MarketMind/0.1 (personal research; contact@marketmind.dev)"
_HEADERS = {"User-Agent": _UA}

# ── Wikipedia pageviews ─────────────────────────────────────────────────────
WIKI_PAGEVIEWS_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
    "{article}/daily/{start}/{end}"
)
WIKI_SPIKE_RATIO = 3.0        # latest day / trailing-28-day median
WIKI_MIN_SPIKE_VIEWS = 1000   # absolute floor so tiny articles don't fire on noise
WIKI_TRAILING_DAYS = 28
WIKI_MIN_HISTORY = 14         # need at least this many trailing days for a median
WIKI_MAX_ITEMS = 5
WIKI_REQUEST_DELAY = 0.1      # seconds between sequential requests (be polite)

# label -> canonical en.wikipedia title. The pageviews API does not follow redirects, so
# titles must be canonical (all verified 200 on 2026-09-27). Labels are universe tickers
# (config/asset_universe.py) or macro attention themes.
WIKI_ARTICLES: dict[str, str] = {
    "SPY": "S&P_500",
    "QQQ": "Nasdaq-100",
    "IWM": "Russell_2000_Index",
    "DIA": "Dow_Jones_Industrial_Average",
    "TLT": "United_States_Treasury_security",
    "GLD": "Gold",
    "SLV": "Silver",
    "USO": "Petroleum",
    "UNG": "Natural_gas",
    "EEM": "Emerging_market",
    "AAPL": "Apple_Inc.",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "GOOGL": "Alphabet_Inc.",
    "AMZN": "Amazon_(company)",
    "META": "Meta_Platforms",
    "TSLA": "Tesla,_Inc.",
    "JPM": "JPMorgan_Chase",
    "XOM": "ExxonMobil",
    "BTC-USD": "Bitcoin",
    "ETH": "Ethereum",
    "FED": "Federal_Reserve",
    "RECESSION": "Recession",
    "INFLATION": "Inflation",
    "TARIFF": "Tariff",
    "CRASH": "Stock_market_crash",
}

# ── GDELT 2.0 raw exports ───────────────────────────────────────────────────
GDELT_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_EXPORT_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
GDELT_FILES = 4                   # latest 4 x 15 min = ~1 hour of events
GDELT_MAX_ZIP_BYTES = 20_000_000  # safety cap per file (real files are ~30-300 KB)
GDELT_GOLDSTEIN_MAX = -7.0        # keep events at or below this Goldstein score ...
GDELT_MIN_MENTIONS = 10           # ... or with at least this many mentions (in roots 14-20)
GDELT_MIN_CLUSTER_MENTIONS = 10   # drop clusters whose total mentions stay below this
GDELT_MAX_ITEMS = 5
_GDELT_HIGH_IMPACT_ROOTS = {"14", "15", "16", "17", "18", "19", "20"}
# Sanctions / embargo / aid-cut codes kept regardless of Goldstein or mentions:
# 163 impose embargo/boycott/sanctions, 1621 reduce/stop economic assistance,
# 1312 threaten to boycott/embargo/sanction.
_GDELT_ECON_CODES = ("163", "1621", "1312")
_CAMEO_ROOT_LABELS = {
    "13": "Sanctions threat",
    "14": "Protest", "15": "Military posture", "16": "Reduced relations / sanctions",
    "17": "Coercion", "18": "Assault", "19": "Armed fighting", "20": "Mass violence",
}
# Column indices of the 61-column GDELT 2.0 event export (verified 2026-09-27).
_G_EVENTCODE, _G_ROOT, _G_GOLDSTEIN, _G_MENTIONS = 26, 28, 30, 31
_G_SOURCES, _G_TONE, _G_GEO_NAME, _G_GEO_CC, _G_URL = 32, 34, 52, 53, 60
_G_ACTOR1, _G_ACTOR2 = 6, 16
_G_ACTOR1_CC, _G_ACTOR2_CC, _G_ACTOR1_TYPE, _G_ACTOR2_TYPE = 7, 17, 12, 22
_G_NCOLS = 61
# Market relevance filter: conflict-root events must be international (two different actor
# countries) or involve a state / armed actor; drops domestic crime ("POLICE vs SUSPECT").
_GDELT_STATE_TYPES = {"GOV", "MIL", "REB", "INS", "SEP", "UAF", "SPY"}

# ── IMF PortWatch chokepoints ───────────────────────────────────────────────
PORTWATCH_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
PORTWATCH_PAGE = "https://portwatch.imf.org/pages/chokepoints"
# portid -> display name (from the live service's distinct values, 2026-09-27).
PORTWATCH_CHOKEPOINTS: dict[str, str] = {
    "chokepoint6": "Strait of Hormuz",
    "chokepoint1": "Suez Canal",
    "chokepoint4": "Bab el-Mandeb Strait",
    "chokepoint2": "Panama Canal",
    "chokepoint5": "Malacca Strait",
    "chokepoint3": "Bosporus Strait",
    "chokepoint7": "Cape of Good Hope",
    "chokepoint11": "Taiwan Strait",
}
PORTWATCH_DEVIATION = 0.20    # |7d avg / 90d avg - 1| threshold
PORTWATCH_RECENT_DAYS = 7
PORTWATCH_BASELINE_DAYS = 90
PORTWATCH_MIN_RECENT = 5      # days of data needed in the recent window
PORTWATCH_MIN_BASELINE = 60   # days of data needed in the baseline window
PORTWATCH_MIN_BASE_AVG = 3.0  # ignore chokepoints with < 3 transits/day on average
PORTWATCH_LOOKBACK_DAYS = 130  # query window; data lags ~1 week, so this covers 7 + 90 days
PORTWATCH_MAX_RECORDS = 2000


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


def _make_item(source: Any, key: str, title: str, url: str, published: str, summary: str,
               default_rel: float) -> Any:
    from marketmind.pipeline.scout import NewsItem

    return NewsItem(
        id=hashlib.sha256(key.encode()).hexdigest()[:16],
        title=title,
        url=url,
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=published,
        summary=summary[:500],
        source_reliability=_reliability(source, default_rel),
    )


# ═══ Wikipedia pageviews ════════════════════════════════════════════════════

def detect_pageview_spike(views: list[tuple[str, int]]) -> dict | None:
    """Spike check on a chronological [(yyyymmdd, views), ...] series.

    Latest point vs median of up to WIKI_TRAILING_DAYS preceding points. None if no spike.
    """
    if len(views) < WIKI_MIN_HISTORY + 1:
        return None
    latest_day, latest = views[-1]
    trailing = [v for _, v in views[-(WIKI_TRAILING_DAYS + 1):-1]]
    median = statistics.median(trailing)
    if latest < WIKI_MIN_SPIKE_VIEWS:
        return None
    ratio = latest / median if median > 0 else float("inf")
    if ratio < WIKI_SPIKE_RATIO:
        return None
    return {"day": latest_day, "views": int(latest), "median": float(median), "ratio": ratio}


def wiki_spike_to_newsitem(label: str, article: str, spike: dict, source: Any) -> Any:
    day = spike["day"][:8]
    iso_day = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    name = article.replace("_", " ")
    ratio_txt = f"{spike['ratio']:.1f}x" if spike["ratio"] != float("inf") else "new"
    title = (f"Wikipedia attention spike: '{name}' ({label}) {spike['views']:,} views on {iso_day}, "
             f"{ratio_txt} its 28-day median")
    summary = (f"en.wikipedia user pageviews for '{name}' reached {spike['views']:,} on {iso_day} vs a "
               f"trailing 28-day median of {spike['median']:,.0f} (threshold {WIKI_SPIKE_RATIO:g}x). "
               f"Retail/public attention proxy; check the news driving the spike.")
    url = f"https://pageviews.wmcloud.org/?project=en.wikipedia.org&platform=all-access&agent=user&range=latest-30&pages={quote(article, safe='')}"
    return _make_item(source, f"wiki_spike:{article}:{day}", title, url, iso_day, summary, 0.6)


async def fetch_wikipedia_attention(source: Any, config: Any = None) -> list[Any]:
    """Pageview spikes across WIKI_ARTICLES (sequential requests, small delay).

    A 404 for one article is logged and skipped (renamed title); any other non-200
    (429, 5xx) raises immediately. Raises if no article could be fetched at all.
    """
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=WIKI_TRAILING_DAYS + 2)
    spikes: list[tuple[str, str, dict]] = []
    ok = 0
    first_error: Exception | None = None
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        for i, (label, article) in enumerate(WIKI_ARTICLES.items()):
            if i and WIKI_REQUEST_DELAY:
                await asyncio.sleep(WIKI_REQUEST_DELAY)
            url = WIKI_PAGEVIEWS_URL.format(article=quote(article, safe=""),
                                            start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 404:
                logger.warning("Wikipedia pageviews 404 for %s (%s); title renamed?", article, label)
                first_error = first_error or httpx.HTTPStatusError(
                    f"404 for {article}", request=getattr(resp, "request", None), response=resp)
                continue
            resp.raise_for_status()
            ok += 1
            items = resp.json().get("items", [])
            series = [(str(it.get("timestamp", "")), int(it.get("views", 0))) for it in items]
            spike = detect_pageview_spike(series)
            if spike:
                spikes.append((label, article, spike))
    if ok == 0:
        raise first_error or RuntimeError("Wikipedia pageviews: no article fetched")
    spikes.sort(key=lambda s: s[2]["ratio"], reverse=True)
    return [wiki_spike_to_newsitem(l, a, s, source) for l, a, s in spikes[:WIKI_MAX_ITEMS]]


# ═══ GDELT 2.0 ══════════════════════════════════════════════════════════════

def _is_high_impact(row: list[str]) -> bool:
    code = row[_G_EVENTCODE]
    if code.startswith(_GDELT_ECON_CODES):
        return True
    if row[_G_ROOT] not in _GDELT_HIGH_IMPACT_ROOTS:
        return False
    try:
        goldstein = float(row[_G_GOLDSTEIN])
        mentions = int(row[_G_MENTIONS])
    except ValueError:
        return False
    if not (goldstein <= GDELT_GOLDSTEIN_MAX or mentions >= GDELT_MIN_MENTIONS):
        return False
    a1, a2 = row[_G_ACTOR1_CC], row[_G_ACTOR2_CC]
    international = bool(a1 and a2 and a1 != a2)
    state_actor = bool({row[_G_ACTOR1_TYPE], row[_G_ACTOR2_TYPE]} & _GDELT_STATE_TYPES)
    return international or state_actor


@dataclass
class GdeltCluster:
    country_code: str
    root: str
    country_name: str = ""
    events: int = 0
    mentions: int = 0
    sources: int = 0
    min_goldstein: float = 10.0
    tone_sum: float = 0.0
    top_url: str = ""
    top_mentions: int = -1
    top_actors: str = ""


def aggregate_gdelt_rows(rows: Iterable[list[str]],
                         clusters: dict[tuple[str, str], GdeltCluster] | None = None,
                         seen_urls: set[str] | None = None) -> dict[tuple[str, str], GdeltCluster]:
    """Fold high-impact event rows into per-(ActionGeo country, CAMEO root) clusters.

    Memory is bounded by the number of distinct (country, root) pairs, not by row count.
    Rows sharing a SOURCEURL with an already-counted row in the same cluster are skipped
    so one article coded into many events does not dominate.
    """
    clusters = {} if clusters is None else clusters
    seen_urls = set() if seen_urls is None else seen_urls
    for row in rows:
        if len(row) < _G_NCOLS or not _is_high_impact(row):
            continue
        cc = row[_G_GEO_CC] or "XX"
        root = row[_G_ROOT] if row[_G_ROOT] in _CAMEO_ROOT_LABELS else "16"  # 1621 etc.
        url = row[_G_URL]
        dedup_key = f"{cc}|{root}|{url}"
        if url and dedup_key in seen_urls:
            continue
        if url and len(seen_urls) < 50_000:
            seen_urls.add(dedup_key)
        try:
            mentions = int(row[_G_MENTIONS])
            n_sources = int(row[_G_SOURCES])
            goldstein = float(row[_G_GOLDSTEIN])
            tone = float(row[_G_TONE])
        except ValueError:
            continue
        c = clusters.get((cc, root))
        if c is None:
            c = clusters[(cc, root)] = GdeltCluster(country_code=cc, root=root)
        c.events += 1
        c.mentions += mentions
        c.sources += n_sources
        c.min_goldstein = min(c.min_goldstein, goldstein)
        c.tone_sum += tone
        if mentions > c.top_mentions:
            c.top_mentions = mentions
            c.top_url = url
            c.country_name = (row[_G_GEO_NAME].split(",")[-1].strip() or cc)
            actors = [a for a in (row[_G_ACTOR1], row[_G_ACTOR2]) if a]
            c.top_actors = " vs ".join(actors)
    return clusters


def top_gdelt_clusters(clusters: dict[tuple[str, str], GdeltCluster],
                       limit: int = GDELT_MAX_ITEMS) -> list[GdeltCluster]:
    ranked = [c for c in clusters.values() if c.mentions >= GDELT_MIN_CLUSTER_MENTIONS]
    # Weight by severity: a -10 Goldstein cluster outranks a same-size -5 cluster.
    ranked.sort(key=lambda c: c.mentions * (1 + max(0.0, -c.min_goldstein) / 10), reverse=True)
    return ranked[:limit]


def gdelt_cluster_to_newsitem(c: GdeltCluster, window_label: str, source: Any) -> Any:
    label = _CAMEO_ROOT_LABELS.get(c.root, c.root)
    where = "unlocated" if c.country_code == "XX" else (c.country_name or c.country_code)
    actors = f" ({c.top_actors})" if c.top_actors else ""
    title = (f"GDELT: {label} in {where}{actors}: {c.events} events, {c.mentions} mentions "
             f"(min Goldstein {c.min_goldstein:g})")
    summary = (f"GDELT 2.0 event cluster, CAMEO root {c.root} ({label}), ActionGeo country "
               f"{c.country_code}, window {window_label}. {c.events} high-impact events, "
               f"{c.mentions} mentions across {c.sources} sources, avg tone "
               f"{c.tone_sum / max(c.events, 1):.1f}. Top source article linked.")
    return _make_item(source, f"gdelt:{window_label}:{c.country_code}:{c.root}", title,
                      c.top_url or "https://www.gdeltproject.org/", window_label, summary, 0.5)


def iter_export_rows(zip_bytes: bytes) -> Iterable[list[str]]:
    """Stream rows of a GDELT export zip without materialising the CSV."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def parse_lastupdate(text: str) -> str:
    """Return the YYYYMMDDHHMMSS stamp of the latest export file listed in lastupdate.txt."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
            return parts[2].rsplit("/", 1)[-1].split(".", 1)[0]
    raise ValueError("GDELT lastupdate.txt: no export file listed")


def _previous_stamps(latest: str, n: int) -> list[str]:
    t = datetime.strptime(latest, "%Y%m%d%H%M%S")
    return [(t - timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(n)]


async def fetch_gdelt_events(source: Any, config: Any = None) -> list[Any]:
    """Top high-impact GDELT event clusters over the latest ~hour of 15-minute exports.

    Raises on non-200 for lastupdate.txt and the newest export; an older export that is
    missing (404) is skipped since GDELT occasionally drops a slot.
    """
    clusters: dict[tuple[str, str], GdeltCluster] = {}
    seen: set[str] = set()
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(GDELT_LASTUPDATE_URL, headers=_HEADERS)
        resp.raise_for_status()
        latest = parse_lastupdate(resp.text)
        stamps = _previous_stamps(latest, GDELT_FILES)
        for i, stamp in enumerate(stamps):
            r = await client.get(GDELT_EXPORT_URL.format(stamp=stamp), headers=_HEADERS)
            if i > 0 and r.status_code == 404:
                logger.info("GDELT export %s missing; skipped", stamp)
                continue
            r.raise_for_status()
            if len(r.content) > GDELT_MAX_ZIP_BYTES:
                raise ValueError(f"GDELT export {stamp} too large ({len(r.content)} bytes)")
            aggregate_gdelt_rows(iter_export_rows(r.content), clusters, seen)
    t_end = datetime.strptime(latest, "%Y%m%d%H%M%S") + timedelta(minutes=15)
    t_start = t_end - timedelta(minutes=15 * GDELT_FILES)
    window = f"{t_start:%Y-%m-%d %H:%M}-{t_end:%H:%M} UTC"
    return [gdelt_cluster_to_newsitem(c, window, source) for c in top_gdelt_clusters(clusters)]


# ═══ IMF PortWatch ══════════════════════════════════════════════════════════

def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def chokepoint_deviations(records: list[dict], prior_year: list[dict] | None = None) -> list[dict]:
    """Per chokepoint: latest 7-day avg daily transits vs the preceding 90-day avg.

    records / prior_year: dicts with 'portid', 'date' (YYYY-MM-DD) and 'n_total'.
    Returns every chokepoint with enough data (flag=True when |deviation| >= threshold),
    sorted by |deviation| descending.
    """
    by_port: dict[str, dict[date, float]] = {}
    for r in records:
        try:
            d = date.fromisoformat(str(r["date"])[:10])
            by_port.setdefault(str(r["portid"]), {})[d] = float(r["n_total"])
        except (KeyError, TypeError, ValueError):
            continue
    prior: dict[str, list[float]] = {}
    out = []
    for port, series in by_port.items():
        latest = max(series)
        recent_start = latest - timedelta(days=PORTWATCH_RECENT_DAYS - 1)
        base_start = recent_start - timedelta(days=PORTWATCH_BASELINE_DAYS)
        recent = [v for d, v in series.items() if d >= recent_start]
        base = [v for d, v in series.items() if base_start <= d < recent_start]
        if len(recent) < PORTWATCH_MIN_RECENT or len(base) < PORTWATCH_MIN_BASELINE:
            continue
        r_avg, b_avg = _mean(recent), _mean(base)
        if b_avg is None or b_avg < PORTWATCH_MIN_BASE_AVG:
            continue
        dev = r_avg / b_avg - 1
        yoy = None
        if prior_year:
            py_start = recent_start - timedelta(days=364)
            py_end = latest - timedelta(days=364)
            vals = []
            for pr in prior_year:
                try:
                    if str(pr["portid"]) != port:
                        continue
                    d = date.fromisoformat(str(pr["date"])[:10])
                    if py_start <= d <= py_end:
                        vals.append(float(pr["n_total"]))
                except (KeyError, TypeError, ValueError):
                    continue
            py_avg = _mean(vals)
            if py_avg:
                yoy = r_avg / py_avg - 1
        out.append({"portid": port, "latest": latest, "recent_avg": r_avg, "base_avg": b_avg,
                    "deviation": dev, "yoy": yoy, "flag": abs(dev) >= PORTWATCH_DEVIATION - 1e-9})
    out.sort(key=lambda x: abs(x["deviation"]), reverse=True)
    return out


def chokepoint_to_newsitem(dev: dict, source: Any) -> Any:
    name = PORTWATCH_CHOKEPOINTS.get(dev["portid"], dev["portid"])
    direction = "up" if dev["deviation"] > 0 else "down"
    pct = abs(dev["deviation"]) * 100
    latest = dev["latest"].isoformat()
    title = (f"{name} transits {direction} {pct:.0f}% vs 90-day avg: {dev['recent_avg']:.1f}/day "
             f"(7 days to {latest}) vs {dev['base_avg']:.1f}/day")
    yoy = f"; vs same week last year {dev['yoy'] * 100:+.0f}%" if dev.get("yoy") is not None else ""
    summary = (f"IMF PortWatch daily vessel transits (all ship types) through {name}: 7-day average "
               f"{dev['recent_avg']:.1f}/day to {latest} vs trailing 90-day average "
               f"{dev['base_avg']:.1f}/day ({dev['deviation'] * 100:+.0f}%, threshold "
               f"±{PORTWATCH_DEVIATION * 100:.0f}%){yoy}. AIS-based; data lags about a week.")
    return _make_item(source, f"portwatch:{dev['portid']}:{latest}", title, PORTWATCH_PAGE,
                      latest, summary, 0.85)


async def _portwatch_query(client: httpx.AsyncClient, where: str) -> list[dict]:
    params = {"where": where, "outFields": "date,portid,n_total", "returnGeometry": "false",
              "orderByFields": "date ASC", "resultRecordCount": str(PORTWATCH_MAX_RECORDS), "f": "json"}
    resp = await client.get(PORTWATCH_URL, params=params, headers=_HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:  # ArcGIS reports query errors with HTTP 200
        raise ValueError(f"PortWatch query error: {data['error']}")
    return [f.get("attributes", {}) for f in data.get("features", [])]


async def fetch_portwatch_chokepoints(source: Any, config: Any = None) -> list[Any]:
    """NewsItems only for key chokepoints whose 7-day transits deviate >= 20% from the 90-day avg."""
    ports = ",".join(f"'{p}'" for p in PORTWATCH_CHOKEPOINTS)
    since = datetime.now(timezone.utc).date() - timedelta(days=PORTWATCH_LOOKBACK_DAYS)
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        records = await _portwatch_query(client, f"portid IN ({ports}) AND date >= DATE '{since}'")
        if not records:
            return []
        latest = max(date.fromisoformat(str(r["date"])[:10]) for r in records if r.get("date"))
        py_end = latest - timedelta(days=364)
        py_start = py_end - timedelta(days=PORTWATCH_RECENT_DAYS - 1)
        prior = await _portwatch_query(
            client, f"portid IN ({ports}) AND date >= DATE '{py_start}' AND date <= DATE '{py_end}'")
    return [chokepoint_to_newsitem(d, source) for d in chokepoint_deviations(records, prior) if d["flag"]]
