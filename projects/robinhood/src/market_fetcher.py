"""
market_fetcher.py - Market data fetcher with local JSON cache.

Fetches daily and weekly historical OHLCV data for a given ticker
using yfinance as the data source. Results are cached locally in JSON
files keyed by ticker, timeframe, and date to minimize network requests.

Dependencies: yfinance, pandas (whitelisted in techContext.md)
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Union

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/market_data")


class MarketDataCache:
    """Local JSON cache for market data to reduce yfinance network requests.

    Accepts an optional ``now`` callable (default ``date.today``) so that
    tests can freeze time without mutating the built-in ``date`` type.
    """

    def __init__(
        self,
        cache_dir: Union[str, Path] = CACHE_DIR,
        now: Optional[Callable[[], date]] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self._now = now or date.today
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str, timeframe: str) -> Path:
        """Return the filesystem path for a (ticker, timeframe) cache file."""
        safe_ticker = ticker.upper().replace(".", "_")
        return self.cache_dir / f"{safe_ticker}_{timeframe}.json"

    def get(
        self, ticker: str, timeframe: str, ref_date: Optional[date] = None
    ) -> Optional[pd.DataFrame]:
        """Return cached DataFrame if a valid cache entry exists for ref_date."""
        if ref_date is None:
            ref_date = self._now()
        cache_file = self._cache_path(ticker, timeframe)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read error for %s %s: %s", ticker, timeframe, exc)
            return None

        cached_date_str = entry.get("last_updated")
        if cached_date_str != ref_date.isoformat():
            logger.debug(
                "Cache stale for %s %s: cached=%s, required=%s",
                ticker,
                timeframe,
                cached_date_str,
                ref_date.isoformat(),
            )
            return None

        records = entry.get("data", [])
        if not records:
            return None
        df = pd.DataFrame(records)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df.set_index("Date", inplace=True)
        return df

    def set(
        self,
        ticker: str,
        timeframe: str,
        df: pd.DataFrame,
        ref_date: Optional[date] = None,
    ) -> None:
        """Write a DataFrame to the cache file."""
        if ref_date is None:
            ref_date = self._now()

        data_df = df.reset_index()
        data_df["Date"] = data_df["Date"].astype(str)
        records = data_df.to_dict(orient="records")

        entry = {
            "ticker": ticker.upper(),
            "timeframe": timeframe,
            "last_updated": ref_date.isoformat(),
            "data": records,
        }
        cache_file = self._cache_path(ticker, timeframe)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)
        logger.debug("Cached %s %s (%d rows)", ticker, timeframe, len(records))

    def clear(self, ticker: str, timeframe: str) -> None:
        """Remove a specific cache entry."""
        cache_file = self._cache_path(ticker, timeframe)
        if cache_file.exists():
            cache_file.unlink()
            logger.debug("Cleared cache for %s %s", ticker, timeframe)


class MarketFetcher:
    """Fetch daily and weekly OHLCV data for a given ticker via yfinance."""

    def __init__(self, cache: Optional[MarketDataCache] = None):
        self.cache = cache or MarketDataCache()

    def fetch_daily(
        self,
        ticker: str,
        period: str = "6mo",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV data for the given ticker.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'NVDA').
            period: yfinance period string (default '6mo').
            force_refresh: If True, bypass cache and fetch from network.

        Returns:
            pd.DataFrame with columns [Open, High, Low, Close, Volume].
        """
        if not force_refresh:
            cached = self.cache.get(ticker, "daily")
            if cached is not None:
                logger.info("Cache hit for %s daily", ticker)
                return cached

        logger.info("Fetching daily data for %s (period=%s)", ticker, period)
        raw = self._fetch_yfinance(ticker, period=period, interval="1d")
        self.cache.set(ticker, "daily", raw)
        return raw

    def fetch_weekly(
        self,
        ticker: str,
        period: str = "1y",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch weekly OHLCV data for the given ticker.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'NVDA').
            period: yfinance period string (default '1y').
            force_refresh: If True, bypass cache and fetch from network.

        Returns:
            pd.DataFrame with columns [Open, High, Low, Close, Volume].
        """
        if not force_refresh:
            cached = self.cache.get(ticker, "weekly")
            if cached is not None:
                logger.info("Cache hit for %s weekly", ticker)
                return cached

        logger.info("Fetching weekly data for %s (period=%s)", ticker, period)
        raw = self._fetch_yfinance(ticker, period=period, interval="1wk")
        self.cache.set(ticker, "weekly", raw)
        return raw

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_yfinance(ticker: str, period: str, interval: str) -> pd.DataFrame:
        """Raw yfinance download call. Returns a clean DataFrame."""
        raw: pd.DataFrame = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if raw.empty:
            raise ValueError(
                f"No data returned by yfinance for ticker={ticker!r}, "
                f"period={period!r}, interval={interval!r}"
            )

        # yfinance returns a MultiIndex column header by default post-v0.2.50.
        # Flatten to simple column names.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        return raw