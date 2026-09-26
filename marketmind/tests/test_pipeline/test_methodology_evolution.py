"""Tests for SHARP rule evolution — validation, atomic edits, dynamic assembly (P3-2b)."""
import pytest

from marketmind.pipeline.methodology_rules import (
    MainAIRule,
    RuleRegistry,
    RuleImpactHypothesis,
    assemble_dynamic_prompt,
)
from marketmind.pipeline.methodology_evolution import (
    RuleValidator,
    RuleEvolver,
    StageAttributionAnalyzer,
    StageAttribution,
    AttributionBatch,
    _format_metrics_for_attribution,
    _parse_attribution_response,
    run_cross_stage_attribution,
)


class TestRuleValidator:
    """Walk-forward validation gate for SHARP rules."""

    def test_insufficient_data_defers(self):
        """Too few outcome data points defers retirement."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=5)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-TEST01",
            suspected_impact="negative",
            confidence=0.7,
            evidence_summary="Test"
        )
        outcome_data = [
            {"date": "2024-01-01", "outcome_score": 0.8, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.7, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.9, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.6, "rule_active": True},
        ]
        should_retire, reason = validator.validate_hypothesis(hypothesis, outcome_data)
        assert not should_retire
        assert "insufficient_data" in reason

    def test_negative_impact_confirmed_retires(self):
        """When without-rule outcomes are better than with-rule, retire the rule."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=5)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-TEST02",
            suspected_impact="negative",
            confidence=0.8,
            evidence_summary="Bad rule"
        )
        outcome_data = [
            {"date": "2024-01-01", "outcome_score": 0.3, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.2, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.4, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.3, "rule_active": True},
            {"date": "2024-01-05", "outcome_score": 0.35, "rule_active": True},
            {"date": "2024-01-06", "outcome_score": 0.8, "rule_active": False},
            {"date": "2024-01-07", "outcome_score": 0.9, "rule_active": False},
            {"date": "2024-01-08", "outcome_score": 0.85, "rule_active": False},
        ]
        should_retire, reason = validator.validate_hypothesis(hypothesis, outcome_data)
        assert should_retire
        assert "Negative impact confirmed" in reason

    def test_positive_impact_confirmed_keeps(self):
        """When with-rule outcomes exceed without-rule, keep the rule."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=5)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-TEST03",
            suspected_impact="positive",
            confidence=0.8,
            evidence_summary="Good rule"
        )
        outcome_data = [
            {"date": "2024-01-01", "outcome_score": 0.8, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.9, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.85, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.7, "rule_active": True},
            {"date": "2024-01-05", "outcome_score": 0.75, "rule_active": True},
            {"date": "2024-01-06", "outcome_score": 0.3, "rule_active": False},
            {"date": "2024-01-07", "outcome_score": 0.4, "rule_active": False},
            {"date": "2024-01-08", "outcome_score": 0.35, "rule_active": False},
        ]
        should_retire, _ = validator.validate_hypothesis(hypothesis, outcome_data)
        assert not should_retire

    def test_wfe_degradation_retires(self):
        """Walk-forward degradation: declining with-rule scores signal retirement."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=5)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-TEST04",
            suspected_impact="negative",
            confidence=0.75,
            evidence_summary="Degraded"
        )
        outcome_data = [
            {"date": "2024-01-01", "outcome_score": 0.6, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.5, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.4, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.3, "rule_active": True},
            {"date": "2024-01-05", "outcome_score": 0.2, "rule_active": True},
            {"date": "2024-01-06", "outcome_score": 0.8, "rule_active": False},
            {"date": "2024-01-07", "outcome_score": 0.9, "rule_active": False},
            {"date": "2024-01-08", "outcome_score": 0.85, "rule_active": False},
        ]
        should_retire, _ = validator.validate_hypothesis(hypothesis, outcome_data)
        assert should_retire


class TestRuleEvolver:
    """Evolution engine with atomic edits."""

    def test_apply_evolution_retires_bad_rules(self):
        """Validated negative-impact hypothesis retires the rule."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-BAD01", content="Bad", category="risk")
        registry.register(rule)
        validator = RuleValidator(registry, min_validation_windows=5)
        evolver = RuleEvolver(registry, validator)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-BAD01",
            suspected_impact="negative",
            confidence=0.8,
            evidence_summary="Bad"
        )
        outcome_data = {"RRSK-BAD01": [
            {"date": "2024-01-01", "outcome_score": 0.3, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.2, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.4, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.5, "rule_active": True},
            {"date": "2024-01-05", "outcome_score": 0.35, "rule_active": True},
            {"date": "2024-01-06", "outcome_score": 0.8, "rule_active": False},
            {"date": "2024-01-07", "outcome_score": 0.9, "rule_active": False},
            {"date": "2024-01-08", "outcome_score": 0.85, "rule_active": False},
        ]}
        modified = evolver.apply_evolution([hypothesis], outcome_data)
        assert "RRSK-BAD01" in modified
        assert rule.status == "retired"

    def test_apply_evolution_keeps_good_rules(self):
        """Positive impact hypothesis that is confirmed keeps the rule active."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-GOOD01", content="Good", category="risk")
        registry.register(rule)
        validator = RuleValidator(registry, min_validation_windows=5)
        evolver = RuleEvolver(registry, validator)
        hypothesis = RuleImpactHypothesis(
            rule_id="RRSK-GOOD01",
            suspected_impact="positive",
            confidence=0.8,
            evidence_summary="Good"
        )
        outcome_data = {"RRSK-GOOD01": [
            {"date": "2024-01-01", "outcome_score": 0.8, "rule_active": True},
            {"date": "2024-01-02", "outcome_score": 0.9, "rule_active": True},
            {"date": "2024-01-03", "outcome_score": 0.85, "rule_active": True},
            {"date": "2024-01-04", "outcome_score": 0.7, "rule_active": True},
            {"date": "2024-01-05", "outcome_score": 0.75, "rule_active": True},
            {"date": "2024-01-06", "outcome_score": 0.3, "rule_active": False},
            {"date": "2024-01-07", "outcome_score": 0.4, "rule_active": False},
            {"date": "2024-01-08", "outcome_score": 0.35, "rule_active": False},
        ]}
        modified = evolver.apply_evolution([hypothesis], outcome_data)
        assert len(modified) == 0
        assert rule.status == "active"

    def test_tune_threshold(self):
        """Tune a numerical threshold: replace old value with new, retire old, create evolved rule."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-TUNE01", content="Max position size: 5.0% of portfolio",
                          category="risk")
        registry.register(rule)
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)
        result = evolver.tune_threshold("RRSK-TUNE01", 5.0, 7.0, "max_position")
        assert result is not None
        assert "7.0%" in result.content
        assert result.generation == 1
        assert result.parent_rule_id == "RRSK-TUNE01"
        assert rule.status == "retired"

    def test_add_constraint(self):
        """Add a new constraint rule derived from validated learning."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-ADD01", content="Always set a stop loss.",
                          category="risk")
        registry.register(rule)
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)
        result = evolver.add_constraint("Stop loss at 2% below entry", "risk",
                                        parent_rule_id="RRSK-ADD01")
        assert result is not None
        assert "2% below entry" in result.content
        assert result.parent_rule_id == "RRSK-ADD01"
        assert registry.get(result.rule_id) is not None

    def test_remove_constraint(self):
        """Remove a harmful rule from the registry."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-REM01", content="Remove me", category="risk")
        registry.register(rule)
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)
        result = evolver.remove_constraint("RRSK-REM01", "Test removal")
        assert result is True
        assert rule.status == "retired"
        assert "Removed: Test removal" in rule.retire_reason


class TestDynamicPromptAssembly:
    """Build decision prompt from active rules."""

    def test_assemble_excludes_retired(self):
        registry = RuleRegistry()
        registry.register(MainAIRule(rule_id="RRSK-ACT01", content="Active rule",
                                     category="risk_management"))
        registry.register(MainAIRule(rule_id="RRSK-RET01", content="Retired rule",
                                     category="risk_management", status="retired"))
        prompt = assemble_dynamic_prompt(registry)
        assert "Active rule" in prompt
        assert "Retired rule" not in prompt

    def test_assemble_category_order(self):
        registry = RuleRegistry()
        registry.register(MainAIRule(rule_id="RRIS-T01", content="Position first",
                                     category="position_sizing"))
        registry.register(MainAIRule(rule_id="RPRO-T01", content="Output last",
                                     category="output_format"))
        registry.register(MainAIRule(rule_id="RANA-T01", content="Quality middle",
                                     category="quality"))
        prompt = assemble_dynamic_prompt(registry)
        pos_pos = prompt.index("Position first")
        quality_pos = prompt.index("Quality middle")
        output_pos = prompt.index("Output last")
        assert pos_pos < quality_pos < output_pos

    def test_assemble_empty_registry(self):
        registry = RuleRegistry()
        prompt = assemble_dynamic_prompt(registry, "Default instructions")
        assert "Default instructions" in prompt


# ── Cross-stage attribution tests ─────────────────────────────────────────


class TestStageAttribution:
    def test_format_metrics_for_attribution(self):
        metrics = [
            {"date": "2026-05-20", "flash_high_impact": 5, "flash_avg_impact": 3.5,
             "hvr_signals_found": 2, "hvr_articles_investigated": 8,
             "l1_grade": "B", "l1_quadrant": "buy_cautious", "l1_direction": "bullish",
             "l2_ticker_candidates": 4, "l3_green_lights": 2, "l3_yellow_lights": 3,
             "l3_red_lights": 5, "red_team_challenges": 3, "red_team_severe": 1,
             "resonance_dsr": 0.70, "resonance_pbo": 0.05, "resonance_passed": True,
             "decision_cards": 2, "decision_no_trade": False},
        ]
        formatted = _format_metrics_for_attribution(metrics)
        assert "2026-05-20" in formatted
        assert "flash" in formatted.lower()

    def test_format_metrics_empty(self):
        assert "No metrics" in _format_metrics_for_attribution([])

    def test_parse_attribution_valid(self):
        content = '{"primary_failure_stage": "red_team", "confidence": 0.75, "evidence": "Challenges misdirected", "suggested_rule_change": "Require 2+ severe challenges before downgrading", "rule_category": "risk_management"}'
        parsed = _parse_attribution_response(content)
        assert parsed is not None
        assert parsed["primary_failure_stage"] == "red_team"
        assert parsed["confidence"] == 0.75

    def test_parse_attribution_invalid(self):
        assert _parse_attribution_response("not json") is None

    def test_attribution_to_hypothesis_converts(self):
        from marketmind.pipeline.methodology_rules import RuleImpactHypothesis
        analyzer = StageAttributionAnalyzer()
        attr = StageAttribution(
            primary_failure_stage="l1_narrative",
            confidence=0.80,
            evidence="L1 consistently over-graded events",
            suggested_rule_change="Cap event grade at B when price_in < 0.5",
            rule_category="quality",
        )
        hyp = analyzer.attribution_to_hypothesis(attr)
        assert hyp is not None
        assert hyp.suspected_impact == "negative"
        assert hyp.confidence == 0.80
        assert "grade" in hyp.evidence_summary.lower()

    def test_attribution_to_hypothesis_skips_none_suggestion(self):
        analyzer = StageAttributionAnalyzer()
        attr = StageAttribution(
            primary_failure_stage="none",
            confidence=0.70,
            evidence="No single stage at fault",
            suggested_rule_change="none",
            rule_category="quality",
        )
        hyp = analyzer.attribution_to_hypothesis(attr)
        assert hyp is None

    def test_attribution_to_hypothesis_skips_low_confidence(self):
        analyzer = StageAttributionAnalyzer()
        attr = StageAttribution(
            primary_failure_stage="flash_triage",
            confidence=0.40,
            evidence="Maybe flash",
            suggested_rule_change="Change threshold",
            rule_category="quality",
        )
        hyp = analyzer.attribution_to_hypothesis(attr)
        assert hyp is None

    @pytest.mark.asyncio
    async def test_analyzer_skips_high_accuracy(self):
        analyzer = StageAttributionAnalyzer()
        result = await analyzer.analyze_period([{"date": "x"}] * 10, 0.60, 18, 30)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyzer_skips_insufficient_samples(self):
        analyzer = StageAttributionAnalyzer()
        result = await analyzer.analyze_period([{"date": "x"}] * 3, 0.30, 3, 5)
        assert result is None


@pytest.mark.asyncio
async def test_run_cross_stage_attribution_insufficient_data():
    """Returns None when fewer than 7 days of metrics."""
    result = await run_cross_stage_attribution([{"date": "2026-05-20"}])
    assert result is None

