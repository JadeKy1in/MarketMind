"""Price source interface for the ledger (SPEC_v3 S2).

Settlement only needs daily OHLC bars. The default source reads them through
`gateway.price_history` (yfinance, Binance fallback for crypto); another
provider (e.g. Alpaca, once the owner has an account) only has to implement
`PriceSource`. A source returns None when it has no data — callers must then
leave the record unsettled and say so, never estimate (SPEC_v3 L3).
"""
from __future__ import annotations

import logging
from typing import Protocol

from marketmind.gateway.price_history import Bar, complete_bars, get_price_history

logger = logging.getLogger("marketmind.ledger.prices")


class PriceSource(Protocol):
    name: str

    async def daily_bars(self, ticker: str) -> list[Bar] | None:
        """All available daily bars for `ticker`, oldest first, or None."""
        ...


def source_of(source: PriceSource, ticker: str) -> str:
    """Provider that actually served `ticker` (a source may fall back per ticker)."""
    per_ticker = getattr(source, "served_by", None)
    return (per_ticker or {}).get(ticker, source.name)


class HistoryPriceSource:
    """yfinance (+ Binance for crypto) via gateway.price_history, cached per process."""

    name = "yfinance"

    def __init__(self):
        self.served_by: dict[str, str] = {}

    async def daily_bars(self, ticker: str) -> list[Bar] | None:
        hist = await get_price_history(ticker)  # same cache key as L3
        if hist is None or not hist.daily:
            return None
        self.served_by[ticker] = hist.source
        return hist.daily


class StaticPriceSource:
    """In-memory bars, for tests and replays."""

    name = "static"

    def __init__(self, bars: dict[str, list[Bar]]):
        self._bars = bars

    async def daily_bars(self, ticker: str) -> list[Bar] | None:
        return self._bars.get(ticker)


async def latest_quotes(source: PriceSource, tickers: list[str]
                        ) -> dict[str, tuple[float | None, str | None, str | None]]:
    """ticker -> (last close, bar date, source name) for a point-in-time snapshot."""
    out: dict[str, tuple[float | None, str | None, str | None]] = {}
    for t in dict.fromkeys(tickers):
        # partial bars are excluded: settlement compares this close with the
        # completed bar of the same date to detect price re-adjustments
        bars = complete_bars(t, await source.daily_bars(t) or [])
        if bars:
            out[t] = (bars[-1].close, bars[-1].date, source_of(source, t))
        else:
            logger.warning("Snapshot: no price for %s (recorded as unavailable)", t)
            out[t] = (None, None, None)
    return out
