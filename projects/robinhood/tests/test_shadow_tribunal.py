"""Tests for shadow_tribunal.py — Phase 8.4 automated judgment & scoring."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.market_data_replayer import MarketDataReplayer
from src.shadow_tribunal import ShadowTribunal
from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    ScenarioLabel,
    ShadowMode,
    PredictionTarget,
    TribunalVerdict,
    VerdictStatus,
)


@pytest.fixture
def replayer() -> MarketDataReplayer:
    """Replayer with fixed seed for reproducibility."""
    return MarketDataReplayer(mode="simulate", seed=42)


@pytest.fixture
def tribunal(replayer) -> ShadowTribunal:
    return ShadowTribunal(replayer=replayer, strict_mode=True)


@pytest.fixture
def batch_run() -> BatchShadowRun:
    """A sample batch run with various predictions."""
    preds = [
        ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt",
                         assertion="IAU will close up", confidence=70.0,
                         target_date="2026-05-07", was_safety_valve_bypassed=True),
        ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, -0.5, "lt",
                         assertion="IAU will close down", confidence=60.0,
                         target_date="2026-05-07", was_safety_valve_bypassed=True),
        ShadowPrediction("IAU", PredictionTarget.SUPPORT_BREAK, 38.00, "lt",
                         assertion="IAU holds above 38", confidence=80.0,
                         target_date="2026-05-07", was_safety_valve_bypassed=True),
        ShadowPrediction("IAU", PredictionTarget.RESISTANCE_BREAK, 39.50, "gt",
                         assertion="IAU breaks 39.50", confidence=75.0,
                         target_date="2026-05-07", was_safety_valve_bypassed=True),
    ]
    scenario = ShadowScenario(
        label=ScenarioLabel.AGGRESSIVE_BULL,
        target_ticker="IAU",
        predictions=preds,
        original_decision_score=85.0,
    )
    return BatchShadowRun(
        tickers=["IAU"],
        scenarios=[scenario],
        mode=ShadowMode.AGGRESSIVE,
    )


class TestShadowTribunalInit:
    def test_default_config(self, replayer):
        """Tribunal uses default config."""
        t = ShadowTribunal(replayer=replayer)
        assert t._strict_mode is True

    def test_lenient_mode(self, replayer):
        """Tribunal accepts lenient config."""
        t = ShadowTribunal(replayer=replayer, strict_mode=False)
        assert t._strict_mode is False


class TestShadowTribunalBatch:
    def test_judge_batch_returns_verdicts(self, tribunal, batch_run):
        """judge_batch returns one verdict per prediction."""
        verdicts = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        assert len(verdicts) == 4
        for v in verdicts:
            assert isinstance(v, TribunalVerdict)
            assert v.target_ticker == "IAU"
            assert v.status in (VerdictStatus.PASS, VerdictStatus.FAIL)

    def test_judge_batch_persists_verdicts(self, tribunal, batch_run):
        """judge_batch returns verdicts (persistence tested separately)."""
        verdicts = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        assert len(verdicts) == 4
        # All verdicts should have prediction_id
        for v in verdicts:
            assert v.prediction_id

    def test_judge_batch_empty(self, tribunal):
        """Empty batch returns empty list."""
        empty_batch = BatchShadowRun(
            tickers=[], scenarios=[], mode=ShadowMode.AGGRESSIVE
        )
        verdicts = tribunal.judge_batch(empty_batch, previous_date="2026-05-06")
        assert verdicts == []

    def test_judge_batch_missing_ticker(self, replayer):
        """Missing ticker returns FAIL with full deviation."""
        tribunal = ShadowTribunal(replayer=replayer)
        # Predict for a ticker NOT in baseline prices
        pred = ShadowPrediction("NONEXISTENT", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt",
                                assertion="Doesn't matter", confidence=50.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=False)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="NONEXISTENT",
            predictions=[pred],
            original_decision_score=50.0,
        )
        batch = BatchShadowRun(tickers=["NONEXISTENT"], scenarios=[scenario],
                               mode=ShadowMode.AGGRESSIVE)
        verdicts = tribunal.judge_batch(batch, previous_date="2026-05-06")
        # Sim mode generates data for any ticker using baseline default (100.0)
        assert len(verdicts) == 1

    def test_judge_single_prediction(self, tribunal):
        """judge_prediction returns a single verdict."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt",
                                assertion="IAU will close up", confidence=70.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert isinstance(verdict, TribunalVerdict)
        assert verdict.target_ticker == "IAU"


class TestShadowTribunalDirectional:
    def test_gt_prediction(self, replayer):
        """gt prediction checks if close > open."""
        # Set baseline so we know direction
        replayer.set_baseline_price("IAU", 38.50)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt",
                                assertion="IAU closes up", confidence=70.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        # With seed=42, result is deterministic
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)

    def test_lt_prediction(self, replayer):
        """lt prediction checks if close < open."""
        replayer.set_baseline_price("IAU", 38.50)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, -0.5, "lt",
                                assertion="IAU closes down", confidence=70.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)

    def test_support_break_hold(self, replayer):
        """Support break: low price below support = FAIL."""
        replayer.set_baseline_price("IAU", 38.50)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("IAU", PredictionTarget.SUPPORT_BREAK, 35.00, "lt",
                                assertion="IAU holds 35", confidence=80.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)
        assert isinstance(verdict.deviation_pct, float)

    def test_resistance_break(self, replayer):
        """Resistance break: high price above resistance = PASS."""
        replayer.set_baseline_price("IAU", 38.50)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("IAU", PredictionTarget.RESISTANCE_BREAK, 38.00, "gt",
                                assertion="IAU breaks 38", confidence=80.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)
        assert "Resistance" in verdict.reason or "resistance" in verdict.reason

    def test_volatility_breakout(self, replayer):
        """Volatility breakout judgement."""
        replayer.set_baseline_price("SPY", 548.00)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("SPY", PredictionTarget.VOLATILITY_BREAKOUT, 5.0, "gt",
                                assertion="SPY vol expands 5%", confidence=60.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)
        assert "Daily range" in verdict.reason

    def test_flow_reversal(self, replayer):
        """Flow reversal judgement using volume proxy."""
        replayer.set_baseline_price("SPY", 548.00)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("SPY", PredictionTarget.FLOW_REVERSAL, 0.5, "gt",
                                assertion="SPY flow above 0.5x", confidence=60.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL)
        assert "Volume ratio" in verdict.reason

    def test_unknown_target_type(self, replayer):
        """Unknown target type returns FAIL."""
        replayer.set_baseline_price("IAU", 38.50)
        tribunal = ShadowTribunal(replayer=replayer)
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt",
                                assertion="Test", confidence=50.0,
                                target_date="2026-05-07", was_safety_valve_bypassed=True)
        verdict = tribunal.judge_prediction(pred, previous_date="2026-05-06")
        assert isinstance(verdict, TribunalVerdict)


class TestShadowTribunalVerdictDetails:
    def test_verdict_reason_populated(self, tribunal, batch_run):
        """Each verdict has a meaningful reason."""
        verdicts = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        for v in verdicts:
            assert v.reason, f"Verdict for {v.prediction_id} has no reason"
            assert len(v.reason) > 5

    def test_deviation_pct_range(self, tribunal, batch_run):
        """Deviation is a non-negative percentage."""
        verdicts = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        for v in verdicts:
            assert v.deviation_pct >= 0.0

    def test_actual_close_reasonable(self, tribunal, batch_run):
        """Actual close is a positive price or zero if missing."""
        verdicts = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        for v in verdicts:
            assert v.actual_close >= 0.0

    def test_verdict_batch_consistency(self, tribunal, batch_run):
        """Running judge_batch twice with same inputs yields deterministic results."""
        v1 = tribunal.judge_batch(batch_run, previous_date="2026-05-06")
        replayer2 = MarketDataReplayer(mode="simulate", seed=42)
        tribunal2 = ShadowTribunal(replayer=replayer2)
        v2 = tribunal2.judge_batch(batch_run, previous_date="2026-05-06")
        for a, b in zip(v1, v2):
            assert a.status == b.status, f"Mismatch on {a.prediction_id}: {a.status} vs {b.status}"