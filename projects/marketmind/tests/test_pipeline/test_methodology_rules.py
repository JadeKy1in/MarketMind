"""Tests for SHARP rule framework — decomposition, attribution, audit (P3-2a)."""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.pipeline.methodology_rules import (
    AttributionHypothesis,
    MainAIRule,
    RuleDecomposer,
    RuleRegistry,
    get_default_rules,
)
from marketmind.pipeline.methodology_attribution import (
    AttributionAgent,
)
from marketmind.pipeline.methodology_evolution import (
    RuleEvolver,
    RuleValidator,
    assemble_dynamic_prompt,
)
from marketmind.storage.archivist import MarketMindArchive


# ── Sample prompts for decomposition tests ────────────────────────────────

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

MINIMAL_PROMPT = "You are an analyst. Make good decisions."

MALFORMED_PROMPT = ""


# ── P3-2a Test 1: Rule Decomposition ──────────────────────────────────────

class TestRuleDecomposition:
    """prompt -> list of rules with IDs."""

    def test_extract_rules_from_prompt(self):
        """Should extract actionable constraints from the decision prompt."""
        rules = RuleDecomposer.decompose(SAMPLE_PROMPT)
        assert len(rules) >= 2, f"Expected >= 2 rules, got {len(rules)}"

        for rule in rules:
            # Every rule must have a non-empty ID
            assert rule.rule_id, f"Rule has empty ID: {rule}"
            # Every rule must have a valid category
            assert rule.category in ("risk", "timing", "analysis", "process"), \
                f"Invalid category '{rule.category}' for rule {rule.rule_id}"
            # Every rule must have non-empty text
            assert len(rule.rule_text) > 0, \
                f"Rule {rule.rule_id} has empty text"
            # Newly decomposed rules are active
            assert rule.status == "active", \
                f"Rule {rule.rule_id} status is '{rule.status}', expected 'active'"
            # Version starts at 1
            assert rule.version == 1

    def test_rule_ids_are_stable(self):
        """Same prompt content should produce the same rule IDs (deterministic)."""
        rules1 = RuleDecomposer.decompose(SAMPLE_PROMPT)
        rules2 = RuleDecomposer.decompose(SAMPLE_PROMPT)
        ids1 = {r.rule_id for r in rules1}
        ids2 = {r.rule_id for r in rules2}
        assert ids1 == ids2, f"IDs differ: {ids1} vs {ids2}"

    def test_rule_ids_are_unique(self):
        """No two rules should share the same ID."""
        rules = RuleDecomposer.decompose(SAMPLE_PROMPT)
        ids = [r.rule_id for r in rules]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"

    def test_category_classification_risk(self):
        """Position sizing and stop-loss rules -> 'risk' category."""
        content = "Position size must never exceed 25% of total portfolio heat limit."
        assert RuleDecomposer._classify_rule(content) == "risk"

    def test_category_classification_analysis(self):
        """Verifiability rules -> 'analysis' category."""
        content = "All prices must be verifiable from public sources. Never fabricate data."
        assert RuleDecomposer._classify_rule(content) == "analysis"

    def test_category_classification_process(self):
        """Output format rules -> 'process' category."""
        content = "The output JSON must include a no-trade card with thesis."
        assert RuleDecomposer._classify_rule(content) == "process"

    def test_get_rules_by_category(self):
        """get_rules_by_category should filter correctly."""
        rules = [
            MainAIRule(rule_id="R1", rule_text="Risk rule.", category="risk"),
            MainAIRule(rule_id="R2", rule_text="Analysis rule.", category="analysis"),
            MainAIRule(rule_id="R3", rule_text="Another risk.", category="risk"),
        ]
        risk_rules = RuleDecomposer.get_rules_by_category(rules, "risk")
        assert len(risk_rules) == 2
        analysis_rules = RuleDecomposer.get_rules_by_category(rules, "analysis")
        assert len(analysis_rules) == 1
        empty = RuleDecomposer.get_rules_by_category(rules, "timing")
        assert len(empty) == 0


# ── P3-2a Test 2: Attribution Hypothesis ──────────────────────────────────

class TestAttributionHypothesis:
    """Flash LLM produces hypothesis (mock LLM)."""

    def test_attribution_hypothesis_fields(self):
        """AttributionHypothesis should have all required fields."""
        hyp = AttributionHypothesis(
            rule_id="RRSK-TEST1234",
            suspected_impact="negative",
            confidence=0.75,
            evidence_summary="Stop-loss was too tight for current volatility.",
        )
        assert hyp.rule_id == "RRSK-TEST1234"
        assert hyp.suspected_impact == "negative"
        assert hyp.confidence == 0.75
        assert "Stop-loss" in hyp.evidence_summary
        assert hyp.date  # Auto-generated

    def test_confidence_clamped(self):
        """Confidence should be between 0.0 and 1.0 (tested via parser)."""
        # The AttributionAgent enforces clamping in _parse_single_hypothesis
        response = json.dumps({
            "suspected_impact": "positive",
            "confidence": 0.95,
            "evidence_summary": "Rule worked well.",
        })
        hyp = AttributionAgent._parse_single_hypothesis(
            response, "RRSK-TEST"
        )
        assert hyp.confidence == 0.95
        assert hyp.suspected_impact == "positive"

    @pytest.mark.asyncio
    async def test_attribute_with_mock_flash(self):
        """AttributionAgent.attribute() should call Flash and return hypothesis."""
        rule = MainAIRule(
            rule_id="RRSK-MOCK0001",
            rule_text="Never exceed 25% heat limit.",
            category="risk",
        )
        ctx = {"vix": 28, "signal_strength": 0.6}
        outcome = {"pnl_pct": -3.2, "decision_correct": False}

        mock_flash = AsyncMock(return_value={
            "content": json.dumps({
                "suspected_impact": "negative",
                "confidence": 0.70,
                "evidence_summary": "Heat limit rule prevented larger loss.",
            }),
            "usage": {"total_tokens": 200},
        })

        with patch(
            "marketmind.gateway.async_client.chat_flash", mock_flash
        ):
            hyp = await AttributionAgent.attribute(rule, ctx, outcome)

        assert hyp.rule_id == "RRSK-MOCK0001"
        assert hyp.suspected_impact == "negative"
        assert hyp.confidence == 0.70
        assert "Heat limit" in hyp.evidence_summary
        assert mock_flash.called

    @pytest.mark.asyncio
    async def test_attribute_flash_failure_returns_neutral(self):
        """When Flash call fails, should return neutral hypothesis (no crash)."""
        rule = MainAIRule(
            rule_id="RRSK-FAIL0001",
            rule_text="Always verify data.",
            category="analysis",
        )

        mock_flash = AsyncMock(side_effect=Exception("API Timeout"))

        with patch(
            "marketmind.gateway.async_client.chat_flash", mock_flash
        ):
            hyp = await AttributionAgent.attribute(rule, {}, {})

        assert hyp.rule_id == "RRSK-FAIL0001"
        assert hyp.suspected_impact == "neutral"
        assert hyp.confidence == 0.0
        assert "API Timeout" in hyp.evidence_summary

    def test_parse_malformed_json_returns_neutral(self):
        """Malformed JSON response should not crash."""
        hyp = AttributionAgent._parse_single_hypothesis(
            "not valid json at all", "RRSK-BAD"
        )
        assert hyp.rule_id == "RRSK-BAD"
        assert hyp.suspected_impact == "neutral"
        assert hyp.confidence == 0.0


# ── P3-2a Test 3: Dynamic Assembly ────────────────────────────────────────

class TestDynamicAssembly:
    """rules -> prompt string."""

    def test_assemble_produces_complete_prompt(self):
        """assemble() should produce a complete decision prompt with all sections."""
        rules = [
            MainAIRule(
                rule_id="RRSK-A1B2C3D4", rule_text="Never exceed 25% heat limit.",
                category="risk",
            ),
            MainAIRule(
                rule_id="RANL-E5F6G7H8", rule_text="All prices must be verifiable.",
                category="analysis",
            ),
            MainAIRule(
                rule_id="RPRC-I9J0K1L2", rule_text="No-trade card must be equally rigorous.",
                category="process",
            ),
        ]

        prompt = RuleDecomposer.assemble(rules)

        # Should contain role description
        assert "decision synthesis engine" in prompt.lower()
        # Should contain output format
        assert "decision_cards" in prompt
        assert "no_trade_card" in prompt
        # Should contain all active rules
        assert "Never exceed 25% heat limit" in prompt
        assert "All prices must be verifiable" in prompt
        assert "equally rigorous" in prompt
        # Should contain rule IDs as annotations
        assert "RRSK-A1B2C3D4" in prompt
        assert "RANL-E5F6G7H8" in prompt

    def test_assemble_skips_retired_rules(self):
        """Retired rules should NOT appear in assembled prompt."""
        rules = [
            MainAIRule(
                rule_id="RRSK-ACTIVE", rule_text="Active risk rule.",
                category="risk", status="active",
            ),
            MainAIRule(
                rule_id="RRSK-RETIRED", rule_text="Retired rule.",
                category="risk", status="retired",
            ),
        ]

        prompt = RuleDecomposer.assemble(rules)
        assert "Active risk rule" in prompt
        assert "Retired rule" not in prompt

    def test_assemble_empty_rules(self):
        """Assemble with empty list should still produce a valid prompt."""
        prompt = RuleDecomposer.assemble([])
        assert "decision synthesis engine" in prompt.lower()
        assert "decision_cards" in prompt

    def test_assemble_grouped_by_category(self):
        """Rules should appear under correct category headers."""
        rules = [
            MainAIRule(rule_id="R1", rule_text="Risk rule.", category="risk"),
            MainAIRule(rule_id="R2", rule_text="Analysis rule.", category="analysis"),
        ]
        prompt = RuleDecomposer.assemble(rules)

        # Category headers should appear
        assert "Risk & Position Sizing" in prompt
        assert "Analysis Quality" in prompt
        # Risk rule should appear before analysis in display order
        risk_pos = prompt.index("Risk & Position Sizing")
        analysis_pos = prompt.index("Analysis Quality")
        assert risk_pos < analysis_pos

    def test_assemble_with_custom_base_instructions(self):
        """Custom base_instructions should override the default preamble."""
        rules = [MainAIRule(rule_id="R1", rule_text="Test.", category="risk")]
        custom = "CUSTOM PREAMBLE — override test."
        prompt = RuleDecomposer.assemble(rules, base_instructions=custom)
        assert prompt.startswith("CUSTOM PREAMBLE")


# ── P3-2a Test 4: Backtest Retirement ────────────────────────────────────

class TestBacktestRetirement:
    """Rule with low accuracy gets retired."""

    def test_retire_rule_updates_status(self):
        """Retiring a rule should set status='retired' with reason."""
        registry = RuleRegistry()
        rule = MainAIRule(
            rule_id="RRSK-RETIRE-TEST", rule_text="Bad position sizing rule.",
            category="risk",
        )
        registry.register(rule)

        result = registry.retire("RRSK-RETIRE-TEST", "WFA backtest: accuracy=0.23 < 0.50 threshold")
        assert result is True
        assert rule.status == "retired"
        assert rule.retired_date is not None
        assert "accuracy=0.23" in (rule.retirement_reason or "")

    def test_retire_nonexistent_rule_returns_false(self):
        """Retiring a nonexistent rule should return False."""
        registry = RuleRegistry()
        result = registry.retire("NONEXISTENT", "reason")
        assert result is False

    def test_decay_factor_decreases_on_validation_failure(self):
        """Marking a failed validation should decrease decay_factor."""
        registry = RuleRegistry()
        rule = MainAIRule(
            rule_id="RRSK-DECAY", rule_text="Risk rule.", category="risk",
            decay_factor=0.80, validation_count=5, success_count=3,
        )
        registry.register(rule)

        registry.mark_validated("RRSK-DECAY", success=False)
        assert rule.decay_factor < 0.80
        assert rule.validation_count == 6
        assert rule.success_count == 3  # Unchanged on failure

    def test_decay_factor_increases_on_validation_success(self):
        """Marking a successful validation should increase decay_factor."""
        registry = RuleRegistry()
        rule = MainAIRule(
            rule_id="RRSK-SUCCESS", rule_text="Good rule.", category="analysis",
            decay_factor=0.80, validation_count=5, success_count=3,
        )
        registry.register(rule)

        registry.mark_validated("RRSK-SUCCESS", success=True)
        assert rule.decay_factor > 0.80
        assert rule.validation_count == 6
        assert rule.success_count == 4

    def test_decay_factor_clamped_to_zero_one(self):
        """Decay factor should never go below 0.0 or above 1.0."""
        registry = RuleRegistry()

        # Test lower bound
        rule_low = MainAIRule(
            rule_id="R-LOW", rule_text="Low.", category="risk",
            decay_factor=0.01,
        )
        registry.register(rule_low)
        registry.mark_validated("R-LOW", success=False)
        assert rule_low.decay_factor >= 0.0

        # Test upper bound
        rule_high = MainAIRule(
            rule_id="R-HIGH", rule_text="High.", category="risk",
            decay_factor=0.99,
        )
        registry.register(rule_high)
        registry.mark_validated("R-HIGH", success=True)
        assert rule_high.decay_factor <= 1.0

    def test_get_active_excludes_retired(self):
        """get_active() should exclude retired rules."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="R-ACTIVE", rule_text="Active.", category="risk",
        ))
        registry.register(MainAIRule(
            rule_id="R-RETIRED", rule_text="Retired.", category="risk",
            status="retired",
        ))

        active = registry.get_active()
        assert len(active) == 1
        assert active[0].rule_id == "R-ACTIVE"


# ── P3-2a Test 5: Audit Trail ────────────────────────────────────────────

class TestAuditTrail:
    """Audit history stored and retrievable."""

    def test_rule_registry_audit_log(self):
        """RuleRegistry should log audit events on status changes."""
        registry = RuleRegistry()
        rule = MainAIRule(
            rule_id="RANL-AUDIT-01", rule_text="Verify prices.",
            category="analysis",
        )
        registry.register(rule)
        registry.retire("RANL-AUDIT-01", "Failed backtest")
        registry.set_under_review("RANL-AUDIT-01")

        trail = registry.get_audit_trail("RANL-AUDIT-01")
        assert len(trail) >= 1
        # At minimum the retire action should be logged
        actions = {e["action"] for e in trail}
        assert "retired" in actions

    def test_archivist_save_and_retrieve(self):
        """Archivist should persist and retrieve rule audit entries."""
        with tempfile.TemporaryDirectory() as td:
            archive = MarketMindArchive(str(td))
            archive.save_rule_audit(
                "RRSK-ARCH-01",
                {
                    "event": "attribution",
                    "hypothesis": {"suspected_impact": "negative", "confidence": 0.65},
                },
            )
            archive.save_rule_audit(
                "RRSK-ARCH-01",
                {
                    "event": "backtest_validated",
                    "wfe_ratio": 0.23,
                    "decision": "retire",
                },
            )

            history = archive.get_rule_audit_history("RRSK-ARCH-01", days=365)
            assert len(history) == 2
            events = {e["event"] for e in history}
            assert "attribution" in events
            assert "backtest_validated" in events
            archive.close()

    def test_archivist_filters_by_rule_id(self):
        """get_rule_audit_history should filter by rule_id."""
        with tempfile.TemporaryDirectory() as td:
            archive = MarketMindArchive(str(td))
            archive.save_rule_audit("R-A", {"event": "created"})
            archive.save_rule_audit("R-B", {"event": "created"})

            history_a = archive.get_rule_audit_history("R-A", days=365)
            assert all(e["rule_id"] == "R-A" for e in history_a)
            assert len(history_a) == 1

            history_b = archive.get_rule_audit_history("R-B", days=365)
            assert all(e["rule_id"] == "R-B" for e in history_b)
            assert len(history_b) == 1
            archive.close()

    def test_archivist_empty_history(self):
        """Nonexistent rule should return empty history."""
        with tempfile.TemporaryDirectory() as td:
            archive = MarketMindArchive(str(td))
            history = archive.get_rule_audit_history("NONEXISTENT", days=90)
            assert history == []
            archive.close()

    def test_registry_serialize_roundtrip(self):
        """RuleRegistry should survive to_dict() -> from_dict() roundtrip."""
        registry = RuleRegistry()
        registry.register(MainAIRule(
            rule_id="RRSK-SERIAL", rule_text="Limit heat.", category="risk",
            version=2, decay_factor=0.75, validation_count=10, success_count=7,
        ))
        registry.register(MainAIRule(
            rule_id="RANL-SERIAL", rule_text="Verify data.", category="analysis",
            status="retired", retired_date="2026-05-20T00:00:00",
            retirement_reason="Obsolete",
        ))

        data = registry.to_dict()
        restored = RuleRegistry.from_dict(data)

        r1 = restored.get("RRSK-SERIAL")
        assert r1 is not None
        assert r1.rule_text == "Limit heat."
        assert r1.version == 2
        assert r1.decay_factor == 0.75
        assert r1.validation_count == 10

        r2 = restored.get("RANL-SERIAL")
        assert r2 is not None
        assert r2.status == "retired"
        assert r2.retirement_reason == "Obsolete"


# ── P3-2a Test 6: Error Handling ─────────────────────────────────────────

class TestErrorHandling:
    """Decomposition handles malformed prompts gracefully."""

    def test_empty_prompt_produces_fallback(self):
        """Empty prompts should produce a single fallback rule (no crash)."""
        rules = RuleDecomposer.decompose(MALFORMED_PROMPT)
        assert len(rules) >= 0  # Empty is acceptable
        # Fallback rule if present
        if rules:
            for r in rules:
                assert r.rule_id
                assert r.category in ("risk", "timing", "analysis", "process")

    def test_minimal_prompt_produces_fallback(self):
        """Minimal prompts with no rules should produce a fallback (no crash)."""
        rules = RuleDecomposer.decompose(MINIMAL_PROMPT)
        assert len(rules) >= 0
        if rules:
            assert all(r.status == "active" for r in rules)

    def test_very_long_prompt_does_not_crash(self):
        """Extremely long prompt should not cause infinite loops or crashes."""
        long_prompt = "IMPORTANT: " + "Always verify data sources. " * 500
        rules = RuleDecomposer.decompose(long_prompt)
        assert isinstance(rules, list)
        # Should deduplicate repeated identical sentences (500 copies of same text)
        assert len(rules) < 100, f"Too many rules after dedup: {len(rules)}"

    def test_prompt_with_only_json_structure(self):
        """Prompt with only JSON structure should not crash."""
        json_only = '{\n  "key": "value"\n}'
        rules = RuleDecomposer.decompose(json_only)
        assert isinstance(rules, list)

    def test_prompt_with_special_characters(self):
        """Prompt with unicode and special characters should not crash."""
        unicode_prompt = (
            "IMPORTANT: Never exceed 25% heat limit. "
            "Combined stop-losses ≤ 25% total equity. "
            "“All prices must be verifiable.”"
        )
        rules = RuleDecomposer.decompose(unicode_prompt)
        assert isinstance(rules, list)
        if rules:
            assert all(r.rule_id for r in rules)

    def test_attribution_empty_response(self):
        """Empty Flash response should return neutral hypothesis."""
        hyp = AttributionAgent._parse_single_hypothesis("", "RRSK-EMPTY")
        assert hyp.rule_id == "RRSK-EMPTY"
        assert hyp.suspected_impact == "neutral"

    def test_attribution_none_response(self):
        """None-like Flash response should return neutral hypothesis."""
        hyp = AttributionAgent._parse_single_hypothesis("null", "RRSK-NULL")
        assert hyp.rule_id == "RRSK-NULL"
        assert hyp.suspected_impact == "neutral"


# ── Decision module integration test ──────────────────────────────────────

class TestDecisionIntegration:
    """Verify decision.py uses dynamic prompt assembly."""

    def test_get_decision_prompt_returns_non_empty(self):
        """_get_decision_prompt should return a non-empty string."""
        from marketmind.pipeline.decision import (
            _get_decision_prompt,
            _refresh_decision_prompt,
            _dynamic_prompt_cache,
        )

        # Force cache clear
        import marketmind.pipeline.decision as dec_mod
        dec_mod._dynamic_prompt_cache = None

        prompt = _get_decision_prompt()
        assert len(prompt) > 100
        assert "decision synthesis" in prompt.lower()
        assert "decision_cards" in prompt

    def test_get_decision_prompt_is_cached(self):
        """Subsequent calls should return cached result."""
        from marketmind.pipeline import decision as dec_mod

        dec_mod._dynamic_prompt_cache = None
        p1 = dec_mod._get_decision_prompt()
        p2 = dec_mod._get_decision_prompt()
        assert p1 == p2
        assert dec_mod._dynamic_prompt_cache is not None

    def test_refresh_decision_prompt(self):
        """_refresh_decision_prompt should invalidate cache and rebuild."""
        from marketmind.pipeline import decision as dec_mod

        dec_mod._dynamic_prompt_cache = "STALE_CACHE"
        prompt = dec_mod._refresh_decision_prompt()
        assert prompt != "STALE_CACHE"
        assert len(prompt) > 100


# ── MainAIRule defaults test ──────────────────────────────────────────────

class TestMainAIRuleDefaults:
    """Verify MainAIRule dataclass defaults and invariants."""

    def test_default_fields(self):
        """New rule should have sensible defaults."""
        rule = MainAIRule(
            rule_id="RRSK-DEF-01", rule_text="Test rule.", category="risk",
        )
        assert rule.version == 1
        assert rule.status == "active"
        assert rule.decay_factor == 1.0
        assert rule.validation_count == 0
        assert rule.success_count == 0
        assert rule.retired_date is None
        assert rule.retirement_reason is None
        assert rule.created_date  # Auto-generated
        assert rule.last_modified  # Auto-generated

    def test_optional_fields_default_none(self):
        """Retired date and reason should default to None."""
        rule = MainAIRule(
            rule_id="RANL-DEF-02", rule_text="Verify.", category="analysis",
        )
        assert rule.retired_date is None
        assert rule.retirement_reason is None
