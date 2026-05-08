"""
shadow_formatter.py — Phase 8.3 Shadow Mode Output Formatter

Transforms a BatchShadowRun (containing all scenarios and predictions) into
a structured ShadowReport suitable for:
  1. Console output (human-readable tables)
  2. JSON serialisation (for the event store audit trail)
  3. Tribunal consumption (predictions-to-judge list)

The formatter applies the Zero-Hedging Protocol's assertion formatting rules:
  - NO fuzzy language in output
  - Every prediction rendered as a precise, testable assertion
  - Batch metadata presented as a summary header

SPARC:
  Specification: format raw shadow predictions into structured reports + console output.
  Pseudocode: report builder + table renderer + JSON dumper.
  Architecture: pure transformation — no I/O, no side effects.
  Refinement: zero-hedging enforcement on output text; no new hedge words introduced.
  Completion: ready for main.py integration.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from src.shadow_types import (
    BatchShadowRun,
    PredictionTarget,
    ScenarioLabel,
    ShadowPrediction,
    ShadowScenario,
    ShadowScenarioType,
    TribunalVerdict,
    VerdictStatus,
)


# ============================================================
# Data structures
# ============================================================

@dataclass
class ShadowReport:
    """A formatted, human-readable report for one batch run.

    This is the output representation of a BatchShadowRun.
    It includes formatted strings, aggregated stats, and a clean
    JSON-serialisable body.

    Attributes:
        batch_id: Links back to the source BatchShadowRun.
        generated_at: Report generation timestamp.
        tickers_processed: Number of tickers in the batch.
        total_predictions: Total predictions across all scenarios.
        output_text: Human-readable console output.
        output_json: JSON body for file/event-store persistence.
        aggressive_count: Count of aggressive-scenario predictions.
        ambiguous_count: Count of ambiguous-scenario predictions.
    """

    batch_id: str = ""
    generated_at: str = ""
    tickers_processed: int = 0
    total_predictions: int = 0
    output_text: str = ""
    output_json: str = ""
    aggressive_count: int = 0
    ambiguous_count: int = 0


@dataclass
class TribunalSummary:
    """Summary of tribunal results for a batch.

    Attributes:
        batch_id: Links back to the source batch.
        total_judged: Total predictions that received a verdict.
        passed: Number of PASS verdicts.
        failed: Number of FAIL verdicts.
        pass_rate_pct: Percentage of predictions that passed.
        ticker_breakdown: Dict mapping ticker -> accuracy stats.
        verdicts: List of individual veredicts for detailed review.
    """

    batch_id: str = ""
    total_judged: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate_pct: float = 0.0
    ticker_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    verdicts: List[TribunalVerdict] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda:
        datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z")


# ============================================================
# Formatter
# ============================================================

class ShadowFormatter:
    """Formats BatchShadowRun into ShadowReport and TribunalSummary."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format_batch_report(
        self,
        batch: BatchShadowRun,
        include_json: bool = True,
    ) -> ShadowReport:
        """Format a batch run into a full ShadowReport.

        Args:
            batch: The BatchShadowRun to format.
            include_json: If True, include output_json field.

        Returns:
            ShadowReport with human-readable text and (optionally) JSON.
        """
        lines: List[str] = []
        lines.append(f"{'='*70}")
        lines.append(f"  SHADOW MODE REPORT — Batch {batch.batch_id[:8]}")
        lines.append(f"{'='*70}")
        lines.append(f"  Mode: {batch.mode.value.upper()}")
        lines.append(f"  Generated: {batch.generated_at}")
        lines.append(f"  Tickers: {', '.join(batch.tickers)}")
        lines.append(f"  Total Predictions: {batch.total_predictions}")
        lines.append(f"  Scenarios: {len(batch.scenarios)}")
        lines.append(f"{'='*70}")
        lines.append("")

        agg_count = 0
        amb_count = 0

        for idx, scenario in enumerate(batch.scenarios):
            lines.append(f"  ───────────────────────────────")
            lines.append(f"  Scenario #{idx + 1}: {scenario.label.value.upper()}")
            lines.append(f"  Ticker: {scenario.target_ticker}")
            lines.append(f"  Macro Theme: {scenario.macro_theme or 'N/A'}")
            lines.append(f"  Original Confidence: {scenario.original_decision_score:.1f}")
            lines.append(f"  Predictions: {scenario.prediction_count}")
            lines.append("")

            for p_idx, pred in enumerate(scenario.predictions):
                lines.append(f"    [{p_idx + 1}] {pred.target_type.value.replace('_', ' ').upper()}")
                lines.append(f"        ASSERTION: {pred.assertion}")
                lines.append(f"        VALUE: {pred.predicted_value} ({pred.comparison_operator})")
                lines.append(f"        CONFIDENCE: {pred.confidence:.1f}%")
                lines.append(f"        TARGET: {pred.target_date}")
                lines.append(f"        RV: {'BY-PASSED' if pred.was_safety_valve_bypassed else 'INTACT'}")
                if pred.original_safety_valves:
                    lines.append(f"        VALVES: {', '.join(pred.original_safety_valves)}")
                lines.append("")

            if scenario.label in (ScenarioLabel.AGGRESSIVE_BULL, ScenarioLabel.AGGRESSIVE_BEAR):
                agg_count += scenario.prediction_count
            else:
                amb_count += scenario.prediction_count

        lines.append(f"{'='*70}")
        lines.append(f"  SUMMARY")
        lines.append(f"  Aggressive Predictions: {agg_count}")
        lines.append(f"  Ambiguous Predictions: {amb_count}")
        lines.append(f"  Total: {batch.total_predictions}")
        lines.append(f"{'='*70}")

        output_text = "\n".join(lines)

        output_json = ""
        if include_json:
            output_json = json.dumps(
                self._batch_to_dict(batch),
                indent=2,
                sort_keys=True,
                default=str,
            )

        return ShadowReport(
            batch_id=batch.batch_id,
            generated_at=batch.generated_at,
            tickers_processed=len(batch.tickers),
            total_predictions=batch.total_predictions,
            output_text=output_text,
            output_json=output_json,
            aggressive_count=agg_count,
            ambiguous_count=amb_count,
        )

    def format_tribunal_summary(
        self,
        batch: BatchShadowRun,
        verdicts: List[TribunalVerdict],
    ) -> TribunalSummary:
        """Format tribunal verdicts into a summary.

        Args:
            batch: The original batch run that generated the predictions.
            verdicts: List of TribunalVerdicts from the tribunal.

        Returns:
            TribunalSummary with pass rates, ticker breakdown, and all verdicts.
        """
        passed = sum(1 for v in verdicts if v.status == VerdictStatus.PASS)
        failed = sum(1 for v in verdicts if v.status == VerdictStatus.FAIL)
        total = len(verdicts)
        pass_rate = (passed / total * 100.0) if total > 0 else 0.0

        # Ticker breakdown
        ticker_stats: Dict[str, Dict[str, Any]] = {}
        for v in verdicts:
            ticker = v.target_ticker
            if ticker not in ticker_stats:
                ticker_stats[ticker] = {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "avg_deviation": 0.0,
                    "deviations": [],
                }
            stats = ticker_stats[ticker]
            stats["total"] += 1
            if v.status == VerdictStatus.PASS:
                stats["passed"] += 1
            elif v.status == VerdictStatus.FAIL:
                stats["failed"] += 1
            stats["deviations"].append(v.deviation_pct)

        # Compute averages per ticker
        for ticker, stats in ticker_stats.items():
            devs = stats.pop("deviations", [])
            stats["avg_deviation_pct"] = round(
                sum(devs) / len(devs), 2
            ) if devs else 0.0
            stats["pass_rate_pct"] = round(
                (stats["passed"] / stats["total"] * 100.0), 2
            ) if stats["total"] > 0 else 0.0

        return TribunalSummary(
            batch_id=batch.batch_id,
            total_judged=total,
            passed=passed,
            failed=failed,
            pass_rate_pct=round(pass_rate, 2),
            ticker_breakdown=ticker_stats,
            verdicts=list(verdicts),
        )

    def render_tribunal_summary_text(self, summary: TribunalSummary) -> str:
        """Render a human-readable text version of the tribunal summary."""
        lines: List[str] = []
        lines.append(f"{'='*70}")
        lines.append(f"  THE TRIBUNAL — VERDICT SUMMARY")
        lines.append(f"{'='*70}")
        lines.append(f"  Batch: {summary.batch_id[:8]}")
        lines.append(f"  Judged: {summary.total_judged}")
        lines.append(f"  PASS: {summary.passed}")
        lines.append(f"  FAIL: {summary.failed}")
        lines.append(f"  PASS RATE: {summary.pass_rate_pct:.1f}%")
        lines.append("")

        if summary.ticker_breakdown:
            lines.append(f"  ── Per-Ticker Breakdown ──")
            for ticker, stats in sorted(summary.ticker_breakdown.items()):
                lines.append(
                    f"    {ticker}: {stats['passed']}/{stats['total']} passed "
                    f"({stats['pass_rate_pct']:.1f}%) | "
                    f"avg dev: {stats['avg_deviation_pct']:.2f}%"
                )
            lines.append("")

        lines.append(f"{'='*70}")
        lines.append(f"  END TRIBUNAL REPORT")
        lines.append(f"{'='*70}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _batch_to_dict(self, batch: BatchShadowRun) -> Dict[str, Any]:
        """Convert a batch run to a serialisable dict."""
        return {
            "batch_id": batch.batch_id,
            "mode": batch.mode,
            "generated_at": batch.generated_at,
            "tickers": list(batch.tickers),
            "total_predictions": batch.total_predictions,
            "scenarios": [
                self._scenario_to_dict(s) for s in batch.scenarios
            ],
            "source_reports": list(batch.source_reports),
        }

    def _scenario_to_dict(self, scenario: ShadowScenario) -> Dict[str, Any]:
        """Convert a scenario to a serialisable dict."""
        return {
            "scenario_id": scenario.scenario_id,
            "label": scenario.label.value,
            "target_ticker": scenario.target_ticker,
            "macro_theme": scenario.macro_theme,
            "prediction_count": scenario.prediction_count,
            "predictions": [
                self._prediction_to_dict(p) for p in scenario.predictions
            ],
        }

    def _prediction_to_dict(self, pred: ShadowPrediction) -> Dict[str, Any]:
        """Convert a prediction to a serialisable dict."""
        return {
            "prediction_id": pred.prediction_id,
            "target_ticker": pred.target_ticker,
            "target_type": pred.target_type.value,
            "assertion": pred.assertion,
            "predicted_value": pred.predicted_value,
            "comparison_operator": pred.comparison_operator,
            "confidence": pred.confidence,
            "target_date": pred.target_date,
            "was_safety_valve_bypassed": pred.was_safety_valve_bypassed,
        }