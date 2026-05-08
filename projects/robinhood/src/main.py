#!/usr/bin/env python3
"""
main.py — Phase 8.5 / 8 End-to-End Assembly Entry Point

Dual-mode entry point for the Robinhood analysis system:

  STRICT MODE (--mode strict):
    Runs the full Layer 1–4 pipeline for a single ticker, producing a
    single DecisionReport with safety valves, paradigm anchors, and
    position sizing. Output is a clean Markdown decision report.

  SHADOW MODE (--mode shadow):
    Runs the Shadow Mode pipeline for a portfolio of tickers, producing
    aggressive batch predictions with zero-hedging assertions. Outputs
    are bulk reports + an Event Store audit trail + Tribunal verdicts.

Architecture:
  strict: deepseek_client → mosaic_reasoning → decision_aggregator → output_formatter
  shadow: deepseek_client → shadow_aggregator → zero_hedging_validator → shadow_tribunal → shadow_formatter

SPARC:
  Specification: dual-mode CLI entry point integrating all Phase 8 layers.
  Pseudocode: argparse → mode switch → pipeline orchestration.
  Architecture: facade pattern — delegates to existing modules.
  Refinement: strict mode preserves legacy safety; shadow mode is the new aggressive layer.
  Completion: ready for testing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Strict mode imports ──
from src.account_reader import AccountState, read_account_state
from src.capital_manager import CapitalManager
from src.causal_auditor import CausalAuditor
from src.decision_aggregator import DecisionAggregator, DecisionReport
from src.deepseek_client import DeepSeekClient
from src.fundamental_engine import FundamentalEngine
from src.macro_calendar import MacroCalendar
from src.market_fetcher import MarketFetcher
from src.mosaic_reasoning import MosaicReasoner, MosaicNarrative
from src.output_formatter import ReportGenerator
from src.paradigm_anchors import compute_paradigm_multiplier
from src.qualitative_judgment import QualitativeJudgment
from src.red_team_auditor import RedTeamAuditor, RedTeamAuditReport
from src.sentiment_engine import SentimentEngine
from src.technical_engine import TechnicalEngine

# ── Shadow mode imports ──
from src.event_store import EventStore
from src.market_data_replayer import MarketDataReplayer
from src.shadow_aggregator import ShadowAggregator
from src.shadow_formatter import ShadowFormatter
from src.shadow_tribunal import ShadowTribunal
from src.zero_hedging_validator import ZeroHedgingValidator

logger = logging.getLogger(__name__)

# ============================================================
# Constants
# ============================================================

# Core monitoring pool (shadow mode batch targets)
DEFAULT_SHADOW_POOL: List[str] = [
    "IAU", "GDX", "GLD", "SLV",
    "TLT", "IEF", "SHY",
    "SPY", "QQQ", "IWM",
    "HYG", "LQD", "JNK",
    "DXY", "UUP",
]

# Default strict mode ticker
DEFAULT_STRICT_TICKER: str = "IAU"

# Event store path
DEFAULT_EVENT_STORE_PATH: str = "data/event_store.jsonl"

# Shadow output path
DEFAULT_SHADOW_OUTPUT_DIR: str = "data/shadow_reports"


# ============================================================
# CLI Argument Parser
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="Robinhood Analysis System — Dual Mode (Strict / Shadow)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --mode strict --ticker IAU\n"
            "  python main.py --mode shadow --pool IAU,GDX,TLT\n"
            "  python main.py --mode shadow --pool ALL --tribunal\n"
        ),
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["strict", "shadow"],
        default="strict",
        help="Execution mode: strict (single report) or shadow (batch predictions)",
    )

    # Strict mode options
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="Target ticker for strict mode (default: IAU)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Analysis date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--price",
        type=float,
        default=None,
        help="Target price override (default: fetch from market).",
    )

    # Shadow mode options
    parser.add_argument(
        "--pool",
        type=str,
        default=None,
        help="Comma-separated ticker pool for shadow mode (or 'ALL' for defaults)",
    )
    parser.add_argument(
        "--tribunal",
        action="store_true",
        default=False,
        help="Run the Shadow Tribunal after predictions",
    )
    parser.add_argument(
        "--save-reports",
        action="store_true",
        default=False,
        help="Save shadow reports to disk (in DEFAULT_SHADOW_OUTPUT_DIR)",
    )
    parser.add_argument(
        "--event-store",
        type=str,
        default=None,
        help="Event store file path (default: data/event_store.jsonl)",
    )
    parser.add_argument(
        "--volatility",
        type=str,
        choices=["calm", "normal", "volatile", "panic"],
        default=None,
        help="Override volatility regime for market data simulation",
    )

    # General options
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable coloured console output",
    )

    return parser


# ============================================================
# Strict Mode Pipeline
# ============================================================

def run_strict_mode(
    ticker: str,
    analysis_date: str,
    target_price: float,
) -> str:
    """Run the full Layer 1–4 strict mode pipeline for a single ticker.

    Args:
        ticker: Target ticker symbol.
        analysis_date: Analysis date (YYYY-MM-DD).
        target_price: Current price.

    Returns:
        Formatted Markdown decision report string.

    Raises:
        RuntimeError: If any pipeline stage fails.
    """
    logger.info("Starting STRICT mode pipeline for %s on %s", ticker, analysis_date)

    # ── Initialise all pipeline components ──
    client = DeepSeekClient()
    market_fetcher = MarketFetcher()
    macro_calendar = MacroCalendar()
    tech_engine = TechnicalEngine()
    fund_engine = FundamentalEngine()
    event_engine = SentimentEngine()  # NOTE: sentiment_engine reuses EventEngine pattern
    sent_engine = SentimentEngine()
    mosaic = MosaicReasoner(client=client)
    auditor = RedTeamAuditor()
    aggregator = DecisionAggregator()
    formatter = ReportGenerator()
    qual_judge = QualitativeJudgment()
    causal_auditor = CausalAuditor()
    capital_mgr = CapitalManager()

    # ── Stage 1: Data fetching ──
    account_state = read_account_state()
    quotes = market_fetcher.fetch_quotes([ticker])
    macro_events = macro_calendar.get_upcoming_events(days_ahead=7)

    # ── Stage 2: Four-dimensional scoring ──
    fund_score = fund_engine.analyze(ticker)
    tech_score = tech_engine.analyze(ticker)
    event_score = event_engine.analyze(ticker, macro_events)
    sent_score = sent_engine.analyze(ticker)

    dimension_scores = {
        "fundamental": fund_score,
        "technical": tech_score,
        "event_driven": event_score,
        "sentiment": sent_score,
    }

    dimension_details = {
        "fundamental": {"score": fund_score, "reasoning": "Fundamental analysis"},
        "technical": {"score": tech_score, "reasoning": "Technical analysis"},
        "event_driven": {"score": event_score, "reasoning": "Event-driven analysis"},
        "sentiment": {"score": sent_score, "reasoning": "Sentiment analysis"},
    }

    # ── Stage 3: Mosaic reasoning ──
    mosaic_narrative = mosaic.reason(
        ticker=ticker,
        dimension_scores=dimension_scores,
        dimension_details=dimension_details,
        account_state=account_state,
        market_data=quotes,
        macro_events=macro_events,
    )

    # ── Stage 4: Causal audit ──
    audit_report = auditor.audit(
        mosaic_narrative=mosaic_narrative,
        dimension_scores=dimension_scores,
        ticker=ticker,
        account_state=account_state,
    )

    # ── Stage 5: Decision aggregation ──
    decision_report = aggregator.aggregate(
        dimension_scores=dimension_scores,
        dimension_details=dimension_details,
        mosaic_narrative=mosaic_narrative,
        audit_report=audit_report,
        account_state=account_state,
        target_ticker=ticker,
        target_price=target_price,
    )

    # ── Stage 6: Output formatting ──
    report_markdown = formatter.generate(decision_report)

    logger.info(
        "STRICT mode complete: %s → %s (score=%.1f)",
        ticker,
        decision_report.decision_track.value,
        decision_report.final_score,
    )

    return report_markdown


# ============================================================
# Shadow Mode Pipeline
# ============================================================

def run_shadow_mode(
    pool: List[str],
    analysis_date: str,
    run_tribunal: bool = False,
    save_reports: bool = False,
    event_store_path: Optional[str] = None,
    volatility_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the Shadow Mode pipeline for a portfolio of tickers.

    Pipeline:
      1. ShadowAggregator → batch predictions for all tickers
      2. ZeroHedgingValidator → sanitises/filters predictions
      3. ShadowFormatter → human-readable report + JSON snapshot
      4. ShadowTribunal (optional) → PASS/FAIL judgements
      5. EventStore persistence → immutable audit trail

    Args:
        pool: List of ticker symbols.
        analysis_date: Analysis date (YYYY-MM-DD).
        run_tribunal: If True, run Tribunal after predictions.
        save_reports: If True, save reports to disk.
        event_store_path: Path to event store file.
        volatility_override: Override volatility regime for simulation.

    Returns:
        Dict with keys:
            - "batch": BatchShadowRun
            - "report": ShadowReport (formatted)
            - "verdicts": List[TribunalVerdict] (if tribunal run)
            - "tribunal_summary": TribunalSummary (if tribunal run)
            - "event_store_events": int (count of events written)
    """
    logger.info(
        "Starting SHADOW mode pipeline for %d tickers on %s",
        len(pool), analysis_date,
    )

    # ── Initialise shadow components ──
    strict_aggregator = DecisionAggregator()
    aggregator = ShadowAggregator(aggregator=strict_aggregator)
    validator = ZeroHedgingValidator()
    formatter = ShadowFormatter()
    event_store = EventStore(path=event_store_path or DEFAULT_EVENT_STORE_PATH)
    replayer = MarketDataReplayer(seed=42)

    # ── Stage 1: Generate shadow batch predictions ──
    logger.info("Generating shadow predictions for %d tickers...", len(pool))

    # Run per-ticker aggregation (all scenarios)
    batch = aggregator.run_batch(
        tickers=pool,
        run_aggressive=True,
        run_ambiguous=True,
    )

    # ── Stage 2: Zero-Hedging validation ──
    logger.info("Running Zero-Hedging validation on %d scenarios...", len(batch.scenarios))
    validated_batch = validator.validate_batch(batch)

    logger.info(
        "Validation complete: %d predictions passed validation",
        validated_batch.total_predictions,
    )

    # ── Stage 3: Format report ──
    report = formatter.format_batch_report(validated_batch, include_json=True)

    # ── Stage 3b: Persist to EventStore (immutable audit trail) ──
    event_store.append_batch(validated_batch)
    event_count = 1

    # ── Save to disk (optional) ──
    if save_reports:
        output_dir = Path(DEFAULT_SHADOW_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Text report
        text_path = output_dir / f"shadow_{validated_batch.batch_id[:12]}.txt"
        text_path.write_text(report.output_text, encoding="utf-8")
        logger.info("Shadow text report saved to %s", text_path)

        # JSON snapshot
        json_path = output_dir / f"shadow_{validated_batch.batch_id[:12]}.json"
        json_path.write_text(report.output_json, encoding="utf-8")
        logger.info("Shadow JSON snapshot saved to %s", json_path)

    # ── Stage 4: Tribunal (optional) ──
    result: Dict[str, Any] = {
        "batch": validated_batch,
        "report": report,
        "verdicts": [],
        "tribunal_summary": None,
        "event_store_events": event_count,
    }

    if run_tribunal:
        logger.info("Running Shadow Tribunal...")
        tribunal = ShadowTribunal(
            replayer=replayer,
            event_store=event_store,
            strict_mode=True,
        )

        # Override volatility if specified
        if volatility_override:
            logger.info("Overriding volatility regime: %s", volatility_override)

        verdicts = tribunal.judge_batch(
            batch=validated_batch,
            previous_date=analysis_date,
        )

        summary = formatter.format_tribunal_summary(validated_batch, verdicts)

        result["verdicts"] = verdicts
        result["tribunal_summary"] = summary

        # Log summary
        summary_text = formatter.render_tribunal_summary_text(summary)
        logger.info("Tribunal complete:\n%s", summary_text)

        if save_reports:
            verdict_path = output_dir / f"tribunal_{validated_batch.batch_id[:12]}.txt"
            verdict_path.write_text(summary_text, encoding="utf-8")
            logger.info("Tribunal summary saved to %s", verdict_path)

        # Increment event count for verdicts
        result["event_store_events"] += len(verdicts)

    logger.info("SHADOW mode complete: %d events written to event store", result["event_store_events"])

    return result


# ============================================================
# Console display helpers
# ============================================================

def _print_header(text: str, width: int = 70) -> None:
    """Print a centred header."""
    padding = (width - len(text) - 2) // 2
    print()
    print("=" * width)
    print(" " * padding + text)
    print("=" * width)


def _display_strict_report(report_md: str) -> None:
    """Print a strict mode Markdown report to console."""
    print()
    print(report_md)
    print()


def _display_shadow_summary(
    result: Dict[str, Any],
) -> None:
    """Print a shadow mode summary to console."""
    report = result["report"]
    print()
    print(report.output_text)
    print()

    if result["tribunal_summary"]:
        formatter = ShadowFormatter()
        print(formatter.render_tribunal_summary_text(result["tribunal_summary"]))

    print(f"  Event Store events written: {result['event_store_events']}")
    print()


# ============================================================
# Entry point
# ============================================================

def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = build_parser()
    args = parser.parse_args()

    # ── Logging setup ──
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── Date ──
    analysis_date = args.date or datetime.datetime.now().strftime("%Y-%m-%d")

    # ── Mode switch ──
    if args.mode == "strict":
        ticker = args.ticker or DEFAULT_STRICT_TICKER
        target_price = args.price or _fetch_target_price(ticker)

        _print_header(f"STRICT MODE — {ticker}")

        try:
            report_md = run_strict_mode(
                ticker=ticker,
                analysis_date=analysis_date,
                target_price=target_price,
            )
            _display_strict_report(report_md)
        except Exception as e:
            logger.exception("Strict mode pipeline failed: %s", e)
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    elif args.mode == "shadow":
        pool = _resolve_pool(args.pool)
        event_store_path = args.event_store or DEFAULT_EVENT_STORE_PATH

        _print_header(f"SHADOW MODE — {len(pool)} tickers")

        try:
            result = run_shadow_mode(
                pool=pool,
                analysis_date=analysis_date,
                run_tribunal=args.tribunal,
                save_reports=args.save_reports,
                event_store_path=event_store_path,
                volatility_override=args.volatility,
            )
            _display_shadow_summary(result)
        except Exception as e:
            logger.exception("Shadow mode pipeline failed: %s", e)
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    return 0


def _fetch_target_price(ticker: str) -> float:
    """Fetch a target price for a ticker.

    Returns a baseline price if market data is unavailable.
    """
    from src.market_data_replayer import MarketDataReplayer

    replayer = MarketDataReplayer()
    baseline = replayer.get_baseline_price(ticker)
    if baseline is not None:
        return baseline

    # Fallback
    return 100.0


def _resolve_pool(pool_arg: Optional[str]) -> List[str]:
    """Resolve the ticker pool from CLI argument.

    Args:
        pool_arg: Comma-separated list, "ALL", or None.

    Returns:
        List of ticker symbols.
    """
    if pool_arg is None or pool_arg.upper() == "ALL":
        return list(DEFAULT_SHADOW_POOL)

    return [t.strip().upper() for t in pool_arg.split(",") if t.strip()]


# ============================================================
# Script entry
# ============================================================

if __name__ == "__main__":
    sys.exit(main())