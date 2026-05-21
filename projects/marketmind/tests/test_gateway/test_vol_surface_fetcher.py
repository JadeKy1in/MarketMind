"""Tests for gateway/vol_surface_fetcher.py — volatility surface data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.vol_surface_fetcher import (
    get_vix_term_structure,
    get_skew_index,
    get_vvix,
    get_global_vol_indexes,
    _cache,
    _clear_cache,
    _parse_float,
    _find_column,
)


# ---------------------------------------------------------------------------
# yfinance mock helper
# ---------------------------------------------------------------------------

class _FakeYfHistory:
    """Fake DataFrame-like object to mock yfinance.Ticker.history()."""
    def __init__(self, close_val: float, date_str: str = "2026-05-20"):
        self._close = close_val
        self._date_str = date_str
        self.empty = False

    @property
    def iloc(self):
        return _FakeIloc(self)

    def __bool__(self):
        return True


class _FakeIloc:
    def __init__(self, parent: _FakeYfHistory):
        self._parent = parent

    def __getitem__(self, idx):
        return _FakeLatestRow(self._parent._close, self._parent._date_str)


class _FakeLatestRow:
    def __init__(self, close_val: float, date_str: str):
        self._close = close_val
        self._name = _FakeTimestamp(date_str)

    def __getitem__(self, key):
        if key == "Close":
            return self._close
        raise KeyError(key)


class _FakeTimestamp:
    def __init__(self, date_str: str):
        self._date_str = date_str

    def strftime(self, fmt: str) -> str:
        return self._date_str

    def __str__(self):
        return self._date_str


def _make_fake_close(val: float, date_str: str = "2026-05-20"):
    """Create a fake yfinance result tuple for asyncio.to_thread mock."""
    return _FakeYfHistory(val, date_str)


# ===================================================================
# VIX Term Structure tests
# ===================================================================


@pytest.mark.asyncio
class TestVIXTermStructure:
    """CBOE VIX term structure CSV returns futures data."""

    async def test_vix_term_structure_returns_dict(self):
        _clear_cache()
        csv_text = (
            "Trade Date,Futures,Price\r\n"
            "2026-05-19,VX/Jun 2026,18.45\r\n"
            "2026-05-19,VX/Jul 2026,19.80\r\n"
            "2026-05-20,VX/Jun 2026,18.90\r\n"
            "2026-05-20,VX/Jul 2026,20.15\r\n"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp
            result = await get_vix_term_structure()

        assert result["indicator"] == "vix_term_structure"
        assert result["front_month"] == 18.90
        assert result["next_month"] == 20.15
        assert result["contango_pct"] == pytest.approx(6.61, abs=0.1)
        assert result["in_backwardation"] is False
        assert result["source"] == "cboe"
        assert "error" not in result

    async def test_vix_term_structure_backwardation(self):
        _clear_cache()
        csv_text = (
            "Trade Date,Futures,Price\r\n"
            "2026-05-20,VX/Jun 2026,22.00\r\n"
            "2026-05-20,VX/Jul 2026,20.50\r\n"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp
            result = await get_vix_term_structure()

        assert result["in_backwardation"] is True
        assert result["contango_pct"] < 0

    async def test_vix_term_empty_csv_returns_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = ""
            mock_get.return_value = mock_resp
            result = await get_vix_term_structure()
        assert result["error"] == "source_unavailable"


# ===================================================================
# SKEW Index tests
# ===================================================================


@pytest.mark.asyncio
class TestSkewIndex:
    """CBOE SKEW Index (tail risk) with yfinance fallback."""

    async def test_skew_index_from_cboe_returns_dict(self):
        _clear_cache()
        html = (
            '<html><body>'
            '<script>var data = {"SKEW": 142.35, "lastSalePrice": 142.35};</script>'
            '</body></html>'
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = html
            mock_get.return_value = mock_resp
            result = await get_skew_index()

        assert result["indicator"] == "skew"
        assert result["value"] == 142.35
        assert result["source"] == "cboe"
        assert "error" not in result

    async def test_skew_index_falls_back_to_yfinance(self):
        """When CBOE page has no extractable value, fall back to yfinance."""
        _clear_cache()
        html = "<html><body>Nothing useful here</body></html>"

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = html
            mock_get.return_value = mock_resp
            with patch(
                "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
                new_callable=AsyncMock
            ) as mock_yf:
                mock_yf.return_value = {"value": 138.50, "date": "2026-05-20"}
                result = await get_skew_index()

        assert result["indicator"] == "skew"
        assert result["value"] == 138.50
        assert result["source"] == "cboe"
        assert "error" not in result
        mock_yf.assert_called_once()

    async def test_skew_index_all_failures_returns_error(self):
        """When both CBOE and yfinance fail, return error."""
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = "<html><body>Nothing</body></html>"
            mock_get.return_value = mock_resp
            with patch(
                "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
                new_callable=AsyncMock
            ) as mock_yf:
                mock_yf.return_value = None
                result = await get_skew_index()

        assert result["error"] == "source_unavailable"


# ===================================================================
# VVIX tests
# ===================================================================


@pytest.mark.asyncio
class TestVVIX:
    """CBOE VVIX via yfinance."""

    async def test_vvix_returns_dict(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
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
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
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
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
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
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
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
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = None
            result = await get_global_vol_indexes()

        assert result["error"] == "source_unavailable"


# ===================================================================
# Cache tests
# ===================================================================


@pytest.mark.asyncio
class TestVolSurfaceCache:
    """In-memory cache prevents duplicate HTTP calls."""

    async def test_cache_works(self):
        _clear_cache()
        csv_text = (
            "Trade Date,Futures,Price\r\n"
            "2026-05-20,VX/Jun 2026,18.90\r\n"
            "2026-05-20,VX/Jul 2026,20.15\r\n"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp
            r1 = await get_vix_term_structure()
            r2 = await get_vix_term_structure()
            mock_get.assert_called_once()
            assert r1 is r2

    async def test_vvix_cache_works(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.vol_surface_fetcher._fetch_yfinance_raw",
            new_callable=AsyncMock
        ) as mock_yf:
            mock_yf.return_value = {"value": 95.20, "date": "2026-05-20"}
            r1 = await get_vvix()
            r2 = await get_vvix()
            mock_yf.assert_called_once()
            assert r1 is r2


# ===================================================================
# Graceful degradation tests
# ===================================================================


@pytest.mark.asyncio
class TestVolSurfaceDegradation:
    """Graceful degradation when APIs are unavailable."""

    async def test_graceful_degradation(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=AsyncMock(),
                response=AsyncMock(status_code=500),
            )
            mock_get.return_value = mock_resp
            vix = await get_vix_term_structure()
            assert vix["error"] == "source_unavailable"

    async def test_network_error_handled(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = OSError("Connection refused")
            result = await get_vix_term_structure()
        assert result["error"] == "source_unavailable"


# ===================================================================
# Helper function tests
# ===================================================================


class TestVolSurfaceHelpers:
    def test_parse_float_valid(self):
        assert _parse_float("18.90") == 18.90
        assert _parse_float("-0.35") == -0.35
        assert _parse_float("142") == 142.0

    def test_parse_float_invalid(self):
        assert _parse_float(None) == 0.0
        assert _parse_float("abc") == 0.0
        assert _parse_float("") == 0.0

    def test_find_column_exact_match(self):
        row = {"Trade Date": "2026-05-20", "Price": "18.90"}
        assert _find_column(row, ["Trade Date", "date"]) == "Trade Date"
        assert _find_column(row, ["price", "settle"]) == "Price"

    def test_find_column_case_insensitive(self):
        row = {"trade date": "2026-05-20", "PRICE": "18.90"}
        assert _find_column(row, ["Trade Date"]) == "trade date"
        assert _find_column(row, ["Price", "Settle"]) == "PRICE"

    def test_find_column_no_match(self):
        row = {"a": "1", "b": "2"}
        assert _find_column(row, ["date", "price"]) is None
