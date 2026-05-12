#!/usr/bin/env python3
"""
main.py — SignalFoundry Unified Entry Point

Supports three modes:
  daily   — Full daily analysis: Scout -> Deep Dive -> Pro -> Multi-Profile
  strict  — Single ticker pipeline
  shadow  — Multi-personality shadow trading

Usage:
  python src/main.py --mode daily --mock --verbose
  python src/main.py --mode strict --ticker IAU --mock
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env file
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip().strip('"').strip("'"))

from src.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)
DEFAULT_STRICT_TICKER = "IAU"


def _read_portfolio_json(filepath):
    """Read portfolio.json, return AccountState."""
    import json as _json
    with open(filepath, encoding="utf-8") as f:
        data = _json.load(f)
    from src.account_reader import AccountState, Position
    positions = data.get("positions", [])
    cash = 0.0
    holdings = []
    for p in positions:
        if p.get("ticker", "").upper() == "CASH":
            cash = float(p.get("shares", 0)) * float(p.get("avg_cost", 1.0))
        else:
            holdings.append({
                "ticker": p.get("ticker", "UNKNOWN"),
                "shares": int(p.get("shares", 0)),
                "avg_cost": float(p.get("avg_cost", 0)),
                "current_price": float(p.get("current_price", 0)),
            })
    return AccountState(
        last_updated="portfolio.json", cash=cash,
        buying_power=cash * 2.0,
        positions=[Position(**h) for h in holdings],
    )


def build_parser():
    p = argparse.ArgumentParser(description="SignalFoundry — Daily Analysis Pipeline")
    p.add_argument("--mode", choices=["daily", "strict", "shadow"], default="daily")
    p.add_argument("--ticker", type=str, default=None)
    p.add_argument("--mock", action="store_true", default=False)
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    p.add_argument("--output", type=str, default=None)
    p.add_argument("--no-pro", action="store_true", default=False)
    return p


def run_daily_mode(mock=False, verbose=False, no_pro=False, status_callback=None):
    """Full daily pipeline."""
    if verbose:
        print("=" * 60, file=sys.stderr)
        print("SignalFoundry — Daily Pipeline", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    client = DeepSeekClient() if not mock else None
    errors = []
    now = datetime.datetime.now()
    report_date = now.strftime("%Y-%m-%d")

    # ---- S1: Scout ----
    if status_callback:
        status_callback("S1: 新闻采集...")
    from src.scout_fetcher import scout_pipeline
    scout = scout_pipeline(mock=mock)
    if verbose:
        print(f"  Raw events: {len(scout.raw_events)}", file=sys.stderr)

    # ---- S2: Data Collection ----
    if status_callback:
        status_callback("S2: 数据采集...")

    # Account
    acct_path = Path(__file__).resolve().parent.parent.parent / "command_center" / "portfolio.json"
    try:
        account = _read_portfolio_json(str(acct_path))
    except Exception as exc:
        account = None
        errors.append(f"Account: {exc}")

    # Market data
    from src.market_fetcher import MarketFetcher
    fetcher = MarketFetcher()
    weekly = None
    try:
        weekly = fetcher.fetch_weekly("SPY", period="1y", force_refresh=not mock)
    except Exception:
        pass

    # Sentiment
    from src.sentiment_collector import SentimentCollector
    sentiment_data = []
    try:
        sc = SentimentCollector()
        sentiment_data = sc.fetch_all(limit_per_source=5, force_refresh=not mock)
    except Exception:
        pass

    # Macro calendar
    from src.macro_calendar import MacroCalendarCollector
    macro_list = []
    try:
        mc = MacroCalendarCollector()
        me = mc.fetch_upcoming(days_ahead=14, force_refresh=not mock)
        macro_list = me if isinstance(me, list) else []
    except Exception:
        pass

    pos_list = [p.to_dict() for p in account.positions] if account else []

    # ---- S3: Four Engines ----
    if status_callback:
        status_callback("S3: 四维分析...")
    from src.fundamental_engine import analyze_fundamental
    from src.technical_engine import analyze_technical
    from src.event_engine import analyze_event_driven
    from src.sentiment_engine import analyze_sentiment

    fundamental = {"score": 50, "reasoning": "N/A"}
    try:
        fundamental = analyze_fundamental(macro_list, pos_list, client=client)
    except Exception as exc:
        fundamental["reasoning"] = str(exc)

    technical = {"score": 50, "reasoning": "N/A"}
    try:
        if weekly is not None and len(weekly) >= 26:
            tech_df = weekly.copy()
            tech_df.columns = [c.lower() for c in tech_df.columns]
            technical = analyze_technical(tech_df)
    except Exception:
        pass

    event_driven = {"score": 50, "reasoning": "N/A"}
    try:
        event_driven = analyze_event_driven(macro_list, client=client)
    except Exception:
        pass

    sentiment_result = {"sentiment": "Neutral", "magnitude": 0}
    try:
        texts = [s.get("raw_text", "") for s in sentiment_data if s.get("raw_text")]
        if texts:
            sentiment_result = analyze_sentiment(" | ".join(texts[:5]), client=client)
    except Exception:
        pass

    if verbose:
        print(f"  F={fundamental.get('score')} T={technical.get('score')} "
              f"E={event_driven.get('score')} S={sentiment_result.get('sentiment')}", file=sys.stderr)

    # ---- S4: Resonance + Portfolio ----
    if status_callback:
        status_callback("S4: 共振聚合...")
    from src.resonance_aggregator import compute_resonance
    resonance = {"signal": "WAIT", "weighted_score": 50.0, "dimension_scores": {}}
    try:
        resonance = compute_resonance(
            fundamental=fundamental, technical=technical,
            event_driven=event_driven, sentiment_engine_output=sentiment_result,
        )
    except Exception as exc:
        errors.append(f"Resonance: {exc}")

    capital = {"overall_strategy": "N/A"}
    try:
        if account:
            from src.capital_manager import compute_full_portfolio
            capital = compute_full_portfolio(account, resonance)
    except Exception:
        pass

    # ---- Build Scout context (ALL events with body) ----
    scout_context = ""
    if scout.raw_events:
        parts = []
        for evt in scout.raw_events:
            src = getattr(evt, 'source_name', 'Unknown')
            title = getattr(evt, 'title', '')
            body = getattr(evt, 'body', '')[:300]
            parts.append(f"[{src}] {title}" + (f"\n   {body}" if body else ""))
        scout_context = "\n\n".join(parts)

    # ---- Flash preprocessing ----
    flash_context = ""
    if not no_pro and not mock and client and scout.raw_events:
        if status_callback:
            status_callback("S4.5: Flash 预处理...")
        try:
            from src.flash_preprocessor import preprocess_scout_events, format_flash_context
            flash_result = preprocess_scout_events(scout.raw_events, client)
            flash_context = format_flash_context(flash_result)
            if verbose:
                print(f"  Flash: {flash_result.get('events_processed', 0)} events", file=sys.stderr)
        except Exception as exc:
            errors.append(f"Flash: {exc}")

    # ---- S5: Pro Model ----
    pro_response = None
    if not no_pro and not mock and client:
        if status_callback:
            status_callback("S5: Pro 深度分析...")
        try:
            from src.pro_model_deep_dive import build_pro_model_prompt
            prompt_bundle = build_pro_model_prompt(
                resonance_result=resonance,
                capital_result=capital,
                ticker="PORTFOLIO",
                account_state=account.to_dict() if account else None,
                scout_context=scout_context,
                review_context="",
                flash_context=flash_context,
            )
            raw = client.pro(
                system_prompt=prompt_bundle.get("system_prompt", ""),
                user_prompt=prompt_bundle.get("user_prompt", ""),
                call_profile="analysis",
            )
            pro_response = raw if isinstance(raw, dict) and "error" not in raw else None
        except Exception as exc:
            errors.append(f"Pro: {exc}")

    # ---- S6: Output ----
    if status_callback:
        status_callback("S6: 报告生成...")
    return _format_daily_report(report_date, scout, resonance, capital, pro_response, errors)


def _format_daily_report(date, scout, resonance, capital, pro_response, errors):
    """Generate structured Markdown report."""
    signal = resonance.get("signal", "N/A")
    score = resonance.get("weighted_score", 0)
    lines = [
        f"# 深度宏观研报: {date}",
        f"**信号:** {signal} | **加权分:** {score:.1f}/100",
        "", "---", "",
        "## 1. 今日宏观线索发现 (Scout)", "",
    ]
    if scout.raw_events:
        for evt in scout.raw_events[:20]:
            src = getattr(evt, 'source_name', 'Unknown')
            cat = getattr(evt, 'category', 'general')
            title = getattr(evt, 'title', '')[:200]
            lines.append(f"- **[{src}]** ({cat}) {title}")
    else:
        lines.append("(无新闻线索)")
    lines.extend(["", f"实时信源捕获: {len(scout.raw_events)} 条新闻", ""])

    # Pro analysis
    if pro_response and isinstance(pro_response, dict):
        rpt = pro_response.get("report", "") or pro_response.get("research_report", "")
        if rpt and isinstance(rpt, str) and len(rpt) > 50:
            lines.extend(["---", "", "## 2. Pro 模型深度分析", "", rpt[:8000], ""])
        else:
            for key, label in {"summary": "执行摘要", "risk_assessment": "风险评估"}.items():
                val = pro_response.get(key, "")
                if val and isinstance(val, str) and len(val) > 30:
                    lines.append(f"### {label}")
                    lines.append(val[:3000])
                    lines.append("")
    else:
        dim_scores = resonance.get("dimension_scores", {})
        dim_details = resonance.get("dimension_details", {})
        lines.extend(["---", "", "## 2. 四维共振分析", "",
                       "| 维度 | 分数 | 推理摘要 |", "|------|------|---------|"])
        for dim in ("fundamental", "technical", "event_driven", "sentiment"):
            s = dim_scores.get(dim, "N/A")
            r = str(dim_details.get(dim, {}).get("reasoning", "N/A"))[:100]
            lines.append(f"| {dim} | {s} | {r} |")
        lines.append("")

    # Price audit
    lines.extend(["---", "", "## 3. 价格真实性审核", "",
                   "*以下价格由 AI 生成，未经实时验证，请以实际交易终端价格为准。*", ""])

    # Errors
    if errors:
        lines.extend(["", "## 管线错误", ""])
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    lines.extend(["", "---", "*SignalFoundry 生成 | 物理隔离纪律执行*"])
    return "\n".join(lines)


def main():
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.mode == "daily":
        report = run_daily_mode(mock=args.mock, verbose=args.verbose, no_pro=args.no_pro)
    elif args.mode == "strict":
        ticker = (args.ticker or DEFAULT_STRICT_TICKER).upper()
        print(f"# SignalFoundry Analysis: {ticker}\n\nMock/Strict mode placeholder.")
    elif args.mode == "shadow":
        print("Shadow mode placeholder.")
    else:
        print(f"Unknown mode: {args.mode}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report saved to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(report)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
