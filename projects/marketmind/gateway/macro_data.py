"""On-demand, session-cached macro/commodities/supply-chain data fetchers.

Three public functions, all using direct httpx (no new dependencies):

- get_macro_indicator("BDI" | "GSCPI") — FRED API (free key, env FRED_KEY)
- get_cot_data("ES" | "CL" | "GC" | "NG") — CFTC SODA API (no key, public JSON)
- get_eia_inventory("crude" | "gasoline" | "distillate") — EIA API v2 (free key, env EIA_KEY)

All data is CONTEXT only, not trading signals (Law 3 compliance).
Session-level in-memory cache (same pattern as market_data.py).
Graceful degradation: return {"error": "source_unavailable"} on failure.

Red Team compliant (per red-team-macro-data-design.md):
- Direct httpx, no fredapi/cot_reports libraries
- Staleness annotation (date + cadence) on every response
- All keys from config.settings.MarketMindConfig
- CFTC data via SODA API (free, no key, JSON)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("marketmind.gateway.macro_data")

# ---------------------------------------------------------------------------
# FRED API constants
# ---------------------------------------------------------------------------
_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series IDs for supported macro indicators
_FRED_SERIES: dict[str, dict[str, str]] = {
    "BDI": {
        "series_id": "DRSAGRGQ086SBEA",
        "label": "Baltic Dry Index",
        "cadence": "daily",
    },
    "GSCPI": {
        "series_id": "GSCPI",
        "label": "Global Supply Chain Pressure Index",
        "cadence": "monthly",
    },
}

# ---------------------------------------------------------------------------
# CFTC SODA API constants (public, no key)
# ---------------------------------------------------------------------------
_CFTC_SODA_BASE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Market names for SODA API LIKE filtering
_CFTC_ASSETS: dict[str, dict[str, str]] = {
    "ES": {
        "market_filter": "S&P 500",
        "label": "S&P 500 Futures (E-mini)",
        "cadence": "weekly",
    },
    "CL": {
        "market_filter": "CRUDE OIL",
        "label": "Crude Oil Futures (CL)",
        "cadence": "weekly",
    },
    "GC": {
        "market_filter": "GOLD",
        "label": "Gold Futures (GC)",
        "cadence": "weekly",
    },
    "NG": {
        "market_filter": "NATURAL GAS",
        "label": "Natural Gas Futures (NG)",
        "cadence": "weekly",
    },
}

# ---------------------------------------------------------------------------
# EIA API v2 constants
# ---------------------------------------------------------------------------
_EIA_BASE = "https://api.eia.gov/v2"

# Product codes for EIA weekly stocks data
_EIA_PRODUCTS: dict[str, dict[str, str]] = {
    "crude": {
        "route": "/petroleum/stoc/wstk/data/",
        "label": "Crude Oil (excl. SPR)",
        "cadence": "weekly",
    },
    "gasoline": {
        "route": "/petroleum/stoc/wstk/data/",
        "label": "Total Gasoline",
        "cadence": "weekly",
    },
    "distillate": {
        "route": "/petroleum/stoc/wstk/data/",
        "label": "Distillate Fuel Oil",
        "cadence": "weekly",
    },
}

# ---------------------------------------------------------------------------
# Session-level cache (lives as long as the Python process)
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _cache_key(*args: str) -> str:
    """Derive a unique cache key from ordered arguments."""
    return "|".join(a.upper() for a in args)


def _clear_cache() -> None:
    """Clear the module-level cache (used between tests)."""
    _cache.clear()
    _cache_locks.clear()


# ===================================================================
# Public API
# ===================================================================


async def get_macro_indicator(indicator: str) -> dict:
    """Fetch the latest value of a macro indicator from FRED.

    Args:
        indicator: "BDI" (Baltic Dry Index) or "GSCPI" (Global Supply Chain
                   Pressure Index).

    Returns:
        Dict with keys: indicator, value, date, source, cadence, label.
        Or {"error": "source_unavailable"} on failure.
    """
    indicator = indicator.strip().upper()
    key = _cache_key("macro", indicator)

    # Fast path: cache hit
    if key in _cache:
        return _cache[key]

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        # Double-check cache after acquiring lock
        if key in _cache:
            return _cache[key]

        result = await _fetch_fred(indicator)
        _cache[key] = result
        return result


async def get_cot_data(asset: str) -> dict:
    """Fetch the latest Commitments of Traders report for a futures asset.

    Uses the CFTC SODA API (free, no key, JSON response).

    Args:
        asset: "ES" (S&P 500), "CL" (Crude Oil), "GC" (Gold), or "NG" (Natural Gas).

    Returns:
        Dict with keys: asset, commercial_net, speculative_net, date, source,
        cadence, label, signal.
        Or {"error": "source_unavailable"} on failure.
    """
    asset = asset.strip().upper()
    key = _cache_key("cot", asset)

    if key in _cache:
        return _cache[key]

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]

        result = await _fetch_cftc(asset)
        _cache[key] = result
        return result


async def get_eia_inventory(product: str) -> dict:
    """Fetch the latest weekly US petroleum inventory data from EIA.

    Uses EIA API v2 (free key via env EIA_KEY).

    Args:
        product: "crude", "gasoline", or "distillate".

    Returns:
        Dict with keys: product, inventory_mbbl, date, source, cadence, label.
        Or {"error": "source_unavailable"} on failure.
    """
    product = product.strip().lower()
    key = _cache_key("eia", product)

    if key in _cache:
        return _cache[key]

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]

        result = await _fetch_eia(product)
        _cache[key] = result
        return result


# ===================================================================
# FRED implementation
# ===================================================================


async def _fetch_fred(indicator: str) -> dict:
    """Fetch latest observation for a FRED series."""
    series_info = _FRED_SERIES.get(indicator)
    if series_info is None:
        return {
            "error": "source_unavailable",
            "detail": f"Unknown indicator: '{indicator}'. Supported: BDI, GSCPI",
        }

    fred_key = _get_fred_key()
    if not fred_key:
        logger.warning("FRED_KEY not configured — cannot fetch %s", indicator)
        return {"error": "source_unavailable", "detail": "FRED_KEY not configured"}

    series_id = series_info["series_id"]
    url = (
        f"{_FRED_BASE}?series_id={series_id}"
        f"&api_key={fred_key}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit=1"
    )

    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])

        if not observations or observations[0].get("value") in (None, "."):
            return {"error": "source_unavailable", "detail": f"No data for {indicator}"}

        obs = observations[0]
        return {
            "indicator": indicator,
            "label": series_info["label"],
            "value": _parse_float(obs.get("value")),
            "date": obs.get("date", ""),
            "source": "fred",
            "cadence": series_info["cadence"],
            "series_id": series_id,
        }
    except httpx.HTTPStatusError as e:
        logger.warning("FRED API error for %s: %s", indicator, e)
        return {"error": "source_unavailable", "detail": f"FRED API returned {e.response.status_code}"}
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", indicator, e)
        return {"error": "source_unavailable", "detail": str(e)}
    finally:
        await client.aclose()


# ===================================================================
# CFTC SODA API implementation
# ===================================================================


async def _fetch_cftc(asset: str) -> dict:
    """Fetch latest COT report for an asset from CFTC SODA API."""
    asset_info = _CFTC_ASSETS.get(asset)
    if asset_info is None:
        return {
            "error": "source_unavailable",
            "detail": f"Unknown asset: '{asset}'. Supported: ES, CL, GC, NG",
        }

    market_filter = asset_info["market_filter"]

    # SODA API SoQL query — filter by market name, latest date, limit 1
    query = (
        f"SELECT market_and_exchange_names, report_date_as_yyyy_mm_dd, "
        f"noncomm_positions_long_all, noncomm_positions_short_all, "
        f"comm_positions_long_all, comm_positions_short_all "
        f"WHERE market_and_exchange_names LIKE '%{quote(market_filter)}%' "
        f"AND report_date_as_yyyy_mm_dd > '2026-01-01' "
        f"ORDER BY report_date_as_yyyy_mm_dd DESC "
        f"LIMIT 1"
    )

    url = f"{_CFTC_SODA_BASE}?$query={query}"

    client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            return {"error": "source_unavailable", "detail": f"No COT data for {asset}"}

        row = data[0]
        noncomm_long = _parse_int(row.get("noncomm_positions_long_all", 0))
        noncomm_short = _parse_int(row.get("noncomm_positions_short_all", 0))
        comm_long = _parse_int(row.get("comm_positions_long_all", 0))
        comm_short = _parse_int(row.get("comm_positions_short_all", 0))

        commercial_net = comm_long - comm_short
        speculative_net = noncomm_long - noncomm_short

        # Simple heuristic signal
        signal = _cot_signal(asset, speculative_net)

        return {
            "asset": asset,
            "label": asset_info["label"],
            "commercial_net": commercial_net,
            "speculative_net": speculative_net,
            "noncomm_long": noncomm_long,
            "noncomm_short": noncomm_short,
            "comm_long": comm_long,
            "comm_short": comm_short,
            "date": row.get("report_date_as_yyyy_mm_dd", ""),
            "source": "cftc",
            "cadence": asset_info["cadence"],
            "signal": signal,
        }
    except httpx.HTTPStatusError as e:
        logger.warning("CFTC SODA API error for %s: %s", asset, e)
        return {"error": "source_unavailable", "detail": f"CFTC API returned {e.response.status_code}"}
    except Exception as e:
        logger.warning("CFTC fetch failed for %s: %s", asset, e)
        return {"error": "source_unavailable", "detail": str(e)}
    finally:
        await client.aclose()


def _cot_signal(asset: str, speculative_net: int) -> str:
    """Generate a human-readable signal description from COT positioning.

    Extreme speculative long suggests the trend is crowded (contrarian bearish).
    Extreme speculative short suggests capitulation (contrarian bullish).
    These thresholds are fixed heuristics, not backtest-optimized (Law 3).
    """
    if speculative_net > 40000:
        return (
            f"Speculative net long {speculative_net:,} — elevated positioning, "
            "contrarian bearish (crowded long)"
        )
    elif speculative_net < -40000:
        return (
            f"Speculative net short {speculative_net:,} — elevated positioning, "
            "contrarian bullish (crowded short)"
        )
    elif speculative_net > 15000:
        return f"Speculative moderately net long {speculative_net:,} — no extreme signal"
    elif speculative_net < -15000:
        return f"Speculative moderately net short {speculative_net:,} — no extreme signal"
    else:
        return f"Speculative positioning near neutral ({speculative_net:,}) — no directional signal"


# ===================================================================
# EIA API v2 implementation
# ===================================================================


async def _fetch_eia(product: str) -> dict:
    """Fetch latest weekly US petroleum inventory from EIA API v2."""
    product_info = _EIA_PRODUCTS.get(product)
    if product_info is None:
        return {
            "error": "source_unavailable",
            "detail": f"Unknown product: '{product}'. Supported: crude, gasoline, distillate",
        }

    eia_key = _get_eia_key()
    if not eia_key:
        logger.warning("EIA_KEY not configured — cannot fetch %s", product)
        return {"error": "source_unavailable", "detail": "EIA_KEY not configured"}

    route = product_info["route"]
    url = (
        f"{_EIA_BASE}{route}"
        f"?api_key={eia_key}"
        f"&frequency=weekly"
        f"&data[0]=value"
        f"&sort[0][column]=period"
        f"&sort[0][direction]=desc"
        f"&length=1"
    )

    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        response_data = data.get("response", {})
        records = response_data.get("data", [])

        if not records:
            return {"error": "source_unavailable", "detail": f"No EIA data for {product}"}

        record = records[0]
        inventory_mbbl = _parse_float(record.get("value", 0))

        return {
            "product": product,
            "label": product_info["label"],
            "inventory_mbbl": inventory_mbbl,
            "date": record.get("period", ""),
            "source": "eia",
            "cadence": product_info["cadence"],
        }
    except httpx.HTTPStatusError as e:
        logger.warning("EIA API error for %s: %s", product, e)
        return {"error": "source_unavailable", "detail": f"EIA API returned {e.response.status_code}"}
    except Exception as e:
        logger.warning("EIA fetch failed for %s: %s", product, e)
        return {"error": "source_unavailable", "detail": str(e)}
    finally:
        await client.aclose()


# ===================================================================
# Helpers
# ===================================================================


def _get_fred_key() -> str:
    """Get FRED API key from config or environment."""
    try:
        from marketmind.config.settings import MarketMindConfig
        cfg = MarketMindConfig()
        if cfg.fred_key:
            return cfg.fred_key
    except Exception:
        pass
    return os.environ.get("FRED_KEY", "").strip()


def _get_eia_key() -> str:
    """Get EIA API key from config or environment."""
    try:
        from marketmind.config.settings import MarketMindConfig
        cfg = MarketMindConfig()
        if cfg.eia_key:
            return cfg.eia_key
    except Exception:
        pass
    return os.environ.get("EIA_KEY", "").strip()


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
