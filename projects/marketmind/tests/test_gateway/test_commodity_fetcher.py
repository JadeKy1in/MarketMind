"""Tests for gateway/commodity_fetcher.py — commodity supply/demand data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.commodity_fetcher import (
    get_lme_metal_inventory,
    get_usda_wasde,
    get_eia_extended,
    _cache,
    _clear_cache,
    _parse_float,
    _extract_lme_inventory,
    _extract_wasde_value,
)


@pytest.mark.asyncio
class TestLMEMetalInventory:
    """LME API returns warehouse inventory data."""

    async def test_lme_inventory_valid_metal(self):
        _clear_cache()
        fixture = {"metal": "copper", "warehouse_stocks": 125000, "date": "2026-05-19"}
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("copper")

        assert result["metal"] == "copper"
        assert result["inventory_tonnes"] == 125000.0
        assert result["source"] == "lme"
        assert "error" not in result

    async def test_lme_inventory_unknown_metal(self):
        _clear_cache()
        result = await get_lme_metal_inventory("platinum")
        assert result["error"] == "source_unavailable"
        assert "Unknown metal" in result.get("detail", "")

    async def test_lme_case_insensitive(self):
        _clear_cache()
        fixture = {"metal": "aluminium", "warehouse_stocks": 500000}
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("ALUMINUM")
        assert result["metal"] == "aluminum"
        assert result["inventory_tonnes"] == 500000.0

    async def test_lme_nested_data_structure(self):
        _clear_cache()
        fixture = {"data": {"inventory": 32000, "on_warrant": 28000}}
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("zinc")
        assert result["inventory_tonnes"] == 32000.0

    async def test_lme_list_response(self):
        _clear_cache()
        fixture = [{"inventory": 78000, "metal": "nickel"}]
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("nickel")
        assert result["inventory_tonnes"] == 78000.0

    async def test_lme_empty_response_returns_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {}
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("copper")
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestUSDAWASDE:
    """USDA WASDE data fetcher."""

    async def test_usda_wasde_graceful(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.text = "<html><body>No data tables</body></html>"
            mock_get.return_value = mock_resp
            result = await get_usda_wasde()
        assert result["error"] == "source_unavailable"

    async def test_usda_wasde_http_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=AsyncMock(), response=AsyncMock(status_code=503))
            mock_get.return_value = mock_resp
            result = await get_usda_wasde()
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestEIAExtended:
    """EIA API v2 extended data fetcher."""

    async def test_eia_extended_valid_product(self):
        _clear_cache()
        fixture = {
            "response": {
                "id": "natural-gas/stor/wkly",
                "data": [{"period": "2026-05-15", "value": 3100, "units": "Bcf"}],
            }
        }
        with patch(
            "marketmind.gateway.commodity_fetcher._get_eia_key", return_value="test_key"
        ), patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            result = await get_eia_extended("natgas_storage")

        assert result["product"] == "natgas_storage"
        assert result["value"] == 3100.0
        assert result["source"] == "eia"
        assert "error" not in result

    async def test_eia_extended_unknown_product(self):
        _clear_cache()
        result = await get_eia_extended("uranium")
        assert result["error"] == "source_unavailable"

    async def test_eia_extended_no_key(self):
        _clear_cache()
        with patch("marketmind.gateway.commodity_fetcher._get_eia_key", return_value=""):
            result = await get_eia_extended("crude_production")
        assert result["error"] == "source_unavailable"


@pytest.mark.asyncio
class TestCommodityCache:
    """In-memory cache prevents duplicate HTTP calls."""

    async def test_commodity_cache_works(self):
        _clear_cache()
        fixture = {"metal": "copper", "warehouse_stocks": 125000}
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp
            r1 = await get_lme_metal_inventory("copper")
            r2 = await get_lme_metal_inventory("copper")
            mock_get.assert_called_once()
            assert r1 is r2


@pytest.mark.asyncio
class TestCommodityDegradation:
    """Graceful degradation when APIs are unavailable."""

    async def test_lme_http_error_handled(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=AsyncMock(), response=AsyncMock(status_code=500))
            mock_get.return_value = mock_resp
            result = await get_lme_metal_inventory("copper")
        assert result["error"] == "source_unavailable"

    async def test_lme_network_error_handled(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = OSError("Connection refused")
            result = await get_lme_metal_inventory("aluminum")
        assert result["error"] == "source_unavailable"


class TestCommodityHelpers:
    def test_parse_float_valid(self):
        assert _parse_float("125000") == 125000.0
        assert _parse_float("-0.5") == -0.5

    def test_parse_float_invalid(self):
        assert _parse_float(None) == 0.0

    def test_extract_lme_inventory_direct(self):
        assert _extract_lme_inventory({"warehouse_stocks": 125000}) == 125000.0

    def test_extract_lme_inventory_nested(self):
        assert _extract_lme_inventory({"data": {"inventory": 78000}}) == 78000.0

    def test_extract_lme_inventory_list(self):
        assert _extract_lme_inventory([{"inventory": 32000}]) == 32000.0

    def test_extract_lme_inventory_none(self):
        assert _extract_lme_inventory({}) is None
        assert _extract_lme_inventory({"other": "data"}) is None

    def test_extract_wasde_value_found(self):
        html = "Corn ending stocks forecast at 1,540 million bushels for 2026/27"
        assert _extract_wasde_value(html, "corn") == 1540.0

    def test_extract_wasde_value_not_found(self):
        assert _extract_wasde_value("No commodity data here", "corn") is None
