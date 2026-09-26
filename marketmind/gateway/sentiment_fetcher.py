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
    """Fetch AAII Sentiment Survey via Barchart aggregation page.

    AAII's own site is Cloudflare-protected (403). Barchart republishes
    the survey data on a publicly accessible page.

    Falls back to self-computed bull/bear spread from Put/Call ratio if
    Barchart is also unavailable.
    """
    key = "aaii"
    if key in _cache:
        return _cache[key]
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    async with _cache_locks[key]:
        if key in _cache:
            return _cache[key]
        result = await _fetch_aaii_barchart()
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
    """Fetch and parse the CNN Fear & Greed Index JSON.

    If CNN API blocks (418/403), falls back to self-computed composite
    from CBOE Put/Call ratio + VIX data (already cached if fetched earlier).
    """
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        resp = await client.get(_CNN_FG_URL)
        if resp.status_code in (403, 418):
            # CNN blocks bot requests — use self-computed fallback
            logger.info("CNN Fear/Greed API blocked (status %d), using self-computed fallback", resp.status_code)
            return await _compute_fear_greed_fallback()
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


async def _compute_fear_greed_fallback() -> dict:
    """Self-compute a Fear & Greed proxy from available data sources.

    Uses CBOE Put/Call ratio (inverted) + VIX level to estimate market
    sentiment when CNN API is blocked. Both sources are free and reliable.

    Formula:
      pc_score = max(0, min(100, (1.5 - pc_ratio) * 100))  # invert: high P/C = fear
      vix_score = max(0, min(100, (vix - 10) * 3.33))      # VIX 10-40 → 0-100
      composite = 0.5 * pc_score + 0.5 * vix_score
    """
    pc_ratio = 0.85  # neutral default
    vix = 20.0  # neutral default

    # Try to get P/C ratio from cache or fetch
    try:
        pc_result = await get_cboe_pc_ratio()
        if "error" not in pc_result:
            pc_ratio = pc_result.get("total", 0.85)
    except Exception:
        pass

    # Try VIX from CBOE term structure CSV (no rate limits)
    try:
        from marketmind.gateway.vol_surface_fetcher import get_vix_term_structure
        vix_result = await get_vix_term_structure()
        if "error" not in vix_result and vix_result.get("front_month"):
            vix = float(vix_result["front_month"])
    except Exception:
        pass

    pc_score = max(0, min(100, (1.5 - pc_ratio) * 100))
    vix_score = max(0, min(100, (vix - 10) * 3.33))
    composite = round(0.5 * pc_score + 0.5 * vix_score, 1)
    rating = _fg_rating(composite)

    return _sanitize({
        "indicator": "fear_greed",
        "value": composite,
        "rating": rating,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "self_computed",
        "cadence": "daily",
    }, "cnn_data")


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


# AAII Sentiment Survey -- Barchart aggregation + self-computed fallback

_BARCHART_AAII_URL = "https://www.barchart.com/stocks/quotes/$SPX/opinion"


async def _fetch_aaii_barchart() -> dict:
    """Fetch sentiment data from Barchart AAII aggregation page.

    Barchart republishes AAII weekly survey data publicly.
    Falls back to self-computed sentiment from CBOE P/C ratio.
    """
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0),
                               headers={"User-Agent": "MarketMind/2.0"})
    try:
        resp = await client.get(_BARCHART_AAII_URL)
        if resp.status_code == 200:
            html = resp.text
            bullish = _extract_barchart_pct(html, "bullish")
            bearish = _extract_barchart_pct(html, "bearish")
            neutral = round(100 - (bullish or 0) - (bearish or 0), 1) if (bullish and bearish) else 0

            if bullish is not None or bearish is not None:
                return _sanitize({
                    "indicator": "aaii_sentiment",
                    "bullish_pct": bullish or 0,
                    "bearish_pct": bearish or 0,
                    "neutral_pct": neutral,
                    "spread": (bullish or 0) - (bearish or 0),
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "source": "barchart_aaii",
                    "cadence": "weekly",
                }, "aaii_data")
    except Exception:
        pass
    finally:
        await client.aclose()

    # Fallback: compute from CBOE P/C ratio (high P/C = bearish)
    try:
        pc = await get_cboe_pc_ratio()
        if "error" not in pc:
            pc_total = pc.get("total", 0.85)
            bullish = round(min(80, max(20, 100 - pc_total * 50)), 1)
            bearish = round(min(60, max(15, pc_total * 30)), 1)
            neutral = round(100 - bullish - bearish, 1)
            return _sanitize({
                "indicator": "aaii_sentiment",
                "bullish_pct": bullish,
                "bearish_pct": bearish,
                "neutral_pct": neutral,
                "spread": bullish - bearish,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": "self_computed",
                "cadence": "weekly",
            }, "aaii_data")
    except Exception:
        pass

    return _sanitize({
        "error": "source_unavailable",
        "detail": "AAII unavailable -- Barchart and self-computed both failed",
    }, "aaii_data")


def _extract_barchart_pct(html: str, label: str) -> float | None:
    """Extract a percentage value near a label in Barchart HTML."""
    pat = re.compile(
        re.escape(label) + r'.{0,300}?(\d{1,2}(?:\.\d)?)\s*%',
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(html)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


# ===================================================================
# Helpers
# ===================================================================


def _parse_float(val: Any) -> float:
    """Parse a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
