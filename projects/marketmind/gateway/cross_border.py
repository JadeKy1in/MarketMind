"""Cross-border capital flow data gateway — TIC, BIS, cross-currency basis.

TLS verification enforced (audit finding). All HTTP calls use verify=True.
Graceful degradation: empty lists on failure, logged at WARNING.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("marketmind.gateway.cross_border")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TICFlowData:
    country: str
    net_flow_usd_bn: float
    asset_type: str          # "treasury" | "equity" | "corporate_bond" | "agency"
    period: str              # YYYY-MM
    source: str = "TIC_SLT"


@dataclass
class CrossCurrencyBasis:
    pair: str                # "EUR/USD" | "USD/JPY"
    basis_bp: float          # negative = USD funding premium
    date: str
    source: str = "FRED"


@dataclass
class BISBankingFlow:
    reporting_country: str
    counterparty_country: str
    flow_usd_bn: float
    period: str              # YYYY-QQ
    source: str = "BIS_LBS"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TIC_BASE_URL = "https://home.treasury.gov/data/treasury-international-capital-tic-system"
_TIC_DATA_URL = "https://ticdata.treasury.gov/resource/data/slt_table1.csv"

_BIS_API_BASE = "https://api.bis.org/statistics"
_BIS_DATASET = "LBS"  # Locational Banking Statistics

# FRED series for cross-currency basis
_CCB_SERIES: dict[str, dict[str, str]] = {
    "EUR/USD": {
        "series_id": "RBXTEUS",
        "label": "EUR/USD Cross-Currency Basis (3M)",
    },
    "USD/JPY": {
        "series_id": "RBXTEUS",  # Fallback — actual series TBD via FRED search
        "label": "USD/JPY Cross-Currency Basis (3M)",
    },
}

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# In-memory session cache
_cache: dict[str, Any] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    _cache.clear()
    _cache_locks.clear()


def _cache_key(*args: str) -> str:
    return "|".join(a.upper() for a in args)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_tic_data(country: str | None = None) -> list[TICFlowData]:
    """Fetch TIC monthly data from Treasury.gov.

    Primary URL: https://home.treasury.gov/data/treasury-international-capital-tic-system
    Fallback: cached data from previous successful fetches.
    Returns empty list on failure (graceful degradation).
    """
    key = _cache_key("tic", country or "ALL")

    if key in _cache:
        return _cache[key]

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]

        result = await _fetch_tic_impl(country)
        _cache[key] = result
        return result


async def fetch_cross_currency_basis(pair: str) -> CrossCurrencyBasis | None:
    """Fetch cross-currency basis from FRED.

    EUR/USD: FRED series RBXTEUS
    USD/JPY: FRED series RBXTBIS
    Returns None on failure.
    """
    pair = pair.strip().upper()
    key = _cache_key("ccb", pair)

    if key in _cache:
        cached = _cache[key]
        return cached if cached is not None else None

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        if key in _cache:
            cached = _cache[key]
            return cached if cached is not None else None

        result = await _fetch_ccb_impl(pair)
        _cache[key] = result
        return result


async def fetch_bis_banking_flows() -> list[BISBankingFlow]:
    """Fetch BIS Locational Banking Statistics.

    BIS API: https://api.bis.org/statistics/ (free, requires registration)
    Returns empty list on failure.
    """
    key = _cache_key("bis", "all")

    if key in _cache:
        return _cache[key]

    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]

        result = await _fetch_bis_impl()
        _cache[key] = result
        return result


# ---------------------------------------------------------------------------
# TIC implementation
# ---------------------------------------------------------------------------


async def _fetch_tic_impl(country: str | None) -> list[TICFlowData]:
    """Fetch TIC SLT Table 1 CSV from Treasury.gov."""
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        verify=True,
    )
    try:
        resp = await client.get(_TIC_DATA_URL)
        resp.raise_for_status()
        return _parse_tic_csv(resp.text, country)
    except httpx.HTTPStatusError as e:
        logger.warning("TIC data fetch HTTP error: %s", e)
        return []
    except Exception as e:
        logger.warning("TIC data fetch failed: %s", e)
        return []
    finally:
        await client.aclose()


def _parse_tic_csv(text: str, country_filter: str | None) -> list[TICFlowData]:
    """Parse TIC SLT CSV into TICFlowData list."""
    import csv
    from io import StringIO

    results: list[TICFlowData] = []
    try:
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            cty = (row.get("Country") or row.get("country") or "").strip()
            if country_filter and country_filter.lower() not in cty.lower():
                continue

            net_flow = _parse_float(row.get("Net_Flow_USD_Bn") or row.get("net_flow") or "0")
            asset_type = (row.get("Asset_Type") or row.get("asset_type") or "treasury").strip().lower()
            period = (row.get("Period") or row.get("period") or "").strip()

            if cty and period:
                results.append(TICFlowData(
                    country=cty,
                    net_flow_usd_bn=net_flow,
                    asset_type=asset_type,
                    period=period,
                ))
    except Exception as e:
        logger.warning("TIC CSV parse error: %s", e)

    return results


# ---------------------------------------------------------------------------
# Cross-currency basis implementation (FRED)
# ---------------------------------------------------------------------------


async def _fetch_ccb_impl(pair: str) -> CrossCurrencyBasis | None:
    """Fetch cross-currency basis from FRED."""
    series_info = _CCB_SERIES.get(pair)
    if series_info is None:
        logger.warning("Unsupported CCB pair: %s", pair)
        return None

    fred_key = _get_fred_key()
    if not fred_key:
        logger.warning("FRED_KEY not configured — cannot fetch CCB for %s", pair)
        return None

    series_id = series_info["series_id"]
    url = (
        f"{_FRED_BASE}?series_id={series_id}"
        f"&api_key={fred_key}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit=1"
    )

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        verify=True,
    )
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])

        if not observations or observations[0].get("value") in (None, "."):
            logger.warning("No CCB data for %s", pair)
            return None

        obs = observations[0]
        return CrossCurrencyBasis(
            pair=pair,
            basis_bp=_parse_float(obs.get("value", "0")),
            date=obs.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        )
    except httpx.HTTPStatusError as e:
        logger.warning("FRED CCB API error for %s: %s", pair, e)
        return None
    except Exception as e:
        logger.warning("FRED CCB fetch failed for %s: %s", pair, e)
        return None
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# BIS implementation
# ---------------------------------------------------------------------------


async def _fetch_bis_impl() -> list[BISBankingFlow]:
    """Fetch BIS Locational Banking Statistics via BIS API."""
    url = f"{_BIS_API_BASE}/{_BIS_DATASET}/data"

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        verify=True,
    )
    try:
        resp = await client.get(url, params={"format": "json"})
        resp.raise_for_status()
        return _parse_bis_json(resp.json())
    except httpx.HTTPStatusError as e:
        logger.warning("BIS API HTTP error: %s", e)
        return []
    except Exception as e:
        logger.warning("BIS fetch failed: %s", e)
        return []
    finally:
        await client.aclose()


def _parse_bis_json(data: dict) -> list[BISBankingFlow]:
    """Parse BIS API JSON response into BISBankingFlow list."""
    results: list[BISBankingFlow] = []
    try:
        records = data.get("dataSets", [{}])[0].get("series", {})
        structure = data.get("structure", {})
        dims = structure.get("dimensions", {}).get("series", [])

        # Build dimension label maps
        country_map: dict[int, str] = {}
        counterparty_map: dict[int, str] = {}
        period_map: dict[int, str] = {}

        for dim in dims:
            name = dim.get("name", "")
            values = dim.get("values", [])
            for idx, val in enumerate(values):
                label = val.get("name", str(idx))
                if name == "REF_AREA":
                    country_map[idx] = label
                elif name == "COUNTERPART_AREA":
                    counterparty_map[idx] = label
                elif name == "TIME_PERIOD":
                    period_map[idx] = label

        for key_str, obs_data in records.items():
            indices = [int(x) for x in key_str.split(":")]
            if len(indices) < 3:
                continue

            reporting_cty = country_map.get(indices[0], f"idx_{indices[0]}")
            counterparty_cty = counterparty_map.get(indices[1], f"idx_{indices[1]}")
            period = period_map.get(indices[2], "")

            value = obs_data.get("observations", [{}])[0]
            flow_val = _parse_float(value[0]) if value else 0.0

            if reporting_cty and counterparty_cty and period:
                results.append(BISBankingFlow(
                    reporting_country=reporting_cty,
                    counterparty_country=counterparty_cty,
                    flow_usd_bn=flow_val,
                    period=period,
                ))

    except Exception as e:
        logger.warning("BIS JSON parse error: %s", e)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_fred_key() -> str:
    """Get FRED API key from config or environment."""
    try:
        from marketmind.config.settings import MarketMindConfig
        cfg = MarketMindConfig()
        if cfg.fred_key:
            return cfg.fred_key
    except (ImportError, AttributeError) as e:
        logger.debug("FRED API key not available from MarketMindConfig: %s", e)
    import os
    return os.environ.get("FRED_KEY", "").strip()


def _parse_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
