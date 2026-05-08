"""
pro_model_deep_dive.py - Layer 3 Pro Model Deep Dive / Final Brain (Task 3.3)

Orchestrates the final LLM call to DeepSeek, packing all four engine outputs
plus the resonance result into a structured "action directive" that forces a
thousand-word-level deep research report.

Key design:
  1. Merges resonance_aggregator output + capital_manager output + raw engine details.
  2. Builds a system prompt that forces strict JSON output with an exhaustive
     "deep_research" section (no 200-400 word limit; target 1000+ words).
  3. NEVER calls the actual DeepSeek API in this module; only constructs the
     prompt payload. The caller decides whether to dispatch.
  4. Implements Output Format Enforcement: the expected JSON schema is defined
     as a Pydantic-style dict spec, validated by the caller if needed.
"""

from __future__ import annotations

import json
from typing import Any

from src.account_reader import AccountState, read_account_state
from src.capital_manager import compute_full_portfolio, compute_position_sizing
from src.resonance_aggregator import compute_resonance

# ---------------------------------------------------------------------------
# Output JSON Schema Specification
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA_SPEC: dict[str, Any] = {
    "type": "object",
    "required": [
        "executive_summary",
        "trading_decision",
        "position_management",
        "deep_research",
        "risk_assessment",
        "action_plan",
    ],
    "properties": {
        "executive_summary": {
            "type": "object",
            "required": ["signal", "weighted_score", "conviction_level",
                         "override_available", "one_liner"],
            "properties": {
                "signal": {"type": "string", "enum": ["STRONG_BUY", "BUY",
                                                       "SELL", "HOLD", "WAIT"]},
                "weighted_score": {"type": "number"},
                "conviction_level": {"type": "string",
                                     "enum": ["HIGH", "MEDIUM", "LOW"]},
                "override_available": {"type": "boolean"},
                "one_liner": {"type": "string"},
            },
        },
        "trading_decision": {
            "type": "object",
            "required": ["action", "max_shares", "max_notional",
                         "cash_reserve_kept", "ticker", "price_target_suggestion"],
            "properties": {
                "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD",
                                                       "AVOID"]},
                "max_shares": {"type": "integer"},
                "max_notional": {"type": "number"},
                "cash_reserve_kept": {"type": "number"},
                "ticker": {"type": "string"},
                "price_target_suggestion": {"type": "string"},
            },
        },
        "position_management": {
            "type": "object",
            "required": ["position_adjustment", "exit_suggestion",
                         "portfolio_impact"],
            "properties": {
                "position_adjustment": {"type": "object"},
                "exit_suggestion": {"type": "object"},
                "portfolio_impact": {"type": "string"},
            },
        },
        "deep_research": {
            "type": "object",
            "required": ["macro_analysis", "fundamental_deep_dive",
                         "technical_context", "sentiment_landscape",
                         "event_risk_calendar", "scenario_analysis",
                         "final_reasoning"],
            "properties": {
                "macro_analysis": {"type": "string",
                                   "description": "500+ words macro context"},
                "fundamental_deep_dive": {"type": "string",
                    "description": "300+ words on fundamentals"},
                "technical_context": {"type": "string",
                    "description": "300+ words technical analysis"},
                "sentiment_landscape": {"type": "string",
                    "description": "200+ words sentiment context"},
                "event_risk_calendar": {"type": "string",
                    "description": "200+ words on upcoming events"},
                "scenario_analysis": {"type": "string",
                    "description": ("Bull/bear/base scenarios, each "
                                    "150+ words")},
                "final_reasoning": {"type": "string",
                    "description": "500+ words final synthesis"},
            },
        },
        "risk_assessment": {
            "type": "object",
            "required": ["max_loss_scenario", "stop_loss_level",
                         "correlation_risk", "liquidity_concern",
                         "overall_risk_rating"],
            "properties": {
                "max_loss_scenario": {"type": "string"},
                "stop_loss_level": {"type": "string"},
                "correlation_risk": {"type": "string"},
                "liquidity_concern": {"type": "string"},
                "overall_risk_rating": {"type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH", "EXTREME"]},
            },
        },
        "action_plan": {
            "type": "object",
            "required": ["immediate_steps", "contingency_triggers",
                         "review_timeline"],
            "properties": {
                "immediate_steps": {"type": "array", "items": {"type": "string"}},
                "contingency_triggers": {"type": "array",
                    "items": {"type": "string"}},
                "review_timeline": {"type": "string"},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# System Prompt Construction
# ---------------------------------------------------------------------------

def _build_dimension_summary(
    resonance_result: dict[str, Any],
) -> str:
    """Build a compact text summary of the four dimensions for the prompt.

    Args:
        resonance_result: Output from compute_resonance().

    Returns:
        Formatted string.
    """
    ds = resonance_result.get("dimension_scores", {})
    dd = resonance_result.get("dimension_details", {})

    lines: list[str] = [
        "=== Four-Dimensional Resonance Analysis ===",
        f"Weighted Score: {resonance_result.get('weighted_score', 'N/A')}/100",
        f"Resonance Signal: {resonance_result.get('signal', 'N/A')}",
        f"Soft Veto Triggered: {resonance_result.get('soft_veto_triggered', False)}",
        f"Override Available: {resonance_result.get('override_available', False)}",
        f"Resonance Condition Met: {resonance_result.get('resonance_condition_met', False)}",
        "",
        "[Dimension Scores]",
    ]
    for dim in ("fundamental", "technical", "event_driven", "sentiment"):
        score = ds.get(dim, "N/A")
        reasoning = dd.get(dim, {}).get("reasoning", "No reasoning provided.")
        lines.append(f"  {dim}: {score}/100")
        lines.append(f"    Reasoning: {reasoning}")
    return "\n".join(lines)


def _build_capital_summary(
    capital_result: dict[str, Any] | None,
) -> str:
    """Build a text summary of capital management for the prompt.

    Args:
        capital_result: Output from compute_full_portfolio() or None.

    Returns:
        Formatted string.
    """
    if capital_result is None:
        return "[Capital Management: Not computed]"

    lines: list[str] = [
        "=== Capital Management Analysis ===",
        f"Overall Strategy: {capital_result.get('overall_strategy', 'N/A')}",
        "",
        "[Cash Summary]",
    ]
    cash = capital_result.get("cash_summary", {})
    lines.append(f"  Total Cash: ${cash.get('total_cash', 0):.2f}")
    lines.append(f"  Reserved Cash: ${cash.get('reserved_cash', 0):.2f}")
    lines.append(f"  Deployable Cash: ${cash.get('deployable_cash', 0):.2f}")

    pos_actions = capital_result.get("position_actions", [])
    if pos_actions:
        lines.append("")
        lines.append("[Position Actions]")
        for pa in pos_actions:
            lines.append(
                f"  {pa.get('ticker', '?')}: {pa.get('action', '?')} "
                f"| Max Shares: {pa.get('max_shares', 0)} "
                f"| Notional: ${pa.get('max_notional', 0):.2f}"
            )
            if pa.get("exit_suggestion"):
                es = pa["exit_suggestion"]
                lines.append(
                    f"    Exit: {es.get('type', '?')} - "
                    f"{es.get('shares_to_sell', 0)} shares "
                    f"(${es.get('estimated_notional', 0):.2f})"
                )
            if pa.get("position_adjustment"):
                adj = pa["position_adjustment"]
                lines.append(f"    Adjustment: {adj.get('type', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_pro_model_prompt(
    resonance_result: dict[str, Any],
    capital_result: dict[str, Any] | None = None,
    ticker: str = "AAPL",
    account_state: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build the complete prompt bundle for the Pro Model (DeepSeek).

    This function NEVER dispatches to an external API. It only constructs
    the prompt payload. The caller decides whether to actually send it.

    Args:
        resonance_result: Output from compute_resonance().
        capital_result: Output from compute_full_portfolio(), or None.
        ticker: The target ticker symbol.
        account_state: Raw account state dict (from account_state.json)
            for additional context.

    Returns:
        Dict with 'system_prompt' and 'user_prompt' keys.
    """
    # Build the dimension summary
    dim_summary = _build_dimension_summary(resonance_result)
    cap_summary = _build_capital_summary(capital_result)

    # Account state summary
    acct_lines: list[str] = ["=== Account State ==="]
    if account_state:
        acct_lines.append(f"  Cash: ${account_state.get('cash', 0):.2f}")
        acct_lines.append(
            f"  Buying Power: ${account_state.get('buying_power', 0):.2f}"
        )
        for pos in account_state.get("positions", []):
            acct_lines.append(
                f"  {pos.get('ticker', '?')}: {pos.get('shares', 0)} shares "
                f"@ ${pos.get('avg_cost', 0):.2f} avg "
                f"(current: ${pos.get('current_price', 0):.2f})"
            )
    else:
        acct_lines.append("  Not provided.")
    acct_summary = "\n".join(acct_lines)

    override_flag = resonance_result.get("override_available", False)

    # ===================================================================
    # SYSTEM PROMPT
    # ===================================================================
    system_prompt = f"""You are a Senior Portfolio Strategist operating within the SkillFoundry Four-Dimensional Resonance Framework. Your role is to synthesize the outputs of four independent analysis engines into a single, decisive action directive. You MUST produce a response that is rigorous, data-driven, and actionable.

## Core Directive
You are NOT a chatbot. You are an institutional-grade trading decision engine. Every word in your output must serve the single purpose of making or justifying a capital allocation decision for {ticker}.

## Input Data Integrity
You will receive:
  1. Four-Dimensional Resonance Scores (fundamental, technical, event_driven, sentiment)
  2. Capital Management Sizing (cash allocation, position limits, exit suggestions)
  3. Account State (cash balance, buying power, current holdings)

## Output Format Enforcement
You MUST respond with a single JSON object. NO markdown wrapping, NO code fences, NO explanatory text outside the JSON.

The JSON schema is:
{json.dumps(OUTPUT_SCHEMA_SPEC, indent=2)}

## Critical Constraints

1. **Override Protocol**: {"Override IS available (soft veto was triggered). You MAY override the soft veto if your deep analysis provides strong justification. If overriding, explain explicitly in deep_research.final_reasoning." if override_flag else "Override is NOT available. The resonance condition was met cleanly. Proceed with the signal as computed."}

2. **Deep Research Mandate**: The `deep_research` field must contain a MINIMUM of 1500 words across its subfields. This is NOT optional. Each subfield (macro_analysis, fundamental_deep_dive, technical_context, sentiment_landscape, event_risk_calendar, scenario_analysis, final_reasoning) must be substantive. Target: 300-500 words per subfield except scenario_analysis (min 450 words across three scenarios) and final_reasoning (min 500 words synthesis).

3. **Specificity Requirement**: Price targets must be specific numbers, not ranges like "somewhere between X and Y". If you are uncertain, state the single best estimate and explain the confidence interval separately.

4. **No Generic Language**: Avoid phrases like "may potentially" or "could possibly." State your conviction. Use "will," "is expected to," "the data indicates," or be explicit: "uncertainty is high because..."

5. **Position Management Precision**: If an exit suggestion is present, specify EXACTLY how many shares to sell at what price trigger. If a position adjustment is present, specify whether to average up, down, or maintain.

6. **Risk Quantification**: The risk_assessment section must include a specific stop-loss price level (not a percentage alone). The max_loss_scenario must quantify worst-case dollar loss.
"""

    # ===================================================================
    # USER PROMPT
    # ===================================================================
    user_prompt = f"""## Analysis Context for {ticker}

### Engine Outputs
{dim_summary}

### Capital Management
{cap_summary}

### Account State
{acct_summary}

### Instructions
Produce the JSON decision directive as specified in the system prompt. Your response will be parsed automatically and fed into downstream execution systems. Any deviation from the JSON schema will cause a parse failure.

Remember:
- {override_flag} = Override flag status (True means soft veto was triggered and you may override if justified)
- Deep research section must be 1500+ words total
- Price targets must be specific
- Risk assessment must include quantified stop-loss price level
- Action plan must contain at least 3 immediate steps and 2 contingency triggers

Begin your response now. Output ONLY valid JSON.
"""

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def format_pro_model_response(raw_response: str) -> dict[str, Any]:
    """Parse and validate the raw response from a Pro Model call.

    Strips any markdown code fences, then attempts JSON parse.

    Args:
        raw_response: The raw text returned by the LLM.

    Returns:
        Parsed dict if valid JSON, or error dict on parse failure.
    """
    cleaned = raw_response.strip()

    # Strip code fences if present
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": raw_response}

    return parsed