"""Decision generator: decision card + "no-trade" card synthesis."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from marketmind.pipeline.fragility_scanner import FragilityReport
    from marketmind.pipeline.cross_border_analyzer import CrossBorderFlowReport

logger = logging.getLogger("marketmind.pipeline.decision")

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.pipeline.red_team import RedTeamReport
from marketmind.pipeline.resonance import ResonanceResult


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
class SignalConflict:
    hypothesis: str
    signal_a: tuple[str, float]   # (source_module, value)
    signal_b: tuple[str, float]   # (source_module, value)
    divergence: float             # abs(signal_a - signal_b)
    description: str


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


# ── SHARP dynamic prompt assembly (P3-2a) ────────────────────────────────────

# Module-level cache: decompose once, reuse across calls. The cache is
# invalidated only by explicit calls to _refresh_decision_prompt().
_dynamic_prompt_cache: str | None = None
_cached_rule_count: int = 0


def _get_decision_prompt() -> str:
    """Return the decision system prompt assembled from active SHARP rules.

    On first call, decomposes the static DECISION_SYSTEM_PROMPT into
    auditable rules and reassembles only the active ones. Subsequent
    calls return the cached result for zero-overhead.

    Call _refresh_decision_prompt() to invalidate the cache after
    rule retirements or evolutions.
    """
    global _dynamic_prompt_cache, _cached_rule_count
    if _dynamic_prompt_cache is not None:
        return _dynamic_prompt_cache

    from marketmind.pipeline.methodology_rules import RuleDecomposer

    rules = RuleDecomposer.decompose(DECISION_SYSTEM_PROMPT)
    active_rules = [r for r in rules if r.status == "active"]
    _cached_rule_count = len(active_rules)
    _dynamic_prompt_cache = RuleDecomposer.assemble(active_rules)
    logger.debug(
        "SHARP: assembled decision prompt from %d active rules "
        "(out of %d decomposed)",
        _cached_rule_count, len(rules),
    )
    return _dynamic_prompt_cache


def _refresh_decision_prompt() -> str:
    """Invalidate the SHARP prompt cache and rebuild from current rules.

    Call after rule retirements or evolutions (P3-2b) to ensure the
    decision prompt reflects the latest rule state.
    """
    global _dynamic_prompt_cache
    _dynamic_prompt_cache = None
    return _get_decision_prompt()


async def generate_decision(
    l1: Layer1Result,
    l2: Layer2Result,
    l3: Layer3BatchResult,
    red_team: RedTeamReport,
    resonance: ResonanceResult,
    hypotheses: list | None = None,
    fragility_report: "FragilityReport | None" = None,
    cross_border_report: "CrossBorderFlowReport | None" = None,
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
    user_prompt = _build_decision_prompt(l1, l2, l3, red_team, resonance, hypotheses, fragility_report, cross_border_report)
    try:
        result = await chat_pro(
            system_prompt=_get_decision_prompt(),
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
    hypotheses: list | None = None,
    fragility_report=None,
    cross_border_report=None,
) -> str:
    green = [r.ticker for r in l3.green_lights]
    challenges_str = "\n".join(f"- [{c.severity}] {c.challenge}" for c in red_team.challenges[:5])

    hypothesis_summary = _build_hypothesis_summary(hypotheses) if hypotheses else ""

    conflict_summary = ""
    if hypotheses:
        conflicts = _detect_signal_conflicts(hypotheses)
        if conflicts:
            conflict_text = "\n".join(c.description for c in conflicts)
            conflict_summary = (
                f"\n## ⚠️ 信号冲突 (ANALYST_DISAGREEMENT)\n{conflict_text}\n"
                f"请在你的决策中处理这些冲突——不要忽略或平均化，作出判断。\n"
            )

    fragility_section = ""
    if fragility_report is not None:
        fscore = getattr(fragility_report, 'overall_fragility_score', 0.0)
        fsummary = getattr(fragility_report, 'summary', '')
        crossed = getattr(fragility_report, 'crossed', [])
        fragility_section = f"\n## Systemic Fragility Scan\nScore: {fscore:.2f} | {fsummary}\n"
        if crossed:
            fragility_section += "CRITICAL CROSSED THRESHOLDS:\n"
            for a in crossed[:5]:
                t = getattr(a, 'threshold', None)
                name = getattr(t, 'name_zh', 'unknown') if t else 'unknown'
                cur = getattr(a, 'current_value', 'N/A')
                fragility_section += f"- [{getattr(a, 'severity', 'WARN')}] {name}: current={cur}\n"

    cross_border_section = ""
    if cross_border_report is not None:
        quality = getattr(cross_border_report, 'data_quality', 'UNAVAILABLE')
        summary = getattr(cross_border_report, 'summary', '')
        cross_border_section = f"\n## Cross-Border Flow Analysis (Quality: {quality})\n{summary}\n"
        ccb_alerts = getattr(cross_border_report, 'ccb_alerts', [])
        if ccb_alerts:
            cross_border_section += "CCB Alerts: " + "; ".join(str(a) for a in ccb_alerts[:3]) + "\n"
        unusual = getattr(cross_border_report, 'unusual_patterns', [])
        if unusual:
            cross_border_section += "Unusual Patterns: " + "; ".join(str(p) for p in unusual[:3]) + "\n"

    return f"""{hypothesis_summary}{conflict_summary}{fragility_section}{cross_border_section}## Signal Resonance
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


def _detect_signal_conflicts(hypotheses: list) -> list[SignalConflict]:
    """Find where independent analysis modules disagree on the same hypothesis.

    Checks for:
    - causal.net_directional_force vs flow.flow_imbalance divergence > 0.4
    - scenario confidence vs fragility overall_score divergence
    - regime consensus direction vs scenario expected return direction

    Conflicts are NOT auto-resolved — they're flagged as ANALYST_DISAGREEMENT
    for the user to review in decision cards.
    """
    conflicts = []
    for h in hypotheses:
        if not h:
            continue

        causal = getattr(h, 'causal', None)
        flow = getattr(h, 'flow', None)
        scenario_tree = getattr(h, 'scenario_tree', None)

        if causal and flow:
            c_force = causal.net_directional_force
            f_imbalance = flow.flow_imbalance
            div = abs(c_force - f_imbalance)
            if div > 0.4:
                conflicts.append(SignalConflict(
                    hypothesis=getattr(h, 'refined_hypothesis', '')[:80],
                    signal_a=("causal_decomposition", c_force),
                    signal_b=("flow_decomposition", f_imbalance),
                    divergence=div,
                    description=f"因果分解({c_force:+.2f})与资金流({f_imbalance:+.2f})分歧度{div:.2f}"
                ))

        fragility_score = getattr(h, 'fragility_score', None)
        if scenario_tree and fragility_score is not None:
            sc_conf = scenario_tree.base_case.confidence
            if abs(sc_conf - (1 - fragility_score)) > 0.4:
                conflicts.append(SignalConflict(
                    hypothesis=getattr(h, 'refined_hypothesis', '')[:80],
                    signal_a=("scenario_forecaster", sc_conf),
                    signal_b=("fragility_scanner", 1 - fragility_score),
                    divergence=abs(sc_conf - (1 - fragility_score)),
                    description=f"情景预测置信({sc_conf:.2f})与脆弱性({fragility_score:.2f})不一致"
                ))

    return conflicts


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
