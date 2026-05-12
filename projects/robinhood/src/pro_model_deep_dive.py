"""
pro_model_deep_dive.py - Layer 3 Pro Model Deep Dive / Final Brain

Orchestrates the final LLM call to DeepSeek, packing all four engine outputs
plus the resonance result into a structured action directive.
"""

from __future__ import annotations
import json
from typing import Any

from src.account_reader import AccountState, read_account_state
from src.capital_manager import compute_full_portfolio, compute_position_sizing
from src.resonance_aggregator import compute_resonance
from src.lateral_proxy import PROXY_REFERENCE_PROMPT


def _lateral_proxy_section() -> str:
    return PROXY_REFERENCE_PROMPT


OUTPUT_SCHEMA_SPEC: dict[str, Any] = {
    "type": "object",
    "required": ["executive_summary", "trading_decision", "position_management",
                 "deep_research", "risk_assessment", "action_plan"],
    "properties": {
        "executive_summary": {
            "type": "object",
            "required": ["signal", "weighted_score", "conviction_level",
                         "override_available", "one_liner"],
        },
        "trading_decision": {
            "type": "object",
            "required": ["action", "max_shares", "max_notional",
                         "cash_reserve_kept", "ticker", "price_target_suggestion"],
        },
        "position_management": {
            "type": "object",
            "required": ["position_adjustment", "exit_suggestion", "portfolio_impact"],
        },
        "deep_research": {"type": "object", "required": ["macro_analysis", "final_reasoning"]},
        "risk_assessment": {"type": "object", "required": ["overall_risk_rating", "stop_loss_level"]},
        "action_plan": {"type": "object", "required": ["immediate_steps", "contingency_triggers"]},
    },
}


def _build_dimension_summary(resonance_result: dict[str, Any]) -> str:
    ds = resonance_result.get("dimension_scores", {})
    dd = resonance_result.get("dimension_details", {})
    lines: list[str] = [
        "=== Four-Dimensional Resonance Analysis ===",
        f"Weighted Score: {resonance_result.get('weighted_score', 'N/A')}/100",
        f"Resonance Signal: {resonance_result.get('signal', 'N/A')}",
        f"Soft Veto: {resonance_result.get('soft_veto_triggered', False)}",
        "[Dimension Scores]",
    ]
    for dim in ("fundamental", "technical", "event_driven", "sentiment"):
        score = ds.get(dim, "N/A")
        reasoning = dd.get(dim, {}).get("reasoning", "No reasoning.")[:150]
        lines.append(f"  {dim}: {score}/100 — {reasoning}")
    return "\n".join(lines)


def _build_capital_summary(capital_result: dict[str, Any] | None) -> str:
    if capital_result is None:
        return "[Capital Management: Not computed]"
    lines: list[str] = [
        "=== Capital Management ===",
        f"Strategy: {capital_result.get('overall_strategy', 'N/A')}",
    ]
    return "\n".join(lines)


def _build_price_reference(account_state, ticker):
    """Build a current price reference table to prevent price hallucinations."""
    lines = ["=== CURRENT MARKET PRICES (DO NOT INVENT PRICES) ==="]
    lines.append("You MUST use these prices. If a ticker is not listed below,")
    lines.append("state 'price unknown' rather than inventing a price.")
    lines.append("")
    if account_state:
        lines.append("| Ticker | Current Price |")
        lines.append("|--------|---------------|")
        for pos in account_state.get("positions", []):
            ticker = pos.get("ticker", "?")
            price = pos.get("current_price", "N/A")
            lines.append(f"| {ticker} | ${price} |")
        lines.append("")
    # Add key reference tickers
    # Try to fetch live prices for key reference tickers
    try:
        from src.market_fetcher import MarketFetcher
        fetcher = MarketFetcher()
        ref_tickers = ["IAU", "SLV", "SPY", "GLD", "USO", "WEAT", "MOS", "NVDA"]
        live_prices = {}
        for t in ref_tickers:
            try:
                df = fetcher.fetch_daily(t, period="5d", force_refresh=False)
                if df is not None and len(df) > 0:
                    price = float(df.iloc[-1]["Close"] if "Close" in df.columns else df.iloc[-1]["close"])
                    live_prices[t] = round(price, 2)
            except Exception:
                pass
        if live_prices:
            lines.append("| Ticker | Live Price |")
            lines.append("|--------|-----------|")
            for t, p in sorted(live_prices.items()):
                lines.append(f"| {t} | ${p} |")
            lines.append("")
    except Exception:
        pass
    lines.append("Key reference assets (as of today's data):")
    lines.append("- IAU (iShares Gold Trust): check yfinance for latest")
    lines.append("- SLV (iShares Silver Trust): check yfinance for latest")
    lines.append("- SPY (S&P 500 ETF): check yfinance for latest")
    lines.append("- GLD (SPDR Gold Trust): check yfinance for latest")
    lines.append("- USO (US Oil Fund): check yfinance for latest")
    lines.append("- WEAT (Wheat ETF): check yfinance for latest")
    lines.append("")
    lines.append("CRITICAL: Never fabricate a price. If you don't know the exact current")
    lines.append("price, express triggers as percentages from current (e.g., 'buy if 5% above current').")
    return "\n".join(lines)


def build_pro_model_prompt(
    resonance_result: dict[str, Any],
    capital_result: dict[str, Any] | None = None,
    ticker: str = "AAPL",
    account_state: dict[str, Any] | None = None,
    scout_context: str = "",
    review_context: str = "",
    flash_context: str = "",
) -> dict[str, str]:
    dim_summary = _build_dimension_summary(resonance_result)
    cap_summary = _build_capital_summary(capital_result)
    override_flag = resonance_result.get("override_available", False)

    lateral_instructions = ""
    try:
        lateral_instructions = _lateral_proxy_section()
    except Exception:
        pass

    acct_lines: list[str] = ["=== Account State ==="]
    if account_state:
        acct_lines.append(f"  Cash: ${account_state.get('cash', 0):.2f}")
        for pos in account_state.get("positions", []):
            acct_lines.append(f"  {pos.get('ticker', '?')}: {pos.get('shares', 0)} shares")
    acct_summary = "\n".join(acct_lines)

    system_prompt = (
        "You are a Senior Global Macro Strategist producing institutional-grade "
        "investment research.\n\n"
        "## CRITICAL: Multi-Asset Mandatory Coverage\n"
        "You MUST analyze ALL of the following asset classes. Do NOT skip any:\n"
        "- **Gold & Precious Metals**: Central bank buying, real rates, safe-haven flows, ETF flows\n"
        "- **Crude Oil & Energy**: OPEC+ decisions, supply disruptions, shipping routes (Hormuz, Suez)\n"
        "- **Agricultural Commodities**: Fertilizer costs, weather patterns, planting data, crop prices\n"
        "- **AI/Tech Supply Chain**: Semiconductor equipment, foundry capacity, HBM memory, cloud capex\n"
        "- **Crypto & Digital Assets**: ETF flows, regulatory shifts, institutional adoption signals\n"
        "- **Fixed Income & Credit**: Yield curve shape, corporate spreads, default risk, duration positioning\n"
        "For EACH class, explain WHY macro signals point in a specific direction. "
        "Show the full causal chain from macro event → asset impact. "
        "Do NOT cherry-pick one stock. Justify EVERY stock choice with macro logic.\n\n"
        "## Investment Philosophy\n"
        "1. **Low Risk, High Reward Priority**: Focus on asymmetric opportunities "
        "where downside is limited and upside is substantial. Cash is a valid position.\n"
        "2. **Multi-Horizon Flexibility**: intraday/swing (0.5-5 days), tactical (1-2 weeks), strategic (1 month+).\n"
        "3. **Cash Preservation**: Always maintain adequate cash reserve (10-30%). "
        "The purpose of cash is to be ready when truly asymmetric opportunities appear. "
        "Do NOT get trapped in positions when great opportunities require capital.\n"
        "4. **Every Trade Must Have A Timeline**: Specify exactly WHEN to enter "
        "(buy signal/price trigger), WHEN to exit (target price or date), and "
        "WHAT would invalidate the thesis. Example: 'Sell IAU between May 12-15 "
        "before Wolsh's first speech as Fed Chair.'\n"
        "5. **Don't Fight The Market**: As a non-professional tool relying on "
        "public information, we will always lag institutional investors. "
        "Accept this constraint. Do not try to outsmart the market on timing — "
        "focus on direction and magnitude.\n"
        "6. **Concrete Triggers Only**: Every recommendation must include specific "
        "observable conditions: 'Buy NVDA if it closes above $950 on above-average volume.' "
        "NOT 'Buy on weakness.'\n\n"
        "## Core Directive\n"
        "You are an institutional-grade trading decision engine producing deep "
        "research reports.\n\n"
        "## Required Analysis Depth\n"
        "### 1. Asset Chain Penetration\n"
        "Trace the FULL vertical chain.\n"
        "### 2. Historical Context\n"
        "Reference specific historical episodes with dates.\n"
        "### 3. Mosaic Theory Reasoning\n"
        "Piece together fragmented public signals.\n"
        "### 4. Lateral Data Proxy\n"
        f"{lateral_instructions}\n"
        "## Output Format\n"
        "Respond with a single JSON object.\n"
        "NO markdown wrapping. Output PURE JSON.\n\n"
        "## Writing Style\n"
        "- Narrative essay, not bullet points.\n"
        "- Concrete data, specific dates, named sources.\n"
        "- Show reasoning chains.\n"
        "- Output in Chinese. Professional financial terminology.\n\n"
        "## Critical Constraints\n"
        "1. Every recommendation: specific price level + timeline.\n"
        "2. Every ticker: Robinhood-tradable.\n"
        "3. No generic language.\n"
        "4. Cash reserve: never below 10%.\n"
        "5. Override Protocol: "
        + ("Override IS available." if override_flag
           else "Override NOT available.")
    )

    # Build current price reference table to prevent hallucinations
    price_table = _build_price_reference(account_state, ticker)
    
    user_prompt = (
        f"## Analysis Context for {ticker}\n\n"
        f"{price_table}\n\n"
        f"### Engine Outputs\n{dim_summary}\n\n"
        f"### Capital Management\n{cap_summary}\n\n"
        f"### Account State\n{acct_summary}\n\n"
        f"### Scout Discovery\n{scout_context or 'No scout data.'}\n\n"
        f"### Cognitive Review\n{review_context or 'No prior review.'}\n\n"
        f"### Flash Preprocessing\n{flash_context or 'No Flash preprocessing.'}\n\n"
        "### Instructions\n"
        "Synthesize everything above into a deep research report. "
        "Follow depth requirements: asset chain penetration, historical context, "
        "mosaic theory, lateral proxies, specific price levels. "
        "Chinese output, narrative essay style. PURE JSON output.\n"
        "Begin now. Output ONLY valid JSON."
    )

    return {"system_prompt": system_prompt, "user_prompt": user_prompt}


def format_pro_model_response(raw_response: str) -> dict[str, Any]:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": raw_response}
