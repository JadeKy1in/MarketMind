"""Tests for gateway/sentiment_fetcher.py — sentiment/positioning data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.sentiment_fetcher import (
    get_cboe_pc_ratio,
    get_cnn_fear_greed,
    get_aaii_sentiment,
    _cache,
    _clear_cache,
    _fg_rating,
    _parse_float,
)


@pytest.mark.asyncio
class TestCBOEPCRatio:
    """CBOE CSV returns Put/Call ratio data."""

    async def test_cboe_pc_ratio_returns_dict(self):
        _clear_cache()
        csv_text = (
            "Date,Total P/C Ratio,Equity P/C Ratio,ETF P/C Ratio\n"
            "2026-05-18,0.85,0.72,1.10\n"
            "2026-05-19,0.92,0.78,1.25\n"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp
            result = await get_cboe_pc_ratio()

        assert result["indicator"] == "put_call_ratio"
        assert result["total"] == 0.92
        assert result["equity"] == 0.78
        assert result["etf"] == 1.25
        assert result["source"] == "cboe"
        assert "error" not in result

    async def test_cboe_empty_csv_returns_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = ""
            mock_get.return_value = mock_resp
            result = await get_cboe_pc_ratio()
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestCNNFearGreed:
    """CNN JSON returns Fear & Greed Index data."""

    async def test_cnn_fear_greed_returns_dict(self):
        _clear_cache()
        fixture = {
            "fear_and_greed": {
                "score": "42",
                "rating": "fear",
                "timestamp": "2026-05-19T16:00:00Z",
            },
            "fear_and_greed_historical": {
                "data": [{"x": "2026-05-19", "y": 42}]
            },
        }
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_cnn_fear_greed()

        assert result["indicator"] == "fear_greed"
        assert result["value"] == 42.0
        assert result["rating"] == "fear"
        assert result["source"] == "cnn"
        assert "error" not in result

    async def test_cnn_extreme_fear_rating(self):
        assert _fg_rating(10) == "extreme_fear"
        assert _fg_rating(25) == "extreme_fear"

    async def test_cnn_extreme_greed_rating(self):
        assert _fg_rating(76) == "extreme_greed"

    async def test_cnn_neutral_rating(self):
        assert _fg_rating(50) == "neutral"

    async def test_cnn_missing_key_returns_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"other_key": {}}
            mock_get.return_value = mock_resp
            result = await get_cnn_fear_greed()
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestAAIISentiment:
    """AAII web scraping returns sentiment survey data."""

    async def test_aaii_sentiment_returns_dict(self):
        _clear_cache()
        html = (
            "<html><body>"
            "<h2>AAII Sentiment Survey Results</h2>"
            "<p>Results for Week Ending May 14, 2026</p>"
            "<div>Bullish: <span class='number'>42.5%</span></div>"
            "<div>Neutral: <span class='number'>31.0%</span></div>"
            "<div>Bearish: <span class='number'>26.5%</span></div>"
            "</body></html>"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = html
            mock_get.return_value = mock_resp
            result = await get_aaii_sentiment()

        assert result["indicator"] == "aaii_sentiment"
        assert result["bullish_pct"] == 42.5
        assert result["bearish_pct"] == 26.5
        assert result["neutral_pct"] == 31.0
        assert result["spread"] == 16.0
        assert result["source"] == "aaii"
        assert "error" not in result

    async def test_aaii_scraping_failure_returns_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = "<html><body>Nothing useful</body></html>"
            mock_get.return_value = mock_resp
            result = await get_aaii_sentiment()
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestSentimentCache:
    """In-memory cache prevents duplicate HTTP calls."""

    async def test_sentiment_cache_works(self):
        _clear_cache()
        csv_text = "Date,Total P/C Ratio,Equity P/C Ratio,ETF P/C Ratio\n2026-05-19,0.92,0.78,1.25\n"
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp
            r1 = await get_cboe_pc_ratio()
            r2 = await get_cboe_pc_ratio()
            mock_get.assert_called_once()
            assert r1 is r2


@pytest.mark.asyncio
class TestSentimentDegradation:
    """Graceful degradation when APIs are unavailable."""

    async def test_sentiment_graceful_degradation(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=AsyncMock(), response=AsyncMock(status_code=500))
            mock_get.return_value = mock_resp
            cboe = await get_cboe_pc_ratio()
            cnn = await get_cnn_fear_greed()
            aaii = await get_aaii_sentiment()
            assert cboe["error"] == "source_unavailable"
            assert cnn["error"] == "source_unavailable"
            assert aaii["error"] == "source_unavailable"

    async def test_network_error_handled(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = OSError("Connection refused")
            result = await get_cnn_fear_greed()
        assert result["error"] == "source_unavailable"


class TestSentimentHelpers:
    def test_parse_float_valid(self):
        assert _parse_float("42.5") == 42.5
        assert _parse_float("-0.35") == -0.35

    def test_parse_float_invalid(self):
        assert _parse_float(None) == 0.0
        assert _parse_float("abc") == 0.0
