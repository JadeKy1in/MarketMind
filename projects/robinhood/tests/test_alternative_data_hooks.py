"""Unit tests for Phase 7.1 — alternative_data_hooks module.

Test coverage:
  - Enum validation (SignalLayer, SignalDirection, DegradationLevel)
  - ProxyRoute / ProxyResolution dataclasses
  - ProxyRouter: pass-through, fallback chain, all-fail → absence
  - AlternativeSignal dataclass invariants (+ FULL_3D / QUALITATIVE_ONLY / ABSENCE_SIGNAL)
  - AlternativeSignal.confidence_tag() for all degradation states
  - AlternativeSignalMatrix construction, convergence, divergence (+ degradation tracking)
  - build_absence_signal
  - build_signal_with_proxy
  - compute_z_score / compute_z_score_from_stats
  - create_default_proxy_router
  - Fetcher stubs with proxy routing
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.alternative_data_hooks import (
    SignalLayer,
    SignalDirection,
    DegradationLevel,
    ProxyRoute,
    ProxyResolution,
    ProxyRouter,
    AlternativeSignal,
    AlternativeSignalMatrix,
    compute_z_score,
    compute_z_score_from_stats,
    build_absence_signal,
    build_signal_with_proxy,
    create_default_proxy_router,
    fetch_with_proxy_routing,
    fetch_sec_edgar_signals,
    fetch_cot_report_signals,
    fetch_crypto_privacy_signals,
    fetch_ceo_departure_signals,
)


# ============================================================
# Enum tests
# ============================================================


class TestSignalLayer:
    def test_layer_count(self) -> None:
        """6 concrete layers: L1-L5 + ABSENCE = 6."""
        assert len(SignalLayer) == 6

    def test_layer_values_distinct(self) -> None:
        vals = [m.value for m in SignalLayer]
        assert len(vals) == len(set(vals))

    def test_concrete_member(self) -> None:
        assert SignalLayer.L1_PUBLIC_NEGLECTED.value == "layer_1_public_neglected"

    def test_absence_member(self) -> None:
        assert SignalLayer.ABSENCE.value == "layer_absence_signal"


class TestSignalDirection:
    def test_direction_count(self) -> None:
        assert len(SignalDirection) == 4

    def test_concrete_member(self) -> None:
        assert SignalDirection.DIVERGENT.value == "divergent"


class TestDegradationLevel:
    def test_level_count(self) -> None:
        assert len(DegradationLevel) == 7

    def test_values_distinct(self) -> None:
        vals = [m.value for m in DegradationLevel]
        assert len(vals) == len(set(vals))

    def test_concrete_members(self) -> None:
        assert DegradationLevel.FULL_3D.value == "full_3d"
        assert DegradationLevel.QUANTITATIVE_2D.value == "quantitative_2d"
        assert DegradationLevel.QUALITATIVE_ONLY.value == "qualitative_only"
        assert DegradationLevel.ABSENCE_SIGNAL.value == "absence_signal"


# ============================================================
# Proxy Routing
# ============================================================


class TestProxyRoute:
    def test_basic_construction(self) -> None:
        route = ProxyRoute(
            primary_source="test_primary",
            proxies=["proxy_a", "proxy_b"],
            proxy_descriptions={"proxy_a": "Alpha"},
            layer_hint=SignalLayer.L3_MICROSTRUCTURE,
        )
        assert route.primary_source == "test_primary"
        assert route.proxies == ["proxy_a", "proxy_b"]
        assert route.proxy_descriptions["proxy_a"] == "Alpha"
        assert route.layer_hint == SignalLayer.L3_MICROSTRUCTURE

    def test_default_layer(self) -> None:
        route = ProxyRoute(primary_source="x", proxies=[])
        assert route.layer_hint == SignalLayer.L3_MICROSTRUCTURE


class TestProxyResolution:
    def test_full_success(self) -> None:
        r = ProxyResolution(
            source_used="primary",
            proxy_chain_tried=["primary"],
            proxy_chain_index=0,
            degradation=DegradationLevel.FULL_3D,
        )
        assert r.fallback_description == ""

    def test_failure_absence(self) -> None:
        r = ProxyResolution(
            source_used="primary",
            proxy_chain_tried=["primary", "proxy_a"],
            proxy_chain_index=-1,
            degradation=DegradationLevel.ABSENCE_SIGNAL,
            failure_reason="All sources unavailable",
        )
        assert r.proxy_chain_index == -1
        assert "unavailable" in r.failure_reason


class TestProxyRouter:
    """Verify ProxyRouter resolve logic.

    Covers: pass-through (no route), primary success, proxy fallback,
    checker blocking, all-fail → absence signal, custom checker.
    """

    def test_no_route_registered_falls_through(self) -> None:
        """No route registered → assumes primary is available (FULL_3D)."""
        router = ProxyRouter()
        result = router.resolve("unknown_source")
        assert result.source_used == "unknown_source"
        assert result.proxy_chain_index == 0
        assert result.degradation == DegradationLevel.FULL_3D

    def test_primary_available_full_3d(self) -> None:
        """Primary source resolves → FULL_3D."""
        router = ProxyRouter()
        router.register_route(
            "primary", ProxyRoute(primary_source="primary", proxies=[])
        )
        result = router.resolve("primary")
        assert result.source_used == "primary"
        assert result.proxy_chain_index == 0
        assert result.degradation == DegradationLevel.FULL_3D

    def test_first_proxy_fallback_quantitative_2d(self) -> None:
        """Primary blocked, first proxy succeeds → QUANTITATIVE_2D."""
        router = ProxyRouter()
        router.register_route(
            "primary",
            ProxyRoute(
                primary_source="primary",
                proxies=["proxy_a"],
                proxy_descriptions={"proxy_a": "Fallback A"},
            ),
        )
        router.register_checker("primary", lambda: False)  # primary fails
        router.register_checker("proxy_a", lambda: True)   # proxy succeeds

        result = router.resolve("primary")
        assert result.source_used == "proxy_a"
        assert result.proxy_chain_index == 1
        assert result.degradation == DegradationLevel.QUANTITATIVE_2D
        assert "Fallback A" in result.fallback_description

    def test_deeper_proxy_fallback_qualitative_only(self) -> None:
        """Primary + first proxy fail, second succeeds → QUALITATIVE_ONLY."""
        router = ProxyRouter()
        router.register_route(
            "primary",
            ProxyRoute(
                primary_source="primary",
                proxies=["proxy_a", "proxy_b"],
                proxy_descriptions={"proxy_b": "Deep fallback"},
            ),
        )
        router.register_checker("primary", lambda: False)
        router.register_checker("proxy_a", lambda: False)
        router.register_checker("proxy_b", lambda: True)

        result = router.resolve("primary")
        assert result.source_used == "proxy_b"
        assert result.proxy_chain_index == 2
        assert result.degradation == DegradationLevel.QUALITATIVE_ONLY

    def test_all_sources_fail_absence_signal(self) -> None:
        """All sources fail → ABSENCE_SIGNAL with failure_reason."""
        router = ProxyRouter()
        router.register_route(
            "primary",
            ProxyRoute(primary_source="primary", proxies=["proxy_a"]),
        )
        router.register_checker("primary", lambda: False)
        router.register_checker("proxy_a", lambda: False)

        result = router.resolve("primary")
        assert result.proxy_chain_index == -1
        assert result.degradation == DegradationLevel.ABSENCE_SIGNAL
        assert "All 2 sources" in result.failure_reason

    def test_no_checker_assumes_available(self) -> None:
        """No checker registered for a source → assumed available."""
        router = ProxyRouter()
        router.register_route(
            "primary",
            ProxyRoute(primary_source="primary", proxies=[]),
        )
        result = router.resolve("primary")
        assert result.proxy_chain_index == 0

    def test_proxy_chain_without_descriptions(self) -> None:
        """Fallback_description falls back to source name."""
        router = ProxyRouter()
        router.register_route(
            "primary",
            ProxyRoute(primary_source="primary", proxies=["proxy_a"]),
        )
        router.register_checker("primary", lambda: False)
        router.register_checker("proxy_a", lambda: True)

        result = router.resolve("primary")
        assert "proxy_a" in result.fallback_description


# ============================================================
# AlternativeSignal dataclass
# ============================================================


class TestAlternativeSignalConstruction:
    """Verify dataclass invariants via __post_init__."""

    def make_full_3d_signal(
        self,
        signal_id: str = "sig_001",
        layer: SignalLayer = SignalLayer.L3_MICROSTRUCTURE,
        source_name: str = "monero_btc_ratio",
        source_description: str = "Monero/BTC price ratio",
        current_value: float = 0.0042,
        baseline_mean: float = 0.0050,
        baseline_std: float = 0.0005,
        z_score: float = -1.6,
        direction: SignalDirection = SignalDirection.BEARISH,
        confidence: float = 0.75,
        lookback_window_days: int = 90,
        last_updated: str = "2026-05-05T12:00:00+00:00",
        reasoning_hook: str = "",
        manipulation_risk: str = "",
        degradation: DegradationLevel = DegradationLevel.FULL_3D,
        proxy_chain_used: list[str] | None = None,
        is_absence_signal: bool = False,
        absence_narrative: str = "",
    ) -> AlternativeSignal:
        return AlternativeSignal(
            signal_id=signal_id,
            layer=layer,
            source_name=source_name,
            source_description=source_description,
            current_value=current_value,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            z_score=z_score,
            direction=direction,
            confidence=confidence,
            lookback_window_days=lookback_window_days,
            last_updated=last_updated,
            reasoning_hook=reasoning_hook,
            manipulation_risk=manipulation_risk,
            degradation=degradation,
            proxy_chain_used=proxy_chain_used or [],
            is_absence_signal=is_absence_signal,
            absence_narrative=absence_narrative,
        )

    def test_basic_construction(self) -> None:
        s = self.make_full_3d_signal()
        assert s.signal_id == "sig_001"
        assert s.z_score == -1.6
        assert s.direction == SignalDirection.BEARISH
        assert s.degradation == DegradationLevel.FULL_3D

    def test_confidence_floor(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            self.make_full_3d_signal(confidence=-0.01)

    def test_confidence_ceiling(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            self.make_full_3d_signal(confidence=1.1)

    def test_confidence_zero(self) -> None:
        s = self.make_full_3d_signal(confidence=0.0)
        assert s.confidence == 0.0

    def test_confidence_one(self) -> None:
        s = self.make_full_3d_signal(confidence=1.0)
        assert s.confidence == 1.0

    def test_empty_signal_id(self) -> None:
        with pytest.raises(ValueError, match="signal_id must not be empty"):
            self.make_full_3d_signal(signal_id="")

    def test_empty_source_name(self) -> None:
        with pytest.raises(ValueError, match="source_name must not be empty"):
            self.make_full_3d_signal(source_name="")

    def test_full_3d_missing_value_raises(self) -> None:
        with pytest.raises(ValueError, match="FULL_3D requires"):
            self.make_full_3d_signal(current_value=None)

    def test_full_3d_missing_z_score_raises(self) -> None:
        with pytest.raises(ValueError, match="FULL_3D requires"):
            self.make_full_3d_signal(z_score=None)

    def test_full_3d_missing_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="FULL_3D requires"):
            self.make_full_3d_signal(confidence=None)

    def test_qualitative_only_rejects_value(self) -> None:
        with pytest.raises(ValueError, match="QUALITATIVE_ONLY must have"):
            self.make_full_3d_signal(
                degradation=DegradationLevel.QUALITATIVE_ONLY,
                current_value=10.0,
            )

    def test_qualitative_only_rejects_z_score(self) -> None:
        with pytest.raises(ValueError, match="QUALITATIVE_ONLY must have"):
            self.make_full_3d_signal(
                degradation=DegradationLevel.QUALITATIVE_ONLY,
                z_score=0.5,
            )

    def test_qualitative_only_rejects_confidence(self) -> None:
        with pytest.raises(ValueError, match="QUALITATIVE_ONLY must have"):
            self.make_full_3d_signal(
                degradation=DegradationLevel.QUALITATIVE_ONLY,
                confidence=0.5,
            )

    def test_qualitative_only_valid(self) -> None:
        s = AlternativeSignal(
            signal_id="qual_001",
            layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="test",
            source_description="test",
            current_value=None,
            baseline_mean=None,
            baseline_std=None,
            z_score=None,
            direction=SignalDirection.DIVERGENT,
            confidence=None,
            degradation=DegradationLevel.QUALITATIVE_ONLY,
        )
        assert s.degradation == DegradationLevel.QUALITATIVE_ONLY

    def test_absence_signal_missing_narrative_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty absence_narrative"):
            self.make_full_3d_signal(
                degradation=DegradationLevel.ABSENCE_SIGNAL,
                is_absence_signal=True,
                absence_narrative="",
            )

    def test_absence_signal_missing_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="is_absence_signal=True"):
            self.make_full_3d_signal(
                degradation=DegradationLevel.ABSENCE_SIGNAL,
                is_absence_signal=False,
                absence_narrative="Data missing",
            )

    def test_absence_signal_valid(self) -> None:
        s = AlternativeSignal(
            signal_id="abs_001",
            layer=SignalLayer.ABSENCE,
            source_name="missing_data",
            source_description="test",
            current_value=None,
            baseline_mean=None,
            baseline_std=None,
            z_score=None,
            direction=SignalDirection.DIVERGENT,
            confidence=None,
            degradation=DegradationLevel.ABSENCE_SIGNAL,
            is_absence_signal=True,
            absence_narrative="CFTC COT report not published this week",
        )
        assert s.is_absence_signal is True
        assert s.absence_narrative == "CFTC COT report not published this week"

    def test_quantitative_2d_allows_partial(self) -> None:
        """QUANTITATIVE_2D: value + z-score ok, confidence optional."""
        s = AlternativeSignal(
            signal_id="q2d_001",
            layer=SignalLayer.L2_SEMI_PUBLIC,
            source_name="test",
            source_description="test",
            current_value=100.0,
            baseline_mean=50.0,
            baseline_std=20.0,
            z_score=2.5,
            direction=SignalDirection.BULLISH,
            confidence=None,
            degradation=DegradationLevel.QUANTITATIVE_2D,
        )
        assert s.degradation == DegradationLevel.QUANTITATIVE_2D
        assert s.confidence is None


class TestAlternativeSignalIsAnomalous:
    """Verify the is_anomalous threshold check includes absence signals."""

    def _build(self, z_score: float) -> AlternativeSignal:
        return AlternativeSignal(
            signal_id="anomaly_test",
            layer=SignalLayer.L5_REFLEXIVE_META,
            source_name="vix_term_structure",
            source_description="VIX futures term structure slope",
            current_value=5.0,
            baseline_mean=0.0,
            baseline_std=1.0,
            z_score=z_score,
            direction=SignalDirection.DIVERGENT,
            confidence=0.8,
            degradation=DegradationLevel.FULL_3D,
        )

    def test_anomalous_above_threshold(self) -> None:
        assert self._build(z_score=2.5).is_anomalous() is True

    def test_anomalous_below_negative_threshold(self) -> None:
        assert self._build(z_score=-2.5).is_anomalous() is True

    def test_not_anomalous_below_positive_threshold(self) -> None:
        assert self._build(z_score=1.4).is_anomalous() is False

    def test_not_anomalous_above_negative_threshold(self) -> None:
        assert self._build(z_score=-1.4).is_anomalous() is False

    def test_custom_threshold(self) -> None:
        assert self._build(z_score=2.9).is_anomalous(threshold=3.0) is False
        assert self._build(z_score=3.1).is_anomalous(threshold=3.0) is True

    def test_exact_threshold(self) -> None:
        assert self._build(z_score=1.5).is_anomalous() is False  # not >

    def test_absence_signal_always_anomalous(self) -> None:
        """Absence signals are always considered anomalous."""
        s = AlternativeSignal(
            signal_id="abs_anom",
            layer=SignalLayer.ABSENCE,
            source_name="missing",
            source_description="test",
            current_value=None,
            baseline_mean=None,
            baseline_std=None,
            z_score=None,
            direction=SignalDirection.DIVERGENT,
            confidence=None,
            degradation=DegradationLevel.ABSENCE_SIGNAL,
            is_absence_signal=True,
            absence_narrative="Data disappeared",
        )
        assert s.is_anomalous() is True
        assert s.is_anomalous(threshold=10.0) is True


class TestAlternativeSignalConfidenceTag:
    """Verify confidence_tag() output for all degradation states."""

    def _make(self, degradation: DegradationLevel, **kw) -> AlternativeSignal:
        base = dict(
            signal_id="tag_test",
            layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="src",
            source_description="desc",
        )
        if degradation == DegradationLevel.FULL_3D:
            base.update(current_value=1.0, baseline_mean=0.0, baseline_std=1.0,
                        z_score=1.0, confidence=0.5)
        elif degradation == DegradationLevel.QUALITATIVE_ONLY:
            base.update(current_value=None, baseline_mean=None, baseline_std=None,
                        z_score=None, confidence=None)
        elif degradation == DegradationLevel.ABSENCE_SIGNAL:
            base.update(current_value=None, baseline_mean=None, baseline_std=None,
                        z_score=None, confidence=None,
                        is_absence_signal=True,
                        absence_narrative="Missing")
        else:
            base.update(current_value=1.0, baseline_mean=0.0, baseline_std=1.0,
                        z_score=1.0, confidence=None)
        base.update(kw)
        return AlternativeSignal(degradation=degradation, **base)  # type: ignore

    def test_full_3d_tag(self) -> None:
        assert self._make(DegradationLevel.FULL_3D).confidence_tag() == "[FULL 3D CONFIRMED]"

    def test_quantitative_2d_tag(self) -> None:
        tag = self._make(DegradationLevel.QUANTITATIVE_2D).confidence_tag()
        assert "DATA INSUFFICIENT" in tag
        assert "PROXY ROUTED" in tag

    def test_qualitative_only_tag(self) -> None:
        tag = self._make(DegradationLevel.QUALITATIVE_ONLY).confidence_tag()
        assert "DATA INSUFFICIENT" in tag
        assert "QUALITATIVE ONLY" in tag

    def test_absence_signal_tag(self) -> None:
        tag = self._make(DegradationLevel.ABSENCE_SIGNAL).confidence_tag()
        assert "ABSENCE AS SIGNAL" in tag


# ============================================================
# AlternativeSignalMatrix
# ============================================================


SIG1 = AlternativeSignal(
    signal_id="s1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
    source_name="sec_insider", source_description="SEC insider trading",
    current_value=100.0, baseline_mean=50.0, baseline_std=20.0,
    z_score=2.5, direction=SignalDirection.BEARISH,
    confidence=0.8, degradation=DegradationLevel.FULL_3D,
    last_updated="2026-05-05T12:00:00+00:00",
)
SIG2 = AlternativeSignal(
    signal_id="s2", layer=SignalLayer.L2_SEMI_PUBLIC,
    source_name="ceo_departure", source_description="CEO departure rate",
    current_value=15.0, baseline_mean=5.0, baseline_std=5.0,
    z_score=2.0, direction=SignalDirection.BEARISH,
    confidence=0.7, degradation=DegradationLevel.FULL_3D,
    last_updated="2026-05-05T12:00:00+00:00",
)
SIG3 = AlternativeSignal(
    signal_id="s3", layer=SignalLayer.L3_MICROSTRUCTURE,
    source_name="monero_btc", source_description="Monero/BTC ratio",
    current_value=0.003, baseline_mean=0.005, baseline_std=0.001,
    z_score=-2.0, direction=SignalDirection.BEARISH,
    confidence=0.6, degradation=DegradationLevel.FULL_3D,
    last_updated="2026-05-05T12:00:00+00:00",
)
SIG4 = AlternativeSignal(
    signal_id="s4", layer=SignalLayer.L4_GEO_PHYSICAL,
    source_name="private_jet", source_description="Private jet traffic to SG",
    current_value=200.0, baseline_mean=100.0, baseline_std=40.0,
    z_score=2.5, direction=SignalDirection.BULLISH,
    confidence=0.5, degradation=DegradationLevel.FULL_3D,
    last_updated="2026-05-05T12:00:00+00:00",
)
ABS_SIG = AlternativeSignal(
    signal_id="abs_001", layer=SignalLayer.ABSENCE,
    source_name="missing_data", source_description="Missing COT report",
    current_value=None, baseline_mean=None, baseline_std=None,
    z_score=None, direction=SignalDirection.DIVERGENT,
    confidence=None, degradation=DegradationLevel.ABSENCE_SIGNAL,
    is_absence_signal=True,
    absence_narrative="CFTC COT report not published this week",
    last_updated="2026-05-05T12:00:00+00:00",
)


class TestAlternativeSignalMatrixConstruction:
    def test_empty_matrix_valid(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_001",
            generated_at="2026-05-05T12:00:00+00:00",
        )
        assert m.total_signals_generated == 0
        assert m.all_signals() == []

    def test_matrix_with_signals(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_002",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l3_signals=[SIG3],
        )
        assert m.total_signals_generated == 2

    def test_matrix_with_absence_signals(self) -> None:
        """Absence signals included in total."""
        m = AlternativeSignalMatrix(
            matrix_id="mat_abs",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            absence_signals=[ABS_SIG],
        )
        assert m.total_signals_generated == 2
        assert len(m.absence_signals) == 1

    def test_empty_matrix_id_raises(self) -> None:
        with pytest.raises(ValueError, match="matrix_id must not be empty"):
            AlternativeSignalMatrix(
                matrix_id="",
                generated_at="2026-05-05T12:00:00+00:00",
            )

    def test_empty_generated_at_raises(self) -> None:
        with pytest.raises(ValueError, match="generated_at must not be empty"):
            AlternativeSignalMatrix(
                matrix_id="mat_003",
                generated_at="",
            )

    def test_all_signals_flat(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_004",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l2_signals=[SIG2],
            l3_signals=[SIG3],
            l4_signals=[SIG4],
        )
        result = m.all_signals()
        assert len(result) == 4
        assert all(isinstance(s, AlternativeSignal) for s in result)

    def test_anomalous_signals(self) -> None:
        """All 4 signals have |z_score| > 1.5 → all should pass default threshold."""
        m = AlternativeSignalMatrix(
            matrix_id="mat_005",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l4_signals=[SIG4],
        )
        anomal = m.anomalous_signals()
        assert len(anomal) == 2

    def test_absence_signal_in_anomalous(self) -> None:
        """Absence signals are always considered anomalous."""
        m = AlternativeSignalMatrix(
            matrix_id="mat_abs_anom",
            generated_at="2026-05-05T12:00:00+00:00",
            absence_signals=[ABS_SIG],
        )
        anomal = m.anomalous_signals()
        assert len(anomal) == 1
        assert anomal[0].is_absence_signal

    def test_degradation_count_all_full_3d(self) -> None:
        """All FULL_3D → degradation_count = 0."""
        m = AlternativeSignalMatrix(
            matrix_id="mat_full",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1, SIG2],
        )
        assert m.degradation_count == 0
        assert m.degraded_signal_warnings == []
        assert m.overall_data_quality == "full_3d"

    def test_degradation_count_with_absence(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_degraded",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            absence_signals=[ABS_SIG],
        )
        assert m.degradation_count == 1
        assert len(m.degraded_signal_warnings) == 1
        assert m.overall_data_quality == "degraded_with_absence_signals"


class TestAlternativeSignalMatrixComputeConvergence:
    def test_no_signals_no_warnings(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_empty",
            generated_at="2026-05-05T12:00:00+00:00",
        )
        m.compute_convergence()
        assert m.layer_convergence_count == 0
        assert m.divergence_warnings == []

    def test_one_layer_convergence(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_c1", generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
        )
        m.compute_convergence()
        assert m.layer_convergence_count == 1
        assert len(m.divergence_warnings) == 0

    def test_three_layer_convergence(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_c3", generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l2_signals=[SIG2],
            l3_signals=[SIG3],
        )
        m.compute_convergence()
        assert m.layer_convergence_count == 3

    def test_divergent_direction_no_warning_different_layer(self) -> None:
        """SIG1 is BEARISH, SIG4 is BULLISH, but in DIFFERENT layers → no divergence."""
        m = AlternativeSignalMatrix(
            matrix_id="mat_div", generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l4_signals=[SIG4],
        )
        m.compute_convergence()
        assert m.layer_convergence_count == 2
        assert len(m.divergence_warnings) == 0

    def test_divergent_warning_same_layer(self) -> None:
        """Two signals in Layer 1, one BULLISH one BEARISH → divergence."""
        s_bullish = AlternativeSignal(
            signal_id="sb1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="a", source_description="a",
            current_value=10.0, baseline_mean=5.0, baseline_std=2.0,
            z_score=2.5, direction=SignalDirection.BULLISH,
            confidence=0.8, degradation=DegradationLevel.FULL_3D,
            last_updated="2026-05-05T12:00:00+00:00",
        )
        s_bearish = AlternativeSignal(
            signal_id="sb2", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="b", source_description="b",
            current_value=10.0, baseline_mean=5.0, baseline_std=2.0,
            z_score=2.5, direction=SignalDirection.BEARISH,
            confidence=0.8, degradation=DegradationLevel.FULL_3D,
            last_updated="2026-05-05T12:00:00+00:00",
        )
        m = AlternativeSignalMatrix(
            matrix_id="mat_div_same",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[s_bullish, s_bearish],
        )
        m.compute_convergence()
        assert any("BULLISH and" in w and "BEARISH" in w for w in m.divergence_warnings)

    def test_divergent_direction_warning(self) -> None:
        """DIVERGENT signal in a layer → divergence warning."""
        s = AlternativeSignal(
            signal_id="sd1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="a", source_description="a",
            current_value=10.0, baseline_mean=5.0, baseline_std=2.0,
            z_score=2.5, direction=SignalDirection.DIVERGENT,
            confidence=0.8, degradation=DegradationLevel.FULL_3D,
            last_updated="2026-05-05T12:00:00+00:00",
        )
        m = AlternativeSignalMatrix(
            matrix_id="mat_divergent",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[s],
        )
        m.compute_convergence()
        assert any("DIVERGENT" in w for w in m.divergence_warnings)

    def test_contrarian_direction_warning(self) -> None:
        """CONTRARIAN signal in a layer → divergence warning."""
        s = AlternativeSignal(
            signal_id="sc1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="a", source_description="a",
            current_value=10.0, baseline_mean=5.0, baseline_std=2.0,
            z_score=2.5, direction=SignalDirection.CONTRARIAN,
            confidence=0.8, degradation=DegradationLevel.FULL_3D,
            last_updated="2026-05-05T12:00:00+00:00",
        )
        m = AlternativeSignalMatrix(
            matrix_id="mat_contrarian",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[s],
        )
        m.compute_convergence()
        assert any("CONTRARIAN" in w for w in m.divergence_warnings)

    def test_degradation_warning_in_divergence(self) -> None:
        """Degraded signal → degradation warning appended to divergence_warnings."""
        s = AlternativeSignal(
            signal_id="sd1", layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="a", source_description="a",
            current_value=None, baseline_mean=None, baseline_std=None,
            z_score=None, direction=SignalDirection.BULLISH,
            confidence=None, degradation=DegradationLevel.QUALITATIVE_ONLY,
            last_updated="2026-05-05T12:00:00+00:00",
        )
        m = AlternativeSignalMatrix(
            matrix_id="mat_degrading",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[s],
        )
        m.compute_convergence()
        assert any("Degradation" in w for w in m.divergence_warnings)

    def test_convergence_narrative_format(self) -> None:
        m = AlternativeSignalMatrix(
            matrix_id="mat_narr",
            generated_at="2026-05-05T12:00:00+00:00",
            l1_signals=[SIG1],
            l2_signals=[SIG2],
        )
        m.compute_convergence()
        assert "Convergence:" in m.convergence_narrative
        assert "2" in m.convergence_narrative


# ============================================================
# compute_z_score
# ============================================================


class TestComputeZScore:
    def test_basic_computation(self) -> None:
        values = [10.0, 12.0, 11.0, 13.0, 10.5]
        z, mean, std, cur = compute_z_score(values, current_value=9.0)
        assert isinstance(z, float)
        assert mean == pytest.approx(11.3, abs=0.01)
        assert std > 0

    def test_default_current_value_uses_last(self) -> None:
        values = [10.0, 12.0, 11.0]
        z, mean, std, cur = compute_z_score(values)
        assert cur == 11.0  # values[-1]

    def test_less_than_two_values_raises(self) -> None:
        with pytest.raises(ValueError, match="Need at least 2 values"):
            compute_z_score([5.0])

    def test_zero_std_raises(self) -> None:
        with pytest.raises(ValueError, match="standard deviation is zero"):
            compute_z_score([10.0, 10.0, 10.0], current_value=10.0)

    def test_positive_z_score(self) -> None:
        values = [10.0, 11.0, 10.5]
        z, _, _, _ = compute_z_score(values, current_value=12.0)
        assert z > 0

    def test_negative_z_score(self) -> None:
        values = [10.0, 11.0, 10.5]
        z, _, _, _ = compute_z_score(values, current_value=9.0)
        assert z < 0

    def test_zero_z_score(self) -> None:
        values = [10.0, 12.0]
        z, _, _, _ = compute_z_score(values, current_value=11.0)
        assert z == pytest.approx(0.0, abs=0.001)


# ============================================================
# compute_z_score_from_stats
# ============================================================


class TestComputeZScoreFromStats:
    def test_basic(self) -> None:
        result = compute_z_score_from_stats(15.0, 10.0, 2.5)
        assert result == pytest.approx(2.0, abs=0.001)

    def test_negative(self) -> None:
        result = compute_z_score_from_stats(5.0, 10.0, 2.5)
        assert result == pytest.approx(-2.0, abs=0.001)

    def test_zero(self) -> None:
        result = compute_z_score_from_stats(10.0, 10.0, 2.5)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_zero_std_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_std must be positive"):
            compute_z_score_from_stats(10.0, 5.0, 0.0)

    def test_negative_std_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_std must be positive"):
            compute_z_score_from_stats(10.0, 5.0, -1.0)


# ============================================================
# build_absence_signal
# ============================================================


class TestBuildAbsenceSignal:
    def test_default_absence_narrative(self) -> None:
        result = build_absence_signal(
            source_name="cot_report",
            source_description="CFTC COT report",
            direction=SignalDirection.DIVERGENT,
        )
        assert result.is_absence_signal is True
        assert result.degradation == DegradationLevel.ABSENCE_SIGNAL
        assert bool(result.signal_id) is True
        assert "cot_report" in result.signal_id

    def test_custom_absence_narrative(self) -> None:
        result = build_absence_signal(
            source_name="fed_tga",
            source_description="TGA account balance",
            direction=SignalDirection.BEARISH,
            absence_narrative="TGA data not published for 2 consecutive weeks",
        )
        assert result.absence_narrative == "TGA data not published for 2 consecutive weeks"

    def test_custom_reasoning_hook(self) -> None:
        result = build_absence_signal(
            source_name="test",
            source_description="test",
            direction=SignalDirection.BULLISH,
            reasoning_hook="Could indicate capital flow hiding",
        )
        assert "capital flow" in result.reasoning_hook

    def test_custom_manipulation_risk(self) -> None:
        result = build_absence_signal(
            source_name="test",
            source_description="test",
            direction=SignalDirection.BULLISH,
            manipulation_risk="Government could block data release",
        )
        assert "Government" in result.manipulation_risk

    def test_custom_layer(self) -> None:
        result = build_absence_signal(
            source_name="test", source_description="test",
            direction=SignalDirection.DIVERGENT,
            layer=SignalLayer.L2_SEMI_PUBLIC,
        )
        assert result.layer == SignalLayer.L2_SEMI_PUBLIC


# ============================================================
# build_signal_with_proxy
# ============================================================


class TestBuildSignalWithProxy:
    def test_full_3d(self) -> None:
        result = build_signal_with_proxy(
            signal_id="sig_proxy_1",
            layer=SignalLayer.L3_MICROSTRUCTURE,
            source_name="monero_btc",
            source_description="Monero/BTC ratio",
            proxy_chain_tried=["primary", "proxy_a"],
            proxy_chain_index=0,
            degradation=DegradationLevel.FULL_3D,
            current_value=0.0042,
            baseline_mean=0.005,
            baseline_std=0.0005,
            direction=SignalDirection.BEARISH,
            confidence=0.8,
        )
        assert result.degradation == DegradationLevel.FULL_3D
        assert result.current_value == 0.0042

    def test_qualitative_only_forces_none(self) -> None:
        result = build_signal_with_proxy(
            signal_id="sig_proxy_qual",
            layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            source_name="ceo_social",
            source_description="CEO social silence",
            proxy_chain_tried=["insider", "ceo_social"],
            proxy_chain_index=1,
            degradation=DegradationLevel.QUALITATIVE_ONLY,
            current_value=15.0,  # Should be overridden to None
            baseline_mean=5.0,
            baseline_std=2.0,
            direction=SignalDirection.BEARISH,
            confidence=0.7,  # Should be overridden to None
        )
        assert result.degradation == DegradationLevel.QUALITATIVE_ONLY
        assert result.current_value is None
        assert result.confidence is None
        assert result.z_score is None

    def test_without_stats_returns_none_z_score(self) -> None:
        result = build_signal_with_proxy(
            signal_id="sig_no_stats",
            layer=SignalLayer.L2_SEMI_PUBLIC,
            source_name="congress_trades",
            source_description="STOCK Act trades",
            proxy_chain_tried=["primary"],
            proxy_chain_index=0,
            degradation=DegradationLevel.FULL_3D,
            current_value=100.0,
            direction=SignalDirection.BULLISH,
            confidence=0.5,
        )
        assert result.z_score is None

    def test_with_stats_computes_z_score(self) -> None:
        result = build_signal_with_proxy(
            signal_id="sig_stats_ok",
            layer=SignalLayer.L3_MICROSTRUCTURE,
            source_name="dex_volume",
            source_description="DEX volume spike",
            proxy_chain_tried=["primary"],
            proxy_chain_index=0,
            degradation=DegradationLevel.FULL_3D,
            current_value=200.0,
            baseline_mean=100.0,
            baseline_std=50.0,
            direction=SignalDirection.BULLISH,
            confidence=0.6,
        )
        assert result.z_score == pytest.approx(2.0, abs=0.01)


# ============================================================
# create_default_proxy_router
# ============================================================


class TestCreateDefaultProxyRouter:
    def test_router_has_all_routes(self) -> None:
        router = create_default_proxy_router()
        assert "institutional_flows" in router._routes
        assert "middle_east_oil_spot" in router._routes
        assert "sec_edgar_insider" in router._routes
        assert "crypto_privacy_flows" in router._routes

    def test_institutional_route_has_three_proxies(self) -> None:
        router = create_default_proxy_router()
        route = router._routes["institutional_flows"]
        assert len(route.proxies) == 3
        assert route.proxies[0] == "etf_volume_surge"
        assert "dark_pool_print" in route.proxies

    def test_middle_east_route(self) -> None:
        router = create_default_proxy_router()
        route = router._routes["middle_east_oil_spot"]
        assert "energy_stock_iv" in route.proxies
        assert route.layer_hint == SignalLayer.L4_GEO_PHYSICAL

    def test_insider_route(self) -> None:
        router = create_default_proxy_router()
        route = router._routes["sec_edgar_insider"]
        assert "congress_trading_disclosures" in route.proxies

    def test_crypto_route(self) -> None:
        router = create_default_proxy_router()
        route = router._routes["crypto_privacy_flows"]
        assert "dex_volume_spike" in route.proxies
        assert route.layer_hint == SignalLayer.L3_MICROSTRUCTURE

    def test_resolve_primary_pass_through(self) -> None:
        """No checkers → all primary sources pass through as FULL_3D."""
        router = create_default_proxy_router()
        for src in ["institutional_flows", "middle_east_oil_spot"]:
            result = router.resolve(src)
            assert result.proxy_chain_index == 0
            assert result.degradation == DegradationLevel.FULL_3D


# ============================================================
# fetch_with_proxy_routing
# ============================================================


class TestFetchWithProxyRouting:
    """Integration:  fetch_with_proxy_routing + ProxyRouter + signal builder."""

    def test_primary_available_returns_full_signals(self) -> None:
        router = ProxyRouter()
        router.register_route(
            "my_source",
            ProxyRoute(primary_source="my_source", proxies=[]),
        )

        def _builder(
            src: str, desc: str, deg: DegradationLevel,
            chain: list[str], idx: int
        ) -> list[AlternativeSignal]:
            return [
                AlternativeSignal(
                    signal_id="built_1",
                    layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                    source_name=src,
                    source_description=desc,
                    current_value=1.0, baseline_mean=0.0, baseline_std=1.0,
                    z_score=1.0, direction=SignalDirection.BULLISH,
                    confidence=0.5, degradation=deg,
                    proxy_chain_used=chain,
                )
            ]

        results = fetch_with_proxy_routing(
            router=router,
            primary_source="my_source",
            build_signal_fn=_builder,
        )
        assert len(results) == 1
        assert results[0].source_name == "my_source"
        assert results[0].degradation == DegradationLevel.FULL_3D

    def test_all_fail_returns_absence_signal(self) -> None:
        router = ProxyRouter()
        router.register_route(
            "dead_source",
            ProxyRoute(
                primary_source="dead_source",
                proxies=["proxy1"],
                proxy_descriptions={"dead_source": "Source X data"},
                layer_hint=SignalLayer.L2_SEMI_PUBLIC,
            ),
        )
        router.register_checker("dead_source", lambda: False)
        router.register_checker("proxy1", lambda: False)

        results = fetch_with_proxy_routing(
            router=router,
            primary_source="dead_source",
            build_signal_fn=lambda src, desc, deg, chain, idx: [],
            default_layer=SignalLayer.L2_SEMI_PUBLIC,
            default_description="Fallback description",
        )
        assert len(results) == 1
        assert results[0].is_absence_signal is True
        assert "dead_source" in results[0].source_name

    def test_no_route_registered(self) -> None:
        """No route → no proxy chain → pass-through."""
        router = ProxyRouter()
        results = fetch_with_proxy_routing(
            router=router,
            primary_source="orphan_source",
            build_signal_fn=lambda src, desc, deg, chain, idx: [
                AlternativeSignal(
                    signal_id="orphan",
                    layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                    source_name=src,
                    source_description=desc,
                    current_value=1.0, baseline_mean=0.0, baseline_std=1.0,
                    z_score=1.0, direction=SignalDirection.BULLISH,
                    confidence=0.5, degradation=deg,
                    proxy_chain_used=chain,
                )
            ],
        )
        assert len(results) == 1
        assert results[0].source_name == "orphan_source"


# ============================================================
# Fetcher stubs (proxy-aware)
# ============================================================


class TestFetchSecEdgarSignals:
    def test_no_router_returns_empty(self) -> None:
        assert fetch_sec_edgar_signals() == []

    def test_with_router_returns_signal(self) -> None:
        router = create_default_proxy_router()
        results = fetch_sec_edgar_signals(router=router)
        assert len(results) >= 1

    def test_signal_has_correct_layer(self) -> None:
        router = create_default_proxy_router()
        results = fetch_sec_edgar_signals(router=router)
        if results:
            assert results[0].layer in (
                SignalLayer.L2_SEMI_PUBLIC,
                SignalLayer.ABSENCE,
            )


class TestFetchCotReportSignals:
    def test_no_router_returns_empty(self) -> None:
        assert fetch_cot_report_signals() == []

    def test_with_router_returns_signal(self) -> None:
        router = create_default_proxy_router()
        results = fetch_cot_report_signals(router=router)
        assert len(results) >= 1


class TestFetchCryptoPrivacySignals:
    def test_no_router_returns_empty(self) -> None:
        assert fetch_crypto_privacy_signals() == []

    def test_with_router_returns_signal(self) -> None:
        router = create_default_proxy_router()
        results = fetch_crypto_privacy_signals(router=router)
        assert len(results) >= 1

    def test_signal_has_correct_layer(self) -> None:
        router = create_default_proxy_router()
        results = fetch_crypto_privacy_signals(router=router)
        if results:
            assert results[0].layer in (
                SignalLayer.L3_MICROSTRUCTURE,
                SignalLayer.ABSENCE,
            )

    def test_has_manipulation_risk(self) -> None:
        router = create_default_proxy_router()
        results = fetch_crypto_privacy_signals(router=router)
        if results and not results[0].is_absence_signal:
            assert "wash trading" in results[0].manipulation_risk.lower()


class TestFetchCeoDepartureSignals:
    def test_no_router_returns_empty(self) -> None:
        assert fetch_ceo_departure_signals() == []

    def test_with_router_returns_signal(self) -> None:
        router = create_default_proxy_router()
        results = fetch_ceo_departure_signals(router=router)
        assert len(results) >= 1

    def test_signal_direction_bearish(self) -> None:
        router = create_default_proxy_router()
        results = fetch_ceo_departure_signals(router=router)
        if results and not results[0].is_absence_signal:
            assert results[0].direction == SignalDirection.BEARISH

    def test_has_reasoning_hook(self) -> None:
        router = create_default_proxy_router()
        results = fetch_ceo_departure_signals(router=router)
        if results and not results[0].is_absence_signal:
            assert "CEO" in results[0].reasoning_hook
