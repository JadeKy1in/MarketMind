"""Decision generator: decision card + "no-trade" card synthesis."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("marketmind.pipeline.decision")
from dataclasses import dataclass, field
from typing import Any

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.pipeline.red_team import RedTeamReport
from marketmind.pipeline.resonance import ResonanceResult
from marketmind.shadows.shadow_agent import ShadowVote


@dataclass
class DecisionCard:
    ticker: str
    direction: str                # long | short
    position_size_pct: float      # % of portfolio
    entry_low: float
    entry_high: float
    stop_loss: float
    target_price: float
    max_hold_days: int
    reward_risk_ratio: float
    thesis: str                   # 1-sentence investment thesis
    risk_statement: str           # 1-sentence risk declaration
    red_team_note: str            # most important objection
    cash_reframing: str           # "if I had cash today, would I buy this?"


@dataclass
class NoTradeCard:
    thesis: str                   # why NOT trading is the best action
    supporting_evidence: list[str]
    counterfactual: str           # what would make us trade today instead
    structural_advantages: list[str]  # why no-trade has an edge (esp. in bear/high-VIX)


@dataclass
class DecisionOutput:
    decision_cards: list[DecisionCard] = field(default_factory=list)
    no_trade_card: NoTradeCard | None = None
    summary: str = ""


DECISION_SYSTEM_PROMPT = """You are a decision synthesis engine. Your job is to produce the final decision cards that a human investor will review.

You receive:
- Layer 1 narrative analysis
- Layer 2 fundamental analysis with ticker candidates
- Layer 3 technical review (green/yellow/red lights)
- Red Team challenges
- Signal resonance verdict

Output JSON:
{
  "decision_cards": [
    {
      "ticker": "TICKER",
      "direction": "long|short",
      "position_size_pct": 0.0,
      "entry_low": 0.0,
      "entry_high": 0.0,
      "stop_loss": 0.0,
      "target_price": 0.0,
      "max_hold_days": 30,
      "reward_risk_ratio": 0.0,
      "thesis": "1-sentence thesis",
      "risk_statement": "1-sentence risk",
      "red_team_note": "key objection",
      "cash_reframing": "if I had cash today..."
    }
  ],
  "no_trade_card": {
    "thesis": "why not trading is best",
    "supporting_evidence": ["reason1", "reason2"],
    "counterfactual": "what would make us trade",
    "structural_advantages": ["edge1", "edge2"]
  },
  "summary": "1-paragraph overall assessment"
}

IMPORTANT: The no-trade card must be equally rigorous as the decision cards — not an afterthought. In high-VIX environments, the no-trade card has structural advantages (lower bar to "win").
Position size: never exceed 25% total heat limit. Combined stop-losses across all positions ≤ 25% total equity.
All prices must be verifiable. Never fabricate."""


async def generate_decision(
    l1: Layer1Result,
    l2: Layer2Result,
    l3: Layer3BatchResult,
    red_team: RedTeamReport,
    resonance: ResonanceResult,
    shadow_votes: dict[str, list[ShadowVote]] | None = None,
    # ^^^ DEPRECATED in decision pipeline (2026-05-17).
    #     shadow_votes is always None at app.py:110 by design.
    #     Shadows are an internal competition ecosystem for ranking/evolution/
    #     crystallization — they do NOT vote on investment decisions.
    #     The parameter is preserved only for backward compatibility with
    #     any hypothetical manual invocation that might pass votes directly.
    hypotheses: list | None = None,
) -> DecisionOutput:
    """Generate final decision cards and no-trade card."""
    if not resonance.passed and not l3.green_lights:
        return DecisionOutput(
            no_trade_card=NoTradeCard(
                thesis="No signal passed statistical validation and no ticker cleared technical review.",
                supporting_evidence=[f"DSR={resonance.dsr}, PBO={resonance.pbo}"],
                counterfactual="A signal exceeding DSR > 0 and PBO <= 0.10 with at least 1 green-light ticker.",
                structural_advantages=["Statistical discipline prevents overfitting", "Cash preserves optionality"],
            ),
            summary="No actionable signal today. Cash is a valid position."
        )
    user_prompt = _build_decision_prompt(l1, l2, l3, red_team, resonance, shadow_votes, hypotheses)
    try:
        result = await chat_pro(
            system_prompt=DECISION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )
        return _parse_decision_response(result["content"])
    except Exception as e:
        logger.warning("Decision generation failed: %s", e)
        return DecisionOutput(summary="Decision synthesis failed")


def _build_decision_prompt(
    l1: Layer1Result, l2: Layer2Result, l3: Layer3BatchResult,
    red_team: RedTeamReport, resonance: ResonanceResult,
    shadow_votes: dict | None = None,
    hypotheses: list | None = None,
) -> str:
    green = [r.ticker for r in l3.green_lights]
    challenges_str = "\n".join(f"- [{c.severity}] {c.challenge}" for c in red_team.challenges[:5])

    shadow_consensus_str = ""
    # NOTE: This block is never reached in the live daily pipeline
    # because app.py:110 sets shadow_votes = None by design.
    # Preserved for hypothetical manual invocation or future use.
    if shadow_votes:
        lines = ["## Shadow Ecosystem Consensus"]
        for ticker, votes in shadow_votes.items():
            if not votes:
                continue
            directions = {}
            for v in votes:
                if v.direction != "abstain":
                    directions[v.direction] = directions.get(v.direction, 0) + 1
            total = sum(directions.values())
            if total > 0:
                parts = [f"{d}: {c}/{total}" for d, c in
                         sorted(directions.items(), key=lambda x: -x[1])]
                lines.append(f"{ticker}: {', '.join(parts)}")
        if len(lines) > 1:
            lines.append("Note: Shadows are independent agents. Consensus is informational, not directive.")
            shadow_consensus_str = "\n".join(lines) + "\n\n"

    hypothesis_summary = _build_hypothesis_summary(hypotheses) if hypotheses else ""

    return f"""{shadow_consensus_str}{hypothesis_summary}## Signal Resonance
Verdict: {resonance.verdict} | DSR: {resonance.dsr} | PBO: {resonance.pbo}

## Layer 1 Narrative
Quadrant: {l1.matrix_quadrant} | Sentiment: {l1.sentiment_direction} | Price-in: {l1.price_in_score}

## Layer 2 Fundamentals
Tickers: {', '.join(l2.ticker_candidates[:10])}

## Layer 3 Technical (GREEN lights only)
{', '.join(green) if green else 'None — no ticker passed L3'}

## Red Team Challenges
{challenges_str if challenges_str else 'No challenges raised'}

Produce decision cards for GREEN-light tickers only. Generate a parallel no-trade card with equal rigor."""


def _build_hypothesis_summary(hypotheses: list) -> str:
    """Format HVR investigation results as a pre-analysis summary for the decision prompt.

    Extracts: ACTIONABLE direction/confidence/core_logic/risk, HIGH_CONTENTION risks,
    and the top hypothesis's 4-layer verification summary.
    """
    actionable = [h for h in hypotheses if getattr(h, 'verdict', '') == 'ACTIONABLE']
    high_contention = [h for h in hypotheses if getattr(h, 'verdict', '') == 'HIGH_CONTENTION']

    lines = ["## Pre-Analysis: HVR Investigation Results\n"]

    if actionable:
        lines.append(f"### ACTIONABLE Hypotheses ({len(actionable)})\n")
        for i, h in enumerate(actionable[:5]):
            direction = getattr(h, 'direction', '') or 'N/A'
            confidence = getattr(h, 'confidence', 0)
            core_logic = getattr(h, 'core_logic', '') or getattr(h, 'hypothesis', '')[:120]
            risk_level = getattr(h, 'risk_level', '') or 'N/A'
            time_window = getattr(h, 'time_window', '') or 'N/A'
            bear_case = (getattr(h, 'bear_case', '') or '')[:150]
            lines.append(f"H{i + 1}. [{direction}] (confidence={confidence:.0%}, risk={risk_level}, window={time_window})")
            lines.append(f"   Thesis: {core_logic}")
            if bear_case:
                lines.append(f"   Bear Case: {bear_case}")
            lines.append("")

        # 4-layer verification summary from top hypothesis
        top = actionable[0]
        if any(getattr(top, f'layer_{n}_narrative', '') for n in range(1, 5)):
            lines.append("#### Top Hypothesis 4-Layer Verification")
            for layer_num in range(1, 5):
                narrative = getattr(top, f'layer_{layer_num}_narrative', '') or ''
                if narrative:
                    lines.append(f"  L{layer_num}: {narrative[:200]}")
            lines.append("")

    if high_contention:
        lines.append(f"### HIGH_CONTENTION Risks ({len(high_contention)})\n")
        for i, h in enumerate(high_contention[:3]):
            hypothesis = getattr(h, 'hypothesis', '')[:120]
            bear_case = (getattr(h, 'bear_case', '') or '')[:120]
            lines.append(f"C{i + 1}. {hypothesis}")
            if bear_case:
                lines.append(f"   Counter: {bear_case}")
            lines.append("")
        lines.append("Note: HIGH_CONTENTION means bears and bulls are both credible. Factor this uncertainty into position sizing.\n")

    monitor_count = sum(1 for h in hypotheses if getattr(h, 'verdict', '') == 'MONITOR')
    priced_in_count = sum(1 for h in hypotheses if getattr(h, 'verdict', '') == 'PRICED_IN')
    discarded = sum(1 for h in hypotheses if getattr(h, 'verdict', '') == 'DISCARD')
    if monitor_count or priced_in_count or discarded:
        parts = []
        if monitor_count:
            parts.append(f"{monitor_count} MONITOR")
        if priced_in_count:
            parts.append(f"{priced_in_count} PRICED_IN")
        if discarded:
            parts.append(f"{discarded} DISCARD")
        lines.append(f"Other: {', '.join(parts)} — see archive for details.\n")

    if not lines[1:]:
        return ""  # no hypotheses to summarize

    return "\n".join(lines) + "\n"


def _parse_decision_response(content: str) -> DecisionOutput:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return DecisionOutput(summary="Failed to parse decision output")
    cards = []
    for d in data.get("decision_cards", []):
        cards.append(DecisionCard(
            ticker=d.get("ticker", ""),
            direction=d.get("direction", "long"),
            position_size_pct=float(d.get("position_size_pct", 0)),
            entry_low=float(d.get("entry_low", 0)),
            entry_high=float(d.get("entry_high", 0)),
            stop_loss=float(d.get("stop_loss", 0)),
            target_price=float(d.get("target_price", 0)),
            max_hold_days=int(d.get("max_hold_days", 30)),
            reward_risk_ratio=float(d.get("reward_risk_ratio", 0)),
            thesis=d.get("thesis", ""),
            risk_statement=d.get("risk_statement", ""),
            red_team_note=d.get("red_team_note", ""),
            cash_reframing=d.get("cash_reframing", ""),
        ))
    ntc_data = data.get("no_trade_card", {})
    no_trade = None
    if ntc_data:
        no_trade = NoTradeCard(
            thesis=ntc_data.get("thesis", ""),
            supporting_evidence=ntc_data.get("supporting_evidence", []),
            counterfactual=ntc_data.get("counterfactual", ""),
            structural_advantages=ntc_data.get("structural_advantages", []),
        )
    return DecisionOutput(
        decision_cards=cards,
        no_trade_card=no_trade,
        summary=data.get("summary", ""),
    )
