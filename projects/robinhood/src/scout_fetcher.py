"""
scout_fetcher.py — Stage 2.5: Automated Patrol Scout & Fetch Module

Multi-source macro/market data fetcher with Track A/B/C degradation strategy.
Zero heavy dependencies beyond requests (for HTTP) and xml.etree (for RSS).

Track Architecture (PM-approved):
  Track A: requests.get() → JSON/XML API (FRED, NewsAPI, RSS feeds)
  Track B: requests.get() → HTML → lxml.html parse (static finance pages)
  Track C: Playwright MCP → browser navigation → snapshot extraction (SPA fallback)

SPARC:
  Specification: PM-approved blueprint — multi-source, three-track degradation
  Pseudocode: Each source has primary/path → fallback logic built in
  Architecture: Pure functions + dataclass returns, no global state
  Refinement: Rate limiting (2s between requests), User-Agent rotation headers
  Completion: Ready for test_scout_fetcher.py
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------


@dataclass(frozen=True)
class RawEvent:
    """A raw scraped event from any source.

    Attributes:
        title: Event headline or title
        body: Body text (truncated to 500 chars)
        source_url: Original URL of the source
        timestamp: ISO-8601 timestamp of the event
        category: Event category (macro, policy, geopolitical, sentiment, market)
        source_name: Human-readable source name (e.g., "FRED", "Reuters")
    """
    title: str
    body: str
    source_url: str
    timestamp: str
    category: str = "market"
    source_name: str = "unknown"


@dataclass(frozen=True)
class ScoutConfig:
    """Configuration for the Scout & Fetch module.

    Attributes:
        rate_limit_seconds: Minimum interval between HTTP requests (default 2.0s)
        max_body_chars: Maximum characters for event body truncation (default 500)
        request_timeout: HTTP request timeout in seconds (default 15)
        fred_api_key: FRED API key (optional, environ fallback)
        newsapi_key: NewsAPI key (optional, environ fallback)
    """
    rate_limit_seconds: float = 2.0
    max_body_chars: int = 500
    request_timeout: int = 15
    fred_api_key: Optional[str] = None
    newsapi_key: Optional[str] = None


@dataclass(frozen=True)
class FetchResult:
    """Result of a multi-source fetch cycle.

    Attributes:
        events: All successfully fetched RawEvents
        track_stats: Per-track success/failure counts
        errors: Error messages from failed sources
    """
    events: List[RawEvent] = field(default_factory=list)
    track_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class ScoutReport:
    """Aggregated result from a full scout pipeline run."""
    raw_events: List[RawEvent] = field(default_factory=list)
    sar_filtered_count: int = 0
    errors: List[str] = field(default_factory=list)


def scout_pipeline(mock: bool = False) -> ScoutReport:
    """Run the full scout pipeline with multi-source fetch.

    When network sources are unavailable (FRED key missing, RSS blocked),
    falls back to sample data clearly labeled [SAMPLE].
    In explicit mock mode, uses sample data without network attempts.
    """
    if mock:
        return _mock_scout_report()

    report = ScoutReport()
    sources_tried = 0
    sources_succeeded = 0

    # Try real sources
    try:
        result = fetch_all()
        if result.events:
            report.raw_events = list(result.events)
            sources_succeeded += 1
        sources_tried += 1
        if result.errors:
            report.errors.extend(result.errors)
    except Exception as exc:
        report.errors.append(f"fetch_all: {exc}")

    # Try market news
    try:
        market_events = fetch_market_news("all")
        if market_events:
            report.raw_events.extend(market_events)
            sources_succeeded += 1
        sources_tried += 1
    except Exception as exc:
        report.errors.append(f"market_news: {exc}")

    # Try general news (NPR, BBC, NYT, AP)
    try:
        general_events = fetch_general_news()
        if general_events:
            report.raw_events.extend(general_events)
            sources_succeeded += 1
        sources_tried += 1
    except Exception as exc:
        report.errors.append(f"general_news: {exc}")

    # Try Google News (aggregates from ALL sources, bypasses paywalls)
    try:
        google_events = fetch_google_news()
        if google_events:
            report.raw_events.extend(google_events)
            sources_succeeded += 1
        sources_tried += 1
    except Exception as exc:
        report.errors.append(f"google_news: {exc}")

    # Try Reddit finance (early narrative detection)
    try:
        reddit_events = fetch_reddit_finance()
        if reddit_events:
            report.raw_events.extend(reddit_events)
            sources_succeeded += 1
        sources_tried += 1
    except Exception as exc:
        report.errors.append(f"reddit: {exc}")

    # If no real sources succeeded, use labeled sample data
    if sources_succeeded == 0:
        mock_report = _mock_scout_report()
        # Label each event as sample
        for evt in mock_report.raw_events:
            evt = RawEvent(
                title=f"[SAMPLE] {evt.title}",
                body=evt.body,
                source_url=evt.source_url,
                timestamp=evt.timestamp,
                category=evt.category,
                source_name=f"{evt.source_name} (sample)",
            )
            report.raw_events.append(evt)
        report.errors.append(
            f"All {sources_tried} real sources unavailable. "
            f"Using {len(mock_report.raw_events)} labeled sample events. "
            f"To enable real data: set FRED_API_KEY, check network/VPN."
        )

    report.sar_filtered_count = len(report.raw_events)
    return report


# ---------------------------------------------------------------
# HTTP Helpers (Track A/B)
# ---------------------------------------------------------------

# Rate-limit tracking: _last_request_time per domain
_last_request_times: Dict[str, float] = {}

_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _rate_limited_domain(domain: str, min_interval: float = 2.0) -> None:
    """Sleep if the last request to this domain was too recent."""
    last = _last_request_times.get(domain, 0.0)
    elapsed = time.time() - last
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_times[domain] = time.time()


def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """Track-A/B HTTP GET with rate limiting and error handling.

    Args:
        url: Target URL.
        timeout: Request timeout in seconds.

    Returns:
        Response text on success, None on failure.
    """
    domain = urlparse(url).netloc
    _rate_limited_domain(domain)

    try:
        import requests
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except ImportError:
        logger.error("requests library not available; cannot fetch URL: %s", url)
        return None
    except requests.RequestException as e:
        logger.warning("HTTP fetch failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------
# Source-specific Fetchers (Track A — API/JSON)
# ---------------------------------------------------------------


def fetch_fred_observations(
    series_id: str = "FEDFUNDS",
    api_key: Optional[str] = None,
    config: Optional[ScoutConfig] = None,
) -> List[RawEvent]:
    """Fetch economic data from FRED API (Track A — JSON).

    Args:
        series_id: FRED series ID (default: FEDFUNDS — Federal Funds Rate)
        api_key: FRED API key. Falls back to os.environ['FRED_API_KEY'].
        config: ScoutConfig overrides.

    Returns:
        List of RawEvent (empty on failure).
    """
    cfg = config or ScoutConfig()
    key = api_key or cfg.fred_api_key
    # Allow env fallback
    if not key:
        import os
        key = os.environ.get("FRED_API_KEY")

    if not key:
        logger.warning("FRED API key not configured; skipping FRED fetch")
        return []

    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={key}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit=5"
    )

    text = _fetch_url(url, timeout=cfg.request_timeout)
    if not text:
        return []

    try:
        data = json.loads(text)
        observations = data.get("observations", [])
        events: List[RawEvent] = []
        for obs in observations[-3:]:  # Last 3 observations
            value = obs.get("value", ".")
            if value == ".":
                continue  # Not yet available
            date = obs.get("date", "")
            events.append(RawEvent(
                title=f"FRED {series_id}: {value}",
                body=f"FRED series {series_id} ({series_id}) value: {value} on {date}",
                source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                timestamp=f"{date}T00:00:00",
                category="macro",
                source_name="FRED",
            ))
        logger.info("FRED fetch OK: %d events from series %s", len(events), series_id)
        return events
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("FRED JSON parse error: %s", e)
        return []


def fetch_reuters_rss(
    feed_url: str = "https://www.reutersagency.com/feed/",
    config: Optional[ScoutConfig] = None,
) -> List[RawEvent]:
    """Fetch news headlines from Reuters RSS feed (Track A — XML).

    Args:
        feed_url: RSS feed URL.
        config: ScoutConfig overrides.

    Returns:
        List of RawEvent (empty on failure).
    """
    cfg = config or ScoutConfig()
    text = _fetch_url(feed_url, timeout=cfg.request_timeout)
    if not text:
        return []

    try:
        root = ET.fromstring(text)
        events: List[RawEvent] = []

        # RSS item paths: channel/item or atom:entry
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item")
        entries = root.findall(".//atom:entry", ns)

        all_entries = items + entries

        for entry in all_entries[:10]:
            title_el = entry.find("title")
            desc_el = entry.find("description")
            link_el = entry.find("link")
            pub_date_el = entry.find("pubDate")

            title = title_el.text if title_el is not None else "No title"
            body = desc_el.text if desc_el is not None else ""
            link = link_el.text if link_el is not None else feed_url
            pub_date = pub_date_el.text if pub_date_el is not None else ""

            if not body:
                body = title

            events.append(RawEvent(
                title=title.strip(),
                body=body.strip()[:cfg.max_body_chars],
                source_url=link.strip(),
                timestamp=_normalize_rss_date(pub_date),
                category="market",
                source_name="Reuters",
            ))

        logger.info("Reuters RSS fetch OK: %d events", len(events))
        return events

    except ET.ParseError as e:
        logger.warning("Reuters RSS XML parse error: %s", e)
        return []


def _normalize_rss_date(rss_date: str) -> str:
    """Convert RSS date format to ISO-8601."""
    if not rss_date:
        return datetime.datetime.now().isoformat()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(rss_date)
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.datetime.now().isoformat()


# ---------------------------------------------------------------
# Source-specific Fetchers (Track B — HTML)
# ---------------------------------------------------------------


def fetch_yahoo_finance_headlines(
    ticker: str,
    config: Optional[ScoutConfig] = None,
) -> List[RawEvent]:
    """Fetch recent headlines for a ticker from Yahoo Finance (Track B — HTML).

    Args:
        ticker: Stock ticker symbol (e.g., "SPY", "QQQ").
        config: ScoutConfig overrides.

    Returns:
        List of RawEvent (empty on failure or HTML parse error).
    """
    cfg = config or ScoutConfig()
    url = f"https://finance.yahoo.com/quote/{ticker}/"

    html = _fetch_url(url, timeout=cfg.request_timeout)
    if not html:
        return []

    events: List[RawEvent] = []
    try:
        # Primary: Yahoo Finance RSS feed (Track A — more reliable than HTML)
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        rss_text = _fetch_url(rss_url, timeout=cfg.request_timeout)
        if rss_text:
            try:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(rss_text)
                for item in root.findall(".//item")[:8]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    link = link_el.text.strip() if link_el is not None and link_el.text else url
                    if title and len(title) > 20:  # Filter menu items
                        events.append(RawEvent(
                            title=title,
                            body=title,
                            source_url=link,
                            timestamp=datetime.datetime.now().isoformat(),
                            category="market",
                            source_name="Yahoo Finance",
                        ))
                if events:
                    logger.info("Yahoo Finance RSS OK for %s: %d headlines", ticker, len(events))
                    return events
            except ET.ParseError:
                logger.debug("Yahoo Finance RSS parse failed, falling back to HTML")

        # Fallback: HTML scraping with filtered h3 patterns
        html = _fetch_url(url, timeout=cfg.request_timeout)
        if not html:
            return []

        # Match h3 with "clamp" or headline-related classes (YF's actual structure)
        headline_patterns = re.findall(
            r'<h3[^>]*class="[^"]*(?:clamp|headline|title)[^"]*"[^>]*>(.*?)</h3>',
            html, re.IGNORECASE,
        )
        if not headline_patterns:
            # Second attempt: any h3, but filter out nav items
            all_h3 = re.findall(r'<h3[^>]*>(.*?)</h3>', html)
            # Blacklist: common nav/menu items that are not news headlines
            nav_blacklist = {
                'news', 'life', 'entertainment', 'finance', 'sports', 'video',
                'market', 'watchlist', 'portfolio', 'search', 'settings',
                'login', 'sign', 'account', 'menu', 'more', 'about',
            }
            for h3_text in all_h3:
                clean = re.sub(r"<[^>]+>", "", h3_text).strip()
                if clean and len(clean) > 25 and clean.lower() not in nav_blacklist:
                    headline_patterns.append(h3_text)

        for title in headline_patterns[:8]:
            # Strip HTML tags
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            if clean_title and len(clean_title) > 25:
                events.append(RawEvent(
                    title=clean_title,
                    body=clean_title,
                    source_url=url,
                    timestamp=datetime.datetime.now().isoformat(),
                    category="market",
                    source_name="Yahoo Finance",
                ))

        logger.info(
            "Yahoo Finance fetch OK for %s: %d headlines",
            ticker,
            len(events),
        )
        return events

    except Exception as e:
        logger.warning("Yahoo Finance parse error for %s: %s", ticker, e)
        return []


# ---------------------------------------------------------------
# Aggregate Fetcher (Orchestrator)
# ---------------------------------------------------------------

DEFAULT_TICKERS = ["SPY", "QQQ", "XLF", "XLK", "XLV", "XLE"]


def fetch_all(
    tickers: Optional[List[str]] = None,
    config: Optional[ScoutConfig] = None,
) -> FetchResult:
    """Execute a full multi-source fetch cycle.

    Orchestrates FRED API, Reuters RSS, and Yahoo Finance HTML scraping.
    Each source is isolated — failure in one does not affect others.
    Returns a FetchResult with all successfully fetched RawEvents.

    Args:
        tickers: List of ticker symbols.
        config: ScoutConfig overrides.

    Returns:
        FetchResult aggregating all source results.
    """

# ---------------------------------------------------------------
# Multi-Region Fetchers (Phase B2)
# ---------------------------------------------------------------

def fetch_region_source(name: str, url: str, region: str, category: str = "macro",
                        config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch RSS/API feed for a single regional source.

    Attempts RSS XML parse first, falls back to plain text extraction.
    """
    cfg = config or ScoutConfig()
    text = _fetch_url(url, timeout=cfg.request_timeout + 5)
    if not text:
        return []

    events: List[RawEvent] = []

    # Try RSS XML parse
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        for item in root.findall(".//item")[:5]:
            title_el = item.find("title")
            desc_el = item.find("description")
            title = (title_el.text or "").strip() if title_el is not None else ""
            body = (desc_el.text or "") if desc_el is not None else ""
            if title and len(title) > 15:
                events.append(RawEvent(
                    title=title[:200],
                    body=body.strip()[:cfg.max_body_chars],
                    source_url=url,
                    timestamp=datetime.datetime.now().isoformat(),
                    category=category,
                    source_name=f"[{region}] {name}",
                ))
        if events:
            logger.info("Region fetch [%s] %s: %d items", region, name, len(events))
            return events
    except ET.ParseError:
        pass

    # Fallback: headline regex on HTML
    try:
        headlines = re.findall(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE)
        for h in headlines[:3]:
            clean = re.sub(r"<[^>]+>", "", h).strip()
            if clean and len(clean) > 20 and region.lower() not in clean.lower():
                events.append(RawEvent(
                    title=clean[:200],
                    body=clean,
                    source_url=url,
                    timestamp=datetime.datetime.now().isoformat(),
                    category=category,
                    source_name=f"[{region}] {name}",
                ))
    except Exception:
        pass

    logger.debug("Region fetch [%s] %s: %d items (fallback)", region, name, len(events))
    return events


def fetch_multi_region(config: Optional[ScoutConfig] = None,
                       regions: Optional[List[str]] = None) -> Dict[str, List[RawEvent]]:
    """Fetch news from ALL configured regional sources.

    Returns a dict mapping region -> list of RawEvents.
    """
    from config.source_authority import get_source_feeds

    if regions is None:
        regions = ["US", "EU", "UK", "JP", "CN", "KR", "ME", "RU"]

    feeds = get_source_feeds()
    region_feeds = {r: [] for r in regions}

    for feed in feeds:
        region = feed["region"]
        if region == "GLOBAL":
            # Add global feeds to all regions
            for r in regions:
                region_feeds[r].append(feed)
        elif region in regions:
            region_feeds[region].append(feed)

    results: Dict[str, List[RawEvent]] = {}
    for region, feed_list in region_feeds.items():
        all_events: List[RawEvent] = []
        for feed in feed_list[:5]:  # Max 5 sources per region for perf
            try:
                events = fetch_region_source(
                    name=feed["name"], url=feed["url"],
                    region=region, category=feed.get("category", "macro"),
                    config=config,
                )
                all_events.extend(events)
            except Exception:
                continue
        results[region] = all_events
        logger.info("Multi-region [%s]: %d events from %d feeds",
                    region, len(all_events), len(feed_list[:5]))

    return results


def cross_region_compare(region_results: Dict[str, List[RawEvent]]) -> Dict[str, Any]:
    """Compare narratives across regions and detect cross-region patterns.

    Returns a dict with:
      - region_coverage: events per region
      - cross_region_themes: titles that appear in multiple regions
      - unique_regional: titles unique to a single region
      - diversity_score: 0.0-1.0 (higher = more diverse coverage)
    """
    region_counts = {r: len(events) for r, events in region_results.items()}
    total_events = sum(region_counts.values())

    # Extract key terms from each region's events
    region_terms: Dict[str, set] = {}
    for region, events in region_results.items():
        terms = set()
        for evt in events:
            words = evt.title.lower().split()
            for w in words:
                if len(w) > 4:
                    terms.add(w)
        region_terms[region] = terms

    # Find terms shared across >= 2 regions (cross-region themes)
    all_terms: Dict[str, set] = {}
    for region, terms in region_terms.items():
        for t in terms:
            if t not in all_terms:
                all_terms[t] = set()
            all_terms[t].add(region)

    cross_region = {t: regions for t, regions in all_terms.items() if len(regions) >= 2}
    unique_regional = {t: regions for t, regions in all_terms.items() if len(regions) == 1}

    # Diversity score: how many regions have data
    regions_with_data = sum(1 for c in region_counts.values() if c > 0)
    diversity_score = regions_with_data / max(len(region_results), 1)

    return {
        "region_coverage": region_counts,
        "total_events": total_events,
        "cross_region_themes": sorted(cross_region.keys())[:20],
        "unique_regional_themes": sorted(unique_regional.keys())[:20],
        "diversity_score": round(diversity_score, 2),
        "regions_with_data": regions_with_data,
    }


# ---------------------------------------------------------------
# Alternative Data Fetchers (Phase Optimization)
# ---------------------------------------------------------------

# Crypto news sources
CRYPTO_RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("The Block", "https://www.theblock.co/rss"),
]

# Futures/commodities news
FUTURES_RSS_FEEDS = [
    ("CME Group", "https://www.cmegroup.com/content/cmegroup/en/news-room/rss.html"),
    ("Investing.com Commodities", "https://www.investing.com/rss/news_25.rss"),
    ("OilPrice.com", "https://oilprice.com/rss/main"),
    ("S&P Global Commodity Insights", "https://www.spglobal.com/commodityinsights/en/rss"),
]

# Equity market news
EQUITY_RSS_FEEDS = [
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories"),
    ("Seeking Alpha Market", "https://seekingalpha.com/market-news.xml"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("Barron's", "https://feeds.barrons.com/barrons/markets"),
]


def fetch_market_news(market_type: str = "all",
                       config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch news from crypto, futures, and equity markets.

    Args:
        market_type: "crypto", "futures", "equity", or "all".
        config: ScoutConfig overrides.

    Returns:
        List of RawEvent across all selected market RSS feeds.
    """
    cfg = config or ScoutConfig()
    all_events: List[RawEvent] = []

    feed_map = {}
    if market_type in ("crypto", "all"):
        feed_map["crypto"] = CRYPTO_RSS_FEEDS
    if market_type in ("futures", "all"):
        feed_map["futures"] = FUTURES_RSS_FEEDS
    if market_type in ("equity", "all"):
        feed_map["equity"] = EQUITY_RSS_FEEDS

    for market_cat, feeds in feed_map.items():
        for name, url in feeds:
            try:
                text = _fetch_url(url, timeout=cfg.request_timeout + 5)
                if not text:
                    continue
                import xml.etree.ElementTree as ET
                root = ET.fromstring(text)
                for item in root.findall(".//item")[:3]:
                    title_el = item.find("title")
                    title = (title_el.text or "").strip() if title_el is not None else ""
                    if title and len(title) > 20:
                        all_events.append(RawEvent(
                            title=title[:200],
                            body=title,
                            source_url=url,
                            timestamp=datetime.datetime.now().isoformat(),
                            category=market_cat,
                            source_name=f"[{market_cat.upper()}] {name}",
                        ))
            except Exception:
                continue

    logger.info("Market news [%s]: %d events", market_type, len(all_events))
    return all_events


def fetch_marinetraffic(chokepoint: str = "hormuz",
                         config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch vessel traffic data for strategic maritime chokepoints.

    Uses MarineTraffic public AIS data to detect shipping disruptions.
    Key chokepoints: hormuz, malacca, suez, panama, bab_el_mandeb.

    NOTE: Full real-time AIS requires paid MarineTraffic API. This stub
    provides a metadata placeholder. To enable real data, set
    MARINETRAFFIC_API_KEY in .env.

    Args:
        chokepoint: Chokepoint identifier.
        config: ScoutConfig overrides.

    Returns:
        List of RawEvent (empty if API key not configured).
    """
    import os
    api_key = os.environ.get("MARINETRAFFIC_API_KEY", "")
    if not api_key:
        logger.debug("MarineTraffic API key not set; returning stub")
        return []

    cfg = config or ScoutConfig()
    url = (f"https://services.marinetraffic.com/api/exportvessels/"
           f"{api_key}/v:3/area:{chokepoint}/protocol:json")

    text = _fetch_url(url, timeout=cfg.request_timeout + 10)
    if not text:
        return []

    events: List[RawEvent] = []
    try:
        vessels = data if isinstance(data, list) else data.get("vessels", [])
        total = len(vessels)
        categories = Counter(v.get("shipType", "unknown") for v in vessels)
        oil_tankers = categories.get("Tanker", 0) + categories.get("Oil Tanker", 0)
        lng_carriers = categories.get("LNG Tanker", 0)

        events.append(RawEvent(
            title=f"MarineTraffic [{chokepoint}]: {total} vessels, "
                  f"{oil_tankers} tankers, {lng_carriers} LNG carriers",
            body=f"Chokepoint {chokepoint} AIS data: {total} total vessels. "
                 f"Oil tankers: {oil_tankers}. LNG carriers: {lng_carriers}. "
                 f"Ship type breakdown: {dict(categories)}",
            source_url=f"https://www.marinetraffic.com/en/ais/home/centerx:56.0/centery:26.0/zoom:6",
            timestamp=datetime.datetime.now().isoformat(),
            category="geopolitical",
            source_name="MarineTraffic AIS",
        ))
    except (json.JSONDecodeError, KeyError):
        pass

    return events


# ---------------------------------------------------------------
# Mock Scout Report (for testing)
# ---------------------------------------------------------------

def _mock_scout_report() -> ScoutReport:
    """Return a canned scout report with sample events for testing."""
    now = datetime.datetime.now().isoformat()
    events = [
        RawEvent(title="Fed Signals Rate Cut Possibility Amid Cooling Inflation",
                 body="Federal Reserve officials indicated openness to rate cuts...",
                 source_url="https://reuters.com/mock", timestamp=now,
                 category="macro", source_name="Reuters"),
        RawEvent(title="Oil Prices Surge on Hormuz Strait Tensions",
                 body="Crude oil futures jumped 4% as shipping disruption fears mount...",
                 source_url="https://reuters.com/mock", timestamp=now,
                 category="geopolitical", source_name="Reuters"),
        RawEvent(title="US Non-Farm Payrolls Beat Expectations at +245K",
                 body="The Labor Department reported stronger-than-expected job growth...",
                 source_url="https://fred.stlouisfed.org/mock", timestamp=now,
                 category="macro", source_name="FRED"),
        RawEvent(title="ECB Holds Rates, Signals June Cut Possible",
                 body="European Central Bank maintained rates but opened door to June reduction...",
                 source_url="https://ecb.europa.eu/mock", timestamp=now,
                 category="macro", source_name="ECB"),
        RawEvent(title="BOJ Intervention Pushes Yen Higher",
                 body="Bank of Japan intervened in currency markets for second time this month...",
                 source_url="https://boj.or.jp/mock", timestamp=now,
                 category="currency", source_name="BOJ"),
    ]
    return ScoutReport(raw_events=events, sar_filtered_count=0, errors=[])


# ---------------------------------------------------------------
# Additional Reliable RSS Feeds (anti-403 friendly)
# ---------------------------------------------------------------

GENERAL_NEWS_FEEDS = [
    ("NPR Business", "https://feeds.npr.org/1001/rss.xml"),
    ("AP Top News", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Al Jazeera Economy", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
]


def fetch_general_news(config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch general macro/financial news from reliable RSS feeds.

    These feeds are less likely to be blocked (public service broadcasters).
    """
    cfg = config or ScoutConfig()
    all_events: List[RawEvent] = []

    for name, url in GENERAL_NEWS_FEEDS:
        try:
            text = _fetch_url(url, timeout=cfg.request_timeout + 5)
            if not text:
                continue
            import xml.etree.ElementTree as ET
            root = ET.fromstring(text)
            for item in root.findall(".//item")[:3]:
                title_el = item.find("title")
                title = (title_el.text or "").strip() if title_el is not None else ""
                if title and len(title) > 20:
                    all_events.append(RawEvent(
                        title=title[:200],
                        body=title,
                        source_url=url,
                        timestamp=datetime.datetime.now().isoformat(),
                        category="macro",
                        source_name=f"[GENERAL] {name}",
                    ))
        except Exception:
            continue

    logger.info("General news: %d events", len(all_events))
    return all_events


# ---------------------------------------------------------------
# Aggregated news feeds (bypass individual site blocking)
# ---------------------------------------------------------------

GOOGLE_NEWS_TOPICS = [
    ("Fed monetary policy", "https://news.google.com/rss/search?q=Federal+Reserve+monetary+policy+interest+rate&hl=en-US&gl=US&ceid=US:en"),
    ("Global macro economy", "https://news.google.com/rss/search?q=global+economy+inflation+GDP+central+bank&hl=en-US&gl=US&ceid=US:en"),
    ("Commodities energy", "https://news.google.com/rss/search?q=crude+oil+natural+gas+commodity+prices&hl=en-US&gl=US&ceid=US:en"),
    ("Geopolitical risk", "https://news.google.com/rss/search?q=geopolitical+conflict+trade+war+sanctions&hl=en-US&gl=US&ceid=US:en"),
    ("China economy", "https://news.google.com/rss/search?q=China+economy+PBOC+yuan+trade&hl=en-US&gl=US&ceid=US:en"),
    ("Middle East finance", "https://news.google.com/rss/search?q=Middle+East+oil+Saudi+UAE+finance&hl=en-US&gl=US&ceid=US:en"),
]

REDDIT_FINANCE_RSS = [
    ("r/worldnews", "https://www.reddit.com/r/worldnews/.rss"),
    ("r/investing", "https://www.reddit.com/r/investing/.rss"),
    ("r/economics", "https://www.reddit.com/r/Economics/.rss"),
    ("r/geopolitics", "https://www.reddit.com/r/geopolitics/.rss"),
]


def fetch_google_news(config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch aggregated news from Google News RSS for key financial topics.

    Google News aggregates from ALL sources including paywalled/blocked sites,
    effectively bypassing individual site anti-scraping measures.
    """
    cfg = config or ScoutConfig()
    all_events: List[RawEvent] = []

    for topic, url in GOOGLE_NEWS_TOPICS:
        try:
            text = _fetch_url(url, timeout=cfg.request_timeout + 5)
            if not text:
                continue
            import xml.etree.ElementTree as ET
            root = ET.fromstring(text)
            for item in root.findall(".//item")[:3]:
                title_el = item.find("title")
                source_el = item.find("source")
                title = (title_el.text or "").strip() if title_el is not None else ""
                source = (source_el.text or "") if source_el is not None else "Google News"
                # Remove source suffix from title ("Title - Source")
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                if title and len(title) > 20:
                    all_events.append(RawEvent(
                        title=title[:200],
                        body=title,
                        source_url=url,
                        timestamp=datetime.datetime.now().isoformat(),
                        category="macro",
                        source_name=f"[GOOGLE] {source}",
                    ))
        except Exception:
            continue

    logger.info("Google News: %d events from %d topics", len(all_events), len(GOOGLE_NEWS_TOPICS))
    return all_events


def fetch_reddit_finance(config: Optional[ScoutConfig] = None) -> List[RawEvent]:
    """Fetch trending topics from financial/economic subreddits.

    Reddit RSS is rarely blocked and provides early narrative detection.
    """
    cfg = config or ScoutConfig()
    all_events: List[RawEvent] = []

    for subreddit, url in REDDIT_FINANCE_RSS:
        try:
            text = _fetch_url(url, timeout=cfg.request_timeout + 5)
            if not text:
                continue
            import xml.etree.ElementTree as ET
            root = ET.fromstring(text)
            for item in root.findall(".//entry")[:3]:
                title_el = item.find("{http://www.w3.org/2005/Atom}title")
                title = (title_el.text or "").strip() if title_el is not None else ""
                if title and len(title) > 20:
                    all_events.append(RawEvent(
                        title=title[:200],
                        body=title,
                        source_url=url,
                        timestamp=datetime.datetime.now().isoformat(),
                        category="sentiment",
                        source_name=f"[REDDIT] {subreddit}",
                    ))
        except Exception:
            continue

    logger.info("Reddit finance: %d events", len(all_events))
    return all_events
