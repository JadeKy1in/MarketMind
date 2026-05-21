"""On-demand, session-cached volatility surface data fetchers.

Two public async functions, using httpx + yfinance fallback (no new dependencies):

- get_vix_term_structure() — CBOE VIX futures term structure (public CSV)
- get_skew_index() — CBOE SKEW Index, yfinance fallback

All data is CONTEXT only, not trading signals (Law 3 compliance).
Session-level in-memory cache (same pattern as macro_data.py).
Graceful degradation: return {"error": "source_unavailable"} on failure.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from marketmind.integrity.input_guard import sanitize_for_llm_prompt

logger = logging.getLogger("marketmind.gateway.vol_surface_fetcher")

# ---------------------------------------------------------------------------
# Source URL constants
# ---------------------------------------------------------------------------
_CBOE_VIX_TERM_URL = "https://www.cboe.com/us/futures/market_statistics/vix_term_structure/data.csv"
_CBOE_SKEW_URL = "https://www.cboe.com/us/indices/dashboard/SKEW/"

# Yahoo Finance tickers for volatility indexes
_YF_SKEW = "^SKEW"

# ---------------------------------------------------------------------------
# Session-level cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    """Clear the module-level cache (used between tests)."""
    _cache.clear()
    _cache_locks.clear()


def _sanitize(data: dict, source: str = "vol_surface_data") -> dict:
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


async def get_vix_term_structure() -> dict:
    """Fetch VIX futures term structure from CBOE public CSV.

    Returns front-month and next-month VIX futures prices, contango/backwardation.
    """
    key = "vix_term"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_vix_term_structure()
        _cache[key] = result
        return result


async def get_skew_index() -> dict:
    """Fetch CBOE SKEW Index (tail risk pricing).

    Tries CBOE page first, falls back to yfinance ^SKEW ticker.
    """
    key = "skew"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_skew()
        _cache[key] = result
        return result


# ===================================================================
# VIX Term Structure implementation (CBOE CSV)
# ===================================================================


async def _fetch_vix_term_structure() -> dict:
    """Fetch and parse CBOE VIX term structure CSV.

    Returns front-month and next-month futures with contango/backwardation.
    """
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_CBOE_VIX_TERM_URL)
        resp.raise_for_status()
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

        if not rows:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "CBOE VIX term structure CSV returned empty",
            }, "vix_term_data")

        # Group rows by trade date to find front and next month for latest date
        date_col = _find_column(rows[0], ["Trade Date", "Date", "trade_date", "date"])
        expiry_col = _find_column(rows[0], ["Futures", "Expiration", "futures", "expiration", "Symbol", "symbol"])
        price_col = _find_column(rows[0], ["Price", "Settle", "price", "settle", "Close", "close"])

        if not date_col or not expiry_col or not price_col:
            # Try alternate format: each row is a single date with multiple expiry columns
            return await _parse_vix_term_wide_format(rows)

        # Long format: group by date, find nearest two expiries
        date_groups: dict[str, list[dict]] = {}
        for row in rows:
            d = row.get(date_col, "").strip()
            exp = row.get(expiry_col, "").strip()
            prc = _parse_float(row.get(price_col, ""))
            if d and prc > 0:
                if d not in date_groups:
                    date_groups[d] = []
                date_groups[d].append({"expiry": exp, "price": prc})

        if not date_groups:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "CBOE VIX term structure CSV — no valid date/price rows",
            }, "vix_term_data")

        latest_date = sorted(date_groups.keys())[-1]
        contracts = sorted(date_groups[latest_date], key=lambda x: _expiry_sort_key(x["expiry"]))

        if len(contracts) < 2:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "CBOE VIX term structure — fewer than 2 contracts on latest date",
            }, "vix_term_data")

        front_price = contracts[0]["price"]
        next_price = contracts[1]["price"]

        return _build_vix_term_result(latest_date, front_price, next_price)

    except httpx.HTTPStatusError as e:
        logger.warning("CBOE VIX term structure HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"CBOE VIX term structure returned HTTP {e.response.status_code}",
        }, "vix_term_data")
    except Exception as e:
        logger.warning("VIX term structure fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "vix_term_data")
    finally:
        await client.aclose()


async def _parse_vix_term_wide_format(rows: list[dict]) -> dict:
    """Parse wide-format CSV where columns are date, then expiry1_price, expiry2_price, etc.

    Fallback when normal DictReader column detection fails.
    """
    if not rows:
        return _sanitize({
            "error": "source_unavailable",
            "detail": "CBOE VIX term structure CSV — wide format parse failed (no rows)",
        }, "vix_term_data")

    # Try to find a date column and numeric price columns
    date_col = None
    price_cols = []

    for col in rows[0].keys():
        col_lower = col.lower().strip()
        if any(kw in col_lower for kw in ["date", "trade"]):
            date_col = col
        elif any(kw in col_lower for kw in ["price", "settle", "close", "vx"]):
            price_cols.append(col)

    if not date_col:
        # Use first column as date, rest as prices
        all_cols = list(rows[0].keys())
        date_col = all_cols[0]
        price_cols = all_cols[1:]

    if len(price_cols) < 2:
        # Try numeric columns if named columns didn't work
        price_cols = []
        for col in rows[0].keys():
            if col != date_col:
                val = rows[-1].get(col, "").strip()
                if val and _parse_float(val) > 0:
                    price_cols.append(col)

    if len(price_cols) < 2:
        return _sanitize({
            "error": "source_unavailable",
            "detail": "CBOE VIX term structure — wide format has < 2 price columns",
        }, "vix_term_data")

    last = rows[-1]
    date_val = last.get(date_col, "").strip()
    front_price = _parse_float(last.get(price_cols[0], ""))
    next_price = _parse_float(last.get(price_cols[1], ""))

    if front_price == 0.0 and next_price == 0.0:
        return _sanitize({
            "error": "source_unavailable",
            "detail": "CBOE VIX term structure — zero prices in latest row",
        }, "vix_term_data")

    return _build_vix_term_result(date_val, front_price, next_price)


def _build_vix_term_result(date_val: str, front_price: float, next_price: float) -> dict:
    """Build standardized VIX term structure response."""
    contango_pct = 0.0
    in_backwardation = False
    if front_price > 0:
        contango_pct = round(((next_price - front_price) / front_price) * 100, 2)
        in_backwardation = contango_pct < 0

    return _sanitize({
        "indicator": "vix_term_structure",
        "front_month": front_price,
        "next_month": next_price,
        "contango_pct": contango_pct,
        "in_backwardation": in_backwardation,
        "date": date_val or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "cboe",
        "cadence": "daily",
    }, "vix_term_data")


# ===================================================================
# SKEW Index implementation (CBOE → yfinance fallback)
# ===================================================================


async def _fetch_skew() -> dict:
    """Fetch CBOE SKEW Index. Tries CBOE page, falls back to yfinance."""
    # Primary: try CBOE page scraping
    result = await _fetch_skew_from_cboe()
    if "error" not in result:
        return result

    # Fallback: yfinance
    logger.info("CBOE SKEW page unavailable, falling back to yfinance ^SKEW")
    return await _fetch_skew_from_yfinance()


async def _fetch_skew_from_cboe() -> dict:
    """Attempt to scrape SKEW value from CBOE page."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_CBOE_SKEW_URL)
        resp.raise_for_status()
        html = resp.text

        # Try to find a numeric value near "SKEW" label
        # CBOE pages typically embed JSON or have specific HTML structure
        # Pattern: look for large numeric value (100-200 range typical for SKEW)
        import re

        # Try JSON-LD or embedded data first
        json_patterns = [
            r'"SKEW"[:\s]+(\d+\.?\d*)',
            r'"skew"[:\s]+(\d+\.?\d*)',
            r'"lastSalePrice"[:\s]+(\d+\.?\d*)',
            r'"price"[:\s]+(\d+\.?\d*)',
        ]
        for pat in json_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                value = _parse_float(m.group(1))
                if 50 < value < 250:  # SKEW typically ranges 100-150
                    return _sanitize({
                        "indicator": "skew",
                        "value": value,
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "source": "cboe",
                        "cadence": "daily",
                    }, "skew_data")

        # Try broader HTML patterns
        html_patterns = [
            r'SKEW\s*</\w+>\s*<\w+[^>]*>\s*(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*</\w+>\s*<\w+[^>]*>\s*SKEW',
            r'SKEW[^<]*?(\d{3}\.?\d*)',
        ]
        for pat in html_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                value = _parse_float(m.group(1))
                if 50 < value < 250:
                    return _sanitize({
                        "indicator": "skew",
                        "value": value,
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "source": "cboe",
                        "cadence": "daily",
                    }, "skew_data")

        return _sanitize({
            "error": "source_unavailable",
            "detail": "CBOE SKEW page — could not extract numeric value",
        }, "skew_data")

    except httpx.HTTPStatusError as e:
        logger.warning("CBOE SKEW HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"CBOE SKEW page returned HTTP {e.response.status_code}",
        }, "skew_data")
    except Exception as e:
        logger.warning("CBOE SKEW fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "skew_data")
    finally:
        await client.aclose()


async def _fetch_skew_from_yfinance() -> dict:
    """Fetch SKEW Index from Yahoo Finance ^SKEW ticker."""
    return await _fetch_yfinance_ticker(_YF_SKEW, "skew")


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


# ===================================================================
# Helpers
# ===================================================================


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


def _expiry_sort_key(expiry_str: str) -> tuple[int, int, int]:
    """Parse expiry string into sortable (year, month, day) tuple.

    Handles formats like: "VX/Jun 2026", "Jun 2026", "2026-06-15",
    "VX00 Jun26", "June 15 2026", etc. Unknown strings sort to far future.
    """
    import re

    text = expiry_str.lower().strip()

    # Extract year (4-digit)
    year_match = re.search(r'(20\d{2})', text)
    year = int(year_match.group(1)) if year_match else 9999

    # Extract month (abbreviated or full name)
    month = 0
    for name, num in sorted(_MONTH_MAP.items(), key=lambda x: -len(x[0])):
        if name in text:
            month = num
            break

    # Extract day
    day = 0
    day_pat = re.search(r'(\d{1,2})(?:st|nd|rd|th)?(?:\s|,|\b|[A-Za-z])', text)
    if day_pat:
        try:
            day = int(day_pat.group(1))
        except ValueError:
            pass

    return (year, month, day)


def _parse_float(val: Any) -> float:
    """Parse a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _find_column(row: dict, candidates: list[str]) -> str | None:
    """Find the first matching column name from candidates in the row dict."""
    row_keys_lower = {k.lower().strip(): k for k in row.keys()}
    for candidate in candidates:
        cand_lower = candidate.lower().strip()
        if cand_lower in row_keys_lower:
            return row_keys_lower[cand_lower]
    return None
