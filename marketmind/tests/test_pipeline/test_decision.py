"""Tests for signal conflict detection in decision.py."""

from unittest.mock import Mock

from marketmind.pipeline.decision import (
    SignalConflict,
    _detect_signal_conflicts,
    _build_decision_prompt,
)
from marketmind.pipeline.investigation_types import HypothesisResult
from marketmind.pipeline.verification_chain import VerificationResult


def _make_vr(confidence: float = 0.81) -> VerificationResult:
    return VerificationResult(
        claim="Test claim",
        layer_1_market=confidence,
        layer_2_fundamental=confidence,
        layer_3_multisource=confidence,
        layer_4_historical=confidence,
        weighted_confidence=confidence,
        verdict="VERIFIED",
        sources_used=["source_a", "source_b"],
    )


def _make_hypothesis(**kwargs) -> HypothesisResult:
    defaults = dict(
        hypothesis="Test hypothesis",
        expectation_gap=0.15,
        verification=_make_vr(),
        refined_hypothesis="EUR/USD bullish on ECB rate hike expectations",
        confidence=0.81,
        bear_case="Fed surprise hike could reverse gains",
        bear_case_confidence=0.35,
        verdict="ACTIONABLE",
        logic_chain=["Step 1", "Step 2"],
        direction="EUR/USD 看涨",
        risk_level="中等",
        time_window="2-4周",
        layer_1_narrative="Market pricing shows EUR undervalued ~5%",
        layer_2_narrative="European fundamentals improving, PMI rising",
        core_logic="ECB rate hike expectation drives EUR strength",
    )
    defaults.update(kwargs)
    return HypothesisResult(**defaults)


# ── _detect_signal_conflicts tests ────────────────────────────────────────────

def test_no_conflicts_when_signals_align():
    """Aligned signals → no conflicts."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.6)
    h.flow = Mock(flow_imbalance=0.5)
    h.scenario_tree = Mock(base_case=Mock(confidence=0.80))
    h.fragility_score = 0.20

    conflicts = _detect_signal_conflicts([h])
    assert conflicts == []


def test_conflict_detected_when_divergence_high():
    """causal=+0.8 vs flow=-0.3 → divergence 1.1 > 0.4 → conflict."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.8)
    h.flow = Mock(flow_imbalance=-0.3)
    h.scenario_tree = Mock(base_case=Mock(confidence=0.80))
    h.fragility_score = 0.20

    conflicts = _detect_signal_conflicts([h])
    assert len(conflicts) == 1
    assert conflicts[0].signal_a == ("causal_decomposition", 0.8)
    assert conflicts[0].signal_b == ("flow_decomposition", -0.3)
    assert conflicts[0].divergence == 1.1
    assert "因果分解" in conflicts[0].description


def test_scenario_vs_fragility_conflict():
    """scenario confidence=0.9 vs fragility=0.85 → divergence 0.75 > 0.4 → conflict."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.5)
    h.flow = Mock(flow_imbalance=0.5)
    h.scenario_tree = Mock(base_case=Mock(confidence=0.90))
    h.fragility_score = 0.85

    conflicts = _detect_signal_conflicts([h])
    assert len(conflicts) == 1
    assert conflicts[0].signal_a == ("scenario_forecaster", 0.90)
    assert conflicts[0].signal_b[0] == "fragility_scanner"
    assert abs(conflicts[0].signal_b[1] - 0.15) < 1e-9
    assert "情景预测置信" in conflicts[0].description


def test_both_conflict_types_detected():
    """When both causal/flow and scenario/fragility diverge, both conflicts reported."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.9)
    h.flow = Mock(flow_imbalance=-0.1)
    h.scenario_tree = Mock(base_case=Mock(confidence=0.95))
    h.fragility_score = 0.90

    conflicts = _detect_signal_conflicts([h])
    assert len(conflicts) == 2


def test_missing_causal_or_flow_skips_that_check():
    """If hypothesis has no causal attribute, skip causal/flow check."""
    h = _make_hypothesis()
    h.scenario_tree = Mock(base_case=Mock(confidence=0.90))
    h.fragility_score = 0.85

    conflicts = _detect_signal_conflicts([h])
    assert len(conflicts) == 1
    assert conflicts[0].signal_a[0] == "scenario_forecaster"


def test_missing_scenario_tree_skips_fragility_check():
    """If hypothesis has no scenario_tree, skip scenario/fragility check."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.9)
    h.flow = Mock(flow_imbalance=-0.1)

    conflicts = _detect_signal_conflicts([h])
    assert len(conflicts) == 1
    assert conflicts[0].signal_a[0] == "causal_decomposition"


def test_missing_fragility_score_skips_check():
    """If hypothesis has scenario_tree but no fragility_score, skip that check."""
    h = _make_hypothesis()
    h.scenario_tree = Mock(base_case=Mock(confidence=0.90))

    conflicts = _detect_signal_conflicts([h])
    assert conflicts == []


def test_empty_list_returns_empty():
    """Empty input → empty output."""
    assert _detect_signal_conflicts([]) == []


def test_none_hypothesis_skipped():
    """None entries in the list are skipped."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.9)
    h.flow = Mock(flow_imbalance=-0.1)

    conflicts = _detect_signal_conflicts([None, h, None])
    assert len(conflicts) == 1


def test_divergence_exactly_at_threshold_not_flagged():
    """Divergence == 0.4 exactly → not flagged (must be > 0.4)."""
    h = _make_hypothesis()
    h.causal = Mock(net_directional_force=0.4)
    h.flow = Mock(flow_imbalance=0.0)

    conflicts = _detect_signal_conflicts([h])
    assert conflicts == []


def test_multiple_hypotheses_each_checked():
    """Each hypothesis is independently checked for conflicts."""
    h1 = _make_hypothesis(refined_hypothesis="Hypothesis A")
    h1.causal = Mock(net_directional_force=0.9)
    h1.flow = Mock(flow_imbalance=-0.1)

    h2 = _make_hypothesis(refined_hypothesis="Hypothesis B")
    h2.causal = Mock(net_directional_force=0.5)
    h2.flow = Mock(flow_imbalance=0.4)

    h3 = _make_hypothesis(refined_hypothesis="Hypothesis C")
    h3.causal = Mock(net_directional_force=0.9)
    h3.flow = Mock(flow_imbalance=-0.2)
    h3.scenario_tree = Mock(base_case=Mock(confidence=0.95))
    h3.fragility_score = 0.90

    conflicts = _detect_signal_conflicts([h1, h2, h3])
    assert len(conflicts) == 3  # h1 has 1, h2 none, h3 has 2
