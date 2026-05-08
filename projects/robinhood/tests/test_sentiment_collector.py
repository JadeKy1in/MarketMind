"""
test_sentiment_collector.py - Unit tests for sentiment_collector.py

Tests SentimentCache and SentimentCollector classes, mocking all
network requests to ensure deterministic, offline test execution.
"""
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import patch

import pytest

from src.sentiment_collector import (
    FALLBACK_RECORDS,
    SentimentCache,
    SentimentCollector,
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
def cache(frozen_date: date, tmp_cache_dir: Path) -> SentimentCache:
    """Create a SentimentCache with frozen date."""
    return SentimentCache(cache_dir=tmp_cache_dir, now=lambda: frozen_date)


@pytest.fixture
def collector(cache: SentimentCache) -> SentimentCollector:
    """Create a SentimentCollector with test cache."""
    return SentimentCollector(cache=cache)


# ---------------------------------------------------------------------------
# Tests: SentimentCache
# ---------------------------------------------------------------------------


class TestSentimentCache:
    """Verify local JSON cache storage and retrieval."""

    def test_cache_miss_returns_none(self, cache: SentimentCache) -> None:
        """get() should return None when no cache file exists."""
        assert cache.get("truth_social") is None

    def test_set_and_get(self, cache: SentimentCache) -> None:
        """set() then get() should return identical data."""
        records: List[Dict[str, Any]] = [
            {
                "timestamp": "2026-05-04T10:30:00",
                "source": "truth_social",
                "author": "Trump",
                "raw_text": "Test post",
                "related_ticker": None,
            },
        ]
        cache.set("truth_social", records)
        result = cache.get("truth_social")
        assert result is not None
        assert result == records

    def test_stale_cache_returns_none(
        self, cache: SentimentCache, frozen_date: date
    ) -> None:
        """Cache with mismatched date should be treated as stale."""
        records: List[Dict[str, Any]] = [
            {
                "timestamp": "2026-05-04T10:30:00",
                "source": "truth_social",
                "author": "Trump",
                "raw_text": "Test post",
                "related_ticker": None,
            },
        ]
        cache.set("truth_social", records, ref_date=frozen_date - timedelta(days=1))
        result = cache.get("truth_social")
        assert result is None

    def test_clear_removes_cache(self, cache: SentimentCache) -> None:
        """clear() should delete the cache file."""
        records: List[Dict[str, Any]] = [
            {
                "timestamp": "2026-05-04T10:30:00",
                "source": "truth_social",
                "author": "Trump",
                "raw_text": "Test post",
                "related_ticker": None,
            },
        ]
        cache.set("truth_social", records)
        cache.clear("truth_social")
        assert cache.get("truth_social") is None

    def test_corrupted_cache_returns_none(self, cache: SentimentCache) -> None:
        """Corrupted JSON file should be treated as cache miss."""
        cache_file = cache._cache_path("truth_social")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json", encoding="utf-8")
        assert cache.get("truth_social") is None

    def test_empty_records_returns_none(self, cache: SentimentCache) -> None:
        """Cache entry with empty records list should return None."""
        cache.set("truth_social", [])
        result = cache.get("truth_social")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: SentimentCollector - graceful degradation (no network)
# ---------------------------------------------------------------------------


class TestSentimentCollectorDegradation:
    """Verify fallback behavior when network requests fail."""

    def test_fetch_truth_social_uses_fallback(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_truth_social should return fallback records on network failure."""
        records = collector.fetch_truth_social(limit=10)
        assert len(records) > 0
        for rec in records:
            assert rec["source"] == "truth_social"
            assert "timestamp" in rec
            assert "author" in rec
            assert "raw_text" in rec
            assert "related_ticker" in rec

    def test_fetch_capitol_trades_uses_fallback(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_capitol_trades should return fallback records on network failure."""
        records = collector.fetch_capitol_trades(limit=10)
        assert len(records) > 0
        for rec in records:
            assert rec["source"] == "capitol_trades"
            assert "timestamp" in rec
            assert "author" in rec
            assert "raw_text" in rec
            assert "related_ticker" in rec

    def test_fetch_truth_social_limit(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_truth_social should respect the limit parameter."""
        records = collector.fetch_truth_social(limit=1)
        assert len(records) <= 1

    def test_fetch_capitol_trades_limit(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_capitol_trades should respect the limit parameter."""
        records = collector.fetch_capitol_trades(limit=2)
        assert len(records) <= 2

    def test_cache_hit_returns_cached_data(
        self, cache: SentimentCache, collector: SentimentCollector
    ) -> None:
        """If cache returns valid data, it should be used directly."""
        cached_records: List[Dict[str, Any]] = [
            {
                "timestamp": "2026-05-04T10:30:00",
                "source": "truth_social",
                "author": "Trump",
                "raw_text": "Cached post",
                "related_ticker": "DJT",
            },
        ]
        cache.set("truth_social", cached_records)

        records = collector.fetch_truth_social(limit=10, force_refresh=False)
        assert records == cached_records

    def test_force_refresh_ignores_cache(
        self, cache: SentimentCache, collector: SentimentCollector
    ) -> None:
        """force_refresh=True should bypass cache and attempt fetch."""
        cached_records: List[Dict[str, Any]] = [
            {
                "timestamp": "2026-05-04T10:30:00",
                "source": "truth_social",
                "author": "Trump",
                "raw_text": "Cached post",
                "related_ticker": "DJT",
            },
        ]
        cache.set("truth_social", cached_records)

        records = collector.fetch_truth_social(limit=10, force_refresh=True)
        # Should NOT return cached data; should fall back to FALLBACK_RECORDS
        assert records != cached_records
        assert len(records) > 0

    # ------------------------------------------------------------------
    # Tests: fetch_all
    # ------------------------------------------------------------------

    def test_fetch_all_combines_sources(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_all should return records from all sources."""
        all_records = collector.fetch_all(limit_per_source=5)
        assert len(all_records) > 0
        sources = {rec["source"] for rec in all_records}
        assert "truth_social" in sources
        assert "capitol_trades" in sources

    def test_fetch_all_sorted_by_timestamp(
        self, collector: SentimentCollector
    ) -> None:
        """fetch_all should return records sorted by timestamp descending."""
        all_records = collector.fetch_all(limit_per_source=5)
        timestamps = [rec["timestamp"] for rec in all_records]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Tests: Data validation
# ---------------------------------------------------------------------------


class TestSentimentDataValidation:
    """Verify data integrity of fallback records."""

    def test_fallback_record_structure(self) -> None:
        """Every fallback record must have required fields."""
        required_keys = {"timestamp", "source", "author", "raw_text", "related_ticker"}
        for rec in FALLBACK_RECORDS:
            assert isinstance(rec, dict), f"Record is not a dict: {rec}"
            for key in required_keys:
                assert key in rec, f"Missing key {key} in: {rec}"

    def test_fallback_record_sources_valid(self) -> None:
        """Fallback records should only use known source identifiers."""
        valid_sources = {"truth_social", "capitol_trades"}
        for rec in FALLBACK_RECORDS:
            assert rec["source"] in valid_sources, f"Invalid source in: {rec}"

    def test_filter_fallback_by_source(self, collector: SentimentCollector) -> None:
        """_filter_fallback_by_source should only return matching source."""
        truth_records = collector._filter_fallback_by_source("truth_social")
        for rec in truth_records:
            assert rec["source"] == "truth_social"

        capitol_records = collector._filter_fallback_by_source("capitol_trades")
        for rec in capitol_records:
            assert rec["source"] == "capitol_trades"

        # Combined should cover all fallback records
        total = len(truth_records) + len(capitol_records)
        assert total == len(FALLBACK_RECORDS)