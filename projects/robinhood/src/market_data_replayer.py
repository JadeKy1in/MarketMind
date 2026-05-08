"""
market_data_replayer.py — Phase 8.4 Market Data Replayer

Simulates or replays "next-day" market data to enable the Shadow Tribunal
to judge predictions against reality. This component operates in two modes:

  1. REPLAY mode: Load cached historical data for a specific date.
  2. SIMULATE mode: Generate synthetic market data (for testing when
     no real data is available yet — e.g. same-session tribunal runs).

The replayer provides clean price snapshots (open, high, low, close, volume)
for all tickers in the core monitoring pool.

SPARC:
  Specification: provide price data one day forward for tribunal judging.
  Pseudocode: load/simulate daily OHLCV for each ticker.
  Architecture: stateless function set — no persistence of its own.
  Refinement: simulation uses realistic drift + noise for plausibility.
  Completion: ready for integration into shadow_tribunal.py.
"""

from __future__ import annotations

import datetime
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ============================================================
# Data structures
# ============================================================

@dataclass
class DailyPriceSnapshot:
    """OHLCV data for one ticker on one day.

    Attributes:
        ticker: The ticker symbol.
        date: Date of the snapshot (YYYY-MM-DD).
        open_price: Opening price.
        high_price: Highest price of the session.
        low_price: Lowest price of the session.
        close_price: Closing price.
        volume: Total volume.
        vwap: Volume-weighted average price (calculated if not provided).
    """

    ticker: str = ""
    date: str = ""
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: int = 0
    vwap: float = 0.0

    def __post_init__(self) -> None:
        if not self.vwap and self.volume > 0:
            # Simple VWAP estimate: (close + high + low) / 3
            self.vwap = (self.close_price + self.high_price + self.low_price) / 3.0


@dataclass
class MarketDataSnapshot:
    """Complete market data snapshot for a single date.

    Attributes:
        date: The snapshot date (YYYY-MM-DD).
        tickers: List of tickers included.
        prices: Dict mapping ticker -> DailyPriceSnapshot.
        volatility_regime: Estimated volatility regime description.
        regime_score: Numeric volatility score (0 = calm, 100 = panic).
    """

    date: str = ""
    tickers: List[str] = field(default_factory=list)
    prices: Dict[str, DailyPriceSnapshot] = field(default_factory=dict)
    volatility_regime: str = "normal"
    regime_score: float = 30.0


# ============================================================
# Baseline prices (used as "previous close" for simulation)
# ============================================================

# These are reference prices that the sim uses as starting points.
# In production, these would be loaded from a data warehouse.
_BASELINE_PRICES: Dict[str, float] = {
    "IAU": 38.50,    # Gold ETF
    "GDX": 35.80,    # Gold Miners
    "GLD": 190.00,   # Gold Trust
    "SLV": 24.50,    # Silver Trust
    "TLT": 89.20,    # Long Treasury
    "IEF": 96.50,    # Intermediate Treasury
    "SHY": 82.30,    # Short Treasury
    "SPY": 548.00,   # S&P 500
    "QQQ": 470.00,   # NASDAQ 100
    "IWM": 205.00,   # Russell 2000
    "DIA": 400.00,   # Dow 30
    "DXY": 104.50,   # US Dollar Index
    "UUP": 28.00,    # Bullish Dollar
    "HYG": 76.00,    # High Yield Corp
    "LQD": 108.00,   # Investment Grade Corp
    "JNK": 96.00,    # High Yield Bond
}


# ============================================================
# Market Data Replayer
# ============================================================

class MarketDataReplayer:
    """Provides next-day market data snapshots for the Tribunal.

    In SIMULATE mode, generates plausible price movements based on a
    configurable volatility regime.  In REPLAY mode, loads cached data
    files from a specified directory.
    """

    def __init__(
        self,
        mode: str = "simulate",
        data_dir: Optional[str] = None,
        seed: Optional[int] = None,
        baseline_prices: Optional[Dict[str, float]] = None,
        source: Optional[str] = None,
    ) -> None:
        """Initialise the replayer.

        Args:
            mode: "simulate" or "replay".
            data_dir: Path to cached data files (required for replay mode).
            seed: Random seed for reproducible simulation.
            baseline_prices: Override baseline prices.
            source: Alias for data_dir (backward compatibility). If provided,
                sets data_dir and switches mode to "replay".
        """
        # Backward compatibility: if source is provided, treat it as data_dir
        if source is not None:
            data_dir = source
            mode = "replay"
        self._mode = mode
        self._data_dir = data_dir
        self._rng = random.Random(seed)
        self._baseline = baseline_prices or dict(_BASELINE_PRICES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_next_day_snapshot(
        self,
        previous_date: str,
        tickers: Optional[List[str]] = None,
        volatility_regime: Optional[str] = None,
    ) -> MarketDataSnapshot:
        """Get a snapshot for the *next* trading session.

        Given a previous_date, this returns data for the following day.
        In simulate mode, generates synthetic data.  In replay mode, loads
        from cache.

        Args:
            previous_date: The reference date (YYYY-MM-DD).
            tickers: Subset of tickers. Defaults to all known tickers.
            volatility_regime: Override volatility regime.

        Returns:
            MarketDataSnapshot with OHLCV for the next day.

        Raises:
            FileNotFoundError: In replay mode, if no cached data is found.
            ValueError: If the date format is invalid.
        """
        tickers = tickers or list(self._baseline.keys())

        # Calculate next trading day (skip weekends for realism)
        next_date = self._next_trading_day(previous_date)

        if self._mode == "replay":
            return self._replay_snapshot(next_date, tickers)
        else:
            regime = volatility_regime or self._sample_regime()
            return self._simulate_snapshot(next_date, tickers, regime)

    def set_baseline_price(self, ticker: str, price: float) -> None:
        """Override the baseline price for a ticker."""
        self._baseline[ticker] = price

    def get_baseline_price(self, ticker: str) -> Optional[float]:
        """Get the baseline price for a ticker."""
        return self._baseline.get(ticker)

    # ------------------------------------------------------------------
    # Simulation engine
    # ------------------------------------------------------------------

    def _simulate_snapshot(
        self,
        date: str,
        tickers: List[str],
        regime: str,
    ) -> MarketDataSnapshot:
        """Generate a synthetic market data snapshot."""
        regime_mult, regime_label = self._regime_params(regime)

        prices: Dict[str, DailyPriceSnapshot] = {}

        for ticker in tickers:
            base_price = self._baseline.get(ticker, 100.0)

            # Daily drift: small bias + random noise
            # Regime_mult scales volatility (higher = more extreme moves)
            daily_return = self._rng.gauss(
                mu=0.0, sigma=0.015 * regime_mult
            )

            open_price = base_price
            close_price = base_price * (1.0 + daily_return)

            # Intraday range
            intraday_range = abs(close_price - open_price) * self._rng.uniform(
                1.2, 2.0
            )
            high_price = max(open_price, close_price) + intraday_range * self._rng.uniform(
                0.1, 0.4
            )
            low_price = min(open_price, close_price) - intraday_range * self._rng.uniform(
                0.1, 0.3
            )

            # Volume: inversely related to volatility (panic selling = higher vol)
            volume = int(self._rng.gauss(
                mu=5_000_000 * regime_mult,
                sigma=1_000_000 * regime_mult,
            ))
            volume = max(volume, 100_000)

            prices[ticker] = DailyPriceSnapshot(
                ticker=ticker,
                date=date,
                open_price=round(open_price, 2),
                high_price=round(high_price, 2),
                low_price=round(low_price, 2),
                close_price=round(close_price, 2),
                volume=volume,
            )

        # Regime score
        regime_scores = {
            "calm": 10.0,
            "normal": 30.0,
            "volatile": 60.0,
            "panic": 85.0,
        }
        score = regime_scores.get(regime, 30.0)

        return MarketDataSnapshot(
            date=date,
            tickers=list(tickers),
            prices=prices,
            volatility_regime=regime_label,
            regime_score=score,
        )

    def _regime_params(self, regime: str) -> Tuple[float, str]:
        """Return (vol_multiplier, human_label) for a regime."""
        mapping = {
            "calm": (0.5, "low volatility"),
            "normal": (1.0, "normal"),
            "volatile": (2.0, "elevated volatility"),
            "panic": (3.5, "high stress / panic"),
        }
        return mapping.get(regime, (1.0, "normal"))

    def _sample_regime(self) -> str:
        """Randomly sample a volatility regime."""
        weights = {"calm": 0.2, "normal": 0.5, "volatile": 0.2, "panic": 0.1}
        regimes = list(weights.keys())
        probs = list(weights.values())
        return self._rng.choices(regimes, weights=probs, k=1)[0]

    # ------------------------------------------------------------------
    # Replay engine (stub — for production integration)
    # ------------------------------------------------------------------

    def _replay_snapshot(
        self,
        date: str,
        tickers: List[str],
    ) -> MarketDataSnapshot:
        """Load a cached market data snapshot.

        In a production system, this would load from a database or
        cloud storage (e.g., Parquet files on S3).  This stub raises
        NotImplementedError until the data pipeline is connected.

        Args:
            date: The target date (YYYY-MM-DD).
            tickers: List of tickers to load.

        Returns:
            MarketDataSnapshot.

        Raises:
            NotImplementedError: Always — stub for production integration.
            FileNotFoundError: If data_dir is not configured.
        """
        if not self._data_dir:
            raise FileNotFoundError(
                "Replay mode requires data_dir. "
                "Set data_dir in MarketDataReplayer constructor."
            )

        # Production code would go here:
        #   load from self._data_dir / f"snapshot_{date}.parquet"
        #   parse, validate, return
        raise NotImplementedError(
            f"Replay not yet implemented. Production data pipeline "
            f"should load data for {date} from {self._data_dir}."
        )

    # ------------------------------------------------------------------
    # Date utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _next_trading_day(date_str: str) -> str:
        """Get the next trading day (skip Sat/Sun)."""
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        dt += datetime.timedelta(days=1)

        # Skip weekends: Saturday = 5, Sunday = 6
        while dt.weekday() >= 5:
            dt += datetime.timedelta(days=1)

        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def previous_trading_day(date_str: str) -> str:
        """Get the previous trading day (skip Sat/Sun)."""
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        dt -= datetime.timedelta(days=1)

        while dt.weekday() >= 5:
            dt -= datetime.timedelta(days=1)

        return dt.strftime("%Y-%m-%d")