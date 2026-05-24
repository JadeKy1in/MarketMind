"""Tests for gateway/fred_client.py — FRED macro/finance series expansion."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.fred_client import (
    get_fred_series,
    get_fred_batch,
    get_all_fred_data,
    get_fred_for_shadow,
    SHADOW_FRED_SERIES,
    _FRED_SERIES,
    _cache,
    _clear_cache,
)


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fred_data"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Single series fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetFredSeries:
    """Single FRED series lookup."""

    async def test_dgs10_returns_series_dict(self):
        _clear_cache()
        fixture = _load_fixture("fred_dgs10.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_fred_series("DGS10")

            assert result["series_key"] == "DGS10"
            assert result["series_id"] == "DGS10"
            assert result["value"] > 0
            assert result["source"] == "fred"
            assert result["cadence"] == "daily"
            assert result["unit"] == "%"
            assert "error" not in result

    async def test_case_insensitive(self):
        _clear_cache()
        fixture = _load_fixture("fred_dgs10.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_fred_series("dgs10")
            assert result["series_key"] == "DGS10"

    async def test_gdp_quarterly_cadence(self):
        _clear_cache()
        fixture = _load_fixture("fred_gdp.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_fred_series("GDP")
            assert result["cadence"] == "quarterly"
            assert result["unit"] == "B USD"

    async def test_nfci_negative_value(self):
        _clear_cache()
        fixture = _load_fixture("fred_nfci.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            result = await get_fred_series("NFCI")
            # NFCI negative = loose financial conditions
            assert result["source"] == "fred"
            assert "error" not in result


# ---------------------------------------------------------------------------
# 2. Batch fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetFredBatch:
    """Concurrent batch FRED fetching."""

    async def test_batch_returns_all_keys(self):
        _clear_cache()
        fixture = _load_fixture("fred_dgs10.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            results = await get_fred_batch(["DGS10", "GDP", "NFCI"])
            assert set(results.keys()) == {"DGS10", "GDP", "NFCI"}
            for r in results.values():
                assert "source" in r or "error" in r

    async def test_batch_ignores_unknown_keys(self):
        _clear_cache()
        results = await get_fred_batch(["ZZZZZ", "DGS10"])
        # ZZZZZ is ignored, DGS10 fetched
        assert "ZZZZZ" not in results
        assert "DGS10" in results

    async def test_batch_empty_list(self):
        _clear_cache()
        results = await get_fred_batch([])
        assert results == {}


# ---------------------------------------------------------------------------
# 3. Shadow-specific distribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestShadowDistribution:
    """Per-shadow FRED series filtering."""

    async def test_yield_whisperer_gets_bond_data(self):
        _clear_cache()
        keys = SHADOW_FRED_SERIES.get("expert:bonds:yield_whisperer", [])
        assert "DGS10" in keys
        assert "DFII10" in keys
        assert "T10Y2Y" in keys
        assert "BAMLC0A0CM" in keys

    async def test_intraday_scalper_gets_nothing(self):
        keys = SHADOW_FRED_SERIES.get("momentum:intraday:scalper", [])
        assert keys == []

    async def test_cycle_reader_gets_broad_coverage(self):
        keys = SHADOW_FRED_SERIES.get("expert:macro:cycle_reader", [])
        assert len(keys) >= 8
        assert "GDP" in keys
        assert "SP500" in keys
        assert "NFCI" in keys

    async def test_crash_hunter_gets_valuation(self):
        keys = SHADOW_FRED_SERIES.get("contrarian:crash:hunter", [])
        assert "SP500" in keys
        assert "BAMLC0A0CM" in keys

    async def test_get_fred_for_shadow_calls_batch(self):
        _clear_cache()
        fixture = _load_fixture("fred_dgs10.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            results = await get_fred_for_shadow("expert:bonds:yield_whisperer")
            assert len(results) > 0
            for r in results.values():
                assert "source" in r or "error" in r


# ---------------------------------------------------------------------------
# 4. Session cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionCache:
    """In-memory cache prevents duplicate HTTP calls."""

    async def test_second_call_uses_cache(self):
        _clear_cache()
        fixture = _load_fixture("fred_dgs10.json")

        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            r1 = await get_fred_series("DGS10")
            r2 = await get_fred_series("DGS10")

            mock_get.assert_called_once()
            assert r1 is r2


# ---------------------------------------------------------------------------
# 5. Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDegradation:
    """Graceful degradation when API is unavailable."""

    async def test_no_key_returns_error(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="",
        ):
            result = await get_fred_series("DGS10")
            assert result["error"] == "source_unavailable"
            assert "FRED_KEY" in result.get("detail", "")

    async def test_unknown_series_key(self):
        _clear_cache()
        result = await get_fred_series("MARS_TEMP")
        assert result["error"] == "source_unavailable"

    async def test_empty_observations(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"observations": []}
            mock_get.return_value = mock_resp

            result = await get_fred_series("DGS10")
            assert result["error"] == "source_unavailable"

    async def test_null_value_in_observation(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {
                "observations": [{"date": "2026-05-20", "value": "."}]
            }
            mock_get.return_value = mock_resp

            result = await get_fred_series("DGS10")
            assert result["error"] == "source_unavailable"


# ---------------------------------------------------------------------------
# 6. HTTP error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHTTPErrors:
    """HTTP errors are caught and returned as source_unavailable."""

    async def test_http_500_handled(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=AsyncMock(),
                response=AsyncMock(status_code=500),
            )
            mock_get.return_value = mock_resp

            result = await get_fred_series("DGS10")
            assert result["error"] == "source_unavailable"

    async def test_network_error_handled(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.fred_client._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Connection refused")

            result = await get_fred_series("DGS10")
            assert result["error"] == "source_unavailable"


# ---------------------------------------------------------------------------
# 7. Catalog consistency
# ---------------------------------------------------------------------------


class TestCatalogConsistency:
    """Series catalog is internally consistent."""

    def test_all_series_have_four_tuple_values(self):
        for key, info in _FRED_SERIES.items():
            assert len(info) == 4, f"{key}: expected 4-tuple, got {len(info)}"
            sid, label, cadence, unit = info
            assert isinstance(sid, str) and sid, f"{key}: empty series_id"
            assert isinstance(label, str) and label, f"{key}: empty label"
            assert cadence in ("daily", "weekly", "monthly", "quarterly"), (
                f"{key}: bad cadence {cadence}"
            )

    def test_shadow_fred_series_keys_valid(self):
        for shadow_id, keys in SHADOW_FRED_SERIES.items():
            for key in keys:
                assert key in _FRED_SERIES, (
                    f"Shadow {shadow_id} references unknown series {key}"
                )

    def test_known_series_count(self):
        # Expect 30+ series in the catalog
        assert len(_FRED_SERIES) >= 30
