"""
test_market_fetcher.py - Unit tests for the market_fetcher module.

All yfinance network calls are mocked via pytest-mock to ensure tests
are deterministic and do not depend on external connectivity.

Mock patterns:
- yf.download(...) is mocked at the module level via yfinance.download.
- MarketDataCache file I/O is tested with tmp_path.
- date.today() is frozen via unittest.mock.patch for cache freshness tests.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import PropertyMock

import pandas as pd
import pytest

from src.market_fetcher import MarketDataCache, MarketFetcher
import yfinance as yf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_daily_df() -> pd.DataFrame:
    """Return a DataFrame shaped like yfinance daily output."""
    idx = pd.date_range("2026-01-05", periods=5, freq="B", name="Date")
    data = {
        "Open": [150.0, 151.0, 152.0, 149.0, 153.0],
        "High": [155.0, 153.0, 154.0, 152.0, 156.0],
        "Low":  [148.0, 150.0, 150.5, 148.5, 151.5],
        "Close":[152.0, 152.5, 151.0, 150.0, 154.0],
        "Volume":[10000, 12000, 11000, 9000, 13000],
    }
    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_product([df.columns, ["AAPL"]])
    return df


def _make_mock_weekly_df() -> pd.DataFrame:
    """Return a DataFrame shaped like yfinance weekly output."""
    idx = pd.date_range("2026-01-05", periods=3, freq="W", name="Date")
    data = {
        "Open":  [148.0, 152.0, 153.0],
        "High":  [156.0, 158.0, 159.0],
        "Low":   [147.0, 150.0, 151.0],
        "Close": [155.0, 153.0, 158.0],
        "Volume":[55000, 60000, 62000],
    }
    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_product([df.columns, ["AAPL"]])
    return df


# ---------------------------------------------------------------------------
# MarketDataCache tests
# ---------------------------------------------------------------------------

class TestMarketDataCache:
    """Tests for the local JSON cache layer."""

    def test_get_returns_none_when_no_cache(self, tmp_path: Path):
        """Cache miss should return None silently."""
        cache = MarketDataCache(cache_dir=tmp_path)
        result = cache.get("AAPL", "daily")
        assert result is None

    def test_set_and_get_roundtrip(self, tmp_path: Path):
        """After set(), get() should return the same data."""
        cache = MarketDataCache(cache_dir=tmp_path)
        df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "Close": [102.0, 103.0],
            "Volume": [5000, 6000],
        }, index=pd.DatetimeIndex(["2026-01-01", "2026-01-02"], name="Date"))

        ref_date = date(2026, 1, 3)
        cache.set("AAPL", "daily", df, ref_date=ref_date)
        result = cache.get("AAPL", "daily", ref_date=ref_date)
        assert result is not None
        pd.testing.assert_frame_equal(result, df)

    def test_get_returns_none_on_stale_cache(self, tmp_path: Path):
        """Cache from a different date should be treated as a miss."""
        cache = MarketDataCache(cache_dir=tmp_path)
        df = pd.DataFrame({
            "Open": [100.0],
            "Close": [102.0],
            "Volume": [5000],
        }, index=pd.DatetimeIndex(["2026-01-01"], name="Date"))

        cache.set("AAPL", "daily", df, ref_date=date(2026, 1, 1))
        result = cache.get("AAPL", "daily", ref_date=date(2026, 1, 3))
        assert result is None

    def test_get_returns_none_on_corrupted_cache(self, tmp_path: Path):
        """A corrupt cache file should not crash; returns None."""
        cache_file = tmp_path / "AAPL_daily.json"
        cache_file.write_text("{invalid json}", encoding="utf-8")
        cache = MarketDataCache(cache_dir=tmp_path)
        result = cache.get("AAPL", "daily", ref_date=date.today())
        assert result is None

    def test_clear_removes_cache_entry(self, tmp_path: Path):
        """clear() should delete the cache file."""
        cache = MarketDataCache(cache_dir=tmp_path)
        df = pd.DataFrame({
            "Open": [100.0],
            "Close": [102.0],
            "Volume": [5000],
        }, index=pd.DatetimeIndex(["2026-01-01"], name="Date"))
        cache.set("AAPL", "daily", df, ref_date=date(2026, 1, 1))
        assert cache.get("AAPL", "daily", ref_date=date(2026, 1, 1)) is not None

        cache.clear("AAPL", "daily")
        assert cache.get("AAPL", "daily", ref_date=date(2026, 1, 1)) is None


# ---------------------------------------------------------------------------
# MarketFetcher tests (yfinance mocked)
# ---------------------------------------------------------------------------

class TestMarketFetcher:
    """Tests for MarketFetcher with mocked yfinance."""

    def test_fetch_daily_hits_network_on_cache_miss(self, mocker, tmp_path: Path):
        """When cache is empty, yf.download should be called."""
        mock_download = mocker.patch("yfinance.download", return_value=_make_mock_daily_df())
        cache = MarketDataCache(cache_dir=tmp_path)
        fetcher = MarketFetcher(cache=cache)

        df = fetcher.fetch_daily("AAPL", period="6mo", force_refresh=False)
        mock_download.assert_called_once()
        assert not df.empty
        # should have flattened columns => simple strings
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_fetch_daily_returns_cached_data(self, mocker, tmp_path: Path):
        """When cache is fresh, yf.download should NOT be called."""
        FROZEN_DATE = date(2026, 1, 3)

        cache = MarketDataCache(cache_dir=tmp_path, now=lambda: FROZEN_DATE)
        df_orig = pd.DataFrame({
            "Open": [200.0],
            "Close": [202.0],
            "Volume": [8000],
        }, index=pd.DatetimeIndex(["2026-01-01"], name="Date"))
        cache.set("AAPL", "daily", df_orig, ref_date=FROZEN_DATE)

        mock_download = mocker.patch("yfinance.download")
        fetcher = MarketFetcher(cache=cache)

        df = fetcher.fetch_daily("AAPL", period="6mo", force_refresh=False)

        mock_download.assert_not_called()
        pd.testing.assert_frame_equal(df, df_orig)

    def test_fetch_daily_force_refresh_skips_cache(self, mocker, tmp_path: Path):
        """force_refresh=True should call yfinance even when cache exists."""
        cache = MarketDataCache(cache_dir=tmp_path)
        df_orig = pd.DataFrame({
            "Open": [200.0],
            "Close": [202.0],
            "Volume": [8000],
        }, index=pd.DatetimeIndex(["2026-01-01"], name="Date"))
        cache.set("AAPL", "daily", df_orig, ref_date=date.today())

        mock_download = mocker.patch("yfinance.download", return_value=_make_mock_daily_df())
        fetcher = MarketFetcher(cache=cache)
        df = fetcher.fetch_daily("AAPL", period="6mo", force_refresh=True)
        mock_download.assert_called_once()
        assert not df.empty

    def test_fetch_weekly_returns_data(self, mocker, tmp_path: Path):
        """fetch_weekly should return flattened OHLCV data."""
        mock_download = mocker.patch("yfinance.download", return_value=_make_mock_weekly_df())
        fetcher = MarketFetcher(cache=MarketDataCache(cache_dir=tmp_path))
        df = fetcher.fetch_weekly("AAPL", period="1y", force_refresh=True)
        mock_download.assert_called_once()
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 3  # 3 weekly rows

    def test_fetch_raises_on_empty_response(self, mocker, tmp_path: Path):
        """When yfinance returns empty DataFrame, raise ValueError."""
        empty_df = pd.DataFrame()
        mocker.patch("yfinance.download", return_value=empty_df)
        fetcher = MarketFetcher(cache=MarketDataCache(cache_dir=tmp_path))
        with pytest.raises(ValueError, match="No data returned"):
            fetcher.fetch_daily("INVALID", period="1mo", force_refresh=True)

    def test_fetch_daily_cache_hit_from_prior_date(self, mocker, tmp_path: Path):
        """When get() returns data from cache, download is skipped."""
        FROZEN = date(2026, 1, 5)
        cache = MarketDataCache(cache_dir=tmp_path, now=lambda: FROZEN)
        df_cached = pd.DataFrame({
            "Open": [300.0],
            "High": [310.0],
            "Low":  [290.0],
            "Close":[305.0],
            "Volume":[15000],
        }, index=pd.DatetimeIndex(["2026-01-05"], name="Date"))
        cache.set("NVDA", "daily", df_cached, ref_date=FROZEN)

        mock_download = mocker.patch("yfinance.download")
        fetcher = MarketFetcher(cache=cache)

        df = fetcher.fetch_daily("NVDA", period="6mo", force_refresh=False)

        mock_download.assert_not_called()
        pd.testing.assert_frame_equal(df, df_cached)
