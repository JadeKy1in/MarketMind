"""Backtest data: fetch each instrument's longest daily history once, cache it as JSON.

Sources (docs/TREND_DESIGN.md §6): non-crypto -> yfinance adjusted bars (history back
to 2005; Alpaca only reaches 2016), falling back to get_price_history; crypto -> the
longer of Coinbase (real USD) and Binance (USDT treated as USD), falling back to
get_price_history. Only complete bars are cached. The cache lives in the worktree's
git-ignored `cache/trend/`, never in data/. Network I/O: not used by tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from marketmind.gateway import price_history as ph
from marketmind.gateway.price_history import Bar, PriceHistory, complete_bars

logger = logging.getLogger("marketmind.trend.data")

DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "cache" / "trend"
YEARS = 22


def _save(path: Path, hist: PriceHistory, bars: list[Bar]) -> None:
    path.write_text(json.dumps({
        "ticker": hist.ticker, "source": hist.source,
        "bars": [[b.date, b.open, b.high, b.low, b.close, b.volume] for b in bars],
    }), encoding="utf-8")


def load_cached(ticker: str, cache_dir: Path = DEFAULT_CACHE) -> tuple[str, list[Bar]] | None:
    path = cache_dir / f"{ticker.replace('^', '_')}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["source"], [Bar(*row) for row in doc["bars"]]


async def _fetch_one(ticker: str) -> PriceHistory | None:
    if ph.is_crypto_ticker(ticker):
        cands = [h for h in await asyncio.gather(ph._from_coinbase(ticker, YEARS),
                                                 ph._from_binance(ticker, YEARS)) if h]
        if cands:
            return min(cands, key=lambda h: h.daily[0].date)   # longest history
    else:
        hist = await ph._from_yfinance(ticker, YEARS)
        if hist is not None:
            return hist
    return await ph.get_price_history(ticker, YEARS)


async def fetch_all(tickers: list[str], cache_dir: Path = DEFAULT_CACHE,
                    refresh: bool = False) -> dict[str, str]:
    """Fetch and cache; returns {ticker: status}."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}
    for t in tickers:
        path = cache_dir / f"{t.replace('^', '_')}.json"
        if path.exists() and not refresh:
            status[t] = "cached"
            continue
        hist = await _fetch_one(t)
        if hist is None or not hist.daily:
            status[t] = "unavailable"
            logger.warning("no history for %s", t)
            continue
        bars = complete_bars(t, hist.daily)
        _save(path, hist, bars)
        status[t] = f"{hist.source} {bars[0].date}..{bars[-1].date} ({len(bars)} bars)"
    return status
