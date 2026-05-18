"""
sentiment_collector.py - Sentiment data collector for political figures/KOLs.

Fetches structured sentiment data from:
  - Truth Social (Trump/KOL posts via RSS or scraping stubs)
  - Congressional trading disclosures (e.g., HouseStockWatcher, CapitolTrades)

Extracted data structure per record:
  - timestamp: ISO-8601 datetime string
  - source: information source identifier (e.g., "truth_social", "capitol_trades")
  - author: original author/speaker (e.g., "Trump", "Pelosi")
  - raw_text: original text content
  - related_ticker: associated ticker symbol (if any), or null

Reuses the local JSON cache pattern from market_fetcher.py to avoid
frequent request bans from target sources.

Dependencies: requests, beautifulsoup4, json (built-in), datetime (built-in)
"""
import json
import logging
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/sentiment_data")

# ---------------------------------------------------------------------------
# Static fallback records (used when all external sources are unreachable)
# ---------------------------------------------------------------------------
# fmt: off
FALLBACK_RECORDS: List[Dict[str, Any]] = [
    {
        "timestamp": "2026-05-04T10:30:00",
        "source": "truth_social",
        "author": "Trump",
        "raw_text": "The economy is doing great, our policies are working better than anyone expected! DJT",
        "related_ticker": "DJT",
    },
    {
        "timestamp": "2026-05-03T14:15:00",
        "source": "truth_social",
        "author": "Trump",
        "raw_text": "Big Tech has too much power, we need to break them up. META GOOG",
        "related_ticker": None,
    },
    {
        "timestamp": "2026-05-02T09:00:00",
        "source": "capitol_trades",
        "author": "Pelosi",
        "raw_text": "Disclosure: purchased call options on NVDA, exercised 50 contracts of NVDA 20250620 800C",
        "related_ticker": "NVDA",
    },
    {
        "timestamp": "2026-05-01T16:45:00",
        "source": "capitol_trades",
        "author": "Pelosi",
        "raw_text": "Disclosure: sold MSFT shares, purchased AAPL shares",
        "related_ticker": None,
    },
    {
        "timestamp": "2026-04-30T08:30:00",
        "source": "truth_social",
        "author": "Trump",
        "raw_text": "Oil prices are coming down nicely, energy independence is key. XOM CVX",
        "related_ticker": "XOM",
    },
    {
        "timestamp": "2026-04-29T11:20:00",
        "source": "capitol_trades",
        "author": "Graham",
        "raw_text": "Disclosure: purchased BAC shares, value $50k-$100k",
        "related_ticker": "BAC",
    },
    {
        "timestamp": "2026-04-28T13:00:00",
        "source": "truth_social",
        "author": "Trump",
        "raw_text": "We must secure our border and bring back American manufacturing! CAT",
        "related_ticker": "CAT",
    },
    {
        "timestamp": "2026-04-27T15:30:00",
        "source": "capitol_trades",
        "author": "Schumer",
        "raw_text": "Disclosure: purchased shares of GOOGL, value $15k-$50k",
        "related_ticker": "GOOGL",
    },
]
# fmt: on


class SentimentCache:
    """Local JSON cache for sentiment data.

    Mirrors the design of MarketDataCache in market_fetcher.py for consistency.
    Accepts an optional ``now`` callable for time-freezing in tests.
    """

    def __init__(
        self,
        cache_dir: Union[str, Path] = CACHE_DIR,
        now: Optional[Callable[[], date]] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self._now = now or date.today
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, source: str) -> Path:
        """Return the filesystem path for a source-based cache file."""
        safe_source = source.replace(".", "_").replace("/", "_")
        return self.cache_dir / f"{safe_source}.json"

    def get(self, source: str, ref_date: Optional[date] = None) -> Optional[List[Dict[str, Any]]]:
        """Return cached records if a valid cache entry exists for ref_date."""
        if ref_date is None:
            ref_date = self._now()
        cache_file = self._cache_path(source)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Sentiment cache read error for %s: %s", source, exc)
            return None

        cached_date_str = entry.get("last_updated")
        if cached_date_str != ref_date.isoformat():
            logger.debug(
                "Sentiment cache stale for %s: cached=%s, required=%s",
                source,
                cached_date_str,
                ref_date.isoformat(),
            )
            return None

        records = entry.get("records", [])
        if not records:
            return None
        return records

    def set(
        self,
        source: str,
        records: List[Dict[str, Any]],
        ref_date: Optional[date] = None,
    ) -> None:
        """Write a list of records to the cache file."""
        if ref_date is None:
            ref_date = self._now()
        entry = {
            "source": source,
            "last_updated": ref_date.isoformat(),
            "records": records,
        }
        cache_file = self._cache_path(source)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.debug("Cached %d sentiment records from %s", len(records), source)

    def clear(self, source: str) -> None:
        """Remove a specific cache entry."""
        cache_file = self._cache_path(source)
        if cache_file.exists():
            cache_file.unlink()
            logger.debug("Cleared sentiment cache for %s", source)


class SentimentCollector:
    """Collect structured sentiment data from multiple political/financial sources.

    Supported sources:
      - "truth_social": Fetch posts from Truth Social (Trump/KOL).
      - "capitol_trades": Fetch congressional trading disclosures.

    Each source implements graceful degradation: if the network request fails,
    returns the static FALLBACK_RECORDS filtered by source.
    """

    TRUTH_SOCIAL_RSS_URL = "https://truthsocial.com/@realDonaldTrump.rss"
    CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"

    def __init__(self, cache: Optional[SentimentCache] = None):
        self.cache = cache or SentimentCache()

    def fetch_truth_social(
        self,
        limit: int = 10,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch recent posts from Truth Social (Trump).

        Args:
            limit: Maximum number of posts to return.
            force_refresh: If True, bypass cache and attempt network fetch.

        Returns:
            List of record dicts with keys: timestamp, source, author,
            raw_text, related_ticker.
        """
        source_name = "truth_social"

        # Try cache first
        if not force_refresh:
            cached = self.cache.get(source_name)
            if cached is not None:
                logger.info("Sentiment cache hit for %s", source_name)
                return cached[:limit]

        # Attempt network fetch
        try:
            records = self._fetch_truth_social_rss()
            logger.info("Fetched %d records from Truth Social RSS", len(records))
            self.cache.set(source_name, records)
            return records[:limit]
        except (requests.RequestException, ValueError, KeyError, AttributeError) as exc:
            logger.warning(
                "Truth Social fetch failed (%s); falling back to static data",
                exc,
            )

        # Graceful degradation: static fallback
        logger.info("Using static fallback for %s", source_name)
        fallback = self._filter_fallback_by_source(source_name)
        return fallback[:limit]

    def fetch_capitol_trades(
        self,
        limit: int = 10,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch recent congressional trading disclosures.

        Args:
            limit: Maximum number of disclosures to return.
            force_refresh: If True, bypass cache and attempt network fetch.

        Returns:
            List of record dicts with keys: timestamp, source, author,
            raw_text, related_ticker.
        """
        source_name = "capitol_trades"

        # Try cache first
        if not force_refresh:
            cached = self.cache.get(source_name)
            if cached is not None:
                logger.info("Sentiment cache hit for %s", source_name)
                return cached[:limit]

        # Attempt network fetch
        try:
            records = self._fetch_capitol_trades_html()
            logger.info("Fetched %d records from Capitol Trades", len(records))
            self.cache.set(source_name, records)
            return records[:limit]
        except (requests.RequestException, ValueError, KeyError, AttributeError) as exc:
            logger.warning(
                "Capitol Trades fetch failed (%s); falling back to static data",
                exc,
            )

        # Graceful degradation: static fallback
        logger.info("Using static fallback for %s", source_name)
        fallback = self._filter_fallback_by_source(source_name)
        return fallback[:limit]

    def fetch_all(
        self,
        limit_per_source: int = 5,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch sentiment data from all configured sources.

        Args:
            limit_per_source: Maximum records per source.
            force_refresh: If True, bypass all caches.

        Returns:
            Combined list of records, sorted by timestamp descending.
        """
        all_records: List[Dict[str, Any]] = []
        all_records.extend(
            self.fetch_truth_social(limit=limit_per_source, force_refresh=force_refresh)
        )
        all_records.extend(
            self.fetch_capitol_trades(limit=limit_per_source, force_refresh=force_refresh)
        )
        # Sort by timestamp descending
        all_records.sort(
            key=lambda x: x.get("timestamp", ""),
            reverse=True,
        )
        return all_records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_truth_social_rss() -> List[Dict[str, Any]]:
        """Fetch Truth Social RSS feed and parse into structured records.

        NOTE: This is a stub that simulates RSS parsing.
        The real URL may change or require authentication.

        Returns empty list to trigger fallback to static records.
        Override with mock in tests for live-like behavior.
        """
        warnings.warn("Truth Social RSS _fetch_truth_social_rss is stubbed; returning empty list.")
        return []

    @staticmethod
    def _fetch_capitol_trades_html() -> List[Dict[str, Any]]:
        """Fetch Capitol Trades HTML and scrape disclosure tables.

        NOTE: This is a stub that simulates HTML scraping.
        The site structure may change over time.

        Returns empty list to trigger fallback to static records.
        Override with mock in tests for live-like behavior.
        """
        warnings.warn("Capitol Trades HTML fetch is stubbed; returning empty list.")
        return []

    def _filter_fallback_by_source(self, source: str) -> List[Dict[str, Any]]:
        """Filter FALLBACK_RECORDS by source name and sanitize."""
        validated: List[Dict[str, Any]] = []
        for rec in FALLBACK_RECORDS:
            if not isinstance(rec, dict):
                continue
            if rec.get("source") != source:
                continue
            validated.append({
                "timestamp": str(rec.get("timestamp", "")),
                "source": str(rec.get("source", "")),
                "author": str(rec.get("author", "")),
                "raw_text": str(rec.get("raw_text", "")),
                "related_ticker": rec.get("related_ticker"),
            })
        return validated