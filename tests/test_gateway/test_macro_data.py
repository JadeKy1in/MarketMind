"""Tests for gateway/macro_data.py — macro/commodities/supply-chain fetchers."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.macro_data import (
    get_macro_indicator,
    get_cot_data,
    get_eia_inventory,
    _cache,
    _cache_locks,
    _clear_cache,
    _cot_signal,
    _parse_float,
    _parse_int,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "macro_data"


def _load_fixture(name: str) -> dict | list:
    """Load a canned JSON fixture from tests/fixtures/macro_data/."""
    path = FIXTURES_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. FRED — get_macro_indicator (BDI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFredBDI:
    """FRED API returns Baltic Dry Index data."""

    async def test_bdi_returns_indicator_dict(self):
        _clear_cache()
        fixture = _load_fixture("fred_bdi.json")

        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("BDI")

            assert result["indicator"] == "BDI"
            assert result["value"] == 1450.0
            assert result["date"] == "2026-05-15"
            assert result["source"] == "fred"
            assert result["cadence"] == "daily"
            assert "error" not in result

    async def test_bdi_case_insensitive(self):
        _clear_cache()
        fixture = _load_fixture("fred_bdi.json")

        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("bdi")
            assert result["indicator"] == "BDI"


# ---------------------------------------------------------------------------
# 2. FRED — get_macro_indicator (GSCPI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFredGSCPI:
    """FRED API returns Global Supply Chain Pressure Index data."""

    async def test_gscpi_returns_indicator_dict(self):
        _clear_cache()
        fixture = _load_fixture("fred_gscpi.json")

        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("GSCPI")

            assert result["indicator"] == "GSCPI"
            assert result["value"] == -0.35
            assert result["date"] == "2026-04-01"
            assert result["source"] == "fred"
            assert result["cadence"] == "monthly"
            assert "error" not in result


# ---------------------------------------------------------------------------
# 3. CFTC — get_cot_data (ES)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCFTCES:
    """CFTC SODA API returns COT data for S&P 500 futures."""

    async def test_es_returns_cot_dict(self):
        _clear_cache()
        fixture = _load_fixture("cftc_es.json")

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_cot_data("ES")

            assert result["asset"] == "ES"
            assert result["commercial_net"] == -50000
            assert result["speculative_net"] == 40000
            assert result["date"] == "2026-05-12"
            assert result["source"] == "cftc"
            assert result["cadence"] == "weekly"
            assert "signal" in result
            assert "error" not in result

    async def test_cot_signal_contrarian_bearish(self):
        """Extreme speculative long should yield contrarian bearish signal."""
        signal = _cot_signal("ES", 50000)
        assert "contrarian bearish" in signal.lower()

    async def test_cot_signal_contrarian_bullish(self):
        """Extreme speculative short should yield contrarian bullish signal."""
        signal = _cot_signal("CL", -50000)
        assert "contrarian bullish" in signal.lower()

    async def test_cot_signal_neutral(self):
        """Moderate positioning should yield neutral signal."""
        signal = _cot_signal("GC", 5000)
        assert "no directional signal" in signal


# ---------------------------------------------------------------------------
# 4. EIA — get_eia_inventory (crude)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEIACrude:
    """EIA API v2 returns weekly crude oil inventory data."""

    async def test_crude_returns_inventory_dict(self):
        _clear_cache()
        fixture = _load_fixture("eia_crude.json")

        with patch(
            "marketmind.gateway.macro_data._get_eia_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_eia_inventory("crude")

            assert result["product"] == "crude"
            assert result["inventory_mbbl"] == 455000
            assert result["date"] == "2026-05-09"
            assert result["source"] == "eia"
            assert result["cadence"] == "weekly"
            assert "error" not in result


# ---------------------------------------------------------------------------
# 5. Session cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionCache:
    """In-memory cache prevents duplicate HTTP calls during a session."""

    async def test_second_call_uses_cache(self):
        _clear_cache()
        fixture = _load_fixture("fred_bdi.json")

        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result1 = await get_macro_indicator("BDI")
            result2 = await get_macro_indicator("BDI")

            # Only one HTTP call — second hits cache
            mock_get.assert_called_once()
            assert result1 is result2


# ---------------------------------------------------------------------------
# 6. Degradation — API unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDegradation:
    """Graceful degradation when APIs are unavailable."""

    async def test_fred_no_key_returns_error(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="",
        ):
            result = await get_macro_indicator("BDI")
            assert result["error"] == "source_unavailable"
            assert "FRED_KEY" in result.get("detail", "")

    async def test_fred_unknown_indicator(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"observations": []}
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("BDI")
            assert result["error"] == "source_unavailable"

    async def test_cftc_empty_response(self):
        _clear_cache()
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = []
            mock_get.return_value = mock_resp

            result = await get_cot_data("ES")
            assert result["error"] == "source_unavailable"

    async def test_cftc_unknown_asset(self):
        _clear_cache()
        result = await get_cot_data("XX")
        assert result["error"] == "source_unavailable"
        assert "Unknown asset" in result.get("detail", "")

    async def test_eia_no_key_returns_error(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.macro_data._get_eia_key",
            return_value="",
        ):
            result = await get_eia_inventory("crude")
            assert result["error"] == "source_unavailable"
            assert "EIA_KEY" in result.get("detail", "")

    async def test_eia_unknown_product(self):
        _clear_cache()
        result = await get_eia_inventory("uranium")
        assert result["error"] == "source_unavailable"
        assert "Unknown product" in result.get("detail", "")

    async def test_unknown_indicator(self):
        _clear_cache()
        result = await get_macro_indicator("GDP")
        assert result["error"] == "source_unavailable"


# ---------------------------------------------------------------------------
# 7. HTTP error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHTTPErrors:
    """HTTP-level errors are caught and returned as source_unavailable."""

    async def test_http_500_handled(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            import httpx as _httpx
            mock_resp = AsyncMock()
            mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
                "Server error",
                request=AsyncMock(),
                response=AsyncMock(status_code=500),
            )
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("BDI")
            assert result["error"] == "source_unavailable"

    async def test_network_error_handled(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.macro_data._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Connection refused")

            result = await get_macro_indicator("BDI")
            assert result["error"] == "source_unavailable"


# ---------------------------------------------------------------------------
# 8. Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for helper parsing functions."""

    def test_parse_float_valid(self):
        assert _parse_float("1450") == 1450.0
        assert _parse_float("-0.35") == -0.35

    def test_parse_float_invalid(self):
        assert _parse_float(None) == 0.0
        assert _parse_float("abc") == 0.0

    def test_parse_int_valid(self):
        assert _parse_int("45000") == 45000
        assert _parse_int("-5000") == -5000

    def test_parse_int_invalid(self):
        assert _parse_int(None) == 0
        assert _parse_int("abc") == 0
