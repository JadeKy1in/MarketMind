"""Tests for SHARP rule evolution — validation, atomic edits, dynamic assembly (P3-2b)."""
import pytest

from marketmind.pipeline.methodology_rules import (
    MainAIRule,
    RuleRegistry,
    assemble_dynamic_prompt,
)
from marketmind.pipeline.methodology_evolution import (
    RuleValidator,
    RuleEvolver,
)


class TestRuleValidator:
    """Walk-forward validation gate for SHARP rules."""

    def test_insufficient_audits_defers(self):
        rule = MainAIRule(rule_id="RRSK-TEST01", rule_text="Test rule", category="risk")
        validator = RuleValidator()
        should_retire, reason = validator.validate(rule, [{"correct": True}] * 3)
        assert not should_retire
        assert "Insufficient" in reason

    def test_oos_below_50_retires(self):
        rule = MainAIRule(rule_id="RRSK-TEST02", rule_text="Bad rule", category="risk")
        validator = RuleValidator(train_days=5, test_days=5)
        audits = [{"correct": True}] * 5 + [{"correct": False}] * 5
        should_retire, reason = validator.validate(rule, audits)
        assert should_retire
        assert "0.00%" in reason

    def test_oos_above_50_keeps(self):
        rule = MainAIRule(rule_id="RRSK-TEST03", rule_text="Good rule", category="risk")
        validator = RuleValidator(train_days=5, test_days=5)
        audits = [{"correct": True}] * 5 + [
            {"correct": True}, {"correct": True}, {"correct": True},
            {"correct": False}, {"correct": False}]
        should_retire, _ = validator.validate(rule, audits)
        assert not should_retire

    def test_wfe_degradation_retires(self):
        rule = MainAIRule(rule_id="RRSK-TEST04", rule_text="Degraded", category="risk")
        validator = RuleValidator(train_days=5, test_days=5)
        audits = (
            [{"correct": True}] * 4 + [{"correct": False}] * 1 +
            [{"correct": True}] * 2 + [{"correct": False}] * 3
        )
        should_retire, _ = validator.validate(rule, audits)
        assert should_retire


class TestRuleEvolver:
    """Evolution engine with atomic edits."""

    def test_evolve_retires_bad_rules(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-BAD01", rule_text="Bad", category="risk")
        registry.register(rule)
        validator = RuleValidator(train_days=3, test_days=3)
        evolver = RuleEvolver(registry, validator)
        audits = {"RRSK-BAD01": [{"correct": True}] * 3 + [{"correct": False}] * 3}
        changes = evolver.evolve(audits)
        assert any("RETIRED" in c for c in changes)
        assert rule.status == "retired"

    def test_evolve_keeps_good_rules(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-GOOD01", rule_text="Good", category="risk")
        registry.register(rule)
        validator = RuleValidator(train_days=3, test_days=3)
        evolver = RuleEvolver(registry, validator)
        audits = {"RRSK-GOOD01": [{"correct": True}] * 6}
        changes = evolver.evolve(audits)
        assert not any("RETIRED" in c for c in changes)
        assert rule.status == "active"
        assert rule.validation_count == 6

    def test_tune_threshold(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-TUNE01", rule_text="Max position size: 5.0% of portfolio",
                          category="risk")
        registry.register(rule)
        evolver = RuleEvolver(registry)
        result = evolver.tune_threshold(rule, "max_position", 7.0, 5.0)
        assert "TUNED" in result
        assert rule.version == 2
        assert "7.0%" in rule.rule_text

    def test_add_condition(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-ADD01", rule_text="Always set a stop loss.",
                          category="risk")
        registry.register(rule)
        evolver = RuleEvolver(registry)
        result = evolver.add_condition(rule, "Stop loss at 2% below entry")
        assert "EXTENDED" in result
        assert rule.version == 2
        assert "2% below entry" in rule.rule_text

    def test_remove_rule(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-REM01", rule_text="Remove me", category="risk")
        registry.register(rule)
        evolver = RuleEvolver(registry)
        result = evolver.remove_rule("RRSK-REM01")
        assert "REMOVED" in result
        assert rule.status == "retired"


class TestDynamicPromptAssembly:
    """Build decision prompt from active rules."""

    def test_assemble_excludes_retired(self):
        registry = RuleRegistry()
        registry.register(MainAIRule(rule_id="RRSK-ACT01", rule_text="Active rule",
                                     category="risk"))
        registry.register(MainAIRule(rule_id="RRSK-RET01", rule_text="Retired rule",
                                     category="risk", status="retired"))
        prompt = assemble_dynamic_prompt(registry)
        assert "Active rule" in prompt
        assert "Retired rule" not in prompt

    def test_assemble_category_order(self):
        registry = RuleRegistry()
        registry.register(MainAIRule(rule_id="RRIS-T01", rule_text="Risk first",
                                     category="risk"))
        registry.register(MainAIRule(rule_id="RPRO-T01", rule_text="Process last",
                                     category="process"))
        registry.register(MainAIRule(rule_id="RANA-T01", rule_text="Analysis middle",
                                     category="analysis"))
        prompt = assemble_dynamic_prompt(registry)
        risk_pos = prompt.index("Risk first")
        analysis_pos = prompt.index("Analysis middle")
        process_pos = prompt.index("Process last")
        assert risk_pos < analysis_pos < process_pos

    def test_assemble_decay_note(self):
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="RRSK-DEC01", rule_text="Decaying rule",
                          category="risk", decay_factor=0.3)
        registry.register(rule)
        prompt = assemble_dynamic_prompt(registry)
        assert "[decay=0.3]" in prompt

    def test_assemble_empty_registry(self):
        registry = RuleRegistry()
        prompt = assemble_dynamic_prompt(registry, "Default instructions")
        assert "Default instructions" in prompt

    def test_decay_updates_with_validation(self):
        rule = MainAIRule(rule_id="RRSK-DEC02", rule_text="Test", category="risk")
        rule.validation_count = 100
        rule.success_count = 90
        rule._update_decay()
        assert rule.decay_factor > 0.7

        rule2 = MainAIRule(rule_id="RRSK-DEC03", rule_text="Bad", category="risk")
        rule2.validation_count = 1000
        rule2.success_count = 200
        rule2._update_decay()
        assert rule2.decay_factor < 0.35
