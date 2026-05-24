"""Decision generator: decision card + "no-trade" card synthesis."""
from __future__ import annotations
import json
import logging

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

logger = logging.getLogger("marketmind.pipeline.decision")
from dataclasses import dataclass, field
from typing import Any

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.pipeline.red_team import RedTeamReport
from marketmind.pipeline.resonance import ResonanceResult
from marketmind.shadows.shadow_agent import defang_text

# P3-2b: dynamic prompt assembly (replaces static DECISION_SYSTEM_PROMPT)
_rule_registry = None


@dataclass
class SignalConflict:
    """Detected signal conflict between two analytical dimensions."""
    signal_a: tuple[str, float]   # (source_name, value)
    signal_b: tuple[str, float]   # (source_name, value)
    divergence: float             # absolute difference
    description: str              # Chinese-language conflict description


def _detect_signal_conflicts(hypotheses: list) -> list[SignalConflict]:
    """Detect signal conflicts across analytical dimensions.

    Checks two conflict types:
    1. Causal net_directional_force vs Flow flow_imbalance (divergence > 0.4)
    2. Scenario base confidence vs Fragility score (divergence > 0.4)
    """
    conflicts: list[SignalConflict] = []
    for h in hypotheses:
        if h is None:
            continue

        # Check 1: causal vs flow divergence
        causal = getattr(h, 'causal', None)
        flow = getattr(h, 'flow', None)
        if causal is not None and flow is not None:
            c_force = getattr(causal, 'net_directional_force', 0) or 0
            f_imb = getattr(flow, 'flow_imbalance', 0) or 0
            divergence = abs(c_force - f_imb)
            if divergence > 0.4:
                conflicts.append(SignalConflict(
                    signal_a=("causal_decomposition", c_force),
                    signal_b=("flow_decomposition", f_imb),
                    divergence=divergence,
                    description=f"因果分解与资金流分解信号背离 (divergence={divergence:.2f})，"
                                f"因果分解方向力={c_force:.2f}，资金流失衡={f_imb:.2f}",
                ))

        # Check 2: scenario confidence vs fragility
        scenario = getattr(h, 'scenario_tree', None)
        fragility = getattr(h, 'fragility_score', None)
        if scenario is not None and fragility is not None:
            base = getattr(scenario, 'base_case', None)
            if base is not None:
                sc_conf = getattr(base, 'confidence', 0) or 0
                fg_score = 1.0 - fragility  # invert: high fragility = low confidence
                divergence = abs(sc_conf - fg_score)
                if divergence > 0.4:
                    conflicts.append(SignalConflict(
                        signal_a=("scenario_forecaster", sc_conf),
                        signal_b=("fragility_scanner", fg_score),
                        divergence=divergence,
                        description=f"情景预测置信度与脆弱性评分矛盾 (divergence={divergence:.2f})，"
                                    f"情景预测置信={sc_conf:.2f}，脆弱性调整={fg_score:.2f}",
                    ))
    return conflicts


def _get_decision_prompt() -> str:
    """Get the current decision system prompt, dynamically assembled from active rules."""
    global _rule_registry
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    yr = today[:4]
    date_note = (
        f"\n\n[TODAY: {today}. All trading decisions, entry/exit levels, stop-loss prices "
        f"must be based on CURRENT ({yr}) market conditions. "
        f"Do NOT reference {int(yr)-2}-{int(yr)-1} data as if it were recent.]"
    )
    try:
        from marketmind.pipeline.methodology_rules import (
            assemble_dynamic_prompt, get_default_rules
        )
        if _rule_registry is None:
            _rule_registry = get_default_rules()
        return assemble_dynamic_prompt(_rule_registry) + date_note
    except Exception:
        return DECISION_SYSTEM_PROMPT + date_note


def get_rule_registry():
    """Expose rule registry for SHARP evolution (P3-2b)."""
    global _rule_registry
    if _rule_registry is None:
        from marketmind.pipeline.methodology_rules import get_default_rules
        _rule_registry = get_default_rules()
    return _rule_registry


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
    pre_mortem: str = ""          # Phase B audit: 1-year failure narrative
    no_trade_score: float = 0.0   # Phase B audit: 0-100 strength of no-trade case


@dataclass
class DecisionOutput:
    decision_cards: list[DecisionCard] = field(default_factory=list)
    no_trade_card: NoTradeCard | None = None
    summary: str = ""
    contrarian_challenges: list[dict] = field(default_factory=list)


CONTRARIAN_PROMPT = """你是独立风控分析师。对以下投资决策方案提出2-3个具体的反对意见。
每个反对意见包含：风险描述、潜在损失幅度（百分比）、触发条件。
用中文。输出JSON: {"challenges": [{"risk": "...", "loss_pct": X.X, "trigger": "..."}]}
Output ONLY JSON."""


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
    "structural_advantages": ["edge1", "edge2"],
    "pre_mortem": "Assume 1 year later the traded position lost 50%. Write step-by-step what broke.",
    "no_trade_score": 0.0
  },
  "summary": "1-paragraph overall assessment"
}

IMPORTANT: The no-trade card must be equally rigorous as the decision cards — not an afterthought. Include a pre-mortem narrative (assume 1yr later, traded position lost 50% — what broke?). Score no-trade strength 0-100.
Position size: never exceed 25% total heat limit. Combined stop-losses across all positions ≤ 25% total equity.
All prices must be verifiable. Never fabricate."""


async def generate_contrarian_challenges(decision: DecisionOutput) -> list[dict]:
    """Run a contrarian LLM call challenging the decision thesis.

    Args:
        decision: The DecisionOutput from main synthesis (reads tickers,
                  directions, and theses from decision_cards).

    Returns:
        List of challenge dicts with keys: risk, loss_pct, trigger.
        Returns empty list on any failure (non-blocking).
    """
    if not decision.decision_cards:
        return []

    cards_text = "\n".join(
        f"- {c.ticker} ({c.direction}): {c.thesis[:200]}"
        for c in decision.decision_cards[:5]
    )
    user_prompt = f"待审查的投资方案:\n{cards_text}\n\n请提出2-3个具体的反对意见。"

    try:
        result = await chat_pro(
            system_prompt=CONTRARIAN_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=8192,
            reasoning_effort="minimal",
        )
        content = strip_markdown_fences(result.get("content", ""))
        data = json.loads(content)
        challenges = data.get("challenges", [])
        # Validate each challenge has required keys
        validated = []
        for ch in challenges:
            if isinstance(ch, dict) and "risk" in ch and "loss_pct" in ch and "trigger" in ch:
                validated.append({
                    "risk": str(ch["risk"]),
                    "loss_pct": float(ch["loss_pct"]),
                    "trigger": str(ch["trigger"]),
                })
        return validated
    except Exception:
        logger.warning("Contrarian challenge generation failed (non-blocking)", exc_info=True)
        return []


@monitor(source="decision", impact=ImpactScope.MAIN_PIPELINE)
async def generate_decision(
    l1: Layer1Result,
    l2: Layer2Result,
    l3: Layer3BatchResult,
    red_team: RedTeamReport,
    resonance: ResonanceResult,
) -> DecisionOutput:
    """Generate final decision cards and no-trade card."""
    if not resonance.passed and not l3.green_lights:
        return DecisionOutput(
            no_trade_card=NoTradeCard(
                thesis="No signal passed statistical validation and no ticker cleared technical review.",
                supporting_evidence=[f"DSR={resonance.dsr}, PBO={resonance.pbo}"],
                counterfactual="A signal exceeding DSR > 0 and PBO <= 0.10 with at least 1 green-light ticker.",
                structural_advantages=["Statistical discipline prevents overfitting", "Cash preserves optionality"],
                pre_mortem="",
                no_trade_score=100.0,
            ),
            summary="No actionable signal today. Cash is a valid position."
        )
    user_prompt = _build_decision_prompt(l1, l2, l3, red_team, resonance)
    try:
        # P3-2b: use dynamically assembled prompt from SHARP rule registry
        dynamic_prompt = _get_decision_prompt()
        result = await chat_pro(
            system_prompt=dynamic_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=16384,
        )
        decision = _parse_decision_response(result["content"])
        decision.contrarian_challenges = await generate_contrarian_challenges(decision)
        return decision
    except Exception as e:
        logger.warning("Decision generation failed: %s", e)
        return DecisionOutput(summary="Decision synthesis failed")


def _build_decision_prompt(
    l1: Layer1Result, l2: Layer2Result, l3: Layer3BatchResult,
    red_team: RedTeamReport, resonance: ResonanceResult,
) -> str:
    green = [r.ticker for r in l3.green_lights]
    challenges_str = "\n".join(
        f"- [{c.severity}] {defang_text(c.challenge)}" for c in red_team.challenges[:5]
    )

    defanged_tickers = [defang_text(t) for t in l2.ticker_candidates[:10]]

    return f"""## Signal Resonance
Verdict: {resonance.verdict} | DSR: {resonance.dsr} | PBO: {resonance.pbo}

## Layer 1 Narrative
Quadrant: {defang_text(l1.matrix_quadrant)} | Sentiment: {defang_text(l1.sentiment_direction)} | Price-in: {l1.price_in_score}

## Layer 2 Fundamentals
Tickers: {', '.join(defanged_tickers)}

## Layer 3 Technical (GREEN lights only)
{', '.join(green) if green else 'None — no ticker passed L3'}

## Red Team Challenges
{challenges_str if challenges_str else 'No challenges raised'}

Produce decision cards for GREEN-light tickers only. Generate a parallel no-trade card with equal rigor."""


def _parse_decision_response(content: str) -> DecisionOutput:
    content = strip_markdown_fences(content)
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
            pre_mortem=ntc_data.get("pre_mortem", ""),
            no_trade_score=float(ntc_data.get("no_trade_score", 0)),
        )
    return DecisionOutput(
        decision_cards=cards,
        no_trade_card=no_trade,
        summary=data.get("summary", ""),
    )
