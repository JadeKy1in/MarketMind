"""Tests for gateway/crypto_onchain.py — crypto onchain data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.crypto_onchain import (
    get_defillama_tvl,
    get_stablecoin_mcap,
    get_blockchain_stats,
    get_crypto_fear_greed,
    _cache,
    _cache_locks,
    _clear_cache,
    _parse_float,
    _parse_int,
)

# ---------------------------------------------------------------------------
# Fixtures (inlined — no external fixture files needed)
# ---------------------------------------------------------------------------

DEFILLAMA_PROTOCOLS_FIXTURE = [
    {"name": "Lido", "tvl": 28500000000, "chain": "Ethereum", "category": "Liquid Staking"},
    {"name": "MakerDAO", "tvl": 8500000000, "chain": "Ethereum", "category": "CDP"},
    {"name": "AAVE", "tvl": 6200000000, "chain": "Multi-Chain", "category": "Lending"},
    {"name": "Uniswap", "tvl": 4500000000, "chain": "Multi-Chain", "category": "DEX"},
    {"name": "Curve", "tvl": 3200000000, "chain": "Multi-Chain", "category": "DEX"},
]

DEFILLAMA_DEX_FIXTURE = {
    "total24h": 5800000000,
}

DEFILLAMA_STABLECOINS_FIXTURE = [
    {"name": "Tether USD", "symbol": "USDT", "totalCirculatingUSD": 95000000000},
    {"name": "Circle USD", "symbol": "USDC", "totalCirculatingUSD": 35000000000},
    {"name": "DAI", "symbol": "DAI", "totalCirculatingUSD": 5200000000},
]

BLOCKCHAIN_HASHRATE_FIXTURE = {
    "name": "Hash Rate",
    "unit": "EH/s",
    "period": "day",
    "values": [
        {"x": 1747795200, "y": 520.5},
        {"x": 1747881600, "y": 535.2},
        {"x": 1747968000, "y": 542.8},
    ],
}

BLOCKCHAIN_ADDRESSES_FIXTURE = {
    "name": "Unique Addresses Used",
    "unit": "",
    "period": "day",
    "values": [
        {"x": 1747795200, "y": 850000},
        {"x": 1747881600, "y": 872000},
        {"x": 1747968000, "y": 890000},
    ],
}

ALTERNATIVE_FNG_FIXTURE = {
    "name": "Fear and Greed Index",
    "data": [
        {
            "value": "25",
            "value_classification": "Fear",
            "timestamp": "1747968000",
            "time_until_update": "3600",
        }
    ],
}


# ---------------------------------------------------------------------------
# 1. DefiLlama TVL — get_defillama_tvl()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDefillamaTVL:
    """DefiLlama API returns total TVL + top protocols + DEX volume."""

    async def test_defillama_tvl_returns_dict(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            # First call returns protocols, second returns DEX overview
            proto_resp = MagicMock()
            proto_resp.raise_for_status = lambda: None
            proto_resp.json.return_value = DEFILLAMA_PROTOCOLS_FIXTURE

            dex_resp = MagicMock()
            dex_resp.raise_for_status = lambda: None
            dex_resp.json.return_value = DEFILLAMA_DEX_FIXTURE

            mock_get.side_effect = [proto_resp, dex_resp]

            result = await get_defillama_tvl()

            assert result["indicator"] == "defi_tvl"
            assert result["total_tvl_usd"] > 0
            assert isinstance(result["top_protocols"], list)
            assert len(result["top_protocols"]) == 5  # our fixture has 5 protocols
            assert result["top_protocols"][0]["name"] == "Lido"
            assert result["dex_24h_volume"] == 5800000000
            assert result["date"] is not None
            assert result["source"] == "defillama"
            assert result["cadence"] == "daily"
            assert "error" not in result

    async def test_defillama_tvl_top_protocols_has_required_keys(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            proto_resp = MagicMock()
            proto_resp.raise_for_status = lambda: None
            proto_resp.json.return_value = DEFILLAMA_PROTOCOLS_FIXTURE

            dex_resp = MagicMock()
            dex_resp.raise_for_status = lambda: None
            dex_resp.json.return_value = DEFILLAMA_DEX_FIXTURE

            mock_get.side_effect = [proto_resp, dex_resp]

            result = await get_defillama_tvl()

            top = result["top_protocols"]
            assert len(top) > 0
            proto = top[0]
            assert "name" in proto
            assert "tvl_usd" in proto
            assert "chain" in proto
            assert "category" in proto


# ---------------------------------------------------------------------------
# 2. Stablecoin market cap — get_stablecoin_mcap()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStablecoinMcap:
    """DefiLlama Stablecoins API returns total market cap + top stablecoins."""

    async def test_stablecoin_mcap_returns_dict(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = DEFILLAMA_STABLECOINS_FIXTURE
            mock_get.return_value = mock_resp

            result = await get_stablecoin_mcap()

            assert result["indicator"] == "stablecoin_mcap"
            assert result["total_mcap_usd"] > 0
            assert isinstance(result["top_stablecoins"], list)
            assert len(result["top_stablecoins"]) == 3
            assert result["top_stablecoins"][0]["name"] == "Tether USD"
            assert result["top_stablecoins"][0]["symbol"] == "USDT"
            assert result["date"] is not None
            assert result["source"] == "defillama"
            assert result["cadence"] == "daily"
            assert "error" not in result

    async def test_stablecoin_mcap_empty_list(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = []
            mock_get.return_value = mock_resp

            result = await get_stablecoin_mcap()

            # Should still return a valid structure with zero values
            assert result["indicator"] == "stablecoin_mcap"
            assert result["total_mcap_usd"] == 0.0
            assert result["top_stablecoins"] == []


# ---------------------------------------------------------------------------
# 3. Blockchain stats — get_blockchain_stats()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBlockchainStats:
    """Blockchain.com Charts API returns hashrate and active addresses."""

    async def test_blockchain_stats_returns_dict(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            hr_resp = MagicMock()
            hr_resp.raise_for_status = lambda: None
            hr_resp.json.return_value = BLOCKCHAIN_HASHRATE_FIXTURE

            addr_resp = MagicMock()
            addr_resp.raise_for_status = lambda: None
            addr_resp.json.return_value = BLOCKCHAIN_ADDRESSES_FIXTURE

            mock_get.side_effect = [hr_resp, addr_resp]

            result = await get_blockchain_stats()

            assert result["indicator"] == "btc_network"
            assert result["hash_rate_eh_s"] == 542.8
            assert result["active_addresses"] == 890000
            assert result["date"] is not None
            assert result["source"] == "blockchain.com"
            assert result["cadence"] == "daily"
            assert "error" not in result

    async def test_blockchain_stats_graceful_has_no_data(self):
        """When both endpoints return empty values, graceful degradation kicks in."""
        _clear_cache()

        empty_values = {"name": "Foo", "unit": "", "period": "", "values": []}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = empty_values
            mock_get.return_value = mock_resp

            result = await get_blockchain_stats()

            # Both fetches failed → source_unavailable
            assert result["error"] == "source_unavailable"
            assert "no data" in result.get("detail", "").lower()

    async def test_blockchain_stats_partial_failure(self):
        """When only one endpoint fails, the other still returns data."""
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            hr_resp = MagicMock()
            hr_resp.raise_for_status = lambda: None
            hr_resp.json.return_value = BLOCKCHAIN_HASHRATE_FIXTURE

            # Addresses endpoint throws an exception
            mock_get.side_effect = [hr_resp, Exception("Connection refused")]

            result = await get_blockchain_stats()

            # Hashrate should still be present, addresses should be 0
            assert result["indicator"] == "btc_network"
            assert result["hash_rate_eh_s"] == 542.8
            assert result["active_addresses"] == 0
            assert "error" not in result


# ---------------------------------------------------------------------------
# 4. Crypto Fear & Greed — get_crypto_fear_greed()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCryptoFearGreed:
    """Alternative.me API returns Crypto Fear & Greed Index."""

    async def test_crypto_fear_greed_returns_dict(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = ALTERNATIVE_FNG_FIXTURE
            mock_get.return_value = mock_resp

            result = await get_crypto_fear_greed()

            assert result["indicator"] == "crypto_fear_greed"
            assert result["value"] == 25
            assert result["classification"] == "Fear"
            assert result["date"] is not None
            assert result["source"] == "alternative.me"
            assert result["cadence"] == "daily"
            assert "error" not in result

    async def test_crypto_fear_greed_extreme_greed(self):
        _clear_cache()

        extreme_greed_fixture = {
            "name": "Fear and Greed Index",
            "data": [
                {
                    "value": "82",
                    "value_classification": "Extreme Greed",
                    "timestamp": "1747968000",
                }
            ],
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = extreme_greed_fixture
            mock_get.return_value = mock_resp

            result = await get_crypto_fear_greed()

            assert result["value"] == 82
            assert result["classification"] == "Extreme Greed"

    async def test_crypto_fear_greed_empty_data(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"data": []}
            mock_get.return_value = mock_resp

            result = await get_crypto_fear_greed()

            assert result["error"] == "source_unavailable"
            assert "empty" in result.get("detail", "").lower()


# ---------------------------------------------------------------------------
# 5. Session cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionCache:
    """In-memory cache prevents duplicate HTTP calls during a session."""

    async def test_cache_works_defillama(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            proto_resp = MagicMock()
            proto_resp.raise_for_status = lambda: None
            proto_resp.json.return_value = DEFILLAMA_PROTOCOLS_FIXTURE
            dex_resp = MagicMock()
            dex_resp.raise_for_status = lambda: None
            dex_resp.json.return_value = DEFILLAMA_DEX_FIXTURE
            mock_get.side_effect = [proto_resp, dex_resp]

            result1 = await get_defillama_tvl()
            result2 = await get_defillama_tvl()

            # Only two HTTP calls (protocols + dex), not four
            assert mock_get.call_count == 2
            assert result1 is result2

    async def test_cache_works_stablecoin(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = DEFILLAMA_STABLECOINS_FIXTURE
            mock_get.return_value = mock_resp

            result1 = await get_stablecoin_mcap()
            result2 = await get_stablecoin_mcap()

            mock_get.assert_called_once()
            assert result1 is result2

    async def test_cache_works_crypto_fear_greed(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = ALTERNATIVE_FNG_FIXTURE
            mock_get.return_value = mock_resp

            result1 = await get_crypto_fear_greed()
            result2 = await get_crypto_fear_greed()

            mock_get.assert_called_once()
            assert result1 is result2


# ---------------------------------------------------------------------------
# 6. Graceful degradation — API unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDegradation:
    """Graceful degradation when APIs are unavailable."""

    async def test_defillama_tvl_http_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", side_effect=OSError("Connection refused")):
            result = await get_defillama_tvl()
        assert result["error"] == "source_unavailable"

    async def test_stablecoin_mcap_http_error(self):
        _clear_cache()
        with patch.object(httpx.AsyncClient, "get", side_effect=OSError("Connection refused")):
            result = await get_stablecoin_mcap()
        assert result["error"] == "source_unavailable"

    async def test_blockchain_stats_network_error(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Connection refused")

            result = await get_blockchain_stats()

            assert result["error"] == "source_unavailable"

    async def test_crypto_fear_greed_network_error(self):
        _clear_cache()

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Connection refused")

            result = await get_crypto_fear_greed()

            assert result["error"] == "source_unavailable"


# ---------------------------------------------------------------------------
# 7. Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for helper parsing functions."""

    def test_parse_float_valid(self):
        assert _parse_float("28500000000") == 28500000000.0
        assert _parse_float("542.8") == 542.8
        assert _parse_float("-0.35") == -0.35

    def test_parse_float_invalid(self):
        assert _parse_float(None) == 0.0
        assert _parse_float("abc") == 0.0
        assert _parse_float("") == 0.0

    def test_parse_int_valid(self):
        assert _parse_int("25") == 25
        assert _parse_int("890000") == 890000

    def test_parse_int_invalid(self):
        assert _parse_int(None) == 0
        assert _parse_int("abc") == 0
        assert _parse_int("") == 0
