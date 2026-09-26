"""Tests for gateway/vol_global_fetcher.py — global volatility index data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marketmind.gateway.vol_global_fetcher import (
    get_vvix,
    get_global_vol_indexes,
    _cache,
    _clear_cache,
)


# ===================================================================
# VVIX tests
# ===================================================================


@pytest.mark.asyncio
class TestVVIX:
    """CBOE VVIX via yfinance."""

    async def test_vvix_returns_dict(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = {"value": 95.20, "date": "2026-05-20"}
            result = await get_vvix()

        assert result["indicator"] == "vvix"
        assert result["value"] == 95.20
        assert result["source"] == "cboe"
        assert "error" not in result
        mock_yf.assert_called_once()

    async def test_vvix_yfinance_failure_returns_error(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = None
            result = await get_vvix()

        assert result["error"] == "source_unavailable"


# ===================================================================
# Global Vol Indexes tests
# ===================================================================


@pytest.mark.asyncio
class TestGlobalVolIndexes:
    """Global volatility indexes via yfinance multi-ticker."""

    async def test_global_vol_indexes_returns_dict(self):
        _clear_cache()
        yf_responses = {
            "^V2TX": {"value": 22.15, "date": "2026-05-20"},
            "^VNKY": {"value": 25.30, "date": "2026-05-20"},
            "^VKOSPI": {"value": 18.75, "date": "2026-05-20"},
        }

        async def mock_yf_raw(ticker: str):
            return yf_responses.get(ticker)

        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            side_effect=mock_yf_raw
        ):
            result = await get_global_vol_indexes()

        assert result["indicator"] == "global_vol"
        assert result["vstoxx"] == 22.15
        assert result["vnky"] == 25.30
        assert result["vkospi"] == 18.75
        assert result["source"] == "multi"
        assert "error" not in result

    async def test_global_vol_partial_failure_returns_partial_data(self):
        """When some tickers fail, return available data with zeros for failures."""
        _clear_cache()

        async def mock_yf_raw(ticker: str):
            if ticker == "^V2TX":
                return {"value": 22.15, "date": "2026-05-20"}
            return None

        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            side_effect=mock_yf_raw
        ):
            result = await get_global_vol_indexes()

        assert result["indicator"] == "global_vol"
        assert result["vstoxx"] == 22.15
        assert result["vnky"] == 0.0
        assert result["vkospi"] == 0.0
        assert "error" not in result

    async def test_global_vol_all_failures_returns_error(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = None
            result = await get_global_vol_indexes()

        assert result["error"] == "source_unavailable"


# ===================================================================
# Cache tests
# ===================================================================


@pytest.mark.asyncio
class TestVolGlobalCache:
    """In-memory cache prevents duplicate yfinance calls."""

    async def test_vvix_cache_works(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_global_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = {"value": 95.20, "date": "2026-05-20"}
            r1 = await get_vvix()
            r2 = await get_vvix()
            mock_yf.assert_called_once()
            assert r1 is r2
