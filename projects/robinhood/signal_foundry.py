#!/usr/bin/env python3
"""
signal_foundry.py — DEPRECATED (Phase A, 2026-05-09)

This entry point has been superseded by src/main.py.  Please use:

    python src/main.py --mode strict --ticker AAPL
    python src/main.py --mode strict --ticker AAPL --mock --verbose

All new development targets src/main.py exclusively.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Redirect to the new entry point
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

if __name__ == "__main__":
    print(
        "signal_foundry.py is DEPRECATED. Use src/main.py instead:\n"
        "  python src/main.py --mode strict --ticker AAPL\n"
        "  python src/main.py --mode strict --ticker AAPL --mock --verbose",
        file=sys.stderr,
    )
    sys.exit(1)

# === LEGACY CODE BELOW — kept for reference only, NOT maintained ===

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Layer imports
# ---------------------------------------------------------------------------

from src.account_reader import read_account_state
from src.market_fetcher import fetch_market_data
from src.sentiment_collector import collect_sentiment_data
from src.macro_calendar import fetch_upcoming_events

from src.fundamental_engine import analyze_fundamentals
from src.technical_engine import analyze_technicals
from src.event_engine import analyze_events
from src.sentiment_engine import analyze_sentiment

from src.resonance_aggregator import compute_resonance
from src.capital_manager import compute_full_portfolio
from src.pro_model_deep_dive import build_pro_model_prompt, format_pro_model_response
from src.deepseek_client import dispatch_prompt
from src.output_formatter import format_report

# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal_foundry",
        description=(
            "SkillFoundry - Four-Dimensional Resonance Analysis Pipeline. "
            "Generates institutional-grade research reports for any ticker."
        ),
    )

    parser.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="Target ticker symbol (e.g., AAPL, MSFT, TSLA). Required.",
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help=(
            "Use local sandbox mock data for all API calls. "
            "Includes: mock Pro Model response, mock market data, "
            "mock sentiment data. Default: False (calls real APIs)."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Print the report to stdout only. Do NOT write any files "
            "to disk. Default: False (writes report to "
            "output/reports/<TICKER>_<TIMESTAMP>.md)."
        ),
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Custom output file path for the generated Markdown report. "
            "Overrides the default path scheme."
        ),
    )

    parser.add_argument(
        "--resonance-only",
        action="store_true",
        default=False,
        help=(
            "Skip the Pro Model (DeepSeek) dispatch. Only run Layers 1-3 "
            "and output the raw resonance result in a compact format. "
            "Useful for debugging or quick scans."
        ),
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print detailed progress messages to stderr during pipeline execution.",
    )

    return parser


# ---------------------------------------------------------------------------
# Pipeline Executor
# ---------------------------------------------------------------------------


def _log(msg: str, verbose: bool = False) -> None:
    """Emit a timestamped log line to stderr if verbose is enabled."""
    if verbose:
        print(f"[signal_foundry] {msg}", file=sys.stderr, flush=True)


def _run_layers(
    ticker: str,
    mock: bool,
    resonance_only: bool,
    verbose: bool,
) -> dict[str, Any]:
    """Execute Layers 1-4 sequentially and return all intermediate results.

    Args:
        ticker: Target ticker symbol.
        mock: If True, use mock/sandbox data.
        resonance_only: If True, skip Layer 4 (Pro Model) dispatch.
        verbose: If True, log progress to stderr.

    Returns:
        Dict with keys: 'layer1', 'layer2', 'layer3', 'pro_response',
        'report_markdown', and 'errors'.
    """
    result: dict[str, Any] = {
        "layer1": {},
        "layer2": {},
        "layer3": {},
        "pro_response": None,
        "pro_model_system_prompt": None,
        "pro_model_user_prompt": None,
        "report_markdown": None,
        "errors": [],
    }

    account_path = _PROJECT_ROOT / "input" / "account_state.json"

    # ==================================================================
    # Layer 1: Data Collection
    # ==================================================================
    _log("Layer 1: Data collection starting...", verbose)
    try:
        result["layer1"]["account"] = read_account_state(str(account_path))
    except Exception as exc:
        result["errors"].append(f"Layer1/account: {exc}")
        if verbose:
            traceback.print_exc(file=sys.stderr)

    try:
        result["layer1"]["market_data"] = fetch_market_data(ticker, mock=mock)
    except Exception as exc:
        result["errors"].append(f"Layer1/market: {exc}")
        if verbose:
            traceback.print_exc(file=sys.stderr)

    try:
        result["layer1"]["sentiment_data"] = collect_sentiment_data(
            ticker, mock=mock,
        )
    except Exception as exc:
        result["errors"].append(f"Layer1/sentiment: {exc}")
        if verbose:
            traceback.print_exc(file=sys.stderr)

    try:
        result["layer1"]["macro_events"] = fetch_upcoming_events(mock=mock)
    except Exception as exc:
        result["errors"].append(f"Layer1/macro: {exc}")
        if verbose:
            traceback.print_exc(file=sys.stderr)

    _log("Layer 1 complete.", verbose)

    # ==================================================================
    # Layer 2: Analysis Engines
    # ==================================================================
    _log("Layer 2: Analysis engines starting...", verbose)
    md = result["layer1"].get("market_data", {})
    sd = result["layer1"].get("sentiment_data", {})
    me = result["layer1"].get("macro_events", {})
    acct = result["layer1"].get("account", {})

    try:
        result["layer2"]["fundamental"] = analyze_fundamentals(md)
    except Exception as exc:
        result["errors"].append(f"Layer2/fundamental: {exc}")

    try:
        result["layer2"]["technical"] = analyze_technicals(md)
    except Exception as exc:
        result["errors"].append(f"Layer2/technical: {exc}")

    try:
        result["layer2"]["event"] = analyze_events(me)
    except Exception as exc:
        result["errors"].append(f"Layer2/event: {exc}")

    try:
        result["layer2"]["sentiment"] = analyze_sentiment(sd)
    except Exception as exc:
        result["errors"].append(f"Layer2/sentiment: {exc}")

    _log("Layer 2 complete.", verbose)

    # ==================================================================
    # Layer 3: Resonance / Capital / Build Pro Model Prompts
    # ==================================================================
    _log("Layer 3: Resonance + Capital + Prompt building starting...", verbose)

    l2 = result["layer2"]
    l3 = result["layer3"]

    resonance_input = {
        "fundamental_score": l2.get("fundamental", {}),
        "technical_score": l2.get("technical", {}),
        "event_score": l2.get("event", {}),
        "sentiment_score": l2.get("sentiment", {}),
    }

    try:
        result["layer3"]["resonance"] = compute_resonance(resonance_input)
    except Exception as exc:
        result["errors"].append(f"Layer3/resonance: {exc}")

    try:
        result["layer3"]["capital"] = compute_full_portfolio(
            acct,
            result["layer3"].get("resonance", {}),
        )
    except Exception as exc:
        result["errors"].append(f"Layer3/capital: {exc}")

    # Build Pro Model prompts using build_pro_model_prompt()
    try:
        resonance_result = result["layer3"].get("resonance", {})
        capital_result = result["layer3"].get("capital", {})
        prompt_bundle = build_pro_model_prompt(
            resonance_result=resonance_result,
            capital_result=capital_result,
            ticker=ticker,
            account_state=acct,
        )
    except Exception as exc:
        result["errors"].append(f"Layer3/build_prompt: {exc}")
        prompt_bundle = {}

    result["pro_model_system_prompt"] = prompt_bundle.get("system_prompt", "")
    result["pro_model_user_prompt"] = prompt_bundle.get("user_prompt", "")
    _log("Layer 3 complete.", verbose)

    # ==================================================================
    # Layer 4 (conditional): Pro Model Dispatch + Output Formatting
    # ==================================================================
    if resonance_only:
        _log("Resonance-only mode. Skipping Pro Model dispatch.", verbose)
        return result

    _log("Layer 4: Pro Model dispatch + output formatting...", verbose)

    # Dispatch to DeepSeek (or mock)
    raw_response: str | dict[str, Any] = '{"error": "dispatch failed"}'
    try:
        raw_response = dispatch_prompt(
            system_prompt=result["pro_model_system_prompt"],
            user_prompt=result["pro_model_user_prompt"],
            mock=mock,
            ticker=ticker,
        )
    except Exception as exc:
        result["errors"].append(f"Layer4/dispatch: {exc}")
        raw_response = '{"error": "dispatch failed"}'

    # Parse the raw LLM response using format_pro_model_response
    try:
        if isinstance(raw_response, str):
            pro_response = format_pro_model_response(raw_response)
        else:
            pro_response = raw_response
        result["pro_response"] = pro_response
    except Exception as exc:
        result["errors"].append(f"Layer4/parse_pro: {exc}")
        pro_response = {"error": str(exc)}

    # Format report
    try:
        report = format_report(
            pro_response=pro_response,
            ticker=ticker,
            resonance_result=result["layer3"].get("resonance", None),
        )
        result["report_markdown"] = report
    except Exception as exc:
        result["errors"].append(f"Layer4/format: {exc}")

    _log("Layer 4 complete.", verbose)

    return result


# ---------------------------------------------------------------------------
# Output Handling
# ---------------------------------------------------------------------------

_OUTPUT_DIR = _PROJECT_ROOT / "output" / "reports"


def _ensure_output_dir() -> Path:
    """Create the default output directory if it doesn't exist."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def _default_output_path(ticker: str) -> Path:
    """Generate a timestamped default output path."""
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _ensure_output_dir() / f"{ticker.upper()}_{ts}.md"


def _save_report(report: str, output_path: Path) -> None:
    """Write the Markdown report to the specified path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"[signal_foundry] Report saved to: {output_path.resolve()}")


def _print_report(report: str) -> None:
    """Print the report to stdout."""
    sys.stdout.write(report)
    sys.stdout.write("\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the SignalFoundry CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    ticker = args.ticker.upper()
    mock = args.mock
    dry_run = args.dry_run
    custom_output = args.output
    resonance_only = args.resonance_only
    verbose = args.verbose

    # Print banner
    print(f"SignalFoundry Alpha v1.0", file=sys.stderr, flush=True)
    print(f"  Ticker:   {ticker}", file=sys.stderr)
    print(f"  Mock:     {mock}", file=sys.stderr)
    print(f"  Dry-run:  {dry_run}", file=sys.stderr)
    print(f"  Output:   custom={custom_output is not None} resonance_only={resonance_only}", file=sys.stderr)
    print(f"{'-' * 50}", file=sys.stderr, flush=True)

    # Execute pipeline
    result = _run_layers(
        ticker=ticker,
        mock=mock,
        resonance_only=resonance_only,
        verbose=verbose,
    )

    # Report any errors
    if result["errors"]:
        print(f"\n[signal_foundry] WARNING: {len(result['errors'])} pipeline error(s):", file=sys.stderr)
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)

    # Handle resonance-only mode output
    if resonance_only:
        res_data = result.get("layer3", {})
        resonance = res_data.get("resonance", {})
        capital = res_data.get("capital", {})

        lines: list[str] = [
            f"=== SkillFoundry Resonance-Only Report: {ticker} ===",
            "",
            f"Resonance Score: {resonance.get('weighted_score', 'N/A')}/100",
            f"Signal: {resonance.get('signal', 'N/A')}",
            f"Resonance Condition Met: {resonance.get('resonance_condition_met', 'N/A')}",
            f"Soft Veto Triggered: {resonance.get('soft_veto_triggered', 'N/A')}",
            f"Override Available: {resonance.get('override_available', 'N/A')}",
            "",
            f"Capital Plan: {json.dumps(capital, indent=2)}",
        ]
        report = "\n".join(lines)

        if dry_run:
            _print_report(report)
        else:
            output_path = Path(custom_output) if custom_output else _default_output_path(ticker + "_resonance")
            _save_report(report, output_path)

        sys.exit(0 if not result["errors"] else 1)

    # Get the formatted report
    report = result.get("report_markdown")
    if not report:
        print("[signal_foundry] ERROR: No report was generated. Check pipeline errors above.",
              file=sys.stderr)
        sys.exit(1)

    # Output
    if dry_run:
        _print_report(report)
    elif custom_output:
        _save_report(report, Path(custom_output))
    else:
        output_path = _default_output_path(ticker)
        _save_report(report, output_path)

    # Summary to stderr
    word_count = len(report.split())
    print(f"\n[signal_foundry] Done. Report length: ~{word_count} words.",
          file=sys.stderr, flush=True)

    sys.exit(0 if not result["errors"] else 1)


if __name__ == "__main__":
    main()