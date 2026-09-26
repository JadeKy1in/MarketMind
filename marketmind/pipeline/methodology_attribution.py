"""SHARP AttributionAgent — Flash LLM hypothesis generation for rule impact.

Produces AttributionHypothesis only. The walk-forward backtest gate is the
actual verdict. LLM is NOT the judge.
"""
from __future__ import annotations

import json
import logging
import re

from marketmind.pipeline.methodology_rules import MainAIRule, AttributionHypothesis

logger = logging.getLogger("marketmind.pipeline.methodology_attribution")

ATTRIBUTION_SYSTEM_PROMPT = """[SHARP ATTRIBUTION PROTOCOL]
You are a statistical hypothesis generator analyzing whether specific decision
rules contributed to a trading outcome. Your output is a HYPOTHESIS only —
it will be validated by a walk-forward backtest gate before any action is taken.

Output ONLY valid JSON with this exact structure:
{
  "suspected_impact": "positive|negative|neutral",
  "confidence": 0.0,
  "evidence_summary": "1-2 sentences explaining your reasoning"
}

IMPORTANT: Be conservative in confidence scores. Correlation is not causation.
You are NOT making a verdict — just forming a testable hypothesis."""


class AttributionAgent:
    """Analyze whether a specific rule contributed to a decision outcome.

    CRITICAL: This agent produces HYPOTHESIS only. The walk-forward backtest
    makes the final keep/retire decision. LLM is NOT the judge.
    """

    @staticmethod
    def _parse_single_hypothesis(
        response_text: str, rule_id: str
    ) -> AttributionHypothesis:
        """Parse a single-hypothesis Flash LLM response. Exposed for testing."""
        return _parse_single_hypothesis(response_text, rule_id)

    @staticmethod
    async def attribute(
        rule: MainAIRule,
        decision_context: dict,
        outcome: dict,
    ) -> AttributionHypothesis:
        """Use Flash LLM to form hypothesis about rule impact.

        Args:
            rule: The rule being evaluated.
            decision_context: Context at time of decision (signals, market state).
            outcome: Actual outcome (was decision correct, P&L, etc.).

        Returns:
            AttributionHypothesis with suspected_impact and confidence.
            This is INPUT to the backtest gate, not a verdict.
        """
        user_prompt = _build_attribution_user_prompt(rule, decision_context, outcome)

        try:
            from marketmind.gateway.async_client import chat_flash

            result = await chat_flash(
                system_prompt=ATTRIBUTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=1024,
            )
            return _parse_single_hypothesis(
                result.get("content", "{}"), rule.rule_id
            )
        except Exception as e:
            logger.warning(
                "AttributionAgent Flash call failed for rule %s: %s",
                rule.rule_id, e,
            )
            return AttributionHypothesis(
                rule_id=rule.rule_id,
                suspected_impact="neutral",
                confidence=0.0,
                evidence_summary=f"Flash LLM attribution failed: {e}",
            )


def _build_attribution_user_prompt(
    rule: MainAIRule,
    decision_context: dict,
    outcome: dict,
) -> str:
    """Build the Flash LLM prompt for single-rule attribution."""
    ctx_lines = [f"  {k}: {v}" for k, v in decision_context.items()]
    out_lines = [f"  {k}: {v}" for k, v in outcome.items()]

    return f"""Rule under evaluation:
  ID: {rule.rule_id}
  Category: {rule.category}
  Text: {rule.rule_text}

Decision context:
{chr(10).join(ctx_lines) if ctx_lines else '  (no context provided)'}

Outcome:
{chr(10).join(out_lines) if out_lines else '  (no outcome provided)'}

Based on the above, generate a hypothesis about whether this rule had positive,
negative, or neutral impact on the decision outcome."""


def _parse_single_hypothesis(
    response_text: str, rule_id: str
) -> AttributionHypothesis:
    """Parse a single-hypothesis Flash LLM response."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        data = None

    if not isinstance(data, dict):
        match = re.search(r'\{[\s\S]*\}', response_text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return AttributionHypothesis(
                    rule_id=rule_id,
                    suspected_impact="neutral",
                    confidence=0.0,
                    evidence_summary="Failed to parse attribution response",
                )
        else:
            return AttributionHypothesis(
                rule_id=rule_id,
                suspected_impact="neutral",
                confidence=0.0,
                evidence_summary="Failed to parse attribution response",
            )

    return AttributionHypothesis(
        rule_id=rule_id,
        suspected_impact=data.get("suspected_impact", "neutral"),
        confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
        evidence_summary=data.get("evidence_summary", ""),
    )
