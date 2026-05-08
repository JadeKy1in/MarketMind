"""Tests for market_data_replayer.py — Phase 8.4 historical data replay."""
from __future__ import annotations

import json
import os
import tempfile
import pytest

from src.market_data_replayer import MarketDataReplayer, MarketDataSnapshot


def _sample_bar(ticker: str, timestamp: str, open_p: float, high: float, low: float, close: float, volume: int = 1000000) -> dict:
    return {
        "ticker": ticker,
        "timestamp": timestamp,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _write_bars(tmpdir: str, bars: list[dict]) -> str:
    path = os.path.join(tmpdir, "bars.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for bar in bars:
            f.write(json.dumps(bar) + "\n")
    return path


class TestMarketDataReplayerInit:
    def test_replay_unimplemented(self):
        """Replay stub raises NotImplementedError for production integration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_bars(tmpdir, [])
            rp = MarketDataReplayer(source=path, seed=42)
            with pytest.raises(NotImplementedError):
                rp.get_next_day_snapshot("2026-05-01", ["IAU"])

    def test_default_simulate_mode(self):
        """Default constructor creates a working simulate-mode replayer."""
        rp = MarketDataReplayer(seed=42)
        snap = rp.get_next_day_snapshot("2026-05-01", ["IAU"])
        assert isinstance(snap, MarketDataSnapshot)
        assert "IAU" in snap.prices


class TestMarketDataReplayerReplay:
    def test_single_run(self):
        """get_next_day_snapshot returns snapshot with requested tickers."""
        rp = MarketDataReplayer(seed=42)
        snap = rp.get_next_day_snapshot("2026-05-01", ["IAU"])
        assert "IAU" in snap.prices
        price = snap.prices["IAU"]
        assert price.close_price > 0

    def test_multiple_tickers(self):
        """Snapshot includes all requested tickers."""
        rp = MarketDataReplayer(seed=42)
        snap = rp.get_next_day_snapshot("2026-05-01", ["IAU", "GDX"])
        assert "IAU" in snap.prices
        assert "GDX" in snap.prices

    def test_date_advancement(self):
        """Each new snapshot advances to the next trading day."""
        rp = MarketDataReplayer(seed=42)
        snap1 = rp.get_next_day_snapshot("2026-04-30", ["IAU"])
        snap2 = rp.get_next_day_snapshot("2026-05-01", ["IAU"])
        assert snap2.date > snap1.date

    def test_always_returns_data(self):
        """Simulate mode always generates data — never exhausted."""
        rp = MarketDataReplayer(seed=42)
        for _ in range(5):
            snap = rp.get_next_day_snapshot("2026-04-27", ["IAU"])
            assert "IAU" in snap.prices

    def test_unknown_ticker(self):
        """Unknown ticker gets a default price snapshot."""
        rp = MarketDataReplayer(seed=42)
        snap = rp.get_next_day_snapshot("2026-05-01", ["UNKNOWN"])
        assert "UNKNOWN" in snap.prices
        assert snap.prices["UNKNOWN"].close_price > 0

    def test_reset_via_new_instance(self):
        """Creating a fresh replayer with same seed gives reproducible data."""
        rp1 = MarketDataReplayer(seed=42)
        snap1 = rp1.get_next_day_snapshot("2026-05-01", ["IAU"])
        rp2 = MarketDataReplayer(seed=42)
        snap2 = rp2.get_next_day_snapshot("2026-05-01", ["IAU"])
        assert snap1.prices["IAU"].close_price == snap2.prices["IAU"].close_price

    def test_volatility_regime_effect(self):
        """Different volatility regimes produce different metadata."""
        rp = MarketDataReplayer(seed=42)
        snap = rp.get_next_day_snapshot("2026-05-01", ["IAU"], volatility_regime="panic")
        assert snap.volatility_regime == "high stress / panic"
        assert snap.regime_score == 85.0