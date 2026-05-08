"""
macro_calendar.py - Macroeconomic event calendar collector with graceful degradation.

Fetches upcoming macroeconomic events (CPI, Fed rate decisions, employment data)
from public APIs. Implements graceful degradation: if all network requests fail,
returns a locally embedded static test calendar.

Data structure per event:
  - date: ISO-8601 date string (YYYY-MM-DD)
  - event: human-readable event name
  - importance: one of "high", "medium", "low"

Dependencies: requests, json (built-in), datetime (built-in), pathlib (built-in)
"""
import json
import logging
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/macro_calendar")

# ---------------------------------------------------------------------------
# Static fallback calendar (used when all external sources are unreachable)
# ---------------------------------------------------------------------------
# fmt: off
FALLBACK_EVENTS: List[Dict[str, Any]] = [
    # High importance
    {"date": "2026-05-07", "event": "FOMC Interest Rate Decision",         "importance": "high"},
    {"date": "2026-05-08", "event": "US Non-Farm Payrolls (Apr)",          "importance": "high"},
    {"date": "2026-05-09", "event": "US CPI YoY (Apr)",                    "importance": "high"},
    {"date": "2026-05-10", "event": "US PPI MoM (Apr)",                    "importance": "high"},
    {"date": "2026-05-12", "event": "US Initial Jobless Claims",           "importance": "high"},
    {"date": "2026-05-13", "event": "US Retail Sales MoM (Apr)",            "importance": "high"},
    # Medium importance
    {"date": "2026-05-06", "event": "US Trade Balance (Mar)",               "importance": "medium"},
    {"date": "2026-05-08", "event": "US Unemployment Rate (Apr)",           "importance": "medium"},
    {"date": "2026-05-09", "event": "US Core CPI MoM (Apr)",                "importance": "medium"},
    {"date": "2026-05-11", "event": "US Michigan Consumer Sentiment (May)",  "importance": "medium"},
    {"date": "2026-05-14", "event": "US Industrial Production MoM (Apr)",   "importance": "medium"},
    # Low importance
    {"date": "2026-05-06", "event": "US MBA Mortgage Applications",         "importance": "low"},
    {"date": "2026-05-09", "event": "US Wholesale Inventories MoM (Mar)",   "importance": "low"},
    {"date": "2026-05-12", "event": "US EIA Crude Oil Inventories",         "importance": "low"},
    {"date": "2026-05-13", "event": "US Housing Starts (Apr)",              "importance": "low"},
]
# fmt: on


class MacroCalendarCache:
    """Local JSON cache for macroeconomic calendar data.

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
        """Return cached events if a valid cache entry exists for ref_date."""
        if ref_date is None:
            ref_date = self._now()
        cache_file = self._cache_path(source)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Macro cache read error for %s: %s", source, exc)
            return None

        cached_date_str = entry.get("last_updated")
        if cached_date_str != ref_date.isoformat():
            logger.debug(
                "Macro cache stale for %s: cached=%s, required=%s",
                source,
                cached_date_str,
                ref_date.isoformat(),
            )
            return None

        events = entry.get("events", [])
        if not events:
            return None
        return events

    def set(
        self,
        source: str,
        events: List[Dict[str, Any]],
        ref_date: Optional[date] = None,
    ) -> None:
        """Write a list of events to the cache file."""
        if ref_date is None:
            ref_date = self._now()
        entry = {
            "source": source,
            "last_updated": ref_date.isoformat(),
            "events": events,
        }
        cache_file = self._cache_path(source)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.debug("Cached %d macro events from %s", len(events), source)

    def clear(self, source: str) -> None:
        """Remove a specific cache entry."""
        cache_file = self._cache_path(source)
        if cache_file.exists():
            cache_file.unlink()
            logger.debug("Cleared macro cache for %s", source)


class MacroCalendarCollector:
    """Collect upcoming macroeconomic events with graceful degradation.

    Uses the FRED (Federal Reserve Economic Data) API via fredapi wrapper as
    the primary source. Falls back to the static FALLBACK_EVENTS list if the
    network request fails or the source is unreachable.
    """

    FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[MacroCalendarCache] = None,
    ):
        self.api_key = api_key
        self.cache = cache or MacroCalendarCache()

    def fetch_upcoming(
        self,
        days_ahead: int = 30,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return a list of upcoming macroeconomic events.

        Args:
            days_ahead: Look-ahead window in days (default 30).
            force_refresh: If True, bypass cache and attempt network fetch.

        Returns:
            List of event dicts, each with keys: date, event, importance.
            Falls back to static calendar on any network failure.
        """
        ref_source = "fred_api"
        ref_date = self.cache._now()

        # Try cache first (unless force_refresh is set)
        if not force_refresh:
            cached = self.cache.get(ref_source)
            if cached is not None:
                logger.info("Macro cache hit for %s", ref_source)
                return self._filter_by_window(cached, days_ahead, ref_date=ref_date)

        # Attempt primary source (FRED API)
        if self.api_key:
            try:
                events = self._fetch_from_fred()
                logger.info("Fetched %d macro events from FRED API", len(events))
                self.cache.set(ref_source, events)
                return self._filter_by_window(events, days_ahead, ref_date=ref_date)
            except (requests.RequestException, ValueError, KeyError) as exc:
                logger.warning(
                    "FRED API request failed (%s); falling back to static calendar",
                    exc,
                )

        # Graceful degradation: use static fallback
        logger.info("Using static fallback macro calendar")
        fallback = self._make_fallback_safe(FALLBACK_EVENTS)
        return self._filter_by_window(fallback, days_ahead, ref_date=ref_date)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_from_fred() -> List[Dict[str, Any]]:
        """Attempt to pull event series from FRED API.

        NOTE: This is a stub for the actual FRED API integration.
        Real implementation would query the FRED /series/search endpoint
        for economic indicators and parse their release schedules.

        Raises ValueError to trigger graceful degradation (fallback to
        static calendar). Override with mock in tests for live-like behavior.
        """
        warnings.warn("FRED API _fetch_from_fred is stubbed; raising ValueError for fallback.")
        raise ValueError("FRED API is not configured; stubbed to trigger fallback.")

    @staticmethod
    def _make_fallback_safe(raw_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate and sanitize the fallback event list."""
        validated: List[Dict[str, Any]] = []
        allowed_importance = {"high", "medium", "low"}
        for ev in raw_events:
            if not isinstance(ev, dict):
                continue
            ev_date = ev.get("date", "")
            ev_event = ev.get("event", "")
            ev_importance = ev.get("importance", "low")
            if not ev_date or not ev_event:
                continue
            if ev_importance not in allowed_importance:
                ev_importance = "low"
            validated.append({
                "date": str(ev_date),
                "event": str(ev_event),
                "importance": str(ev_importance),
            })
        return validated

    @staticmethod
    def _filter_by_window(
        events: List[Dict[str, Any]],
        days_ahead: int,
        ref_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Filter events to only those within the look-ahead window."""
        if ref_date is None:
            from datetime import date as _dt
            ref_date = _dt.today()
        cutoff = ref_date + timedelta(days=days_ahead)
        filtered = []
        for ev in events:
            try:
                ev_dt = date.fromisoformat(ev["date"])
            except (ValueError, KeyError):
                continue
            if ref_date <= ev_dt <= cutoff:
                filtered.append(ev)
        # Sort by date then importance
        _importance_rank = {"high": 0, "medium": 1, "low": 2}
        filtered.sort(key=lambda x: (x["date"], _importance_rank.get(x["importance"], 99)))
        return filtered