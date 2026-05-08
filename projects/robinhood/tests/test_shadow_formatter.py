"""Tests for shadow_formatter.py — Phase 8.3 shadow mode output formatting."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.shadow_formatter import ShadowFormatter
from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    ScenarioLabel,
    ShadowMode,
    PredictionTarget,
    TribunalVerdict,
    VerdictStatus,
    EventStoreRef,
)


class TestShadowFormatter:
    def test_minimal_batch_output(self):
        """Format a minimal batch run to ShadowReport."""
        pred = ShadowPrediction(
            target_ticker="IAU",
            target_type=PredictionTarget.DIRECTIONAL_MOVE,
            predicted_value=1.5,
            comparison_operator="gt",
            assertion="IAU will close above 1.5% gain",
            confidence=75.0,
            target_date="2026-05-07",
            was_safety_valve_bypassed=True,
            original_safety_valves=["max_position_pct"],
        )
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            macro_theme="Gold rally",
            original_decision_score=85.0,
        )
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        formatter = ShadowFormatter()
        report = formatter.format_batch_report(batch)
        assert report.batch_id == batch.batch_id
        assert f"Batch {batch.batch_id[:8]}" in report.output_text
        assert "IAU" in report.output_text
        assert report.tickers_processed == 1
        assert report.total_predictions == 1

    def test_multi_ticker_output(self):
        """Format multi-ticker batch."""
        preds = [
            ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                             assertion="IAU up", confidence=70.0, target_date="2026-05-07",
                             was_safety_valve_bypassed=True),
            ShadowPrediction("GDX", PredictionTarget.SUPPORT_BREAK, 30.0, "lt",
                             assertion="GDX breaks 30", confidence=80.0, target_date="2026-05-07",
                             was_safety_valve_bypassed=True),
        ]
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=preds,
            original_decision_score=85.0,
        )
        batch = BatchShadowRun(
            tickers=["IAU", "GDX"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        formatter = ShadowFormatter()
        report = formatter.format_batch_report(batch)
        assert "IAU" in report.output_text
        assert "GDX" in report.output_text
        assert report.tickers_processed == 2

    def test_tribunal_summary(self):
        """Format tribunal verdicts into TribunalSummary."""
        verdicts = [
            TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.5, 39.50, 39.00, "Close above support"),
            TribunalVerdict("p2", "GDX", VerdictStatus.FAIL, 2.5, 28.50, 30.00, "Support broken"),
        ]
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=80.0,
        )
        batch = BatchShadowRun(tickers=["IAU"], scenarios=[scenario], mode=ShadowMode.AGGRESSIVE)

        formatter = ShadowFormatter()
        summary = formatter.format_tribunal_summary(batch, verdicts)
        assert summary.total_judged == 2
        assert summary.passed == 1
        assert summary.failed == 1
        assert abs(summary.pass_rate_pct - 50.0) < 0.01

    def test_tribunal_summary_empty(self):
        """Empty verdicts return zero stats."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=80.0,
        )
        batch = BatchShadowRun(tickers=["IAU"], scenarios=[scenario], mode=ShadowMode.AGGRESSIVE)

        formatter = ShadowFormatter()
        summary = formatter.format_tribunal_summary(batch, [])
        assert summary.total_judged == 0
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.pass_rate_pct == 0.0

    def test_tribunal_summary_ticker_breakdown(self):
        """Ticker breakdown aggregates correctly."""
        verdicts = [
            TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.5, 39.50, 39.00, ""),
            TribunalVerdict("p2", "IAU", VerdictStatus.FAIL, 2.0, 38.00, 40.00, ""),
            TribunalVerdict("p3", "GDX", VerdictStatus.PASS, 1.0, 30.00, 29.50, ""),
        ]
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=80.0,
        )
        batch = BatchShadowRun(tickers=["IAU", "GDX"], scenarios=[scenario],
                               mode=ShadowMode.AGGRESSIVE)

        formatter = ShadowFormatter()
        summary = formatter.format_tribunal_summary(batch, verdicts)
        assert "IAU" in summary.ticker_breakdown
        assert "GDX" in summary.ticker_breakdown
        assert summary.ticker_breakdown["IAU"]["total"] == 2
        assert summary.ticker_breakdown["IAU"]["passed"] == 1
        assert summary.ticker_breakdown["GDX"]["total"] == 1
        assert summary.ticker_breakdown["GDX"]["passed"] == 1

    def test_render_tribunal_summary_text(self):
        """Render tribunal summary to human-readable text."""
        verdicts = [
            TribunalVerdict("p1", "IAU", VerdictStatus.PASS, 0.5, 39.50, 39.00, ""),
        ]
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=80.0,
        )
        batch = BatchShadowRun(tickers=["IAU"], scenarios=[scenario], mode=ShadowMode.AGGRESSIVE)

        formatter = ShadowFormatter()
        summary = formatter.format_tribunal_summary(batch, verdicts)
        text = formatter.render_tribunal_summary_text(summary)
        assert "THE TRIBUNAL" in text
        assert "PASS" in text
        assert "IAU" in text

    def test_json_output(self):
        """JSON body is valid and contains batch info."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="IAU up", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=85.0,
        )
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        formatter = ShadowFormatter()
        report = formatter.format_batch_report(batch, include_json=True)
        assert report.output_json
        parsed = json.loads(report.output_json)
        assert parsed["batch_id"] == batch.batch_id
        assert len(parsed["scenarios"]) == 1

    def test_json_output_disabled(self):
        """JSON output is empty when include_json=False."""
        pred = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                assertion="", confidence=70.0, target_date="2026-05-07",
                                was_safety_valve_bypassed=True)
        scenario = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred],
            original_decision_score=80.0,
        )
        batch = BatchShadowRun(tickers=["IAU"], scenarios=[scenario], mode=ShadowMode.AGGRESSIVE)

        formatter = ShadowFormatter()
        report = formatter.format_batch_report(batch, include_json=False)
        assert report.output_json == ""

    def test_aggressive_and_ambiguous_count(self):
        """Counts for aggressive vs ambiguous scenarios."""
        pred1 = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.5, "gt",
                                 assertion="", confidence=70.0, target_date="2026-05-07",
                                 was_safety_valve_bypassed=True)
        pred2 = ShadowPrediction("TLT", PredictionTarget.DIRECTIONAL_MOVE, 0.5, "gt",
                                 assertion="", confidence=50.0, target_date="2026-05-07",
                                 was_safety_valve_bypassed=False)
        scenario_agg = ShadowScenario(
            label=ScenarioLabel.AGGRESSIVE_BULL,
            target_ticker="IAU",
            predictions=[pred1],
            original_decision_score=85.0,
        )
        scenario_amb = ShadowScenario(
            label=ScenarioLabel.AMBIGUOUS_MIXED,
            target_ticker="TLT",
            predictions=[pred2],
            original_decision_score=50.0,
        )
        batch = BatchShadowRun(
            tickers=["IAU", "TLT"],
            scenarios=[scenario_agg, scenario_amb],
            mode=ShadowMode.AGGRESSIVE,
        )
        formatter = ShadowFormatter()
        report = formatter.format_batch_report(batch)
        assert report.aggressive_count == 1
        assert report.ambiguous_count == 1