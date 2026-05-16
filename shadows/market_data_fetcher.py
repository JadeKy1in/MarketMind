"""Market Data Fetcher -- external price data via yfinance.

Provides next-day return direction for market accuracy gate (P2-4).
Breaks virtual PnL circularity by anchoring shadow predictions to actual
market returns instead of system-calculated PnL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("marketmind.shadows.market_data_fetcher")


class MarketDataFetcher:
    """Fetch OHLCV data from Yahoo Finance for market accuracy validation.

    Used by ShadowMother to validate that shadow directional predictions
    match actual market moves, not just system-calculated virtual PnL.
    """

    def __init__(self):
        self._cache: dict[str, dict[str, float]] = {}
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 5

    def fetch_ohlcv(self, ticker: str, start_date: str,
                    end_date: str | None = None) -> dict[str, dict[str, float]]:
        """Fetch OHLCV for a ticker. Returns {date: {open, high, low, close, volume}}."""
        import yfinance as yf

        cache_key = f"{ticker}:{start_date}:{end_date or 'now'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            tkr = yf.Ticker(ticker)
            end = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            df = tkr.history(start=start_date, end=end)
            if df.empty:
                logger.debug("No price data for %s from %s to %s", ticker, start_date, end)
                return {}

            result = {}
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d")
                result[date_str] = {
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
            self._cache[cache_key] = result
            self._consecutive_failures = 0  # Reset on success
            return result
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_consecutive_failures:
                logger.error(
                    "Market data fetch failed %d consecutive times (last: %s: %s) — "
                    "accuracy gate is degraded. Check network / yfinance API.",
                    self._consecutive_failures, ticker, e
                )
            else:
                logger.warning("Market data fetch failed for %s: %s", ticker, e)
            return {}

    def compute_next_day_return(self, prices: dict[str, dict[str, float]],
                                date: str) -> float | None:
        """Compute the next-day return sign for a given date.

        Returns the return direction (-1, 0, 1) as a float value:
        > 0 if close_next > close_today, < 0 otherwise.
        Returns None if data is unavailable (e.g., holiday/weekend).
        """
        if date not in prices:
            return None
        # Find next available trading day
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        for offset in range(1, 6):  # Check up to 5 days ahead
            next_date = (date_obj + timedelta(days=offset)).strftime("%Y-%m-%d")
            if next_date in prices:
                today_close = prices[date]["close"]
                next_close = prices[next_date]["close"]
                if today_close > 0:
                    return (next_close - today_close) / today_close
                return None
        return None

    def compute_market_accuracy(
        self, shadow_votes: list[dict], ticker: str,
        start_date: str, end_date: str | None = None
    ) -> float:
        """Compute fraction of shadow predictions matching actual market direction.

        accuracy = count(shadow_direction == sign(next_day_return)) / total_predictions

        Args:
            shadow_votes: List of {date, ticker, direction} dicts from shadow_votes table.
            ticker: The ticker to validate against.
            start_date: Start of evaluation window.
            end_date: End of evaluation window.

        Returns:
            Accuracy fraction [0, 1]. Returns 0.5 if insufficient data.
        """
        prices = self.fetch_ohlcv(ticker, start_date, end_date)
        if not prices:
            return 0.5

        correct = 0
        total = 0
        for vote in shadow_votes:
            v_ticker = vote.get("ticker", "")
            v_date = vote.get("date", "")
            v_direction = vote.get("direction", "abstain")

            if v_ticker != ticker:
                continue
            if v_direction == "abstain":
                continue

            next_ret = self.compute_next_day_return(prices, v_date)
            if next_ret is None:
                continue  # Skip if next-day data unavailable (holiday/weekend)

            actual_direction = "long" if next_ret > 0 else "short"
            if v_direction == actual_direction:
                correct += 1
            total += 1

        if total == 0:
            return 0.5

        return correct / total

    def next_day_return_sign(self, prices: dict[str, dict[str, float]],
                             date: str) -> int | None:
        """Get the sign of next-day return: 1=positive, -1=negative, None=unavailable."""
        ret = self.compute_next_day_return(prices, date)
        if ret is None:
            return None
        return 1 if ret > 0 else -1
