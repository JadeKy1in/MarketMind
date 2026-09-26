"""On-demand, session-cached global volatility index data fetchers.

Two public async functions, using httpx + yfinance fallback (no new dependencies):

- get_vvix() — CBOE VVIX via yfinance
- get_global_vol_indexes() — Global vol indexes via yfinance (VSTOXX, NKY VI, KOSPI VI)

All data is CONTEXT only, not trading signals (Law 3 compliance).
Session-level in-memory cache (same pattern as vol_surface_fetcher.py).
Graceful degradation: return {"error": "source_unavailable"} on failure.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from marketmind.integrity.input_guard import sanitize_for_llm_prompt

logger = logging.getLogger("marketmind.gateway.vol_global_fetcher")

# ---------------------------------------------------------------------------
# Source URL constants
# ---------------------------------------------------------------------------
_YF_VVIX = "^VVIX"
_YF_VSTOXX = "^V2TX"
_YF_NKY_VI = "^VNKY"
_YF_KOSPI_VI = "^VKOSPI"

# ---------------------------------------------------------------------------
# Session-level cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    """Clear the module-level cache (used between tests)."""
    _cache.clear()
    _cache_locks.clear()


def _sanitize(data: dict, source: str = "vol_global_data") -> dict:
    """Sanitize all string fields in a data dict before LLM consumption."""
    for key, val in list(data.items()):
        if isinstance(val, str):
            result = sanitize_for_llm_prompt(val, source=source)
            data[key] = result.sanitized
            for warning in result.warnings:
                logger.warning("input_guard [%s] field=%s: %s", source, key, warning)
    return data


# ===================================================================
# Public API
# ===================================================================


async def get_vvix() -> dict:
    """Fetch CBOE VVIX (volatility of VIX) via yfinance ^VVIX ticker."""
    key = "vvix"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_vvix()
        _cache[key] = result
        return result


async def get_global_vol_indexes() -> dict:
    """Fetch global volatility indexes via yfinance.

    Returns VSTOXX (Euro Stoxx 50 vol), NKY VI (Nikkei vol), KOSPI VI (Korea vol).
    """
    key = "global_vol"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_global_vol()
        _cache[key] = result
        return result


# ===================================================================
# VVIX implementation (yfinance)
# ===================================================================


async def _fetch_vvix() -> dict:
    """Fetch CBOE VVIX from Yahoo Finance ^VVIX ticker."""
    return await _fetch_yfinance_ticker(_YF_VVIX, "vvix")


# ===================================================================
# Global Volatility Indexes implementation (yfinance multi-ticker)
# ===================================================================


async def _fetch_global_vol() -> dict:
    """Fetch global volatility indexes: VSTOXX, Nikkei VI, Korea KOSPI VI."""
    tickers = {
        "vstoxx": _YF_VSTOXX,
        "vnky": _YF_NKY_VI,
        "vkospi": _YF_KOSPI_VI,
    }

    results: dict[str, float] = {}
    date_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    errors: list[str] = []

    for i, (name, ticker) in enumerate(tickers.items()):
        if i > 0:
            await asyncio.sleep(2.0)  # rate-limit yfinance calls
        try:
            data = await _fetch_yfinance_raw(ticker)
            if data is not None:
                results[name] = data["value"]
                if data.get("date"):
                    date_val = data["date"]
            else:
                results[name] = 0.0
                errors.append(f"{name}: no data returned")
        except Exception as e:
            results[name] = 0.0
            errors.append(f"{name}: {e}")

    if errors and all(v == 0.0 for v in results.values()):
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"Global vol indexes — all tickers failed: {'; '.join(errors)}",
        }, "global_vol_data")

    return _sanitize({
        "indicator": "global_vol",
        "vstoxx": results.get("vstoxx", 0.0),
        "vnky": results.get("vnky", 0.0),
        "vkospi": results.get("vkospi", 0.0),
        "date": date_val,
        "source": "multi",
        "cadence": "daily",
    }, "global_vol_data")


# ===================================================================
# yfinance helpers
# ===================================================================


async def _fetch_yfinance_ticker(ticker: str, indicator: str) -> dict:
    """Fetch a single ticker from yfinance and return standardized dict."""
    data = await _fetch_yfinance_raw(ticker)
    if data is None:
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"yfinance returned no data for {ticker}",
        }, f"{indicator}_data")

    return _sanitize({
        "indicator": indicator,
        "value": data["value"],
        "date": data["date"],
        "source": "cboe",
        "cadence": "daily",
    }, f"{indicator}_data")


async def _fetch_yfinance_raw(ticker: str) -> dict | None:
    """Fetch OHLCV from yfinance and extract latest close price.

    Returns {"value": float, "date": str} or None on failure.
    Uses asyncio.to_thread to avoid blocking the event loop.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available — cannot fetch %s", ticker)
        return None

    try:
        stock = await asyncio.to_thread(_yf_get_history, ticker)
        if stock is None or stock.empty:
            logger.warning("No data for ticker %s via yfinance", ticker)
            return None

        latest = stock.iloc[-1]
        close_val = float(latest["Close"])
        date_str = (
            latest.name.strftime("%Y-%m-%d")
            if hasattr(latest.name, "strftime")
            else str(latest.name)[:10]
        )

        return {"value": close_val, "date": date_str}
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", ticker, e)
        return None


def _yf_get_history(ticker: str):
    """Synchronous yfinance call — run via asyncio.to_thread."""
    import yfinance as yf
    stock = yf.Ticker(ticker)
    return stock.history(period="5d")
