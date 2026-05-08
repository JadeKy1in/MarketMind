"""Comprehensive tests for Phase 7.2 — Mosaic Reasoning Protocol.

Covers all five engines plus the orchestrator with real AlternativeSignal/AlternativeSignalMatrix
from alternative_data_hooks.py.

Test tiers:
  - Unit tests for each engine function (pure logic)
  - Integration tests for the orchestrator
  - Edge cases: empty matrix, single anomaly, one-layer anomalies, degraded signals
  - PhysicalVerificationIndicator threshold/failure validation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

# Import the real data structures
from src.alternative_data_hooks import (
    AlternativeSignal,
    AlternativeSignalMatrix,
    DegradationLevel,
    SignalDirection,
    SignalLayer,
)

from src.mosaic_reasoning import (
    CrossDomainLink,
    MosaicNarrative,
    PhysicalVerificationIndicator,
    ReverseTimelineStep,
    build_macro_narrative,
    build_reverse_timeline,
    classify_trigger_layers,
    compute_consensus_fragility,
    discover_anomalies,
    estimate_anomaly_confidence,
    generate_physical_verifications,
    map_cross_domain_links,
)


# ============================================================
# Helpers
# ============================================================


def _make_signal(
    signal_id: str = "sig_test_01",
    layer: SignalLayer = SignalLayer.L1_PUBLIC_NEGLECTED,
    direction: SignalDirection = SignalDirection.BULLISH,
    z_score: float = 2.0,
    confidence: float = 0.85,
    current_value: float = 150.0,
    is_absence: bool = False,
    absence_narrative: str = "",
    degradation: DegradationLevel = DegradationLevel.FULL_3D,
) -> AlternativeSignal:
    """Build a minimal AlternativeSignal for testing with real field names."""
    # Auto-set degradation for absence signals to avoid FULL_3D invariants violation
    if is_absence and degradation == DegradationLevel.FULL_3D:
        degradation = DegradationLevel.ABSENCE_SIGNAL
    return AlternativeSignal(
        signal_id=signal_id,
        layer=layer,
        source_name=f"src_{signal_id}",
        source_description=f"Test source for {signal_id}",
        current_value=None if is_absence or degradation == DegradationLevel.QUALITATIVE_ONLY else current_value,
        z_score=None if is_absence or degradation == DegradationLevel.QUALITATIVE_ONLY else z_score,
        direction=direction,
        confidence=None if is_absence or degradation == DegradationLevel.QUALITATIVE_ONLY else confidence,
        degradation=degradation,
        is_absence_signal=is_absence,
        absence_narrative=absence_narrative,
        proxy_chain_used=[],
    )


def _make_matrix(
    signals: List[AlternativeSignal],
    matrix_id: str = "matrix_test_01",
    divergence_warnings: Optional[List[str]] = None,
) -> AlternativeSignalMatrix:
    """Build an AlternativeSignalMatrix from a list of signals distributed across layers."""
    matrix = AlternativeSignalMatrix(
        matrix_id=matrix_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        divergence_warnings=divergence_warnings or [],
    )
    # Distribute signals to appropriate layer bins
    for sig in signals:
        layer = sig.layer
        if layer == SignalLayer.L1_PUBLIC_NEGLECTED:
            matrix.l1_signals.append(sig)
        elif layer == SignalLayer.L2_SEMI_PUBLIC:
            matrix.l2_signals.append(sig)
        elif layer == SignalLayer.L3_MICROSTRUCTURE:
            matrix.l3_signals.append(sig)
        elif layer == SignalLayer.L4_GEO_PHYSICAL:
            matrix.l4_signals.append(sig)
        elif layer == SignalLayer.L5_REFLEXIVE_META:
            matrix.l5_signals.append(sig)
        elif layer == SignalLayer.ABSENCE:
            matrix.absence_signals.append(sig)
    matrix._recompute()
    return matrix


# ============================================================
# Test 1: PhysicalVerificationIndicator
# ============================================================


class TestPhysicalVerificationIndicator:
    """PVI data class invariants and threshold logic."""

    def test_valid_pvi(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_01",
            indicator_name="us10y_yield",
            description="10Y yield must rise above 5%",
            current_value=4.35,
            target_threshold=5.0,
            target_direction="above",
            verification_deadline="2026-06-05T00:00:00Z",
            linked_logic_chain="Yield curve steepening → growth narrative",
            consequence_if_failed="Narrative invalidated",
            data_source="FRED",
            manipulation_risk="low",
        )
        assert pvi.pvi_id == "pvi_01"
        assert pvi.indicator_name == "us10y_yield"

    def test_empty_pvi_id_raises(self) -> None:
        with pytest.raises(ValueError, match="pvi_id must not be empty"):
            PhysicalVerificationIndicator(
                pvi_id="",
                indicator_name="test",
                description="desc",
                current_value=1.0,
                target_threshold=2.0,
                target_direction="above",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src",
                manipulation_risk="low",
            )

    def test_empty_indicator_name_raises(self) -> None:
        with pytest.raises(ValueError, match="indicator_name must not be empty"):
            PhysicalVerificationIndicator(
                pvi_id="pvi_01",
                indicator_name="",
                description="desc",
                current_value=1.0,
                target_threshold=2.0,
                target_direction="above",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src",
                manipulation_risk="low",
            )

    def test_invalid_target_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="target_direction must be one of"):
            PhysicalVerificationIndicator(
                pvi_id="pvi_01",
                indicator_name="test",
                description="desc",
                current_value=1.0,
                target_threshold=2.0,
                target_direction="sideways",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src",
                manipulation_risk="low",
            )

    def test_is_verified_above(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_01",
            indicator_name="test",
            description="desc",
            current_value=4.35,
            target_threshold=5.0,
            target_direction="above",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.is_verified(5.5) is True
        assert pvi.is_verified(4.99) is False
        assert pvi.is_verified(5.0) is True  # Exactly at threshold

    def test_is_verified_below(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_02",
            indicator_name="test",
            description="desc",
            current_value=15.5,
            target_threshold=15.0,
            target_direction="below",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.is_verified(14.0) is True
        assert pvi.is_verified(15.5) is False
        assert pvi.is_verified(15.0) is True  # Exactly at threshold

    def test_is_verified_between(self) -> None:
        """'between' direction treated as exact match."""
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_03",
            indicator_name="test",
            description="desc",
            current_value=100.0,
            target_threshold=100.0,
            target_direction="between",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.is_verified(100.0) is True
        assert pvi.is_verified(99.9) is False

    def test_verification_status_pending(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_01",
            indicator_name="test",
            description="desc",
            current_value=4.0,
            target_threshold=5.0,
            target_direction="above",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.verification_status(None) == "PENDING"

    def test_verification_status_verified(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_01",
            indicator_name="test",
            description="desc",
            current_value=4.0,
            target_threshold=5.0,
            target_direction="above",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.verification_status(5.5) == "VERIFIED"

    def test_verification_status_failed(self) -> None:
        pvi = PhysicalVerificationIndicator(
            pvi_id="pvi_01",
            indicator_name="test",
            description="desc",
            current_value=4.0,
            target_threshold=5.0,
            target_direction="above",
            verification_deadline="2026-06-05",
            linked_logic_chain="chain",
            consequence_if_failed="fail",
            data_source="src",
            manipulation_risk="low",
        )
        assert pvi.verification_status(4.5) == "FAILED"

    def test_negative_threshold_sanity_check(self) -> None:
        """Negative thresholds with current already above target indicates unrealistic metrics."""
        with pytest.raises(ValueError, match="seems unrealistic"):
            PhysicalVerificationIndicator(
                pvi_id="pvi_01",
                indicator_name="test",
                description="desc",
                current_value=-5.0,
                target_threshold=-10.0,
                target_direction="above",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src",
                manipulation_risk="low",
            )


# ============================================================
# Test 2: MosaicNarrative invariants
# ============================================================


class TestMosaicNarrative:
    """MosaicNarrative data class invariants and validation."""

    def make_valid_narrative(self) -> MosaicNarrative:
        pvis = [
            PhysicalVerificationIndicator(
                pvi_id=f"pvi_{i}", indicator_name=f"ind_{i}",
                description="desc", current_value=1.0,
                target_threshold=2.0, target_direction="above",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src", manipulation_risk="low",
            )
            for i in range(3)
        ]
        return MosaicNarrative(
            narrative_id="mn_test_01",
            generated_at=datetime.now(timezone.utc).isoformat(),
            macro_theme="Test regime shift",
            confidence=0.75,
            physical_verifications=pvis,
        )

    def test_valid_narrative(self) -> None:
        n = self.make_valid_narrative()
        assert n.pvi_count >= 3
        assert n.has_physical_verification_passed() is False  # current < threshold

    def test_empty_narrative_id_raises(self) -> None:
        with pytest.raises(ValueError, match="narrative_id must not be empty"):
            MosaicNarrative(
                narrative_id="",
                generated_at="2026-01-01",
                macro_theme="test",
                confidence=0.5,
            )

    def test_empty_macro_theme_raises(self) -> None:
        with pytest.raises(ValueError, match="macro_theme must not be empty"):
            MosaicNarrative(
                narrative_id="mn_01",
                generated_at="2026-01-01",
                macro_theme="",
                confidence=0.5,
            )

    def test_empty_generated_at_raises(self) -> None:
        with pytest.raises(ValueError, match="generated_at must not be empty"):
            MosaicNarrative(
                narrative_id="mn_01",
                generated_at="",
                macro_theme="test",
                confidence=0.5,
            )

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            MosaicNarrative(
                narrative_id="mn_01",
                generated_at="2026-01-01",
                macro_theme="test",
                confidence=1.5,
            )

    def test_consensus_fragility_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="consensus_fragility must be in"):
            MosaicNarrative(
                narrative_id="mn_01",
                generated_at="2026-01-01",
                macro_theme="test",
                confidence=0.5,
                consensus_fragility=150.0,
            )

    def test_less_than_3_pvis_raises(self) -> None:
        pvis = [
            PhysicalVerificationIndicator(
                pvi_id="pvi_0", indicator_name="ind_0",
                description="desc", current_value=1.0,
                target_threshold=2.0, target_direction="above",
                verification_deadline="2026-06-05",
                linked_logic_chain="chain",
                consequence_if_failed="fail",
                data_source="src", manipulation_risk="low",
            )
            for i in range(2)
        ]
        with pytest.raises(ValueError, match="at least 3 PhysicalVerificationIndicators"):
            MosaicNarrative(
                narrative_id="mn_01",
                generated_at="2026-01-01",
                macro_theme="test",
                confidence=0.5,
                physical_verifications=pvis,
            )

    def test_property_counts(self) -> None:
        n = self.make_valid_narrative()
        n.anomaly_signals_used = ["sig_a", "sig_b"]
        n.cross_domain_links = [
            CrossDomainLink(
                link_id="cdl_001",
                source_a="a", source_b="b",
                intermediate_variable="test_var",
                causal_description="chain",
                weakest_assumption="assumption",
                confidence=0.8,
            )
        ]
        n.reverse_timeline = [
            ReverseTimelineStep(
                step_label="T-0", days_offset=0,
                actor_description="actor",
                action_description="action",
                motivation="motive",
                observable_trace="trace",
            )
        ]
        assert n.anomaly_signal_count == 2
        assert n.cross_domain_link_count == 1
        assert n.reverse_timeline_count == 1
        assert n.pvi_count == 3


# ============================================================
# Test 3: CrossDomainLink invariants
# ============================================================


class TestCrossDomainLink:
    def test_invalid_confidence_low(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            CrossDomainLink(
                link_id="cdl_001",
                source_a="a", source_b="b",
                intermediate_variable="var",
                causal_description="desc",
                weakest_assumption="assump",
                confidence=-0.1,
            )

    def test_invalid_confidence_high(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            CrossDomainLink(
                link_id="cdl_001",
                source_a="a", source_b="b",
                intermediate_variable="var",
                causal_description="desc",
                weakest_assumption="assump",
                confidence=1.5,
            )


# ============================================================
# Test 4: Anomaly-First Discovery (Engine 1)
# ============================================================


class TestDiscoverAnomalies:
    def test_detects_high_z_score(self) -> None:
        sig = _make_signal(signal_id="sig_a", z_score=2.5, confidence=0.9)
        sig2 = _make_signal(signal_id="sig_b", z_score=1.0, confidence=0.8)
        matrix = _make_matrix([sig, sig2])
        anomalies = discover_anomalies(matrix)
        assert len(anomalies) == 1
        assert anomalies[0].signal_id == "sig_a"

    def test_detects_absence_signal_regardless_of_z(self) -> None:
        sig = _make_signal(
            signal_id="sig_absence",
            is_absence=True,
            absence_narrative="Data disappeared",
            degradation=DegradationLevel.ABSENCE_SIGNAL,
            z_score=None,
            confidence=None,
            current_value=None,
        )
        matrix = _make_matrix([sig])
        anomalies = discover_anomalies(matrix)
        assert len(anomalies) == 1
        assert anomalies[0].signal_id == "sig_absence"

    def test_custom_z_threshold(self) -> None:
        sig = _make_signal(signal_id="sig_a", z_score=1.2, confidence=0.8)
        matrix = _make_matrix([sig])
        anomalies = discover_anomalies(matrix, z_threshold=1.0)
        assert len(anomalies) == 1

    def test_no_anomalies_returns_empty(self) -> None:
        sig = _make_signal(signal_id="sig_a", z_score=0.5, confidence=0.8)
        matrix = _make_matrix([sig])
        anomalies = discover_anomalies(matrix)
        assert anomalies == []

    def test_sort_order_descending(self) -> None:
        sigs = [
            _make_signal(signal_id=f"s{i}", z_score=float(v), confidence=0.8)
            for i, v in enumerate([0.5, 2.0, 3.0, 1.6])
        ]
        matrix = _make_matrix(sigs)
        anomalies = discover_anomalies(matrix)
        ids = [s.signal_id for s in anomalies]
        assert ids == ["s2", "s1", "s3"]  # sorted by abs(z_score) desc


class TestClassifyTriggerLayers:
    def test_unique_layers_in_order(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=2.0),
            _make_signal(signal_id="s2", layer=SignalLayer.L3_MICROSTRUCTURE, z_score=2.5),
            _make_signal(signal_id="s3", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=3.0),
        ]
        layers = classify_trigger_layers(sigs)
        assert layers == ["layer_1_public_neglected", "layer_3_microstructure"]

    def test_empty_list(self) -> None:
        assert classify_trigger_layers([]) == []


class TestEstimateAnomalyConfidence:
    def test_multi_layer_high_confidence(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=2.0, confidence=0.9),
            _make_signal(signal_id="s2", layer=SignalLayer.L3_MICROSTRUCTURE, z_score=2.5, confidence=0.85),
        ]
        conf = estimate_anomaly_confidence(sigs)
        # unique_layers=2, layer_ratio=2/6=0.333, avg_conf=(0.9+0.85)/2=0.875
        # raw = 0.333*0.8 + 0.875*0.2 = 0.2667 + 0.175 = 0.4417
        assert conf == pytest.approx(0.4417, rel=1e-3)

    def test_single_layer_lower_confidence(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=2.0, confidence=0.6),
        ]
        conf = estimate_anomaly_confidence(sigs)
        # unique_layers=1, layer_ratio=1/6=0.1667, avg_conf=0.6
        # raw = 0.1667*0.8 + 0.6*0.2 = 0.1333 + 0.12 = 0.2533
        assert conf == pytest.approx(0.2533, rel=1e-3)

    def test_empty_returns_zero(self) -> None:
        assert estimate_anomaly_confidence([]) == 0.0

    def test_capped_at_one(self) -> None:
        sigs = [_make_signal(signal_id=f"s{i}", layer=l, z_score=10.0, confidence=1.0)
                for i, l in enumerate([
                    SignalLayer.L1_PUBLIC_NEGLECTED,
                    SignalLayer.L2_SEMI_PUBLIC,
                    SignalLayer.L3_MICROSTRUCTURE,
                    SignalLayer.L4_GEO_PHYSICAL,
                    SignalLayer.L5_REFLEXIVE_META,
                ])]
        conf = estimate_anomaly_confidence(sigs)
        assert conf <= 1.0


# ============================================================
# Test 5: Forced Cross-Domain Mapping (Engine 2)
# ============================================================


class TestMapCrossDomainLinks:
    def test_two_layers_produces_link(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=2.0),
            _make_signal(signal_id="s2", layer=SignalLayer.L3_MICROSTRUCTURE, z_score=3.0),
        ]
        links = map_cross_domain_links(sigs)
        assert len(links) == 1
        assert links[0].source_a == "s1"
        assert links[0].source_b == "s2"
        assert links[0].intermediate_variable == "MarketDepthLiquidityShift"

    def test_same_layer_returns_empty(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=2.0),
            _make_signal(signal_id="s2", layer=SignalLayer.L1_PUBLIC_NEGLECTED, z_score=3.0),
        ]
        links = map_cross_domain_links(sigs)
        assert links == []

    def test_single_anomaly_returns_empty(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0)]
        links = map_cross_domain_links(sigs)
        assert links == []

    def test_divergent_directions_use_divergent_intermediate(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                         z_score=2.0, direction=SignalDirection.BULLISH),
            _make_signal(signal_id="s2", layer=SignalLayer.L3_MICROSTRUCTURE,
                         z_score=3.0, direction=SignalDirection.BEARISH),
        ]
        links = map_cross_domain_links(sigs)
        assert len(links) == 1
        assert links[0].intermediate_variable == "InterLayerDisconnect"

    def test_confidence_bounded(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                         z_score=10.0, confidence=1.0),
            _make_signal(signal_id="s2", layer=SignalLayer.L2_SEMI_PUBLIC,
                         z_score=10.0, confidence=1.0),
        ]
        links = map_cross_domain_links(sigs)
        assert all(0.0 <= l.confidence <= 1.0 for l in links)


# ============================================================
# Test 6: Reverse Timeline Reasoning (Engine 3)
# ============================================================


class TestBuildReverseTimeline:
    def test_bullish_timeline_has_accumulation(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0, direction=SignalDirection.BULLISH)]
        timeline = build_reverse_timeline(sigs, SignalDirection.BULLISH, "test_theme")
        assert len(timeline) == 4
        assert any("Accumulation" in step.action_description for step in timeline)
        assert timeline[0].step_label == "T-0"
        assert timeline[-1].step_label == "T-90"

    def test_bearish_timeline_has_distribution(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0, direction=SignalDirection.BEARISH)]
        timeline = build_reverse_timeline(sigs, SignalDirection.BEARISH, "recession")
        assert any("Distribution" in step.action_description for step in timeline)

    def test_empty_anomalies_uses_default(self) -> None:
        timeline = build_reverse_timeline([], SignalDirection.BEARISH)
        assert len(timeline) == 4
        # Default timeline uses "Marginal price setter" for T-0
        assert timeline[0].actor_description == "Marginal price setter"

    def test_timeline_step_structure(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0)]
        timeline = build_reverse_timeline(sigs, SignalDirection.BULLISH, "growth")
        step = timeline[0]
        assert step.step_label
        assert isinstance(step.days_offset, int)
        assert step.actor_description
        assert step.action_description
        assert step.motivation
        assert step.observable_trace


# ============================================================
# Test 7: Consensus Fragility (Engine 4)
# ============================================================


class TestComputeConsensusFragility:
    def test_baseline_only(self) -> None:
        sig = _make_signal(signal_id="s1", z_score=2.0, confidence=0.9)
        matrix = _make_matrix([sig])
        score, drivers = compute_consensus_fragility(matrix, [sig], 1)
        # baseline 50 + deficit (3-1)*10 = 20 → 70
        assert score >= 50.0
        assert "Baseline 50" in drivers

    def test_divergence_penalty(self) -> None:
        sig = _make_signal(signal_id="s1", z_score=2.0, confidence=0.9)
        matrix = _make_matrix([sig], divergence_warnings=["Divergence L1 vs L3", "Divergence L2 vs L4"])
        score, drivers = compute_consensus_fragility(matrix, [sig], 1)
        # baseline 50 + 2*12=24 + deficit 20 = 94
        assert score >= 74.0
        assert any("divergence" in d.lower() for d in drivers)

    def test_degradation_penalty(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", z_score=2.0, confidence=0.9),
            _make_signal(signal_id="s2", z_score=None, confidence=None,
                         current_value=None, degradation=DegradationLevel.QUALITATIVE_ONLY),
        ]
        matrix = _make_matrix(sigs)
        anomalies = [sigs[0]]  # only the non-degraded is anomalous
        score, drivers = compute_consensus_fragility(matrix, anomalies, 1)
        # baseline 50 + deficit 20 + (degraded 1/2)*20 = 10 → 80
        assert any("degradation" in d.lower() for d in drivers)

    def test_crowding_penalty(self) -> None:
        sigs = [
            _make_signal(signal_id=f"s{i}", z_score=2.0,
                         direction=SignalDirection.BULLISH, confidence=0.9)
            for i in range(4)
        ]
        matrix = _make_matrix(sigs)
        anomalies = sigs  # all anomalies same direction
        score, drivers = compute_consensus_fragility(matrix, anomalies, 1)
        # baseline 50 + deficit 20 + crowding 4/4 same → (1.0-0.7)*50=15 → 85
        assert any("crowding" in d.lower() for d in drivers)

    def test_no_anomalies_max_fragility(self) -> None:
        matrix = _make_matrix([])
        score, drivers = compute_consensus_fragility(matrix, [], 0)
        assert score == 100.0
        assert "No anomalous signals" in drivers[0]

    def test_score_capped_at_100(self) -> None:
        sig = _make_signal(signal_id="s1", z_score=2.0, confidence=0.9)
        matrix = _make_matrix([sig], divergence_warnings=["w1", "w2", "w3", "w4", "w5"])
        anomalies = [sig]
        score, drivers = compute_consensus_fragility(matrix, anomalies, 0)
        # baseline 50 + 5*12=60 + deficit 30 = 140 → capped 100
        assert score == 100.0


# ============================================================
# Test 8: Physical Verification Lock Generator (Engine 5)
# ============================================================


class TestGeneratePhysicalVerifications:
    def test_bullish_produces_4_pvis(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0, direction=SignalDirection.BULLISH)]
        pvis = generate_physical_verifications(sigs, SignalDirection.BULLISH, "growth")
        assert len(pvis) >= 3
        assert any("us10y_yield" in p.indicator_name for p in pvis)

    def test_bearish_produces_4_pvis(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0, direction=SignalDirection.BEARISH)]
        pvis = generate_physical_verifications(sigs, SignalDirection.BEARISH, "recession")
        assert len(pvis) >= 3
        assert any("us10y_yield" in p.indicator_name for p in pvis)
        yield_pvi = next(p for p in pvis if p.indicator_name == "us10y_yield")
        assert yield_pvi.target_direction == "below"

    def test_microstructure_triggers_vix_above(self) -> None:
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L3_MICROSTRUCTURE,
                         z_score=2.0, direction=SignalDirection.BULLISH),
        ]
        pvis = generate_physical_verifications(sigs, SignalDirection.BULLISH, "vol")
        vix_pvi = next(p for p in pvis if p.indicator_name == "vix")
        assert vix_pvi.target_direction == "above"
        assert vix_pvi.target_threshold == 22.0

    def test_no_microstructure_vix_below(self) -> None:
        sigs = [_make_signal(signal_id="s1", z_score=2.0, direction=SignalDirection.BULLISH)]
        pvis = generate_physical_verifications(sigs, SignalDirection.BULLISH)
        vix_pvi = next(p for p in pvis if p.indicator_name == "vix")
        assert vix_pvi.target_direction == "below"
        assert vix_pvi.target_threshold == 15.0

    def test_geo_physical_layer_uses_commodity(self) -> None:
        sigs = [
            _make_signal(
                signal_id="s1",
                layer=SignalLayer.L4_GEO_PHYSICAL,
                z_score=2.0,
                direction=SignalDirection.BULLISH,
            ),
        ]
        pvis = generate_physical_verifications(sigs, SignalDirection.BULLISH, "commodity")
        assert any("commodity_index" in p.indicator_name for p in pvis)
        oil_pvi = next(p for p in pvis if "commodity" in p.indicator_name)
        assert oil_pvi.target_direction in ("above", "below")


# ============================================================
# Test 9: Orchestrator Integration Tests
# ============================================================


class TestBuildMacroNarrativeOrchestrator:
    """End-to-end tests for build_macro_narrative orchestrator."""

    def test_orchestrator_full_pipeline(self) -> None:
        """Integration: orchestrator produces a valid MosaicNarrative from a real matrix."""
        sigs = [
            _make_signal(signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                         z_score=2.5, direction=SignalDirection.BULLISH, confidence=0.9),
            _make_signal(signal_id="s2", layer=SignalLayer.L3_MICROSTRUCTURE,
                         z_score=3.0, direction=SignalDirection.BULLISH, confidence=0.85),
            _make_signal(signal_id="s3", layer=SignalLayer.L5_REFLEXIVE_META,
                         z_score=1.8, direction=SignalDirection.BULLISH, confidence=0.7,
                         is_absence=True, absence_narrative="Meta data gap detected"),
            _make_signal(signal_id="s4", layer=SignalLayer.L2_SEMI_PUBLIC,
                         z_score=0.8, direction=SignalDirection.BULLISH, confidence=0.6),
        ]
        matrix = _make_matrix(sigs, divergence_warnings=["Divergence L1 vs L3"])
        narrative = build_macro_narrative(matrix)
        assert isinstance(narrative, MosaicNarrative)
        assert narrative.narrative_id
        assert narrative.macro_theme
        assert 0.0 <= narrative.confidence <= 1