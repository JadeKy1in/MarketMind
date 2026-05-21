"""On-demand, session-cached sentiment/positioning data fetchers.

Three public async functions, all using direct httpx (no new dependencies):

- get_cboe_pc_ratio() — CBOE Put/Call ratio (public CSV, no key)
- get_cnn_fear_greed() — CNN Fear & Greed Index (public JSON, no key)
- get_aaii_sentiment() — AAII Sentiment Survey (web scraping, no key)

All data is CONTEXT only, not trading signals (Law 3 compliance).
Session-level in-memory cache (same pattern as macro_data.py).
Graceful degradation: return {"error": "source_unavailable"} on failure.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from marketmind.integrity.input_guard import sanitize_for_llm_prompt

logger = logging.getLogger("marketmind.gateway.sentiment_fetcher")

# ---------------------------------------------------------------------------
# Source URL constants
# ---------------------------------------------------------------------------
_CBOE_CSV_URL = "https://www.cboe.com/us/options/market_statistics/symbol_data/csv/?mkt=cone"
_CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
_AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"

# ---------------------------------------------------------------------------
# Session-level cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _clear_cache() -> None:
    """Clear the module-level cache (used between tests)."""
    _cache.clear()
    _cache_locks.clear()


def _sanitize(data: dict, source: str = "sentiment_data") -> dict:
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


async def get_cboe_pc_ratio() -> dict:
    """Fetch the latest CBOE Put/Call ratios from the public CSV endpoint."""
    key = "cboe_pc"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_cboe()
        _cache[key] = result
        return result


async def get_cnn_fear_greed() -> dict:
    """Fetch the latest CNN Fear & Greed Index from the public JSON endpoint."""
    key = "cnn_fg"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_cnn()
        _cache[key] = result
        return result


async def get_aaii_sentiment() -> dict:
    """Fetch the latest AAII Sentiment Survey from the AAII web page.

    Uses text scraping since there is no public API.
    """
    key = "aaii"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_aaii()
        _cache[key] = result
        return result


# ===================================================================
# CBOE Put/Call Ratio implementation
# ===================================================================


async def _fetch_cboe() -> dict:
    """Fetch and parse the CBOE daily market statistics CSV."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_CBOE_CSV_URL)
        resp.raise_for_status()
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "CBOE CSV returned empty — no rows found",
            }, "cboe_data")

        last = rows[-1]
        date_val = last.get("Date", last.get("date", ""))
        total_val = _parse_float(
            last.get("Total P/C Ratio", last.get("total_pc_ratio", last.get("Total", 0)))
        )
        equity_val = _parse_float(
            last.get("Equity P/C Ratio", last.get("equity_pc_ratio", last.get("Equity", 0)))
        )
        etf_val = _parse_float(
            last.get("ETF P/C Ratio", last.get("etf_pc_ratio", last.get("ETF", 0)))
        )

        return _sanitize({
            "indicator": "put_call_ratio",
            "total": total_val,
            "equity": equity_val,
            "etf": etf_val,
            "date": date_val,
            "source": "cboe",
            "cadence": "daily",
        }, "cboe_data")

    except httpx.HTTPStatusError as e:
        logger.warning("CBOE CSV HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"CBOE CSV returned HTTP {e.response.status_code}",
        }, "cboe_data")
    except Exception as e:
        logger.warning("CBOE fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "cboe_data")
    finally:
        await client.aclose()


# ===================================================================
# CNN Fear & Greed Index implementation
# ===================================================================


async def _fetch_cnn() -> dict:
    """Fetch and parse the CNN Fear & Greed Index JSON."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_CNN_FG_URL)
        resp.raise_for_status()
        data = resp.json()

        fg = data.get("fear_and_greed", {})
        if not fg:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "CNN Fear & Greed JSON had no fear_and_greed key",
            }, "cnn_data")

        raw_value = fg.get("score", fg.get("value", 0))
        value = _parse_float(raw_value)
        rating = _fg_rating(value)
        timestamp_str = _extract_cnn_date(data)

        return _sanitize({
            "indicator": "fear_greed",
            "value": value,
            "rating": rating,
            "date": timestamp_str,
            "source": "cnn",
            "cadence": "daily",
        }, "cnn_data")

    except httpx.HTTPStatusError as e:
        logger.warning("CNN Fear & Greed HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"CNN API returned HTTP {e.response.status_code}",
        }, "cnn_data")
    except Exception as e:
        logger.warning("CNN Fear & Greed fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "cnn_data")
    finally:
        await client.aclose()


def _fg_rating(score: float) -> str:
    """Map CNN Fear & Greed numerical score to rating label.

    0-25: extreme_fear, 25-45: fear, 45-55: neutral, 55-75: greed, 75-100: extreme_greed.
    """
    if score <= 25:
        return "extreme_fear"
    elif score <= 45:
        return "fear"
    elif score <= 55:
        return "neutral"
    elif score <= 75:
        return "greed"
    else:
        return "extreme_greed"


def _extract_cnn_date(data: dict) -> str:
    """Extract the most recent date from CNN Fear & Greed JSON structure."""
    fg = data.get("fear_and_greed", {})
    last_updated = fg.get("last_updated", fg.get("timestamp", ""))
    if last_updated:
        return str(last_updated)
    hist = data.get("fear_and_greed_historical", {}).get("data", [])
    if hist and isinstance(hist, list):
        first = hist[0]
        dt = first.get("x", "")
        if dt:
            return str(dt)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ===================================================================
# AAII Sentiment Survey implementation
# ===================================================================


async def _fetch_aaii() -> dict:
    """Fetch and scrape the AAII Sentiment Survey page."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_AAII_URL)
        resp.raise_for_status()
        html = resp.text

        bullish_pct = _extract_aaii_pct(html, "bullish")
        bearish_pct = _extract_aaii_pct(html, "bearish")
        neutral_pct = _extract_aaii_pct(html, "neutral")

        if bullish_pct is None and bearish_pct is None and neutral_pct is None:
            return _sanitize({
                "error": "source_unavailable",
                "detail": "AAII page scraping failed — could not extract sentiment percentages",
            }, "aaii_data")

        spread = (bullish_pct or 0) - (bearish_pct or 0)
        date_val = _extract_aaii_date(html)

        return _sanitize({
            "indicator": "aaii_sentiment",
            "bullish_pct": bullish_pct or 0,
            "bearish_pct": bearish_pct or 0,
            "neutral_pct": neutral_pct or 0,
            "spread": spread,
            "date": date_val,
            "source": "aaii",
            "cadence": "weekly",
        }, "aaii_data")

    except httpx.HTTPStatusError as e:
        logger.warning("AAII HTTP error: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": f"AAII page returned HTTP {e.response.status_code}",
        }, "aaii_data")
    except Exception as e:
        logger.warning("AAII fetch failed: %s", e)
        return _sanitize({
            "error": "source_unavailable",
            "detail": str(e),
        }, "aaii_data")
    finally:
        await client.aclose()


def _extract_aaii_pct(html: str, label: str) -> float | None:
    """Extract a sentiment percentage from AAII HTML using regex.

    Tries 3 patterns: label before pct, pct before label, label in heading context.
    """
    # Pattern 1: label within ~200 chars before a percentage
    pat = re.compile(
        re.escape(label) + r'.{0,200}?(\d{1,2}(?:\.\d)?)\s*%',
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(html)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    # Pattern 2: percentage then label within ~200 chars
    pat2 = re.compile(
        r'(\d{1,2}(?:\.\d)?)\s*%.{0,200}?' + re.escape(label),
        re.IGNORECASE | re.DOTALL,
    )
    m2 = pat2.search(html)
    if m2:
        try:
            return float(m2.group(1))
        except ValueError:
            pass

    # Pattern 3: label in broader context up to ~500 chars
    pat3 = re.compile(
        r'(?:' + re.escape(label) + r').{0,500}?(\d{1,2}(?:\.\d)?)\s*%',
        re.IGNORECASE | re.DOTALL,
    )
    m3 = pat3.search(html)
    if m3:
        try:
            return float(m3.group(1))
        except ValueError:
            pass

    return None


def _extract_aaii_date(html: str) -> str:
    """Extract the survey date from AAII HTML. Falls back to UTC now."""
    date_patterns = [
        r'Results\s+for\s+(?:Week\s+Ending\s+)?(\w+\s+\d{1,2},\s+\d{4})',
        r'Week\s+Ending\s+(\w+\s+\d{1,2},\s+\d{4})',
        r'(\d{1,2}/\d{1,2}/\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for pat in date_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ===================================================================
# Helpers
# ===================================================================


def _parse_float(val: Any) -> float:
    """Parse a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
