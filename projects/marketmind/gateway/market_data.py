"""On-demand, single-ticker, session-cached market data fetcher.

Primary source: yfinance (universal US stock/ETF coverage, no API key)
Secondary source: Finnhub (free API key, 60 calls/min, env FINNHUB_KEY)
Crypto source: Binance public REST API (no key, tickers ending in "-USD")

Architecture — Per the Red Team audit (red-team-market-data-design.md):
- asyncio.Semaphore(5) + 200ms inter-request delay prevents Yahoo throttling
- asyncio.Lock per (ticker, data_type) prevents duplicate in-flight requests
- All string values pass through defang_text() before reaching callers
- Graceful degradation: return {} if all sources fail
- Binance: NEVER pass an API key header. Public endpoints only. No CCXT.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from marketmind.shadows.shadow_agent import defang_text

logger = logging.getLogger("marketmind.gateway.market_data")

# ---------------------------------------------------------------------------
# Lazy yfinance import — allows module to load in mock/test environments
# ---------------------------------------------------------------------------
try:
    import yfinance as yf
except ImportError:
    yf = None

# ---------------------------------------------------------------------------
# Session-level cache (lives as long as the Python process)
# ---------------------------------------------------------------------------
_market_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}

# ---------------------------------------------------------------------------
# Throttling: asyncio.Semaphore(5) + 200ms inter-request delay
# yfinance calls are sync and run in a thread executor; the semaphore
# limits concurrent executor submissions to 5; the global delay ensures
# no two yfinance calls start within 200ms of each other.
# ---------------------------------------------------------------------------
_yf_semaphore = asyncio.Semaphore(5)
_INTER_REQUEST_DELAY = 0.2  # seconds
_last_request_time: float = 0.0
_req_timing_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Finnhub configuration
# ---------------------------------------------------------------------------
_FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "").strip()
_FINNHUB_BASE = "https://finnhub.io/api/v1"

# ---------------------------------------------------------------------------
# Binance configuration — public endpoints only, NO API key ever
# ---------------------------------------------------------------------------
_BINANCE_BASE = "https://api.binance.com/api/v3"


# ===================================================================
# Public API
# ===================================================================


async def get_market_data(ticker: str, data_type: str) -> dict:
    """Fetch market data for a single ticker. On-demand, session-cached.

    Args:
        ticker: Stock/crypto ticker (e.g. "AAPL", "SPY", "BTC-USD").
        data_type: "fundamentals" | "ohlcv" | "technical".
            - fundamentals: company info, financial ratios (P/E, P/B, etc.)
            - ohlcv: daily OHLCV candles for technical analysis
            - technical: same as ohlcv (computed indicators are done by L3)

    Returns:
        Dict with market data, or empty dict {} if ALL sources fail.
    """
    key = _cache_key(ticker, data_type)

    # Fast path: cache hit
    if key in _market_cache:
        return _market_cache[key]

    # Get or create a per-key lock to deduplicate in-flight requests
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()

    async with _cache_locks[key]:
        # Double-check: another caller may have populated the cache while
        # we waited for the lock.
        if key in _market_cache:
            return _market_cache[key]

        result: dict = {}

        # ── Crypto path: Binance public REST (no API key) ──────────
        if ticker.upper().endswith("-USD"):
            result = await _fetch_binance(ticker, data_type)
        else:
            # ── Primary: yfinance ─────────────────────────────────
            result = await _fetch_yfinance(ticker, data_type)
            # ── Fallback: Finnhub ─────────────────────────────────
            if not result:
                result = await _fetch_finnhub(ticker, data_type)

        if not result:
            logger.warning(
                "No market data for %s/%s — all sources failed",
                ticker, data_type,
            )
        else:
            # Sanitize all string values before they reach any caller
            result = _sanitize_value(result)  # type: ignore[assignment]

        _market_cache[key] = result
        return result


# ===================================================================
# Cache helpers
# ===================================================================


def _cache_key(ticker: str, data_type: str) -> str:
    return f"{ticker.upper()}:{data_type}"


# ===================================================================
# yfinance (primary source)
# ===================================================================


async def _fetch_yfinance(ticker: str, data_type: str) -> dict:
    """Fetch data from yfinance with throttling (semaphore + delay).

    Two-level gating:
    1. _req_timing_lock: enforces >=200ms between successive yfinance call starts.
    2. _yf_semaphore(5): caps concurrent yfinance calls at 5.
    """
    if yf is None:
        logger.debug("yfinance not installed — skipping primary source")
        return {}

    # Enforce 200ms minimum spacing between yfinance call starts
    async with _req_timing_lock:
        global _last_request_time
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _INTER_REQUEST_DELAY:
            await asyncio.sleep(_INTER_REQUEST_DELAY - elapsed)
        _last_request_time = time.monotonic()

    # Cap concurrent in-flight yfinance calls
    async with _yf_semaphore:
        try:
            if data_type == "fundamentals":
                result = await asyncio.to_thread(_yf_fundamentals_sync, ticker)
            else:  # ohlcv / technical
                result = await asyncio.to_thread(_yf_ohlcv_sync, ticker)
        except Exception as exc:
            logger.warning("yfinance fetch failed for %s/%s: %s", ticker, data_type, exc)
            return {}

        return result


def _yf_fundamentals_sync(ticker: str) -> dict:
    """Synchronous yfinance fundamental fetch (runs in thread executor).

    Returns ticker.info + financial statements. Returns {} if the ticker
    is invalid, delisted, or the upstream source is broken.
    """
    try:
        t = yf.Ticker(ticker)  # type: ignore[union-attr]
        info = t.info
        if not info:
            return {}

        # Check for valid data: delisted/invalid tickers return mostly-empty info.
        # yfinance sets many fields to None for bad tickers.
        has_fundamental = (
            info.get("trailingPE") is not None
            or info.get("marketCap") is not None
            or info.get("regularMarketPrice") is not None
        )
        if not has_fundamental:
            logger.debug("yfinance returned empty info for ticker %s", ticker)
            return {}

        return {"source": "yfinance", "info": dict(info)}
    except Exception as exc:
        logger.debug("yfinance fundamental fetch error for %s: %s", ticker, exc)
        return {}


def _yf_ohlcv_sync(ticker: str) -> dict:
    """Synchronous yfinance OHLCV fetch (runs in thread executor).

    Returns 3 months of daily OHLCV as list of dicts. Returns {} if no
    data is available.
    """
    try:
        t = yf.Ticker(ticker)  # type: ignore[union-attr]
        hist = t.history(period="3mo")
        if hist is None or hist.empty:
            logger.debug("yfinance returned empty history for ticker %s", ticker)
            return {}

        # Convert DataFrame index (DatetimeIndex) to ISO-format strings
        # so the dict is JSON-serialisable. yfinance names the index "Date"
        # but the actual column name depends on the version — be defensive.
        hist = hist.reset_index()
        date_col = "Date" if "Date" in hist.columns else hist.columns[0]
        hist[date_col] = hist[date_col].dt.strftime("%Y-%m-%d")
        if date_col != "Date":
            hist = hist.rename(columns={date_col: "Date"})

        records = hist.to_dict(orient="records")
        return {"source": "yfinance", "history": records}
    except Exception as exc:
        logger.debug("yfinance OHLCV fetch error for %s: %s", ticker, exc)
        return {}


# ===================================================================
# Finnhub (secondary / fallback)
# ===================================================================


async def _fetch_finnhub(ticker: str, data_type: str) -> dict:
    """Fallback to Finnhub when yfinance fails or times out.

    Finnhub free tier: 60 API calls per minute. The fallback is only
    invoked when yfinance is unavailable, so we stay well within quota
    under normal conditions.
    """
    if not _FINNHUB_KEY:
        return {}

    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        if data_type == "fundamentals":
            return await _finnhub_fundamentals(client, ticker)
        else:  # ohlcv / technical
            return await _finnhub_ohlcv(client, ticker)
    except Exception as exc:
        logger.warning("Finnhub fetch failed for %s/%s: %s", ticker, data_type, exc)
        return {}
    finally:
        await client.aclose()


async def _finnhub_fundamentals(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch Finnhub company profile + key metrics."""
    # Company profile
    profile_url = f"{_FINNHUB_BASE}/stock/profile2?symbol={ticker}&token={_FINNHUB_KEY}"
    try:
        profile_resp = await client.get(profile_url)
        profile = profile_resp.json() if profile_resp.status_code == 200 else {}
    except Exception:
        profile = {}

    # Key metrics
    metrics_url = f"{_FINNHUB_BASE}/stock/metric?symbol={ticker}&token={_FINNHUB_KEY}"
    try:
        metrics_resp = await client.get(metrics_url)
        metrics = metrics_resp.json().get("metric", {}) if metrics_resp.status_code == 200 else {}
    except Exception:
        metrics = {}

    if not profile and not metrics:
        return {}

    return {"source": "finnhub", "profile": profile, "metrics": metrics}


async def _finnhub_ohlcv(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch Finnhub daily candles (1 year lookback)."""
    to_time = int(time.time())
    from_time = to_time - 365 * 24 * 3600
    candles_url = (
        f"{_FINNHUB_BASE}/stock/candle?symbol={ticker}"
        f"&resolution=D&from={from_time}&to={to_time}&token={_FINNHUB_KEY}"
    )
    try:
        resp = await client.get(candles_url)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if data.get("s") != "ok":
            return {}
        return {"source": "finnhub", "candles": data}
    except Exception:
        return {}


# ===================================================================
# Binance public REST (crypto tickers ending in "-USD")
# ===================================================================


async def _fetch_binance(ticker: str, data_type: str) -> dict:
    """Fetch crypto data from Binance public REST API.

    NO API key is ever sent. Public endpoints only.
    The ticker suffix "-USD" is converted to "USDT" for Binance symbols
    (e.g. "BTC-USD" → "BTCUSDT").
    """
    symbol = ticker.upper().replace("-USD", "USDT")
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        if data_type == "fundamentals":
            # Crypto has no P/E, P/B, etc. Return current price only.
            url = f"{_BINANCE_BASE}/ticker/price?symbol={symbol}"
            resp = await client.get(url)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            return {
                "source": "binance",
                "price": data.get("price"),
                "symbol": data.get("symbol"),
                "note": "Crypto does not have equity-style fundamentals (P/E, P/B, etc.)",
            }
        else:  # ohlcv / technical
            url = f"{_BINANCE_BASE}/klines?symbol={symbol}&interval=1d&limit=90"
            resp = await client.get(url)
            if resp.status_code != 200:
                return {}
            raw_klines = resp.json()
            if not raw_klines:
                return {}
            # Binance klines format:
            # [open_time, open, high, low, close, volume, close_time, ...]
            history = []
            for k in raw_klines:
                history.append({
                    "Date": time.strftime("%Y-%m-%d", time.gmtime(k[0] / 1000)),
                    "Open": float(k[1]),
                    "High": float(k[2]),
                    "Low": float(k[3]),
                    "Close": float(k[4]),
                    "Volume": float(k[5]),
                })
            return {"source": "binance", "history": history}
    except Exception as exc:
        logger.warning("Binance fetch failed for %s/%s: %s", ticker, data_type, exc)
        return {}
    finally:
        await client.aclose()


# ===================================================================
# Sanitization — all string values pass through defang_text()
# ===================================================================


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize string values in market data dicts/lists.

    Applies defang_text() to every string, preventing prompt-injection
    vectors from reaching L2/L3 LLM prompts.
    """
    if isinstance(value, str):
        return defang_text(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value
