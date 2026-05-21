"""External market data fetcher for accuracy benchmarking (P2-4).

Uses yfinance to get OHLCV data. Shadows are ranked against system-calculated
PnL -- this module provides EXTERNAL ground-truth to break that circularity.
Market accuracy < 0.50 must block ELITE tier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.market_data_fetcher")


class MarketDataFetcher:
    """Fetch external market data for accuracy benchmarking.

    Without external validation, shadow ranking creates a self-referential
    system. MarketDataFetcher provides an independent accuracy check by
    comparing shadow directional predictions to actual market returns.
    """

    async def fetch_ohlcv(self, ticker: str, period: str = "1mo") -> dict | None:
        """Fetch OHLCV for a ticker via yfinance. Returns standardized dict or None."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not available -- market anchor data skipped")
            return None

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period)
            if hist.empty:
                logger.warning("No data for ticker %s (period=%s)", ticker, period)
                return None

            latest = hist.iloc[-1]
            date_str = (
                latest.name.strftime("%Y-%m-%d")
                if hasattr(latest.name, "strftime")
                else str(latest.name)[:10]
            )
            return {
                "ticker": ticker,
                "date": date_str,
                "open": float(latest["Open"]),
                "high": float(latest["High"]),
                "low": float(latest["Low"]),
                "close": float(latest["Close"]),
                "volume": int(latest["Volume"]),
            }
        except Exception as e:
            logger.warning("OHLCV fetch failed for %s: %s", ticker, e)
            return None

    @staticmethod
    def compute_accuracy(shadow_direction: str, next_day_return: float) -> bool:
        """Check if shadow direction matches sign of next-day return.

        "long" matches positive return, "short" matches negative return,
        "abstain" always returns False.
        """
        if shadow_direction == "abstain":
            return False
        if shadow_direction == "long":
            return next_day_return > 0
        if shadow_direction == "short":
            return next_day_return < 0
        return False

    @staticmethod
    def compute_next_day_return(today_close: float, yesterday_close: float) -> float | None:
        """Compute (today_close - yesterday_close) / yesterday_close."""
        if yesterday_close == 0:
            return None
        return (today_close - yesterday_close) / yesterday_close
