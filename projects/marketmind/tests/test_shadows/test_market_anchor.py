"""Tests for external market anchor — market data fetch, accuracy gate (P2-4)."""
import pytest
from unittest.mock import patch, MagicMock
from marketmind.shadows.market_data_fetcher import MarketDataFetcher
from marketmind.shadows.ranking_engine import RankingEngine
from marketmind.shadows.shadow_state import ShadowStateDB, CODE_VERSION
from marketmind.config.settings import ShadowSettings


class TestMarketDataFetcher:

    def test_compute_market_accuracy_mixed(self):
        """Accuracy should reflect correct fraction of direction matches."""
        mdf = MarketDataFetcher()
        mock_prices = {
            "2026-05-01": {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            "2026-05-02": {"open": 101, "high": 105, "low": 100, "close": 104, "volume": 1200},
            "2026-05-03": {"open": 104, "high": 106, "low": 103, "close": 103, "volume": 900},
        }
        mdf._cache["AAPL:2026-05-01:2026-05-05"] = mock_prices

        votes = [
            # Vote long on 05-01 → next day 05-02 close=104 > open=101 = UP → correct
            {"shadow_id": "s1", "ticker": "AAPL", "date": "2026-05-01",
             "direction": "long"},
            # Vote long on 05-02 → next day 05-03 close=103 < close=104 = DOWN → wrong
            {"shadow_id": "s1", "ticker": "AAPL", "date": "2026-05-02",
             "direction": "long"},
        ]
        with patch.object(mdf, 'fetch_ohlcv', return_value=mock_prices):
            acc = mdf.compute_market_accuracy(votes, "AAPL", "2026-05-01", "2026-05-05")
        assert acc == 0.5  # 1 correct, 1 wrong

    def test_accuracy_returns_default_when_no_votes(self):
        """No votes should return 0.5 (not fail)."""
        mdf = MarketDataFetcher()
        acc = mdf.compute_market_accuracy([], "AAPL", "2026-05-01")
        assert acc == 0.5

    def test_holiday_skip(self):
        """When next-day data is unavailable (holiday), vote should be skipped."""
        mdf = MarketDataFetcher()
        mock_prices = {
            "2026-05-01": {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            # No 2026-05-02 data (weekend/holiday)
            "2026-05-05": {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 800},
        }
        mdf._cache["AAPL:2026-04-25:2026-05-10"] = mock_prices

        votes = [
            {"shadow_id": "s1", "ticker": "AAPL", "date": "2026-05-01",
             "direction": "long"},
        ]
        with patch.object(mdf, 'fetch_ohlcv', return_value=mock_prices):
            acc = mdf.compute_market_accuracy(votes, "AAPL", "2026-04-25", "2026-05-10")
        # Vote on 05-01 — next available day is 05-05 (up: 101→102)
        # direction="long" matches actual="long" → 1 correct
        assert acc == 1.0

    def test_next_day_return_sign(self):
        """next_day_return_sign should return correct direction."""
        mdf = MarketDataFetcher()
        prices = {
            "2026-05-01": {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            "2026-05-02": {"open": 101, "high": 105, "low": 100, "close": 99, "volume": 1200},
        }
        mdf._cache["TEST:2026-05-01:2026-05-04"] = prices
        ret = mdf.compute_next_day_return(prices, "2026-05-01")
        assert ret is not None
        assert ret < 0  # 101 → 99 is negative

    def test_no_price_data_returns_default(self):
        """When yfinance returns no data, accuracy defaults to 0.5."""
        mdf = MarketDataFetcher()
        with patch.object(mdf, 'fetch_ohlcv', return_value={}):
            acc = mdf.compute_market_accuracy(
                [{"shadow_id": "s1", "ticker": "FAKE", "date": "2026-05-01",
                  "direction": "long"}],
                "FAKE", "2026-05-01"
            )
        assert acc == 0.5


class TestAccuracyGate:

    def test_elite_demoted_when_accuracy_below_50(self):
        """ELITE shadow with market accuracy < 0.50 should be demoted to NORMAL."""
        engine = RankingEngine(ShadowSettings())
        scores = [("2026-05-01", 0.78)] * 20 + [("2026-05-20", 0.82)] * 30
        percentiles = [("2026-05-01", 0.55)] * 20 + [("2026-05-20", 0.88)] * 30
        tier = engine.determine_achievement_tier(
            scores, percentiles, 0.10, 0.85, market_accuracy=0.35
        )
        assert tier == "normal"

    def test_elite_retained_when_accuracy_above_50(self):
        """ELITE shadow with market accuracy >= 0.50 should retain tier."""
        engine = RankingEngine(ShadowSettings())
        scores = [("2026-05-01", 0.78)] * 20 + [("2026-05-20", 0.82)] * 30
        percentiles = [("2026-05-01", 0.55)] * 20 + [("2026-05-20", 0.88)] * 30
        tier = engine.determine_achievement_tier(
            scores, percentiles, 0.10, 0.85, market_accuracy=0.55
        )
        assert tier == "elite"

    def test_accuracy_none_does_not_affect_tier(self):
        """When accuracy is None (not computed), tier is unaffected (backward compat)."""
        engine = RankingEngine(ShadowSettings())
        scores = [("2026-05-01", 0.78)] * 20 + [("2026-05-20", 0.82)] * 30
        percentiles = [("2026-05-01", 0.55)] * 20 + [("2026-05-20", 0.88)] * 30
        tier = engine.determine_achievement_tier(
            scores, percentiles, 0.10, 0.85, market_accuracy=None
        )
        assert tier == "elite"


class TestMigration:

    def test_code_version_is_6(self):
        """CODE_VERSION should be 12 after Phase C independent tools migration."""
        assert CODE_VERSION == 12

    def test_market_prices_table_exists(self, tmp_path):
        """Market prices table should be created during init_schema."""
        db_path = str(tmp_path / "test_market.db")
        db = ShadowStateDB(db_path)
        db.init_schema()
        # Verify table exists by inserting and querying
        db.insert_market_price(
            "AAPL", "2026-05-01", 100.0, 101.0, 99.0, 100.5, 1000
        )
        prices = db.get_market_prices("AAPL", "2026-01-01", "2026-12-31")
        assert len(prices) == 1
        assert prices[0]["date"] == "2026-05-01"
        assert prices[0]["close"] == 100.5
        db.close()
