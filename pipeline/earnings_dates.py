"""Earnings calendar — on-demand per-ticker earnings date lookup.

Phase G Layer 6: Returns known earnings dates for a ticker.
Strategy: yfinance calendar data (primary) with session-level in-memory cache.
Graceful degradation: returns note if data unavailable.

Usage:
  - Pre-fetch for L2 active set only (5-15 tickers), not full universe
  - Session-level in-memory cache (same ticker twice returns cached)
  - Not an L1 tool — L2/L3 consumption only
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger("marketmind.pipeline.earnings_dates")

# ── Session-level cache ─────────────────────────────────────────────────────────
_earnings_cache: dict[str, list[dict]] = {}


def _lazy_import_yfinance():
    """Lazy import yfinance — allows module to load in mock/test environments."""
    try:
        import yfinance as yf
        return yf
    except ImportError:
        logger.warning("yfinance not installed — earnings dates unavailable")
        return None


def _parse_fiscal_quarter(earnings_date: date) -> str:
    """Derive fiscal quarter label from earnings date.

    Apple-style fiscal year (ending September): Q1=Oct-Dec, Q2=Jan-Mar,
        Q3=Apr-Jun, Q4=Jul-Sep.
    Standard calendar fiscal: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec.

    Default: standard calendar quarter. AAPL and a few others use shifted fiscal
    years but the yfinance data typically includes the reported quarter directly.
    We derive a sensible label for context.
    """
    month = earnings_date.month
    year = earnings_date.year
    if month <= 3:
        return f"Q1 {year}"
    elif month <= 6:
        return f"Q2 {year}"
    elif month <= 9:
        return f"Q3 {year}"
    else:
        return f"Q4 {year}"


async def get_earnings_date(ticker: str) -> list[dict]:
    """Return known earnings dates for a ticker.

    Uses yfinance calendar data. Session-level in-memory cache prevents
    duplicate API calls for the same ticker.

    Args:
        ticker: Stock ticker (e.g. "AAPL").

    Returns:
        List of dicts, each with:
          - ticker: str
          - date: str (YYYY-MM-DD)
          - fiscal_quarter: str (e.g. "Q3 2026")
          - confirmed: bool (direct from exchange vs estimated)
          - source: str ("yfinance_calendar")
        If data unavailable, returns single-entry list with note.
    """
    ticker = ticker.strip().upper()
    cache_key = f"earnings_{ticker}"

    if cache_key in _earnings_cache:
        logger.debug("Earnings cache hit: %s", ticker)
        return _earnings_cache[cache_key]

    yf = _lazy_import_yfinance()
    if yf is None:
        result = [{
            "ticker": ticker,
            "note": "earnings_data_unavailable",
            "reason": "yfinance_not_installed",
        }]
        _earnings_cache[cache_key] = result
        return result

    try:
        ticker_obj = yf.Ticker(ticker)
        calendar = None
        try:
            calendar = ticker_obj.calendar
        except Exception:
            pass

        if calendar is None or (hasattr(calendar, 'empty') and calendar.empty):
            result = [{
                "ticker": ticker,
                "note": "earnings_data_unavailable",
                "reason": "no_calendar_data",
            }]
            _earnings_cache[cache_key] = result
            return result

        # calendar is typically a dict or DataFrame with earnings date info
        earnings_list: list[dict] = []

        if hasattr(calendar, 'to_dict'):
            cal_dict = calendar.to_dict()
        elif isinstance(calendar, dict):
            cal_dict = calendar
        else:
            cal_dict = {}

        # Extract earnings dates
        earnings_dates = cal_dict.get("Earnings Date", [])
        if not earnings_dates:
            # Alternative key formats from yfinance
            for alt_key in ("Earnings Date", "earningsDate", "Next Earnings Date"):
                if alt_key in cal_dict:
                    earnings_dates = cal_dict[alt_key]
                    break

        if not earnings_dates:
            result = [{
                "ticker": ticker,
                "note": "earnings_data_unavailable",
                "reason": "no_earnings_date_field",
            }]
            _earnings_cache[cache_key] = result
            return result

        # Normalize to list
        if not isinstance(earnings_dates, list):
            earnings_dates = [earnings_dates]

        # Get earnings estimates if available
        earnings_avg = cal_dict.get("Earnings Average")
        earnings_low = cal_dict.get("Earnings Low")
        earnings_high = cal_dict.get("Earnings High")
        revenue_avg = cal_dict.get("Revenue Average")

        today = date.today()
        for i, ed in enumerate(earnings_dates):
            if ed is None:
                continue
            # Convert to string date
            if isinstance(ed, (date, datetime)):
                date_str = ed.strftime("%Y-%m-%d") if hasattr(ed, 'strftime') else str(ed)[:10]
            else:
                date_str = str(ed)[:10]

            try:
                ed_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            # Only include future or very recent dates
            days_until = (ed_date - today).days
            if days_until < -30:
                continue  # Skip earnings more than 30 days in the past

            fiscal_quarter = _parse_fiscal_quarter(ed_date)

            # First entry is typically the confirmed/next date; others are estimated
            confirmed = (i == 0 and days_until >= -7)

            entry = {
                "ticker": ticker,
                "date": date_str,
                "fiscal_quarter": fiscal_quarter,
                "confirmed": confirmed,
                "source": "yfinance_calendar",
            }
            if i == 0:
                entry["earnings_avg_estimate"] = earnings_avg
                entry["earnings_low_estimate"] = earnings_low
                entry["earnings_high_estimate"] = earnings_high
                entry["revenue_avg_estimate"] = revenue_avg

            earnings_list.append(entry)

        if not earnings_list:
            earnings_list = [{
                "ticker": ticker,
                "note": "earnings_data_unavailable",
                "reason": "no_future_dates",
            }]

        logger.info(
            "Earnings dates: %s — %d upcoming dates",
            ticker, len(earnings_list),
        )

    except Exception as e:
        logger.warning("Earnings dates unavailable for %s: %s", ticker, e)
        earnings_list = [{
            "ticker": ticker,
            "note": "earnings_data_unavailable",
            "reason": f"fetch_error: {str(e)[:100]}",
        }]

    _earnings_cache[cache_key] = earnings_list
    return earnings_list
