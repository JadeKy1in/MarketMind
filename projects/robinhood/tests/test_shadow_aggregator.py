"""Tests for shadow_aggregator.py — Phase 8.2 aggressive scenario generation."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.shadow_aggregator import ShadowAggregator
from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    ShadowMode,
    ScenarioLabel,
    PredictionTarget,
)


class TestShadowAggregator:
    def test_init(self):
        """Aggregator initializes with default config."""
        agg = ShadowAggregator()
        assert agg.max_predictions_per_scenario == 10

    def test_init_custom(self):
        """Aggregator accepts custom config."""
        agg = ShadowAggregator(max_predictions_per_scenario=5)
        assert agg.max_predictions_per_scenario == 5

    def test_aggressive_bull_scenario(self):
        """Aggressive bull generates bullish predictions."""
        agg = ShadowAggregator()
        scenario = agg._build_aggressive_bull(["IAU", "GDX"])
        assert scenario.label == ScenarioLabel.AGGRESSIVE_BULL
        assert len(scenario.predictions) > 0
        for pred in scenario.predictions:
            assert pred.comparison_operator in ("gt", "gte")

    def test_aggressive_bear_scenario(self):
        """Aggressive bear generates bearish predictions."""
        agg = ShadowAggregator()
        scenario = agg._build_aggressive_bear(["IAU", "GDX"])
        assert scenario.label == ScenarioLabel.AGGRESSIVE_BEAR
        assert len(scenario.predictions) > 0
        for pred in scenario.predictions:
            assert pred.comparison_operator in ("lt", "lte")

    def test_ambiguous_mixed_scenario(self):
        """Ambiguous mixed generates conflicting predictions."""
        agg = ShadowAggregator()
        scenario = agg._build_ambiguous_mixed(["IAU", "GDX", "TLT"])
        assert scenario.label == ScenarioLabel.AMBIGUOUS_MIXED
        assert len(scenario.predictions) > 0

    def test_ambiguous_flat_scenario(self):
        """Ambiguous flat generates tight-bound predictions."""
        agg = ShadowAggregator()
        scenario = agg._build_ambiguous_flat(["IAU"])
        assert scenario.label == ScenarioLabel.AMBIGUOUS_FLAT
        assert len(scenario.predictions) > 0
        for pred in scenario.predictions:
            assert pred.target_type == PredictionTarget.DIRECTIONAL_MOVE

    def test_generate_strict_mode(self):
        """Strict mode generates only ambiguous scenarios."""
        agg = ShadowAggregator()
        batch = agg.generate(tickers=["IAU"], mode=ShadowMode.STRICT)
        assert batch.mode == ShadowMode.STRICT
        labels = {s.label for s in batch.scenarios}
        assert ScenarioLabel.AGGRESSIVE_BULL not in labels
        assert ScenarioLabel.AGGRESSIVE_BEAR not in labels

    def test_generate_aggressive_mode(self):
        """Aggressive mode generates aggressive scenarios."""
        agg = ShadowAggregator()
        batch = agg.generate(tickers=["IAU", "GDX"], mode=ShadowMode.AGGRESSIVE)
        assert batch.mode == ShadowMode.AGGRESSIVE
        labels = {s.label for s in batch.scenarios}
        assert ScenarioLabel.AGGRESSIVE_BULL in labels
        assert ScenarioLabel.AGGRESSIVE_BEAR in labels

    def test_generate_ambiguous_mode(self):
        """Ambiguous mode generates only ambiguous scenarios."""
        agg = ShadowAggregator()
        batch = agg.generate(tickers=["IAU"], mode=ShadowMode.AMBIGUOUS)
        assert batch.mode == ShadowMode.AMBIGUOUS
        labels = {s.label for s in batch.scenarios}
        assert ScenarioLabel.AGGRESSIVE_BULL not in labels
        assert ScenarioLabel.AGGRESSIVE_BEAR not in labels
        assert ScenarioLabel.AMBIGUOUS_MIXED in labels
        assert ScenarioLabel.AMBIGUOUS_FLAT in labels

    def test_generate_batch_id_unique(self):
        """Each generate call produces a unique batch ID."""
        agg = ShadowAggregator()
        b1 = agg.generate(["IAU"], ShadowMode.AGGRESSIVE)
        b2 = agg.generate(["IAU"], ShadowMode.AGGRESSIVE)
        assert b1.batch_id != b2.batch_id

    def test_generate_timestamps(self):
        """Each batch has generated_at timestamp."""
        agg = ShadowAggregator()
        batch = agg.generate(["IAU"], ShadowMode.AGGRESSIVE)
        assert batch.generated_at is not None
        assert isinstance(batch.generated_at, datetime)

    def test_generate_multi_ticker(self):
        """Generates predictions covering all tickers."""
        agg = ShadowAggregator()
        tickers = ["IAU", "GDX", "TLT", "SPY"]
        batch = agg.generate(tickers, ShadowMode.AGGRESSIVE)
        predicted_tickers = set()
        for scenario in batch.scenarios:
            for pred in scenario.predictions:
                predicted_tickers.add(pred.target_ticker)
        for t in tickers:
            assert t in predicted_tickers, f"Ticker {t} not covered"

    def test_total_predictions_count(self):
        """batch.total_predictions matches actual count."""
        agg = ShadowAggregator()
        batch = agg.generate(["IAU", "GDX"], ShadowMode.AGGRESSIVE)
        actual = sum(len(s.predictions) for s in batch.scenarios)
        assert batch.total_predictions == actual

    def test_empty_tickers(self):
        """Empty ticker list returns empty batch."""
        agg = ShadowAggregator()
        batch = agg.generate([], ShadowMode.AGGRESSIVE)
        assert len(batch.tickers) == 0
        assert len(batch.scenarios) == 0
        assert batch.total_predictions == 0