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
            # BDI proxy: PPI Deep Sea Freight (the old series id did not exist on FRED)
            assert result["series_id"] == "PCU483111483111"
            assert result["cadence"] == "monthly"
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
    """GSCPI is not a FRED series: it comes from the NY Fed CSV (current vintage = last column)."""

    async def test_gscpi_returns_indicator_dict(self):
        _clear_cache()
        csv_text = (
            "Date,Jul-26,Aug-26,Sep-26\n"
            "31-Jul-2026,0.50,0.52,0.55\n"
            "31-Aug-2026,#N/A,#N/A,1.06\n"
            "30-Sep-2026,#N/A,#N/A,#N/A\n"
            ",,,\n"
        )
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = csv_text
            mock_get.return_value = mock_resp

            result = await get_macro_indicator("GSCPI")

            assert "newyorkfed.org" in mock_get.call_args.args[0]
            assert result["indicator"] == "GSCPI"
            assert result["value"] == 1.06
            assert result["date"] == "2026-08-31"
            assert result["source"] == "nyfed"
            assert result["cadence"] == "monthly"
            assert "error" not in result

    async def test_gscpi_http_error_is_unavailable(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock,
                          side_effect=httpx.ConnectError("down")):
            result = await get_macro_indicator("GSCPI")
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
async def test_fred_skips_dot_placeholder_and_keeps_its_date():
    """Newest FRED observation "." (holiday) -> first numeric one, with its own date."""
    _clear_cache()
    payload = {"observations": [{"date": "2026-09-28", "value": "."},
                                {"date": "2026-09-01", "value": "101.5"}]}
    with patch("marketmind.gateway.macro_data._get_fred_key", return_value="test_key"), \
            patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = payload
        mock_get.return_value = mock_resp
        result = await get_macro_indicator("BDI")
    assert "limit=5" in mock_get.call_args.args[0]
    assert result["value"] == 101.5
    assert result["date"] == "2026-09-01"


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
            mock_resp = MagicMock()
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
            mock_resp = MagicMock()
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
            mock_resp = MagicMock()
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
            mock_resp = MagicMock()
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


# ---------------------------------------------------------------------------
# 9. EIA series filter and missing values (red-team fix 2026-09-29)
# ---------------------------------------------------------------------------


def _eia_payload(series, value="206046", units="MBBL", period="2026-09-18"):
    return {"response": {"data": [{"period": period, "series": series, "value": value,
                                   "units": units}]}}


async def _eia_call(product, payload):
    _clear_cache()
    with patch("marketmind.gateway.macro_data._get_eia_key", return_value="test_key"), \
         patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = payload
        mock_get.return_value = mock_resp
        result = await get_eia_inventory(product)
        return result, mock_get.call_args


@pytest.mark.asyncio
class TestEIASeries:

    @pytest.mark.parametrize("product, series", [
        ("crude", "WCESTUS1"), ("gasoline", "WGTSTUS1"), ("distillate", "WDISTUS1"),
    ])
    async def test_each_product_requests_its_own_series(self, product, series):
        result, call = await _eia_call(product, _eia_payload(series))
        assert call.kwargs["params"]["facets[series][]"] == series
        assert "api_key=" not in str(call.args)          # key sent in params, not the URL
        assert result["series"] == series and result["units"] == "MBBL"
        assert result["inventory_mbbl"] == 206046.0 and result["date"] == "2026-09-18"

    async def test_wrong_series_is_unavailable(self):
        result, _ = await _eia_call("gasoline", _eia_payload("WCESTUS1"))
        assert result["error"] == "source_unavailable" and "WCESTUS1" in result["detail"]

    async def test_wrong_units_is_unavailable(self):
        result, _ = await _eia_call("crude", _eia_payload("WCESTUS1", units="MBBL/D"))
        assert result["error"] == "source_unavailable"

    @pytest.mark.parametrize("value", [None, "", "NA", "nan"])
    async def test_missing_value_is_unavailable_never_zero(self, value):
        result, _ = await _eia_call("crude", _eia_payload("WCESTUS1", value=value))
        assert result["error"] == "source_unavailable"
        assert "inventory_mbbl" not in result
