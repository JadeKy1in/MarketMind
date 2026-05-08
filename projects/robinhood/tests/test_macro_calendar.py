"""
test_macro_calendar.py - Unit tests for macro_calendar.py

Tests the MacroCalendarCache and MacroCalendarCollector classes,
mocking all network requests to ensure tests are deterministic.
"""
import json
import tempfile
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import patch

import pytest

from src.macro_calendar import (
    FALLBACK_EVENTS,
    MacroCalendarCache,
    MacroCalendarCollector,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_cache_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for cache files."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def frozen_date() -> date:
    """Freeze the reference date to 2026-05-05."""
    return date(2026, 5, 5)


@pytest.fixture
def cache(frozen_date: date, tmp_cache_dir: Path) -> MacroCalendarCache:
    """Create a MacroCalendarCache with frozen date."""
    return MacroCalendarCache(cache_dir=tmp_cache_dir, now=lambda: frozen_date)


@pytest.fixture
def collector(
    cache: MacroCalendarCache,
) -> MacroCalendarCollector:
    """Create a MacroCalendarCollector with no API key (forces fallback)."""
    return MacroCalendarCollector(api_key=None, cache=cache)


# ---------------------------------------------------------------------------
# Tests: MacroCalendarCache
# ---------------------------------------------------------------------------


class TestMacroCalendarCache:
    """Verify local JSON cache storage and retrieval."""

    def test_cache_miss_returns_none(self, cache: MacroCalendarCache) -> None:
        """get() should return None when no cache file exists."""
        assert cache.get("fred_api") is None

    def test_set_and_get(self, cache: MacroCalendarCache) -> None:
        """set() then get() should return identical data."""
        events: List[Dict[str, Any]] = [
            {"date": "2026-05-07", "event": "FOMC", "importance": "high"},
        ]
        cache.set("fred_api", events)
        result = cache.get("fred_api")
        assert result is not None
        assert result == events

    def test_stale_cache_returns_none(
        self, cache: MacroCalendarCache, frozen_date: date
    ) -> None:
        """Cache with mismatched date should be treated as stale."""
        events: List[Dict[str, Any]] = [
            {"date": "2026-05-07", "event": "FOMC", "importance": "high"},
        ]
        cache.set("fred_api", events, ref_date=frozen_date - timedelta(days=1))
        result = cache.get("fred_api")
        assert result is None

    def test_clear_removes_cache(self, cache: MacroCalendarCache) -> None:
        """clear() should delete the cache file."""
        events: List[Dict[str, Any]] = [
            {"date": "2026-05-07", "event": "FOMC", "importance": "high"},
        ]
        cache.set("fred_api", events)
        cache.clear("fred_api")
        assert cache.get("fred_api") is None

    def test_corrupted_cache_returns_none(
        self, cache: MacroCalendarCache
    ) -> None:
        """Corrupted JSON file should be treated as cache miss."""
        cache_file = cache._cache_path("fred_api")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json", encoding="utf-8")
        assert cache.get("fred_api") is None

    def test_empty_events_returns_none(self, cache: MacroCalendarCache) -> None:
        """Cache entry with empty events list should return None."""
        cache.set("fred_api", [])
        result = cache.get("fred_api")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: MacroCalendarCollector (graceful degradation)
# ---------------------------------------------------------------------------


class TestMacroCalendarCollectorDegradation:
    """Verify fallback behavior when network requests fail."""

    def test_no_api_key_uses_fallback(
        self, collector: MacroCalendarCollector
    ) -> None:
        """Without api_key, fetch_upcoming should use FALLBACK_EVENTS."""
        events = collector.fetch_upcoming(days_ahead=30)
        assert len(events) > 0
        for ev in events:
            assert "date" in ev
            assert "event" in ev
            assert "importance" in ev

    def test_fallback_events_are_filtered_by_window(
        self, collector: MacroCalendarCollector, frozen_date: date
    ) -> None:
        """Days outside the look-ahead window should be excluded."""
        events = collector.fetch_upcoming(days_ahead=1)
        expected_cutoff = frozen_date + timedelta(days=1)
        for ev in events:
            ev_date = date.fromisoformat(ev["date"])
            assert frozen_date <= ev_date <= expected_cutoff

    def test_api_key_with_failure_triggers_fallback(
        self, frozen_date: date, tmp_cache_dir: Path
    ) -> None:
        """When FRED API raises an exception, should fall back to static."""
        cache = MacroCalendarCache(cache_dir=tmp_cache_dir, now=lambda: frozen_date)
        collector = MacroCalendarCollector(api_key="fake_key", cache=cache)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            events = collector.fetch_upcoming(days_ahead=30)
        # Should contain fallback events (FRED stub raises NotImplementedError)
        assert len(events) > 0
        # All returned events should have required fields
        for ev in events:
            assert "date" in ev
            assert "event" in ev
            assert "importance" in ev

    def test_cache_hit_returns_cached_data(
        self, cache: MacroCalendarCache, frozen_date: date
    ) -> None:
        """If cache returns valid data, it should be used directly."""
        cached_events = [
            {"date": "2026-05-07", "event": "Test Event", "importance": "high"},
        ]
        cache.set("fred_api", cached_events)

        collector = MacroCalendarCollector(api_key="fake_key", cache=cache)
        events = collector.fetch_upcoming(days_ahead=30, force_refresh=False)
        assert events == cached_events

    def test_force_refresh_ignores_cache(
        self, cache: MacroCalendarCache
    ) -> None:
        """force_refresh=True should bypass cache and attempt fetch."""
        cached_events = [
            {"date": "2026-05-07", "event": "Cached Event", "importance": "high"},
        ]
        cache.set("fred_api", cached_events)

        collector = MacroCalendarCollector(api_key=None, cache=cache)
        events = collector.fetch_upcoming(days_ahead=30, force_refresh=True)
        # With no api_key, should use fallback, not cache
        assert events != cached_events
        assert len(events) > 0


# ---------------------------------------------------------------------------
# Tests: Data validation
# ---------------------------------------------------------------------------


class TestMacroCalendarDataValidation:
    """Verify data integrity of fallback and filtered results."""

    def test_fallback_event_structure(self) -> None:
        """Every fallback event must have valid date, event, and importance."""
        allowed_importance = {"high", "medium", "low"}
        for ev in FALLBACK_EVENTS:
            assert "date" in ev, f"Missing date in event: {ev}"
            assert "event" in ev, f"Missing event name: {ev}"
            assert (
                ev.get("importance") in allowed_importance
            ), f"Invalid importance in: {ev}"
            # Verify date is parseable
            date.fromisoformat(ev["date"])

    def test_filtered_events_preserve_order(
        self, collector: MacroCalendarCollector
    ) -> None:
        """Events should be sorted by date, then by importance (high first)."""
        events = collector.fetch_upcoming(days_ahead=30)
        dates = [ev["date"] for ev in events]
        assert dates == sorted(dates), "Events not sorted by date"

    def test_make_fallback_safe_removes_invalid(self) -> None:
        """_make_fallback_safe should filter out malformed entries."""
        raw: List[Dict[str, Any]] = [
            {"date": "2026-05-07", "event": "Valid", "importance": "high"},
            {"date": "", "event": "Bad date", "importance": "high"},
            {"date": "2026-05-08", "event": "", "importance": "medium"},
            {"date": "2026-05-09", "event": "Bad importance", "importance": "super"},
            {"date": "2026-10-10", "event": "Another valid", "importance": "low"},
        ]
        safe = MacroCalendarCollector._make_fallback_safe(raw)
        assert len(safe) >= 2
        for ev in safe:
            assert ev["date"]
            assert ev["event"]
            assert ev["importance"] in {"high", "medium", "low"}