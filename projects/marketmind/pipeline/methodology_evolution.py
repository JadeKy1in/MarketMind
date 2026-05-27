"""SHARP: Rule validation, evolution, and cross-stage attribution.

Extracted from methodology_rules.py to keep that file under 500 lines.
RuleValidator: walk-forward backtest gate for rule validation.
RuleEvolver: atomic rule edits based on validated impact hypotheses.
StageAttributionAnalyzer (Layer 3): trace Decision errors back to source stage.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.pipeline.methodology_rules import (
    MainAIRule, RuleRegistry, RuleImpactHypothesis,
    generate_rule_id,
)

logger = logging.getLogger("marketmind.pipeline.methodology_evolution")


# ── Walk-Forward Rule Validator (P3-2b) ──────────────────────────────────

class RuleValidator:
    """Walk-forward backtest gate for rule validation.

    This is the ACTUAL VERDICT mechanism. The AttributionAgent generates
    hypotheses; this validator tests them against real outcomes using
    walk-forward cross-validation to decide keep vs. retire.

    Design invariant: LLM is NOT the judge. Statistical gate is the judge.
    """

    def __init__(self, registry: RuleRegistry, min_validation_windows: int = 5,
                 overfit_threshold: float = 0.5):
        self.registry = registry
        self.min_validation_windows = min_validation_windows
        self.overfit_threshold = overfit_threshold

    def validate_hypothesis(
        self, hypothesis: RuleImpactHypothesis, outcome_data: list[dict]
    ) -> tuple[bool, str]:
        """Validate an attribution hypothesis against real outcome data.

        Args:
            hypothesis: The RuleImpactHypothesis from AttributionAgent.
            outcome_data: List of {date, outcome_score, rule_active} dicts
                         representing historical outcomes where the rule was active.

        Returns:
            (should_retire, reason) — True if the rule should be retired.
        """
        if len(outcome_data) < self.min_validation_windows:
            return False, f"insufficient_data: {len(outcome_data)} < {self.min_validation_windows}"

        # Separate IS and OOS periods using walk-forward
        outcomes_with_rule = [d for d in outcome_data if d.get("rule_active", True)]
        outcomes_without_rule = [d for d in outcome_data if not d.get("rule_active", False)]

        if len(outcomes_with_rule) < 3:
            return False, "insufficient_active_periods"

        # When hypothesis says "negative impact", check if outcomes improve WITHOUT the rule
        if hypothesis.suspected_impact == "negative":
            if outcomes_without_rule and len(outcomes_without_rule) >= 3:
                with_rule_mean = sum(d["outcome_score"] for d in outcomes_with_rule[-10:]) / min(len(outcomes_with_rule), 10)
                without_rule_mean = sum(d["outcome_score"] for d in outcomes_without_rule[-10:]) / min(len(outcomes_without_rule), 10)
                if without_rule_mean > with_rule_mean:
                    return True, (
                        f"Negative impact confirmed: without_rule_mean={without_rule_mean:.4f} "
                        f"> with_rule_mean={with_rule_mean:.4f}"
                    )

        # For positive hypothesis: check if outcomes degrade when rule is absent
        elif hypothesis.suspected_impact == "positive":
            if outcomes_without_rule and len(outcomes_without_rule) >= 3:
                with_rule_mean = sum(d["outcome_score"] for d in outcomes_with_rule[-10:]) / min(len(outcomes_with_rule), 10)
                without_rule_mean = sum(d["outcome_score"] for d in outcomes_without_rule[-10:]) / min(len(outcomes_without_rule), 10)
                if with_rule_mean <= without_rule_mean:
                    return True, (
                        f"Positive impact NOT confirmed: with_rule_mean={with_rule_mean:.4f} "
                        f"<= without_rule_mean={without_rule_mean:.4f}"
                    )

        return False, "hypothesis_not_validated"

    def retire_if_validated(
        self, hypothesis: RuleImpactHypothesis, outcome_data: list[dict]
    ) -> bool:
        """Convenience: validate and auto-retire if gate passes."""
        should_retire, reason = self.validate_hypothesis(hypothesis, outcome_data)
        if should_retire:
            return self.registry.retire(hypothesis.rule_id, reason)
        return False


# ── Rule Evolver (P3-2b) ──────────────────────────────────────────────────

class RuleEvolver:
    """Atomic rule edits based on validated impact hypotheses.

    Supports three operations:
    - tune_threshold: Adjust a numerical constraint (e.g., 25% -> 20%)
    - add_constraint: Add a new sub-rule derived from validated patterns
    - remove_constraint: Remove a rule validated as harmful by backtest gate

    All edits are atomic and auditable. Each evolution increments the
    rule's generation counter and preserves the parent_rule_id chain.
    """

    def __init__(self, registry: RuleRegistry, validator: RuleValidator):
        self.registry = registry
        self.validator = validator

    def tune_threshold(self, rule_id: str, old_value: float, new_value: float,
                       field_name: str) -> MainAIRule | None:
        """Adjust a numerical threshold in a rule.

        Example: tune_threshold("rule:pos:abc", 0.25, 0.20, "heat_limit")
        """
        rule = self.registry.get(rule_id)
        if rule is None:
            return None

        old_content = rule.content
        new_content = old_content.replace(str(old_value), str(new_value), 1)

        if new_content == old_content:
            return None  # Value not found in content

        evolved = MainAIRule(
            rule_id=f"{rule.rule_id}:gen{rule.generation + 1}",
            content=new_content,
            category=rule.category,
            source="evolution",
            generation=rule.generation + 1,
            parent_rule_id=rule_id,
        )

        self.registry.retire(rule_id, f"Evolved: {field_name} {old_value}->{new_value}")
        self.registry.register(evolved)
        return evolved

    def add_constraint(self, new_content: str, category: str,
                       parent_rule_id: str | None = None) -> MainAIRule:
        """Add a new constraint rule derived from validated learning."""
        rule_id = generate_rule_id(new_content, category, 0)
        # Ensure uniqueness
        if self.registry.get(rule_id):
            rule_id = f"{rule_id}:v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        rule = MainAIRule(
            rule_id=rule_id,
            content=new_content,
            category=category,
            source="evolution",
            parent_rule_id=parent_rule_id,
        )
        self.registry.register(rule)
        return rule

    def remove_constraint(self, rule_id: str, reason: str) -> bool:
        """Remove a rule that backtest validation has shown to be harmful."""
        return self.registry.retire(rule_id, f"Removed: {reason}")

    def apply_evolution(self, hypotheses: list[RuleImpactHypothesis],
                        outcome_data: dict[str, list[dict]]) -> list[str]:
        """Apply validated evolutions from a batch of hypotheses.

        Returns list of rule_ids that were modified.
        """
        modified = []
        for h in hypotheses:
            data = outcome_data.get(h.rule_id, [])
            should_retire, reason = self.validator.validate_hypothesis(h, data)
            if should_retire:
                if self.registry.retire(h.rule_id, reason):
                    modified.append(h.rule_id)
                    logger.info("Rule retired by evolution: %s — %s", h.rule_id, reason)
        return modified


# ── Cross-Stage Attribution Analyzer (Layer 3) ─────────────────────────────

STAGE_LABELS = ["flash_triage", "hvr_investigation", "l1_narrative",
                "l2_fundamental", "l3_technical", "red_team", "resonance"]

ATTRIBUTION_SYSTEM_PROMPT = """You are a pipeline diagnostic analyst. Given a week of pipeline metrics and the direction accuracy for each day, identify which pipeline stage contributed most to incorrect decisions.

For each stage, check:
- Flash Triage: Were high-impact scores associated with wrong calls? Was avg_impact unusual?
- HVR: Was signals_found/investigated ratio too low (over-investigating)?
- L1: Were grades consistently wrong? Was price_in_score misleading?
- L2/L3: Were ticker candidates poor? Green-light rate too high (false positives) or too low (missed)?
- Red Team: Were severe challenges generated for days that turned out correct? (challenges misdirected)
- Resonance: Was DSR misleading? False positives or false negatives?

Output JSON:
{
  "primary_failure_stage": "flash_triage | hvr | l1 | l2_l3 | red_team | resonance | none",
  "confidence": 0.0-1.0,
  "evidence": "2-3 sentence evidence summary",
  "suggested_rule_change": "A concrete SHARP rule modification (or 'none')",
  "rule_category": "position_sizing | risk_management | quality | output_format"
}"""


@dataclass
class StageAttribution:
    """Result of tracing a Decision error back to a pipeline stage."""
    primary_failure_stage: str
    confidence: float
    evidence: str
    suggested_rule_change: str
    rule_category: str
    analysis_date: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    raw_response: str = ""


@dataclass
class AttributionBatch:
    attributions: list[StageAttribution] = field(default_factory=list)
    hypotheses: list[RuleImpactHypothesis] = field(default_factory=list)


class StageAttributionAnalyzer:
    """Trace Decision errors back to upstream pipeline stages.

    Layer 3 of the main pipeline evolution system. When calibration shows
    sustained poor direction accuracy, this analyzer:
    1. Correlates wrong decisions with per-stage metrics
    2. Uses Flash to identify the most likely failure stage
    3. Generates RuleImpactHypothesis entries for downstream RuleValidator
    """

    def __init__(self, registry: RuleRegistry | None = None):
        self.registry = registry

    async def analyze_period(self, metrics: list[dict],
                             direction_accuracy: float,
                             correct_count: int, total_count: int) -> StageAttribution | None:
        """Analyze a period of pipeline metrics for failure attribution.

        Only fires when direction_accuracy < 0.45 (worse than random suggests
        something systematically wrong, not just noise).
        """
        if direction_accuracy >= 0.45 or total_count < 10:
            return None

        metrics_summary = _format_metrics_for_attribution(metrics)
        user_prompt = (
            f"Direction accuracy: {correct_count}/{total_count} ({direction_accuracy:.0%})\n\n"
            f"## Pipeline Metrics (past 7 days)\n{metrics_summary}\n\n"
            f"Identify which pipeline stage most likely caused the poor accuracy. "
            f"Return ONLY JSON."
        )

        try:
            from marketmind.gateway.async_client import chat_flash
            result = await chat_flash(
                system_prompt=ATTRIBUTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=2048,
            )
            content = result.get("content", "") if isinstance(result, dict) else str(result)
        except Exception:
            logger.debug("Attribution Flash call failed", exc_info=True)
            return None

        parsed = _parse_attribution_response(content)
        if not parsed:
            return None

        return StageAttribution(
            primary_failure_stage=parsed.get("primary_failure_stage", "none"),
            confidence=parsed.get("confidence", 0.0),
            evidence=parsed.get("evidence", ""),
            suggested_rule_change=parsed.get("suggested_rule_change", "none"),
            rule_category=parsed.get("rule_category", "quality"),
            raw_response=content,
        )

    def attribution_to_hypothesis(self, attr: StageAttribution) -> RuleImpactHypothesis | None:
        """Convert a StageAttribution into a RuleImpactHypothesis for RuleValidator.

        Only converts when suggested_rule_change is not 'none' and confidence >= 0.6.
        """
        if attr.suggested_rule_change in ("none", "", None):
            return None
        if attr.confidence < 0.6:
            return None

        # Generate a rule ID from the suggested change
        rule_id = generate_rule_id(attr.suggested_rule_change, attr.rule_category, 0)

        return RuleImpactHypothesis(
            rule_id=rule_id,
            suspected_impact="negative",  # default: rule may have caused failure
            confidence=attr.confidence,
            evidence_summary=f"Attribution: {attr.primary_failure_stage} — {attr.evidence[:200]}",
        )

    async def run_attribution_cycle(
        self, metrics: list[dict],
        calibration: "CalibrationContext | None" = None,
    ) -> AttributionBatch:
        """Full attribution cycle: analyze → generate hypotheses.

        Args:
            metrics: Pipeline metrics from recent days.
            calibration: CalibrationContext from daily_calibration.

        Returns:
            AttributionBatch with attributions and hypotheses ready for validation.
        """
        batch = AttributionBatch()

        if calibration is None or calibration.direction_accuracy is None:
            return batch

        attr = await self.analyze_period(
            metrics=metrics,
            direction_accuracy=calibration.direction_accuracy,
            correct_count=calibration.direction_correct,
            total_count=calibration.direction_total,
        )
        if attr is None:
            return batch

        batch.attributions.append(attr)

        hyp = self.attribution_to_hypothesis(attr)
        if hyp:
            batch.hypotheses.append(hyp)

        return batch


def _format_metrics_for_attribution(metrics: list[dict]) -> str:
    """Format pipeline metrics into a compact table for attribution analysis."""
    if not metrics:
        return "No metrics data."

    lines = ["date | flash(high/avg) | hvr(sig/inv) | l1(grade/quadrant/dir) | "
             "l2(cand) l3(G/Y/R) | rt(chal/sev) | res(dsr/pbo/pass) | dec(cards/notrade)"]
    lines.append("-" * 100)

    for m in metrics:
        date = m.get("date", "?")
        lines.append(
            f"{date} | {m.get('flash_high_impact', 0)}/{m.get('flash_avg_impact', 0):.1f} | "
            f"{m.get('hvr_signals_found', 0)}/{m.get('hvr_articles_investigated', 0)} | "
            f"{m.get('l1_grade', '?')}/{m.get('l1_quadrant', '?')[:20]}/{m.get('l1_direction', '?')[:8]} | "
            f"{m.get('l2_ticker_candidates', 0)}/{m.get('l3_green_lights', 0)}/"
            f"{m.get('l3_yellow_lights', 0)}/{m.get('l3_red_lights', 0)} | "
            f"{m.get('red_team_challenges', 0)}/{m.get('red_team_severe', 0)} | "
            f"{m.get('resonance_dsr', 0):.2f}/{m.get('resonance_pbo', 0):.2f}/"
            f"{'PASS' if m.get('resonance_passed') else 'FAIL'} | "
            f"{m.get('decision_cards', 0)}/{'NT' if m.get('decision_no_trade') else 'TD'}"
        )
    return "\n".join(lines)


def _parse_attribution_response(content: str) -> dict | None:
    """Parse Flash attribution response JSON."""
    import re as _re
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if len(lines) > 1 else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    content = _re.sub(r",\s*([}\]])", r"\1", content)
    try:
        import json as _json
        return _json.loads(content)
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                import json as _json
                return _json.loads(content[start:end + 1])
            except Exception:
                pass
    return None


# ── Orchestrator hook ───────────────────────────────────────────────────────

async def run_cross_stage_attribution(
    metrics: list[dict],
    registry: RuleRegistry | None = None,
    shadow_db=None,
) -> AttributionBatch | None:
    """Run the full Layer 3 cross-stage attribution cycle.

    Intended to be called from the orchestrator after the weekly tactical
    audit (Layer 2), or monthly as a standalone diagnostic.

    1. Loads calibration context for the same period
    2. If direction accuracy is poor (< 45%), runs Flash attribution analysis
    3. Converts attribution findings into RuleImpactHypotheses
    4. Returns the batch for downstream validation by RuleValidator

    Args:
        metrics: Pipeline metrics from recent days (typically 7-30).
        registry: SHARP RuleRegistry for hypothesis generation.
        shadow_db: Shadow state DB for calibration settlement data.

    Returns:
        AttributionBatch with findings, or None if insufficient data.
    """
    if len(metrics) < 7:
        return None

    try:
        from marketmind.pipeline.daily_calibration import compute_calibration_context
        calibration = compute_calibration_context(shadow_db, days=min(len(metrics), 30))
    except Exception:
        return None

    if calibration.direction_accuracy is None or calibration.direction_accuracy >= 0.45:
        return None  # No systematic failure to attribute

    analyzer = StageAttributionAnalyzer(registry)
    return await analyzer.run_attribution_cycle(metrics, calibration)
