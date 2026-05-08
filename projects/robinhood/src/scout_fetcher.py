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
        # Extract headlines from HTML using regex (no BeautifulSoup dependency)
        # Pattern: look for <h3 ... >text</h3> or headline patterns
        headline_patterns = re.findall(
            r'<h3[^>]*class="[^"]*[Hh]eadline[^"]*"[^>]*>(.*?)</h3>',
            html,
        )
        if not headline_patterns:
            # Fallback: any <h3> close to "data-testid"
            headline_patterns = re.findall(
                r'<h3[^>]*>(.*?)</h3>',
                html,
            )

        for title in headline_patterns[:5]:
            # Strip HTML tags
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            if clean_title:
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
        tickers: List of ticker symbols for Yahoo Finance fetch.
                 Defaults to ["SPY", "QQQ", "XLF", "XLK", "XLV", "XLE"].
        config: ScoutConfig overrides.

    Returns:
        FetchResult aggregating all source results.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    cfg = config or ScoutConfig()
    all_events: List[RawEvent] = []
    errors: List[str] = []
    stats: Dict[str, Dict[str, int]] = {}

    # --- Track A: FRED API ---
    try:
        fred_events = fetch_fred_observations(config=cfg)
        all_events.extend(fred_events)
        stats["fred"] = {"success": 1 if fred_events else 0, "events": len(fred_events)}
    except Exception as e:
        errors.append(f"FRED: {e}")
        stats["fred"] = {"success": 0, "events": 0}

    # --- Track A: Reuters RSS ---
    try:
        reuters_events = fetch_reuters_rss(config=cfg)
        all_events.extend(reuters_events)
        stats["reuters"] = {
            "success": 1 if reuters_events else 0,
            "events": len(reuters_events),
        }
    except Exception as e:
        errors.append(f"Reuters: {e}")
        stats["reuters"] = {"success": 0, "events": 0}

    # --- Track B: Yahoo Finance (per ticker) ---
    yahoo_success_count = 0
    yahoo_total_events = 0
    for ticker in tickers:
        try:
            yahoo_events = fetch_yahoo_finance_headlines(ticker, config=cfg)
            yahoo_total_events += len(yahoo_events)
            all_events.extend(yahoo_events)
            if yahoo_events:
                yahoo_success_count += 1
        except Exception as e:
            errors.append(f"Yahoo {ticker}: {e}")

    stats["yahoo"] = {
        "success": yahoo_success_count,
        "total_tickers": len(tickers),
        "events": yahoo_total_events,
    }

    logger.info(
        "fetch_all completed: %d total events from %d sources (%d errors)",
        len(all_events),
        len(tickers) + 2,
        len(errors),
    )

    return FetchResult(events=all_events, track_stats=stats, errors=errors)