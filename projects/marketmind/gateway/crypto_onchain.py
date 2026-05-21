"""On-demand, session-cached crypto onchain data fetchers.

Four public async functions, all using direct httpx (no new dependencies):

- get_defillama_tvl() — Total DeFi TVL + top protocols + DEX 24h volume
- get_stablecoin_mcap() — Total stablecoin market cap + top stablecoins
- get_blockchain_stats() — Bitcoin network stats (hashrate, active addresses)
- get_crypto_fear_greed() — Crypto-specific Fear & Greed Index

All data is CONTEXT only, not trading signals (Law 3 compliance).
Session-level in-memory cache (same pattern as macro_data.py and sentiment_fetcher.py).
Graceful degradation: return {"error": "source_unavailable"} on failure.

All sources are completely free, no API keys required:
- DefiLlama APIs: https://api.llama.fi/ (public, no key)
- Blockchain.com Charts: https://api.blockchain.info/charts/ (public, no key)
- Alternative.me Fear & Greed: https://api.alternative.me/fng/ (free, 60/min)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from marketmind.integrity.input_guard import sanitize_for_llm_prompt

logger = logging.getLogger("marketmind.gateway.crypto_onchain")

# ---------------------------------------------------------------------------
# Source URL constants (all free, no API key)
# ---------------------------------------------------------------------------
_DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
_DEFILLAMA_DEX_OVERVIEW_URL = "https://api.llama.fi/overview/dexs"
_DEFILLAMA_STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
_BLOCKCHAIN_HASHRATE_URL = "https://api.blockchain.info/charts/hash-rate?format=json"
_BLOCKCHAIN_ADDRESSES_URL = "https://api.blockchain.info/charts/n-unique-addresses?format=json"
_ALTERNATIVE_FNG_URL = "https://api.alternative.me/fng/?limit=1"

# ---------------------------------------------------------------------------
# Session-level cache (lives as long as the Python process)
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    """Clear the module-level cache (used between tests)."""
    _cache.clear()
    _cache_locks.clear()


def _sanitize(data: dict, source: str = "crypto_onchain_data") -> dict:
    """Sanitize all string fields in a data dict before LLM consumption.

    Numeric fields pass through unchanged.  String fields are run through
    input_guard and replaced with their sanitized form.  Any injection
    warnings are logged at WARNING level.
    """
    for key, val in list(data.items()):
        if isinstance(val, str):
            result = sanitize_for_llm_prompt(val, source=source)
            data[key] = result.sanitized
            for warning in result.warnings:
                logger.warning("input_guard [%s] field=%s: %s", source, key, warning)
        elif isinstance(val, list):
            # Sanitize string fields inside list elements (e.g. top_protocols)
            sanitized_list = []
            for item in val:
                if isinstance(item, dict):
                    sanitized_item = {}
                    for ik, iv in item.items():
                        if isinstance(iv, str):
                            r = sanitize_for_llm_prompt(iv, source=source)
                            sanitized_item[ik] = r.sanitized
                            for w in r.warnings:
                                logger.warning("input_guard [%s] field=%s.%s: %s", source, key, ik, w)
                        else:
                            sanitized_item[ik] = iv
                    sanitized_list.append(sanitized_item)
                elif isinstance(item, str):
                    r = sanitize_for_llm_prompt(item, source=source)
                    sanitized_list.append(r.sanitized)
                    for w in r.warnings:
                        logger.warning("input_guard [%s] field=%s[]: %s", source, key, w)
                else:
                    sanitized_list.append(item)
            data[key] = sanitized_list
    return data


# ===================================================================
# Public API
# ===================================================================


async def get_defillama_tvl() -> dict:
    """Fetch total DeFi TVL, top protocols, and DEX 24h volume from DefiLlama.

    Composes two free endpoints:
    - /protocols — total TVL + per-protocol breakdown (top 10 by TVL)
    - /overview/dexs — 24h DEX volume across all tracked DEXs

    Returns:
        Dict with keys: indicator, total_tvl_usd, top_protocols (list of 10),
        dex_24h_volume, date, source, cadence.
        Or {"error": "source_unavailable", "detail": ...} on failure.
    """
    key = "defillama_tvl"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_defillama_tvl()
        _cache[key] = result
        return result


async def get_stablecoin_mcap() -> dict:
    """Fetch total stablecoin market cap from DefiLlama Stablecoins API.

    Returns:
        Dict with keys: indicator, total_mcap_usd, top_stablecoins (list of 10),
        date, source, cadence.
        Or {"error": "source_unavailable", "detail": ...} on failure.
    """
    key = "stablecoin_mcap"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_stablecoin_mcap()
        _cache[key] = result
        return result


async def get_blockchain_stats() -> dict:
    """Fetch Bitcoin network stats (hashrate, active addresses) from Blockchain.com.

    Composes two free endpoints:
    - /charts/hash-rate — current estimated hashrate (EH/s)
    - /charts/n-unique-addresses — unique addresses used per day

    Returns:
        Dict with keys: indicator, hash_rate_eh_s, active_addresses, date,
        source, cadence.
        Or {"error": "source_unavailable", "detail": ...} on failure.
    """
    key = "blockchain_stats"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_blockchain_stats()
        _cache[key] = result
        return result


async def get_crypto_fear_greed() -> dict:
    """Fetch the Crypto Fear & Greed Index from Alternative.me.

    Free API, rate limit: 60 requests per minute.

    Returns:
        Dict with keys: indicator, value, classification, date, source, cadence.
        Or {"error": "source_unavailable", "detail": ...} on failure.
    """
    key = "crypto_fg"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_crypto_fear_greed()
        _cache[key] = result
        return result


# ===================================================================
# DefiLlama TVL implementation
# ===================================================================


async def _fetch_defillama_tvl() -> dict:
    """Fetch total DeFi TVL and top protocols from DefiLlama."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        # Fetch protocol TVL
        resp = await client.get(_DEFILLAMA_PROTOCOLS_URL)
        resp.raise_for_status()
        protocols_data = resp.json()

        # Sum TVL from all protocols and collect top 10
        total_tvl = 0.0
        top_protocols = []
        if isinstance(protocols_data, list):
            # Protocols are already sorted by TVL descending
            for idx, proto in enumerate(protocols_data):
                tvl = _parse_float(proto.get("tvl", 0))
                total_tvl += tvl
                if idx < 10:
                    top_protocols.append({
                        "name": proto.get("name", ""),
                        "tvl_usd": tvl,
                        "chain": proto.get("chain", ""),
                        "category": proto.get("category", ""),
                    })

        # Fetch DEX 24h volume
        dex_24h_volume = 0.0
        try:
            dex_resp = await client.get(_DEFILLAMA_DEX_OVERVIEW_URL)
            dex_resp.raise_for_status()
            dex_data = dex_resp.json()
            dex_24h_volume = _parse_float(dex_data.get("total24h", 0))
        except Exception as e:
            logger.warning("DefiLlama DEX overview fetch failed (non-fatal): %s", e)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return _sanitize({
            "indicator": "defi_tvl",
            "total_tvl_usd": total_tvl,
            "top_protocols": top_protocols,
            "dex_24h_volume": dex_24h_volume,
            "date": today,
            "source": "defillama",
            "cadence": "daily",
        }, "defillama_data")

    except httpx.HTTPStatusError as e:
        logger.warning("DefiLlama API HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"DefiLlama API returned HTTP {e.response.status_code}",
        }, "defillama_data")
    except Exception as e:
        logger.warning("DefiLlama fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "defillama_data")
    finally:
        await client.aclose()


# ===================================================================
# DefiLlama Stablecoin market cap implementation
# ===================================================================


async def _fetch_stablecoin_mcap() -> dict:
    """Fetch total stablecoin market cap from DefiLlama Stablecoins API."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_DEFILLAMA_STABLECOINS_URL)
        resp.raise_for_status()
        data = resp.json()

        # The response is a list of stablecoin objects
        # Each has: name, symbol, price, totalCirculating, totalCirculatingUSD, chainCirculating
        total_mcap = 0.0
        top_stablecoins = []
        if isinstance(data, list):
            # First pass: collect all mcap data
            all_coins = []
            for coin in data:
                name = coin.get("name", "")
                symbol = coin.get("symbol", "")
                mcap_usd = _parse_float(
                    coin.get("totalCirculatingUSD", coin.get("totalCirculating", 0))
                )
                all_coins.append((mcap_usd, name, symbol))
                total_mcap += mcap_usd

            # Sort by market cap descending, take top 10
            all_coins.sort(key=lambda x: x[0], reverse=True)
            for mcap_usd, name, symbol in all_coins[:10]:
                top_stablecoins.append({
                    "name": name,
                    "symbol": symbol,
                    "mcap_usd": mcap_usd,
                })

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return _sanitize({
            "indicator": "stablecoin_mcap",
            "total_mcap_usd": total_mcap,
            "top_stablecoins": top_stablecoins,
            "date": today,
            "source": "defillama",
            "cadence": "daily",
        }, "defillama_data")

    except httpx.HTTPStatusError as e:
        logger.warning("DefiLlama Stablecoins HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"DefiLlama Stablecoins API returned HTTP {e.response.status_code}",
        }, "defillama_data")
    except Exception as e:
        logger.warning("DefiLlama Stablecoins fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "defillama_data")
    finally:
        await client.aclose()


# ===================================================================
# Blockchain.com stats implementation
# ===================================================================


async def _fetch_blockchain_stats() -> dict:
    """Fetch Bitcoin hashrate and active addresses from Blockchain.com Charts API."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    hash_rate_eh_s = 0.0
    active_addresses = 0
    data_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        # Fetch hashrate
        hr_resp = await client.get(_BLOCKCHAIN_HASHRATE_URL)
        hr_resp.raise_for_status()
        hr_data = hr_resp.json()

        # Response format: {"name": "Hash Rate", "unit": "EH/s", "period": "day",
        #   "description": "...", "values": [{"x": unix_ts, "y": value}, ...]}
        hr_values = hr_data.get("values", [])
        if hr_values:
            latest_hr = hr_values[-1]
            hash_rate_eh_s = _parse_float(latest_hr.get("y", 0))
            # Extract date from latest value's unix timestamp
            ts = latest_hr.get("x", 0)
            if ts:
                try:
                    data_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    pass

    except Exception as e:
        logger.warning("Blockchain.com hashrate fetch failed (non-fatal): %s", e)

    try:
        # Fetch unique addresses
        addr_resp = await client.get(_BLOCKCHAIN_ADDRESSES_URL)
        addr_resp.raise_for_status()
        addr_data = addr_resp.json()

        addr_values = addr_data.get("values", [])
        if addr_values:
            latest_addr = addr_values[-1]
            active_addresses = _parse_int(latest_addr.get("y", 0))
            # Use address timestamp if hashrate didn't provide a date
            if not hash_rate_eh_s or data_date == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                ts = latest_addr.get("x", 0)
                if ts:
                    try:
                        data_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                    except (ValueError, OSError):
                        pass

    except Exception as e:
        logger.warning("Blockchain.com addresses fetch failed (non-fatal): %s", e)

    # Only report error if BOTH fetches failed entirely
    if hash_rate_eh_s == 0.0 and active_addresses == 0:
        return _sanitize({
            "error": "source_unavailable",
            "detail": "Blockchain.com API returned no data for hashrate or addresses",
        }, "blockchain_data")

    return _sanitize({
        "indicator": "btc_network",
        "hash_rate_eh_s": hash_rate_eh_s,
        "active_addresses": active_addresses,
        "date": data_date,
        "source": "blockchain.com",
        "cadence": "daily",
    }, "blockchain_data")


# ===================================================================
# Alternative.me Crypto Fear & Greed implementation
# ===================================================================


async def _fetch_crypto_fear_greed() -> dict:
    """Fetch Crypto Fear & Greed Index from Alternative.me."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_ALTERNATIVE_FNG_URL)
        resp.raise_for_status()
        data = resp.json()

        # Response format: {"name": "Fear and Greed Index",
        #   "data": [{"value": "25", "value_classification": "Fear",
        #             "timestamp": "1680998400", "time_until_update": "..."}]}
        data_list = data.get("data", [])
        if not data_list:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "Alternative.me Fear & Greed returned empty data",
            }, "alternative_me_data")

        item = data_list[0]
        value = _parse_int(item.get("value", 0))
        classification = item.get("value_classification", "Unknown")

        # Convert unix timestamp to date string
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts = item.get("timestamp", "")
        if ts:
            try:
                date_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass

        return _sanitize({
            "indicator": "crypto_fear_greed",
            "value": value,
            "classification": classification,
            "date": date_str,
            "source": "alternative.me",
            "cadence": "daily",
        }, "alternative_me_data")

    except httpx.HTTPStatusError as e:
        logger.warning("Alternative.me Fear & Greed HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"Alternative.me API returned HTTP {e.response.status_code}",
        }, "alternative_me_data")
    except Exception as e:
        logger.warning("Alternative.me Fear & Greed fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "alternative_me_data")
    finally:
        await client.aclose()


# ===================================================================
# Helpers
# ===================================================================


def _parse_float(val: Any) -> float:
    """Parse a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _parse_int(val: Any) -> int:
    """Parse a value to int, returning 0 on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0
