"""Tests for SHARP rule framework — decomposition, attribution, audit (P3-2a + P3-2b)."""
import json
import pytest
from unittest.mock import patch, AsyncMock
from marketmind.pipeline.methodology_rules import (
    MainAIRule, RuleImpactHypothesis, RuleDecompositionResult,
    RuleDecomposer, AttributionAgent, RuleRegistry,
    assemble_dynamic_prompt, get_default_rules,
)
from marketmind.pipeline.methodology_evolution import (
    RuleValidator, RuleEvolver,
)
from marketmind.storage.archivist import MarketMindArchive
from pathlib import Path


# ── Sample decision prompt for decomposition tests ───────────────────────

SAMPLE_PROMPT = """You are a decision synthesis engine. Your job is to produce the final decision cards.

You receive:
- Layer 1 narrative analysis
- Layer 2 fundamental analysis
- Layer 3 technical review

Output JSON:
{
  "decision_cards": [],
  "summary": ""
}

IMPORTANT: Position size: never exceed 25% total heat limit. Combined stop-losses must be <= 25% total equity.
All prices must be verifiable. Never fabricate data.
Each decision must have a clearly stated risk thesis with specific stop-loss levels.
"""


class TestRuleDecomposition:

    def test_extract_rules_from_prompt(self):
        """Should extract actionable constraints from the decision prompt."""
        result = RuleDecomposer.decompose(SAMPLE_PROMPT)
        assert result.total_extracted >= 2
        assert len(result.rules) == result.total_extracted
        for rule in result.rules:
            assert rule.rule_id.startswith("rule:")
            assert rule.category in ("position_sizing", "risk_management",
                                     "quality", "output_format")
            assert rule.status == "active"
            assert rule.source == "decomposition"

    def test_rule_ids_are_stable(self):
        """Same rule content should produce the same rule_id (deterministic)."""
        result1 = RuleDecomposer.decompose(SAMPLE_PROMPT)
        result2 = RuleDecomposer.decompose(SAMPLE_PROMPT)
        ids1 = {r.rule_id for r in result1.rules}
        ids2 = {r.rule_id for r in result2.rules}
        assert ids1 == ids2

    def test_empty_prompt_produces_fallback(self):
        """Empty or non-actionable prompts should produce a fallback rule."""
        result = RuleDecomposer.decompose("Just some description. Nothing actionable.")
        assert result.total_extracted == 1  # Fallback rule

    def test_category_classification(self):
        """Rules should be classified into correct categories."""
        position_rule = "Position size must never exceed 25% of total portfolio heat limit."
        risk_rule = "Every stop-loss must be placed at a verifiable support level."
        quality_rule = "All prices must be verifiable from public sources. Never fabricate data."

        assert RuleDecomposer._classify_rule(position_rule) == "position_sizing"
        assert RuleDecomposer._classify_rule(risk_rule) == "risk_management"
        assert RuleDecomposer._classify_rule(quality_rule) == "quality"


class TestAttributionAgent:

    def test_builds_attribution_prompt(self):
        """AttributionAgent should build a valid prompt with rules and context."""
        agent = AttributionAgent()
        rules = [
            MainAIRule(rule_id="rule:risk_management:abc123",
                       content="Never exceed 25% heat limit.", category="risk_management"),
        ]
        prompt = agent.build_attribution_prompt(
            rules,
            outcome_summary="Position lost 5% on AAPL long.",
            context_summary="VIX=28, market selloff, stop-loss triggered."
        )
        assert "SHARP ATTRIBUTION PROTOCOL" in prompt
        assert "rule:risk_management:abc123" in prompt
        assert "Position lost 5%" in prompt

    def test_parse_valid_json_response(self):
        """Should parse a valid JSON response into hypotheses."""
        response = json.dumps({
            "hypotheses": [
                {"rule_id": "rule:risk:abc", "suspected_impact": "positive",
                 "confidence": 0.8, "evidence_summary": "Stop-loss worked correctly."},
                {"rule_id": "rule:quality:def", "suspected_impact": "negative",
                 "confidence": 0.6, "evidence_summary": "Data was stale."},
            ]
        })
        hypotheses = AttributionAgent._parse_attribution_response(response)
        assert len(hypotheses) == 2
        assert hypotheses[0].rule_id == "rule:risk:abc"
        assert hypotheses[0].suspected_impact == "positive"
        assert hypotheses[0].confidence == 0.8

    def test_parse_invalid_json_returns_empty(self):
        """Invalid JSON should return empty list (no crash)."""
        hypotheses = AttributionAgent._parse_attribution_response("not valid json")
        assert hypotheses == []

    @pytest.mark.asyncio
    async def test_generate_hypotheses_caching(self):
        """Same rules+outcome should return cached results."""
        agent = AttributionAgent()
        rules = [MainAIRule(rule_id="rule:test:123", content="Test rule.",
                           category="quality")]

        with patch.object(agent, 'build_attribution_prompt',
                         return_value="test prompt"):
            mock_flash = AsyncMock(return_value={
                "content": json.dumps({"hypotheses": [
                    {"rule_id": "rule:test:123", "suspected_impact": "neutral",
                     "confidence": 0.5, "evidence_summary": "No impact."}
                ]})
            })
            with patch('marketmind.gateway.async_client.chat_flash', mock_flash):
                h1 = await agent.generate_hypotheses(
                    rules, "outcome A", "context A"
                )
                h2 = await agent.generate_hypotheses(
                    rules, "outcome A", "context A"  # Same → cached
                )
                # Second call should use cache (mock_flash called only once)
                assert len(h1) == 1
                assert len(h2) == 1
                assert mock_flash.call_count == 1


class TestRuleRegistry:

    def test_register_and_retrieve_rule(self):
        """Rules should be storable and retrievable."""
        registry = RuleRegistry()
        rule = MainAIRule(
            rule_id="rule:quality:test", content="Never fabricate.",
            category="quality"
        )
        registry.register(rule)
        retrieved = registry.get("rule:quality:test")
        assert retrieved is not None
        assert retrieved.content == "Never fabricate."

    def test_get_active_filters_by_category(self):
        """get_active should filter by category and status."""
        registry = RuleRegistry()
        r1 = MainAIRule(rule_id="rule:risk:a", content="Risk A.",
                       category="risk_management", status="active")
        r2 = MainAIRule(rule_id="rule:risk:b", content="Risk B.",
                       category="risk_management", status="retired")
        r3 = MainAIRule(rule_id="rule:quality:c", content="Quality C.",
                       category="quality", status="active")
        registry.register(r1)
        registry.register(r2)
        registry.register(r3)

        active_risk = registry.get_active(category="risk_management")
        assert len(active_risk) == 1
        assert active_risk[0].rule_id == "rule:risk:a"

        active_all = registry.get_active()
        assert len(active_all) == 2

    def test_retire_rule_with_audit(self):
        """Retiring a rule should update status and log audit."""
        registry = RuleRegistry()
        rule = MainAIRule(rule_id="rule:test:x", content="Test.",
                         category="quality")
        registry.register(rule)

        result = registry.retire("rule:test:x", "Failed backtest validation")
        assert result is True
        assert rule.status == "retired"
        assert rule.retire_reason == "Failed backtest validation"

        audit = registry.get_audit_trail("rule:test:x")
        assert len(audit) == 1
        assert audit[0]["action"] == "retired"

    def test_serialize_and_deserialize(self):
        """Registry should survive round-trip serialization."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:risk:xyz", content="Limit heat.", category="risk_management"
        ))
        data = registry.to_dict()
        restored = RuleRegistry.from_dict(data)
        assert restored.get("rule:risk:xyz") is not None
        assert restored.get("rule:risk:xyz").content == "Limit heat."


class TestArchivistRuleAudit:

    def test_save_and_retrieve_rule_audit(self, tmp_path):
        """Archivist should persist and retrieve rule audit entries."""
        archive = MarketMindArchive(str(tmp_path))
        archive.save_rule_audit(
            "rule:test:1", "decomposed",
            {"source": "DECISION_SYSTEM_PROMPT"}
        )
        archive.save_rule_audit(
            "rule:test:1", "retired",
            {"reason": "Failed backtest", "wfe_ratio": 0.23}
        )

        entries = archive.get_rule_audit("rule:test:1")
        assert len(entries) == 2
        # Entries in same file appear in insertion order
        events = {e["event"] for e in entries}
        assert "retired" in events
        assert "decomposed" in events

    def test_get_rule_audit_filters_by_rule_id(self, tmp_path):
        """get_rule_audit should filter by rule_id."""
        archive = MarketMindArchive(str(tmp_path))
        archive.save_rule_audit("rule:test:a", "created", {})
        archive.save_rule_audit("rule:test:b", "created", {})

        entries_a = archive.get_rule_audit("rule:test:a")
        assert all(e["rule_id"] == "rule:test:a" for e in entries_a)


# ── P3-2b: Rule Validator + Evolver + Dynamic Assembly ──────────────────

class TestRuleValidator:

    def test_insufficient_data_no_retire(self):
        """Validator should not retire when outcome data is insufficient."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=10)
        hypothesis = RuleImpactHypothesis(
            rule_id="rule:test:1", suspected_impact="negative", confidence=0.7,
            evidence_summary="Seems bad."
        )
        should_retire, reason = validator.validate_hypothesis(hypothesis, [])
        assert not should_retire
        assert "insufficient_data" in reason

    def test_negative_impact_validated(self):
        """Rule with negative impact should be retired when outcomes improve without it."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=3)
        hypothesis = RuleImpactHypothesis(
            rule_id="rule:test:1", suspected_impact="negative", confidence=0.8,
            evidence_summary="Rule causes overtrading."
        )
        outcome_data = (
            [{"outcome_score": 0.01, "rule_active": True}] * 10 +   # with rule: low score
            [{"outcome_score": 0.05, "rule_active": False}] * 10     # without rule: higher
        )
        should_retire, reason = validator.validate_hypothesis(hypothesis, outcome_data)
        assert should_retire
        assert "Negative impact confirmed" in reason

    def test_positive_impact_not_confirmed(self):
        """Rule claimed positive but outcomes don't support it → retire."""
        registry = RuleRegistry()
        validator = RuleValidator(registry, min_validation_windows=3)
        hypothesis = RuleImpactHypothesis(
            rule_id="rule:test:2", suspected_impact="positive", confidence=0.6,
            evidence_summary="Claimed helpful."
        )
        outcome_data = (
            [{"outcome_score": 0.01, "rule_active": True}] * 10 +   # with rule: low
            [{"outcome_score": 0.05, "rule_active": False}] * 10     # without: higher
        )
        should_retire, reason = validator.validate_hypothesis(hypothesis, outcome_data)
        assert should_retire
        assert "NOT confirmed" in reason

    def test_retire_if_validated_auto_updates_registry(self):
        """retire_if_validated should call registry.retire when gate passes."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:test:3", content="Bad rule.", category="quality"
        ))
        validator = RuleValidator(registry, min_validation_windows=3)
        hypothesis = RuleImpactHypothesis(
            rule_id="rule:test:3", suspected_impact="negative", confidence=0.8,
            evidence_summary="Harmful."
        )
        outcome_data = (
            [{"outcome_score": 0.01, "rule_active": True}] * 5 +
            [{"outcome_score": 0.06, "rule_active": False}] * 5
        )
        result = validator.retire_if_validated(hypothesis, outcome_data)
        assert result is True
        assert registry.get("rule:test:3").status == "retired"


class TestRuleEvolver:

    def test_tune_threshold_creates_evolved_rule(self):
        """tune_threshold should retire old rule and create evolved version."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:pos:heat", content="Never exceed 25% total heat limit.",
            category="position_sizing"
        ))
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)

        # Content has "25%" — pass values that match text representation
        evolved = evolver.tune_threshold("rule:pos:heat", 25, 20, "heat_limit")
        assert evolved is not None
        assert "20%" in evolved.content or "20 " in evolved.content
        assert evolved.generation == 1
        assert evolved.parent_rule_id == "rule:pos:heat"
        assert registry.get("rule:pos:heat").status == "retired"

    def test_add_constraint_creates_new_rule(self):
        """add_constraint should add a new rule to the registry."""
        registry = RuleRegistry()
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)

        rule = evolver.add_constraint(
            "Always verify sector correlation before entering a position.",
            category="risk_management"
        )
        assert rule is not None
        assert registry.get(rule.rule_id) is not None
        assert rule.source == "evolution"

    def test_remove_constraint_retires_rule(self):
        """remove_constraint should retire a rule."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:bad:1", content="Ignore stop-losses on trend days.",
            category="risk_management"
        ))
        validator = RuleValidator(registry)
        evolver = RuleEvolver(registry, validator)

        result = evolver.remove_constraint("rule:bad:1", "Backtest shows losses")
        assert result is True
        assert registry.get("rule:bad:1").status == "retired"


class TestDynamicPromptAssembly:

    def test_assemble_from_registry(self):
        """Should assemble a prompt from active rules in registry."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:risk:a", content="Never exceed 25% heat.",
            category="risk_management"
        ))
        registry.register(MainAIRule(
            rule_id="rule:quality:b", content="All prices must be verifiable.",
            category="quality"
        ))
        # Retired rule should NOT appear
        registry.register(MainAIRule(
            rule_id="rule:old:c", content="Old rule.", category="risk_management",
            status="retired"
        ))

        prompt = assemble_dynamic_prompt(registry)
        assert "Never exceed 25% heat" in prompt
        assert "All prices must be verifiable" in prompt
        assert "Old rule" not in prompt

    def test_assemble_default_rules(self):
        """get_default_rules should decompose DECISION_SYSTEM_PROMPT."""
        registry = get_default_rules()
        active = registry.get_active()
        assert len(active) >= 2
        for rule in active:
            assert rule.status == "active"

    def test_decision_module_dynamic_prompt(self):
        """_get_decision_prompt should return non-empty string."""
        from marketmind.pipeline.decision import _get_decision_prompt
        prompt = _get_decision_prompt()
        assert len(prompt) > 100
        assert "decision synthesis" in prompt.lower()


class TestEvolutionEndToEnd:

    def test_attribution_to_retirement_flow(self):
        """Full flow: decompose → attribute → validate → retire → evolve."""
        # 1. Decompose
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="rule:quality:test1", content="Always double-check data sources.",
            category="quality"
        ))
        validator = RuleValidator(registry, min_validation_windows=3)
        evolver = RuleEvolver(registry, validator)

        # 2. Attribution hypothesis says negative
        hypothesis = RuleImpactHypothesis(
            rule_id="rule:quality:test1", suspected_impact="negative",
            confidence=0.75, evidence_summary="Slows decision-making without benefit."
        )

        # 3. Backtest validates negative impact
        outcome_data = (
            [{"outcome_score": 0.02, "rule_active": True}] * 5 +
            [{"outcome_score": 0.07, "rule_active": False}] * 5
        )

        # 4. Validate → should retire
        should_retire, reason = validator.validate_hypothesis(hypothesis, outcome_data)
        assert should_retire
        registry.retire(hypothesis.rule_id, reason)
        assert registry.get("rule:quality:test1").status == "retired"

        # 5. Audit trail captured
        audit = registry.get_audit_trail("rule:quality:test1")
        assert len(audit) == 1
        assert audit[0]["action"] == "retired"
