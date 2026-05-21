"""Market anchor step — external market data validation for shadow ranking.

Runs between vote collection and ranking. Fetches OHLCV data for tickers
referenced by shadow analyses, stores prices in market_prices table, and
computes directional accuracy per shadow. Market accuracy < 0.50 blocks
ELITE tier promotion.

Extracted from shadow_mother.py per workspace modular architecture rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from marketmind.shadows.market_data_fetcher import MarketDataFetcher

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.shadows.market_anchor")


class MarketAnchorStep:
    """Fetch external market data and compute per-shadow directional accuracy.

    Without external validation, shadow ranking creates a self-referential
    system. This step provides an independent accuracy check by comparing
    shadow directional predictions to actual market returns.
    """

    def __init__(self, state_db: "ShadowStateDB") -> None:
        self.state_db = state_db

    async def execute(
        self,
        today: str,
        shadow_analyses: dict,
    ) -> dict[str, float]:
        """Fetch external market data and compute per-shadow accuracy.

        Args:
            today: Date string in YYYY-MM-DD format.
            shadow_analyses: Dict mapping shadow_id -> ShadowAnalysisOutput
                             from the vote collection step.

        Returns:
            Dict mapping shadow_id -> market_accuracy (0.0-1.0).
        """
        market_accuracies: dict[str, float] = {}
        fetcher = MarketDataFetcher()

        # Collect unique tickers from today's shadow analyses
        tickers_needed: set[str] = set()
        for sid, output in shadow_analyses.items():
            analyses = getattr(output, "analyses", []) or []
            for a in analyses:
                ticker = a.get("ticker", "") if isinstance(a, dict) else getattr(a, "ticker", "")
                if ticker:
                    tickers_needed.add(ticker)

        if not tickers_needed:
            logger.debug("No tickers to fetch for market anchor")
            return market_accuracies

        # Fetch OHLCV for each ticker
        for ticker in tickers_needed:
            data = await fetcher.fetch_ohlcv(ticker, period="5d")
            if data is None:
                continue
            try:
                # Look up yesterday's close to compute next_day_return
                yesterday_prices = self.state_db.get_market_prices(
                    ticker, end_date=data["date"])
                ndr = None
                if yesterday_prices:
                    yesterday_close = yesterday_prices[-1].get("close", 0)
                    if yesterday_close and yesterday_close > 0:
                        ndr = (data["close"] - yesterday_close) / yesterday_close
                        # Update yesterday's next_day_return
                        yesterday_date = yesterday_prices[-1].get("date", "")
                        if yesterday_date:
                            conn = self.state_db._connect()
                            try:
                                conn.execute(
                                    "UPDATE market_prices SET next_day_return = ? "
                                    "WHERE ticker = ? AND date = ?",
                                    (ndr, ticker, yesterday_date))
                                conn.commit()
                            finally:
                                conn.close()

                self.state_db.insert_market_price(
                    ticker=ticker, date=data["date"],
                    open_price=data["open"], high=data["high"],
                    low=data["low"], close=data["close"],
                    volume=data["volume"],
                    next_day_return=None)
            except Exception as e:
                logger.debug("Failed to insert market price for %s: %s", ticker, e)

        # Compute per-shadow accuracy from historical analyses
        for sid in shadow_analyses:
            try:
                analyses = self.state_db.get_analyses_with_direction(sid, days=90)
                if not analyses:
                    continue
                correct = 0
                total = 0
                for a in analyses:
                    ndr = self.state_db.get_next_day_return(a["ticker"], a["date"])
                    if ndr is not None:
                        if fetcher.compute_accuracy(a["direction"], ndr):
                            correct += 1
                        total += 1
                if total > 0:
                    market_accuracies[sid] = correct / total
            except Exception as e:
                logger.debug("Accuracy computation failed for %s: %s", sid, e)

        return market_accuracies
