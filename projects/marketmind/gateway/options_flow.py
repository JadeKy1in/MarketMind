"""Options flow data via yfinance option chains (OBSERVATIONAL only).

Phase G Layer 6: Fetches unusual options activity using yfinance option chains.
Uses RELATIVE thresholds (market-cap adjusted) per Red Team audit recommendation.

CRITICAL — Law 3 boundary:
  Options flow is OBSERVATIONAL ONLY. It goes to L2/L3 as confirmation/timing.
  It does NOT go to L1 narrative. Not used as a primary signal source.
  Prompt annotation included: "Use to CONFIRM or QUESTION existing theses,
  not to INITIATE new ones."

Red Team design: CONDITIONAL PASS (red-team-options-calendar-design.md).
Blockers addressed:
  1. SKIP Tradier entirely — yfinance options only (Law 2 concern).
  2. Premium filter with RELATIVE thresholds (market-cap adjusted).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("marketmind.gateway.options_flow")

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_ALERTS_PER_TICKER = 5
MIN_DTE = 5       # Minimum days-to-expiration (exclude 0-DTE gamblers)
MAX_DTE = 120     # Maximum days-to-expiration (through quarter-end positioning)
MEGA_CAP_THRESHOLD = 500e9   # $500B market cap
MEGA_CAP_MIN_PREMIUM = 100000  # $100K minimum premium for mega-caps
PREMIUM_NOTIONAL_PCT_THRESHOLD = 0.005  # 0.5% of underlying*100
VOLUME_RATIO_THRESHOLD = 3.0  # 3x average daily option volume
OPTIONS_FLOW_RELIABILITY = 0.12  # Inherently noisy — low reliability weight

# ── Prompt annotation constant (injected with every options flow result) ────────
OBSERVATIONAL_ANNOTATION = (
    "Options flow data is OBSERVATIONAL. "
    "Use to CONFIRM or QUESTION existing theses, not to INITIATE new ones."
)

# ── Session-level cache ─────────────────────────────────────────────────────────
_options_cache: dict[str, dict] = {}


def _lazy_import_yfinance():
    """Lazy import yfinance — allows module to load in mock/test environments."""
    try:
        import yfinance as yf
        return yf
    except ImportError:
        logger.warning("yfinance not installed — options flow unavailable")
        return None


def _calculate_premium(
    volume: int,
    last_price: float,
) -> float:
    """Calculate total premium notional for a single option contract.

    Each option contract represents 100 shares. Premium notional = volume * price * 100.
    """
    return volume * last_price * 100


def _filter_by_dte(dte: int | None) -> bool:
    """Check if DTE is within the acceptable range (5-120 days)."""
    if dte is None:
        return True  # Include if DTE unknown
    return MIN_DTE <= dte <= MAX_DTE


def _build_alerts(
    ticker: str,
    option_data: dict | None,
    underlying_price: float | None = None,
    market_cap: float | None = None,
    avg_daily_volume: int | None = None,
) -> list[dict]:
    """Build options flow alert list from option chain data.

    Applies the premium filter with RELATIVE thresholds:
      - premium_notional_pct = total_premium / (underlying_price * 100) > 0.5%
      - volume_ratio = volume / avg_daily_option_volume > 3.0x
      - Market-cap skip: mega-cap (>$500B) requires premium > $100K

    Args:
        ticker: Stock ticker.
        option_data: Raw option chain data dict.
        underlying_price: Current underlying price (required for relative calc).
        market_cap: Market capitalization for mega-cap threshold.
        avg_daily_volume: Average daily option volume for ratio check.

    Returns:
        List of alert dicts (capped at MAX_ALERTS_PER_TICKER).
    """
    if not option_data or not underlying_price or underlying_price <= 0:
        return []

    options = option_data.get("options", [])
    if not isinstance(options, list) or not options:
        return []

    alerts: list[dict] = []

    for opt in options:
        volume = opt.get("volume", 0)
        last_price = opt.get("lastPrice", 0)
        dte = opt.get("dte")

        # DTE filter
        if not _filter_by_dte(dte):
            continue

        # Skip zero-volume
        if volume <= 0:
            continue

        premium = _calculate_premium(volume, last_price)

        # Mega-cap minimum premium gate
        if market_cap and market_cap >= MEGA_CAP_THRESHOLD and premium < MEGA_CAP_MIN_PREMIUM:
            continue

        # Relative premium notional check
        premium_pct = premium / (underlying_price * 100)
        if premium_pct < PREMIUM_NOTIONAL_PCT_THRESHOLD:
            continue

        # Volume ratio check (if avg daily volume available)
        if avg_daily_volume and avg_daily_volume > 0:
            vol_ratio = volume / avg_daily_volume
            if vol_ratio < VOLUME_RATIO_THRESHOLD:
                continue
        else:
            vol_ratio = None

        alerts.append({
            "ticker": ticker,
            "contract": opt.get("contractSymbol", ""),
            "option_type": opt.get("optionType", "call"),
            "strike": opt.get("strike", 0),
            "expiration": opt.get("expiration", ""),
            "dte": dte,
            "volume": volume,
            "last_price": last_price,
            "premium_notional": round(premium, 2),
            "premium_notional_pct": round(premium_pct, 4),
            "volume_ratio": round(vol_ratio, 2) if vol_ratio else None,
            "open_interest": opt.get("openInterest", 0),
            "implied_volatility": opt.get("impliedVolatility"),
        })

    # Sort by premium notional descending
    alerts.sort(key=lambda x: x["premium_notional"], reverse=True)
    return alerts[:MAX_ALERTS_PER_TICKER]


async def get_options_flow(ticker: str) -> dict:
    """Fetch unusual options activity for a ticker via yfinance option chains.

    Uses RELATIVE thresholds (market-cap adjusted):
      - premium_notional_pct = total_premium / (underlying_price * 100) > 0.5%
      - volume_ratio = volume / avg_daily_option_volume > 3.0x
      - Market-cap skip: mega-cap (>$500B) requires premium > $100K
      - DTE filter: 5-120 days (includes weeklies through quarter-end positioning)

    Alerts capped at 5 per ticker per session.
    Session-level in-memory cache prevents duplicate API calls.

    Args:
        ticker: Stock ticker (e.g. "AAPL", "SPY").

    Returns:
        Dict with keys: ticker, alerts, source, reliability, annotation.
        Empty alerts list if no unusual activity detected or data unavailable.
    """
    ticker = ticker.strip().upper()
    cache_key = f"options_{ticker}"

    if cache_key in _options_cache:
        logger.debug("Options flow cache hit: %s", ticker)
        return _options_cache[cache_key]

    yf = _lazy_import_yfinance()
    if yf is None:
        result = {
            "ticker": ticker,
            "alerts": [],
            "source": "yfinance_options",
            "reliability": OPTIONS_FLOW_RELIABILITY,
            "annotation": OBSERVATIONAL_ANNOTATION,
            "note": "yfinance_not_available",
        }
        _options_cache[cache_key] = result
        return result

    try:
        ticker_obj = yf.Ticker(ticker)

        # Get underlying price and market cap (for thresholds)
        info = {}
        try:
            info = ticker_obj.info or {}
        except Exception:
            pass

        underlying_price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        market_cap = info.get("marketCap")
        avg_daily_volume = info.get("averageVolume")  # shares — rough proxy for option volume
        # Option volume is typically ~20% of share volume for liquid tickers
        estimated_opt_volume = int(avg_daily_volume * 0.2) if avg_daily_volume else None

        # Get option chain data
        option_data = {}
        try:
            expirations = ticker_obj.options
            if expirations and len(expirations) > 0:
                # Get nearest 3 expiration dates for coverage
                nearest_dates = expirations[:3]
                all_options = []
                for exp_date in nearest_dates:
                    try:
                        chain = ticker_obj.option_chain(exp_date)
                        calls = getattr(chain, 'calls', None)
                        puts = getattr(chain, 'puts', None)
                        if calls is not None and hasattr(calls, 'to_dict'):
                            call_list = calls.to_dict('records')
                            for c in call_list:
                                c['optionType'] = 'call'
                                c['expiration'] = exp_date
                                all_options.append(c)
                        if puts is not None and hasattr(puts, 'to_dict'):
                            put_list = puts.to_dict('records')
                            for p in put_list:
                                p['optionType'] = 'put'
                                p['expiration'] = exp_date
                                all_options.append(p)
                    except Exception:
                        continue
                option_data = {"options": all_options}
        except Exception as e:
            logger.debug("Option chain fetch failed for %s: %s", ticker, e)

        # Calculate DTE for each option
        from datetime import date as dt_date
        today = dt_date.today()
        for opt in option_data.get("options", []):
            exp_str = opt.get("expiration", "")
            try:
                if exp_str:
                    exp_date = dt_date.fromisoformat(exp_str[:10])
                    opt["dte"] = (exp_date - today).days
                else:
                    opt["dte"] = None
            except (ValueError, TypeError):
                opt["dte"] = None

        # Build alerts with premium filter
        alerts = _build_alerts(
            ticker=ticker,
            option_data=option_data,
            underlying_price=underlying_price,
            market_cap=market_cap,
            avg_daily_volume=estimated_opt_volume,
        )

        result = {
            "ticker": ticker,
            "alerts": alerts,
            "source": "yfinance_options",
            "reliability": OPTIONS_FLOW_RELIABILITY,
            "annotation": OBSERVATIONAL_ANNOTATION,
            "underlying_price": underlying_price,
            "market_cap": market_cap,
        }

        logger.info(
            "Options flow: %s — %d alerts (underlying=%.2f, cap=%.1fB)",
            ticker, len(alerts),
            underlying_price or 0,
            (market_cap or 0) / 1e9,
        )

    except Exception as e:
        logger.warning("Options flow unavailable for %s: %s", ticker, e)
        result = {
            "ticker": ticker,
            "alerts": [],
            "source": "yfinance_options",
            "reliability": OPTIONS_FLOW_RELIABILITY,
            "annotation": OBSERVATIONAL_ANNOTATION,
            "note": f"fetch_error: {str(e)[:100]}",
        }

    _options_cache[cache_key] = result
    return result
