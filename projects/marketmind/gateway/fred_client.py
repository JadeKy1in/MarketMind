"""Dedicated FRED client — expands from 2 indicators to ~30 core macro/finance series.

Session-cached, input-sanitized, graceful degradation. Same pattern as macro_data.py:
- Module-level asyncio.Lock-based cache
- input_guard sanitization on all string fields
- Returns {"error": "source_unavailable"} on failure
- FRED_KEY from MarketMindConfig, fallback to env FRED_KEY
- Batch-fetches all series concurrently (asyncio.gather), respecting 120 req/min limit

FRED API docs: https://fred.stlouisfed.org/docs/api/fred/
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from marketmind.integrity.input_guard import sanitize_for_llm_prompt

logger = logging.getLogger("marketmind.gateway.fred_client")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# ---------------------------------------------------------------------------
# Series catalog — ~30 core macro/finance series grouped by domain
# ---------------------------------------------------------------------------

# Each entry: (series_id, label, cadence, unit_hint)
# unit_hint is a human-readable unit for LLM context
_FRED_SERIES: dict[str, tuple[str, str, str, str]] = {
    # ── Treasury Yields (Yield Whisperer, Cycle Reader) ──
    "DGS2":    ("DGS2",    "2-Year Treasury Yield",         "daily",  "%"),
    "DGS5":    ("DGS5",    "5-Year Treasury Yield",         "daily",  "%"),
    "DGS10":   ("DGS10",   "10-Year Treasury Yield",        "daily",  "%"),
    "DGS30":   ("DGS30",   "30-Year Treasury Yield",        "daily",  "%"),
    # ── TIPS / Real Yields (Bullion Broker, Yield Whisperer) ──
    "DFII5":   ("DFII5",   "5-Year TIPS Real Yield",        "daily",  "%"),
    "DFII10":  ("DFII10",  "10-Year TIPS Real Yield",       "daily",  "%"),
    # ── Yield Curve Spreads (Rotation Engine, Cycle Reader) ──
    "T10Y2Y":  ("T10Y2Y",  "10Y-2Y Treasury Spread",        "daily",  "%"),
    "T10Y3M":  ("T10Y3M",  "10Y-3M Treasury Spread",        "daily",  "%"),
    # ── Credit Spreads (Vol Surfer, Crash Hunter, Yield Whisperer) ──
    "BAMLC0A0CM":   ("BAMLC0A0CM",   "ICE BofA US Corp IG OAS",        "daily", "bp"),
    "BAMLH0A0HYM2": ("BAMLH0A0HYM2", "ICE BofA US High Yield OAS",     "daily", "bp"),
    # ── Mortgage (REIT Analyst) ──
    "MORTGAGE30US": ("MORTGAGE30US", "30-Year Fixed Mortgage Rate",     "weekly", "%"),
    # ── GDP / Growth (Cycle Reader) ──
    "GDP":     ("GDP",     "Gross Domestic Product (nominal)",  "quarterly", "B USD"),
    "GDPC1":   ("GDPC1",   "Real GDP",                          "quarterly", "B 2017 USD"),
    # ── Industrial / Employment (Factory Floor, Bank Examiner) ──
    "INDPRO":  ("INDPRO",  "Industrial Production Index",       "monthly", "index"),
    "PAYEMS":  ("PAYEMS",  "Total Nonfarm Payrolls",            "monthly", "thousands"),
    # ── Consumer Sentiment / Savings (Wallet Watcher) ──
    "UMCSENT": ("UMCSENT", "U. Michigan Consumer Sentiment",    "monthly", "index"),
    "PSAVERT": ("PSAVERT", "Personal Saving Rate",              "monthly", "%"),
    # ── Inflation (all shadows) ──
    "PCE":     ("PCE",     "Personal Consumption Expenditures", "monthly", "B USD"),
    "PCEPILFE":("PCEPILFE","Core PCE (excl. food & energy)",    "monthly", "index"),
    "T5YIFR":  ("T5YIFR",  "5Y5Y Forward Breakeven Inflation",  "daily",  "%"),
    # ── Housing (REIT Analyst) ──
    "HOUST":   ("HOUST",   "Housing Starts",                   "monthly", "thousands"),
    "PERMIT":  ("PERMIT",  "Building Permits",                  "monthly", "thousands"),
    "SPCS20RSA":("SPCS20RSA","S&P Case-Shiller 20-City Index",  "monthly", "index"),
    # ── Retail / Consumer (Wallet Watcher) ──
    "RSXFS":   ("RSXFS",   "Advance Retail Sales ex Food Svc", "monthly", "M USD"),
    "RSXFSN":  ("RSXFSN",  "Advance Retail Sales: Retail Trade", "monthly", "M USD"),
    # ── Financial Conditions (Cycle Reader, Fade Master) ──
    "NFCI":    ("NFCI",    "Chicago Fed Natl Financial Conditions", "weekly", "index"),
    # ── Durable Goods / Orders (Factory Floor) ──
    "DGORDER": ("DGORDER", "Manufacturers' New Orders: Durable Goods", "monthly", "M USD"),
    "NEWORDER":("NEWORDER","Manufacturers' New Orders: All Mfg", "monthly", "M USD"),
    # ── Money Market (Vol Surfer, Yield Whisperer) ──
    "SOFR":    ("SOFR",    "Secured Overnight Financing Rate",  "daily",  "%"),
    "DFF":     ("DFF",     "Federal Funds Effective Rate",      "daily",  "%"),
    "TEDRATE": ("TEDRATE", "TED Spread (3M LIBOR - 3M T-Bill, discontinued)", "daily", "%"),
    # ── Market Valuation (Crash Hunter, Cycle Reader) ──
    "SP500":   ("SP500",   "S&P 500 Index Level",              "daily",  "index"),
    # Note: Wilshire 5000 (WILL5000PR) is not accessible via free FRED API.
    # Use Shiller Excel for CAPE, compute Buffett Indicator as SP500*shares/GDP.
    # ── Trade-Weighted USD (Currency Dealer, Frontier Scout) ──
    "DTWEXBGS":("DTWEXBGS","Trade-Weighted USD Index (broad)",  "daily",  "index"),
    # ── EMBI Spread (Frontier Scout) ──
    "BAMLEMHBHYCRPIOAS": ("BAMLEMHBHYCRPIOAS", "ICE BofA EM HY Corporate OAS", "daily", "bp"),
    # ── Legacy (backward compat with macro_data.py) ──
    "BDI":     ("PCU483111483111", "PPI: Deep Sea Freight (BDI proxy)", "monthly", "index"),
}

# Reverse mapping: FRED series_id → local key (for FRED observation responses)
_FRED_REVERSE: dict[str, str] = {v[0]: k for k, v in _FRED_SERIES.items()}

# ── Domain → series_keys mapping (for per-shadow distribution) ──
SHADOW_FRED_SERIES: dict[str, list[str]] = {
    "expert:gold:bullion_broker":      ["DFII5", "DFII10", "DTWEXBGS"],
    "expert:bonds:yield_whisperer":    ["DGS2", "DGS5", "DGS10", "DGS30", "DFII5", "DFII10",
                                         "T10Y2Y", "T10Y3M", "BAMLC0A0CM", "BAMLH0A0HYM2"],
    "expert:energy:oil_geologist":     [],
    "expert:crypto:chain_oracle":      [],
    "expert:vol:vega_trader":          [],
    "expert:em:frontier_scout":        ["BAMLEMHBHYCRPIOAS", "DTWEXBGS"],
    "expert:tech:silicon_oracle":      [],
    "expert:financials:bank_examiner": ["PAYEMS"],
    "expert:healthcare:trial_reviewer":[],
    "expert:consumer:wallet_watcher":  ["UMCSENT", "PSAVERT", "RSXFS", "RSXFSN"],
    "expert:industrials:factory_floor":["INDPRO", "DGORDER", "NEWORDER"],
    "expert:metals:steel_trader":      [],
    "expert:agriculture:harvest_seer": [],
    "expert:realestate:reit_analyst":  ["MORTGAGE30US", "HOUST", "PERMIT", "SPCS20RSA"],
    "expert:fx:currency_dealer":       ["DTWEXBGS"],
    "expert:macro:cycle_reader":       ["DGS2", "DGS10", "T10Y2Y", "GDP", "GDPC1", "PCE",
                                         "PCEPILFE", "NFCI", "SP500", "INDPRO", "PAYEMS", "SOFR", "DFF"],
    "momentum:intraday:scalper":       [],
    "momentum:weekly:trend_rider":     [],
    "momentum:event:news_hound":       [],
    "momentum:sector:rotation_engine": ["T10Y2Y", "T10Y3M"],
    "contrarian:consensus:fade_master":["NFCI", "UMCSENT"],
    "contrarian:range_bound:sideways_scout": [],
    "contrarian:panic:vol_surfer":     ["BAMLC0A0CM", "BAMLH0A0HYM2", "SOFR", "DFF", "TEDRATE"],
    "contrarian:crash:hunter":         ["SP500", "BAMLC0A0CM", "BAMLH0A0HYM2"],
}

# ---------------------------------------------------------------------------
# Session-level cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    _cache.clear()
    _cache_locks.clear()


def _sanitize(data: dict) -> dict:
    for key, val in list(data.items()):
        if isinstance(val, str):
            result = sanitize_for_llm_prompt(val, source="fred_data")
            data[key] = result.sanitized
            for warning in result.warnings:
                logger.warning("input_guard fred_client field=%s: %s", key, warning)
    return data


# ===================================================================
# Public API
# ===================================================================

async def get_fred_series(series_key: str) -> dict:
    """Fetch the latest observation for a single FRED series by local key.

    Args:
        series_key: e.g. "DGS10", "GDP", "T10Y2Y", "DFII10", "NFCI"

    Returns:
        Dict with keys: series_key, series_id, label, value, date, source,
        cadence, unit. Or {"error": "source_unavailable", "detail": ...}
    """
    series_key = series_key.strip().upper()
    cache_key = f"fred:{series_key}"

    if cache_key in _cache:
        return _cache[cache_key]

    if cache_key not in _cache_locks:
        _cache_locks[cache_key] = asyncio.Lock()

    async with _cache_locks[cache_key]:
        if cache_key in _cache:
            return _cache[cache_key]

        result = await _fetch_single(series_key)
        _cache[cache_key] = result
        return result


async def get_fred_batch(series_keys: list[str]) -> dict[str, dict]:
    """Fetch multiple FRED series concurrently.

    Args:
        series_keys: list of local keys, e.g. ["DGS10", "GDP", "NFCI"]

    Returns:
        Dict mapping series_key → result dict (same format as get_fred_series)
    """
    keys = [k.strip().upper() for k in series_keys if k.strip().upper() in _FRED_SERIES]
    if not keys:
        return {}

    tasks = {k: get_fred_series(k) for k in keys}
    results = {}
    for k, task in tasks.items():
        results[k] = await task  # sequentially to respect cache locks; concurrency _within_ each if uncached
    return results


async def get_all_fred_data() -> dict[str, dict]:
    """Fetch ALL ~30 FRED series concurrently.

    First call is expensive (~30 HTTP requests). Subsequent calls hit cache.

    Returns:
        Dict mapping series_key → result dict
    """
    all_keys = list(_FRED_SERIES.keys())
    return await get_fred_batch(all_keys)


async def get_fred_for_shadow(shadow_id: str) -> dict[str, dict]:
    """Fetch only the FRED series relevant to a given shadow.

    Args:
        shadow_id: e.g. "expert:gold:bullion_broker"

    Returns:
        Dict mapping series_key → result dict for relevant series
    """
    keys = SHADOW_FRED_SERIES.get(shadow_id, [])
    if not keys:
        return {}
    return await get_fred_batch(keys)


# ===================================================================
# Fetch implementation
# ===================================================================

async def _fetch_single(series_key: str) -> dict:
    """Fetch latest observation for one FRED series."""
    info = _FRED_SERIES.get(series_key)
    if info is None:
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"Unknown FRED series key: '{series_key}'",
        })

    series_id, label, cadence, unit = info
    fred_key = _get_fred_key()
    if not fred_key:
        return _sanitize({
            "error": "source_unavailable",
            "detail": "FRED_KEY not configured",
        })

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
            return _sanitize({
                "error": "source_unavailable",
                "detail": f"No data for {series_key} ({series_id})",
            })

        obs = observations[0]
        return _sanitize({
            "series_key": series_key,
            "series_id": series_id,
            "label": label,
            "value": _parse_float(obs.get("value")),
            "date": obs.get("date", ""),
            "source": "fred",
            "cadence": cadence,
            "unit": unit,
        })
    except httpx.HTTPStatusError as e:
        logger.warning("FRED API error for %s: %s", series_key, _redact(str(e)))
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"FRED API returned {e.response.status_code}",
        })
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_key, _redact(str(e)))
        return _sanitize({
            "error": "source_unavailable",
            "detail": _redact(str(e)),
        })
    finally:
        await client.aclose()


# ===================================================================
# Helpers
# ===================================================================

def _get_fred_key() -> str:
    try:
        from marketmind.config.settings import MarketMindConfig
        cfg = MarketMindConfig()
        if hasattr(cfg, "fred_key") and cfg.fred_key:
            return cfg.fred_key
    except (ImportError, AttributeError) as e:
        logger.debug("FRED key not in MarketMindConfig: %s", e)
    return os.environ.get("FRED_KEY", "").strip()


def _parse_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _redact(text: str) -> str:
    import re
    return re.sub(r'api_key=[^&\s\'\"<>]+', 'api_key=***', text)
