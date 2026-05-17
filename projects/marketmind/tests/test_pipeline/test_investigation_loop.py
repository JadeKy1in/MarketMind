"""Tests for HVR investigation loop — C6+C8 fixes."""
import pytest

from marketmind.pipeline.investigation_loop import (
    HypothesisResult,
    InvestigationConfig,
    _classify_layer_interpretation,
    _determine_verdict,
    _parse_json_strict,
)
from marketmind.pipeline.verification_chain import VerificationResult


class TestInvestigationConfig:
    """Verify InvestigationConfig loads defaults from investigation_config.py."""

    def test_defaults_match_config(self):
        c = InvestigationConfig()
        assert c.max_hypotheses == 5
        assert c.max_deepening_steps == 3
        assert c.max_api_calls == 5
        assert c.diminishing_threshold == 0.05
        assert c.expectation_gap_threshold == 0.15
        assert c.confidence_action == 0.70
        assert c.confidence_watch == 0.40
        assert c.adversarial_required is True
        assert c.bear_discount == 0.60

    def test_custom_values(self):
        c = InvestigationConfig(
            max_hypotheses=3,
            confidence_action=0.80,
            adversarial_required=False,
        )
        assert c.max_hypotheses == 3
        assert c.confidence_action == 0.80
        assert c.adversarial_required is False
        # Unchanged defaults
        assert c.max_deepening_steps == 3
        assert c.expectation_gap_threshold == 0.15


class TestParseJsonStrict:
    """Verify JSON parser handles normal and markdown-wrapped responses."""

    def test_plain_json(self):
        assert _parse_json_strict('{"key": "val"}') == {"key": "val"}
        assert _parse_json_strict('{"priced_in_pct": 75}') == {"priced_in_pct": 75}

    def test_markdown_wrapped(self):
        result = _parse_json_strict('```json\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_markdown_no_lang(self):
        result = _parse_json_strict('```\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_embedded_json(self):
        result = _parse_json_strict('Some text before {"key": "val"} and after')
        assert result == {"key": "val"}

    def test_empty_and_invalid(self):
        assert _parse_json_strict("") is None
        assert _parse_json_strict("not json at all") is None

    def test_none_content(self):
        assert _parse_json_strict(None) is None


class TestVerdictClassification:
    """Verify verdict classification follows C6+C8 rules."""

    def _cfg(self, **kwargs) -> InvestigationConfig:
        return InvestigationConfig(**kwargs)

    def test_actionable_high_confidence(self):
        c = self._cfg()
        assert _determine_verdict(0.80, 0.30, 0.20, c) == "ACTIONABLE"

    def test_monitor_medium_confidence(self):
        c = self._cfg()
        assert _determine_verdict(0.60, 0.30, 0.20, c) == "MONITOR"
        assert _determine_verdict(0.41, 0.30, 0.20, c) == "MONITOR"

    def test_discard_low_confidence(self):
        c = self._cfg()
        assert _determine_verdict(0.30, 0.30, 0.20, c) == "DISCARD"
        assert _determine_verdict(0.10, 0.30, 0.20, c) == "DISCARD"

    def test_priced_in_override_C6(self):
        """C6 fix: expectation gap below threshold → PRICED_IN regardless of confidence."""
        c = self._cfg(expectation_gap_threshold=0.15)
        # High confidence but low gap → PRICED_IN takes priority
        assert _determine_verdict(0.80, 0.10, 0.20, c) == "PRICED_IN"
        # Boundary: exactly at threshold → not priced in
        assert _determine_verdict(0.80, 0.15, 0.20, c) == "ACTIONABLE"

    def test_high_contention_override_C8(self):
        """C8 fix: strong bear case → HIGH_CONTENTION."""
        c = self._cfg(bear_discount=0.60)
        # bear_confidence 0.55 > 0.60 * 0.80 (0.48) → HIGH_CONTENTION
        assert _determine_verdict(0.80, 0.30, 0.55, c) == "HIGH_CONTENTION"
        # bear_confidence 0.40 < 0.60 * 0.80 (0.48) → normal verdict
        assert _determine_verdict(0.80, 0.30, 0.40, c) == "ACTIONABLE"

    def test_priced_in_beats_contention(self):
        """PRICED_IN takes priority over HIGH_CONTENTION."""
        c = self._cfg(expectation_gap_threshold=0.15, bear_discount=0.60)
        assert _determine_verdict(0.80, 0.10, 0.55, c) == "PRICED_IN"

    def test_higher_threshold_less_sensitive(self):
        c = self._cfg(confidence_action=0.85, confidence_watch=0.50)
        assert _determine_verdict(0.80, 0.30, 0.20, c) == "MONITOR"
        assert _determine_verdict(0.86, 0.30, 0.20, c) == "ACTIONABLE"


class TestLayerInterpretation:
    """Verify human-readable layer score labels."""

    def test_all_ranges(self):
        assert "strongly supports" in _classify_layer_interpretation(0.95)
        assert "strongly supports" in _classify_layer_interpretation(0.80)
        assert "moderately supports" in _classify_layer_interpretation(0.60)
        assert "moderately supports" in _classify_layer_interpretation(0.79)
        assert "neutral" in _classify_layer_interpretation(0.50)
        assert "neutral" in _classify_layer_interpretation(0.40)
        assert "moderately contradicts" in _classify_layer_interpretation(0.20)
        assert "moderately contradicts" in _classify_layer_interpretation(0.39)
        assert "strongly contradicts" in _classify_layer_interpretation(0.15)
        assert "strongly contradicts" in _classify_layer_interpretation(0.01)


class TestHypothesisResult:
    """Verify HypothesisResult dataclass construction."""

    def test_defaults(self):
        v = VerificationResult(
            claim="test",
            layer_1_market=0.50,
            layer_2_fundamental=0.50,
            layer_3_multisource=0.50,
            layer_4_historical=0.50,
            weighted_confidence=0.50,
            verdict="LIKELY",
        )
        r = HypothesisResult(
            hypothesis="Fed will cut rates",
            expectation_gap=0.25,
            verification=v,
            refined_hypothesis="Fed will cut rates by 25bp",
            confidence=0.60,
            bear_case="Inflation may reaccelerate",
            bear_case_confidence=0.30,
            verdict="MONITOR",
            logic_chain=["R0: initial check", "R1: refined after verification"],
        )
        assert r.hypothesis == "Fed will cut rates"
        assert r.expectation_gap == 0.25
        assert r.confidence == 0.60
        assert r.verdict == "MONITOR"
        assert len(r.logic_chain) == 2
        assert r.verification.verdict == "LIKELY"


class TestTriageResultAlias:
    """Verify TriageResult alias for forward compatibility."""

    def test_triage_result_is_flash_signal(self):
        from marketmind.pipeline.investigation_loop import TriageResult
        from marketmind.pipeline.flash_preprocessor import FlashSignal
        assert TriageResult is FlashSignal
