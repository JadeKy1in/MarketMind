"""Tests for shadow_types.py — Phase 8.0 data types."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from src.shadow_types import (
    ShadowPrediction,
    ShadowScenario,
    BatchShadowRun,
    TribunalVerdict,
    VerdictStatus,
    PredictionTarget,
    ComparisonOperator,
    ScenarioLabel,
    ShadowMode,
)


class TestShadowPrediction:
    def test_minimal_creation(self):
        """Create a prediction with minimal required fields."""
        pred = ShadowPrediction(
            target_ticker="IAU",
            target_type=PredictionTarget.DIRECTIONAL_MOVE,
            predicted_value=1.5,
            comparison_operator="gt",
        )
        assert pred.prediction_id is not None
        assert pred.target_ticker == "IAU"
        assert pred.target_type == PredictionTarget.DIRECTIONAL_MOVE
        assert pred.predicted_value == 1.5
        assert pred.comparison_operator == "gt"
        assert pred.reasoning == ""

    def test_full_creation(self):
        """Create a prediction with all optional fields."""
        pred = ShadowPrediction(
            prediction_id="custom-123",
            target_ticker="GDX",
            target_type=PredictionTarget.SUPPORT_BREAK,
            predicted_value=30.0,
            comparison_operator="lt",
            reasoning="Gold miners under pressure from DXY strength",
        )
        assert pred.prediction_id == "custom-123"
        assert pred.reasoning == "Gold miners under pressure from DXY strength"

    def test_unique_ids(self):
        """Each prediction gets a unique UUID."""
        p1 = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt")
        p2 = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt")
        assert p1.prediction_id != p2.prediction_id


class TestShadowScenario:
    def test_minimal_creation(self):
        """Create a scenario with minimal fields."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt")
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            predictions=[pred],
        )
        assert scenario.label == ScenarioLabel.AGGRESSIVE_BULL
        assert len(scenario.predictions) == 1
        assert scenario.predictions[0] is pred

    def test_multiple_predictions(self):
        """Scenario holds multiple predictions."""
        preds = [
            ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt"),
            ShadowPrediction("GDX", PredictionTarget.SUPPORT_BREAK, 30.0, "lt"),
            ShadowPrediction("TLT", PredictionTarget.RESISTANCE_BREAK, 95.0, "gt"),
        ]
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BEAR,
            predictions=preds,
            description="Aggressive bear case with broad sell-off",
        )
        assert scenario.description == "Aggressive bear case with broad sell-off"
        assert len(scenario.predictions) == 3


class TestBatchShadowRun:
    def test_minimal_creation(self):
        """Create a batch run with essential fields."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt")
        scenario = ShadowScenario(label=ScenarioLabel.AGGRESSIVE_BULL, predictions=[pred])
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        assert batch.mode == ShadowMode.AGGRESSIVE
        assert batch.total_predictions == 1
        assert len(batch.tickers) == 1

    def test_total_predictions_agg(self):
        """total_predictions sums across scenarios."""
        s1 = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            predictions=[ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt")],
        )
        s2 = ShadowScenario(
            label=ScenarioLabel.AMBIGUOUS_MIXED,
            predictions=[
                ShadowPrediction("GDX", PredictionTarget.SUPPORT_BREAK, 30.0, "lt"),
                ShadowPrediction("TLT", PredictionTarget.RESISTANCE_BREAK, 95.0, "gt"),
            ],
        )
        batch = BatchShadowRun(
            tickers=["IAU", "GDX", "TLT"],
            scenarios=[s1, s2],
            mode=ShadowMode.AGGRESSIVE,
        )
        assert batch.total_predictions == 3
        assert batch.tickers == ["IAU", "GDX", "TLT"]

    def test_generated_at_default(self):
        """Batch gets auto-generated timestamp."""
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[],
            mode=ShadowMode.AGGRESSIVE,
        )
        assert batch.generated_at is not None
        assert isinstance(batch.generated_at, datetime)

    def test_json_serializable(self):
        """BatchRun dataclass serializes to JSON."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt")
        scenario = ShadowScenario(label=ScenarioLabel.AGGRESSIVE_BULL, predictions=[pred])
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        d = batch.to_dict()
        assert d["tickers"] == ["IAU"]
        assert d["total_predictions"] == 1
        assert d["mode"] == "aggressive"

        # JSON round-trip
        raw = json.dumps(d)
        loaded = json.loads(raw)
        assert loaded["mode"] == "aggressive"
        assert len(loaded["scenarios"]) == 1
        assert len(loaded["scenarios"][0]["predictions"]) == 1


class TestTribunalVerdict:
    def test_minimal_creation(self):
        """Create a verdict with all required fields."""
        v = TribunalVerdict(
            prediction_id="pred-1",
            target_ticker="IAU",
            status=VerdictStatus.PASS,
            deviation_pct=0.0,
            actual_close=39.50,
            predicted_value=39.00,
            reason="Close above support",
        )
        assert v.verdict_id is not None
        assert v.status == VerdictStatus.PASS
        assert v.deviation_pct == 0.0
        assert v.actual_close == 39.50

    def test_fail_verdict(self):
        """FAIL verdict with deviation."""
        v = TribunalVerdict(
            prediction_id="pred-2",
            target_ticker="GDX",
            status=VerdictStatus.FAIL,
            deviation_pct=2.5,
            actual_close=28.50,
            predicted_value=30.00,
            reason="Support broken by 2.5%",
        )
        assert v.status == VerdictStatus.FAIL
        assert v.deviation_pct == 2.5
        assert abs(v.actual_close - 28.50) < 0.001

    def test_unique_verdict_ids(self):
        """Each verdict gets a unique UUID."""
        v1 = TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.0, 39.5, 39.0, "ok")
        v2 = TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.0, 39.5, 39.0, "ok")
        assert v1.verdict_id != v2.verdict_id

    def test_to_dict(self):
        """Verdict serializes to dict."""
        v = TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.0, 39.5, 39.0, "ok")
        d = v.to_dict()
        assert d["verdict_id"] == v.verdict_id
        assert d["status"] == "PASS"
        assert d["deviation_pct"] == 0.0


class TestEnums:
    def test_prediction_target_values(self):
        assert PredictionTarget.DIRECTIONAL_MOVE.value == "directional_move"
        assert PredictionTarget.SUPPORT_BREAK.value == "support_break"
        assert PredictionTarget.RESISTANCE_BREAK.value == "resistance_break"
        assert PredictionTarget.RELATIVE_OUTPERFORM.value == "relative_outperform"
        assert PredictionTarget.VOLATILITY_BREAKOUT.value == "volatility_breakout"
        assert PredictionTarget.FLOW_REVERSAL.value == "flow_reversal"

    def test_scenario_labels(self):
        assert ScenarioLabel.AGGRESSIVE_BULL.value == "aggressive_bull"
        assert ScenarioLabel.AGGRESSIVE_BEAR.value == "aggressive_bear"
        assert ScenarioLabel.AMBIGUOUS_MIXED.value == "ambiguous_mixed"
        assert ScenarioLabel.AMBIGUOUS_FLAT.value == "ambiguous_flat"

    def test_verdict_status(self):
        assert VerdictStatus.PASS.value == "PASS"
        assert VerdictStatus.FAIL.value == "FAIL"