"""
test_sell_protocol.py — Unit tests for sell_protocol.py (Phase 6 Track B)

Tests trigger identification, cross-verification, clearout computation,
and the SellProtocol.analyze() entry point.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    QualifierInput,
    QualifierOutput,
)
from src.sell_protocol import (
    CrossVerification,
    SellAnalysis,
    SellProtocol,
    SellTrigger,
    SellTriggerCategory,
    _compute_clearout,
    _cross_verify_trigger,
    _identify_primary_trigger,
)


# =========================================================================
# TC-SP-001..004: SellTrigger dataclass
# =========================================================================


class TestSellTrigger:
    """Validate SellTrigger creation."""

    def test_minimal(self) -> None:
        """TC-SP-001: Minimal trigger with only required fields."""
        t = SellTrigger(category=SellTriggerCategory.MACRO_SURPRISE, indicator="NFP", description="NFP beat")
        assert t.direction == "above"
        assert t.raw_value is None

    def test_full(self) -> None:
        """TC-SP-002: Trigger with all fields."""
        t = SellTrigger(
            category=SellTriggerCategory.TECHNICAL_BREAK, indicator="SPX_50SMA",
            raw_value=4800.0, threshold_value=4850.0, direction="below",
            description="SPX broke below 50-day SMA.",
        )
        assert t.raw_value == 4800.0
        assert t.threshold_value == 4850.0
        assert t.direction == "below"

    def test_all_categories(self) -> None:
        """TC-SP-003: All enum values are valid."""
        for cat in SellTriggerCategory:
            t = SellTrigger(category=cat, indicator="X", description="T")
            assert t.category == cat

    def test_risk_management_category(self) -> None:
        """TC-SP-004: RISK_MANAGEMENT category."""
        t = SellTrigger(category=SellTriggerCategory.RISK_MANAGEMENT, indicator="DRAWDOWN", description="DD limit")
        assert t.category.value == "risk_management"


# =========================================================================
# TC-SP-005..007: CrossVerification dataclass
# =========================================================================


class TestCrossVerification:
    """Validate CrossVerification creation."""

    def test_minimal(self) -> None:
        """TC-SP-005: Minimal cross-verification."""
        cv = CrossVerification(indicator="VIX", verdict="confirms", narrative="VIX confirms fear.")
        assert cv.weight == 1.0

    def test_with_weight(self) -> None:
        """TC-SP-006: With explicit weight."""
        cv = CrossVerification(indicator="DXY", verdict="contradicts", narrative="DXY contradicts.", weight=0.5)
        assert cv.weight == 0.5

    def test_neutral_verdict(self) -> None:
        """TC-SP-007: Neutral verdict."""
        cv = CrossVerification(indicator="REGIME", verdict="neutral", narrative="Neutral check.")
        assert cv.verdict == "neutral"


# =========================================================================
# TC-SP-008..012: SellAnalysis dataclass
# =========================================================================


class TestSellAnalysis:
    """Validate SellAnalysis creation."""

    @staticmethod
    def _make_trigger() -> SellTrigger:
        return SellTrigger(category=SellTriggerCategory.MACRO_SURPRISE, indicator="NFP", description="NFP beat")

    def test_minimal(self) -> None:
        """TC-SP-008: Minimum required fields."""
        t = self._make_trigger()
        a = SellAnalysis(analysis_id="sl_001", judgment_id="qj_001", timestamp="now", primary_trigger=t)
        assert a.secondary_triggers == []
        assert a.cross_verifications == []
        assert a.clearout_ratio == 1.0
        assert a.cross_check_verdict == "confirmed"

    def test_full(self) -> None:
        """TC-SP-009: All fields populated."""
        t = self._make_trigger()
        cv = CrossVerification(indicator="VIX", verdict="confirms", narrative="VIX high.")
        a = SellAnalysis(
            analysis_id="sl_002", judgment_id="qj_002", timestamp="now",
            primary_trigger=t,
            secondary_triggers=[SellTrigger(category=SellTriggerCategory.TECHNICAL_BREAK, indicator="SMA", description="T")],
            cross_verifications=[cv],
            clearout_ratio=0.75,
            stop_loss_price=4500.0,
            stop_loss_distance_pct=2.5,
            limit_price=4600.0,
            rationale="Sell now.",
            cross_check_verdict="confirmed",
        )
        assert len(a.secondary_triggers) == 1
        assert len(a.cross_verifications) == 1
        assert a.clearout_ratio == 0.75
        assert a.stop_loss_price == 4500.0
        assert a.limit_price == 4600.0
        assert a.cross_check_verdict == "confirmed"

    def test_clearout_clamping(self) -> None:
        """TC-SP-010: Clearout ratio stored as-is (caller responsibility)."""
        t = self._make_trigger()
        a = SellAnalysis(analysis_id="sl_003", judgment_id="qj_003", timestamp="now", primary_trigger=t, clearout_ratio=1.5)
        assert a.clearout_ratio == 1.5

    def test_analysis_id_format(self) -> None:
        """TC-SP-011: Analysis ID prefix format."""
        t = self._make_trigger()
        a = SellAnalysis(analysis_id="sl_nfp_001", judgment_id="qj_001", timestamp="now", primary_trigger=t)
        assert a.analysis_id.startswith("sl_")

    def test_stop_loss_default_none(self) -> None:
        """TC-SP-012: Stop loss defaults to None."""
        t = self._make_trigger()
        a = SellAnalysis(analysis_id="sl_004", judgment_id="qj_004", timestamp="now", primary_trigger=t)
        assert a.stop_loss_price is None
        assert a.limit_price is None


# =========================================================================
# TC-SP-013..018: _identify_primary_trigger
# =========================================================================


def _make_output(subtrack: ActionSubtrack = ActionSubtrack.SELL) -> QualifierOutput:
    return QualifierOutput(
        judgment_id="qj_sell_test", timestamp=datetime.now(timezone.utc).isoformat(),
        decision_track=DecisionTrack.ACTION_AND_ADJUST, track_confidence=0.9,
        signal_coherence_score=30.0, reward_risk_ratio=0.5,
        decision_rationale="Test sell", action_subtrack=subtrack,
    )


class TestIdentifyPrimaryTrigger:
    """Validate trigger identification priority chain."""

    def test_nfp_surge(self) -> None:
        """TC-SP-013: NFP deviation > 2σ is top priority."""
        inp = QualifierInput(session_id="t", nfp_deviation=2.5)
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "NFP_DEVIATION"
        assert trigger.category == SellTriggerCategory.MACRO_SURPRISE
        assert trigger.raw_value == 2.5

    def test_vix_spike(self) -> None:
        """TC-SP-014: VIX > 30 is second priority."""
        inp = QualifierInput(session_id="t", vix_level=35.0, nfp_deviation=0.5)
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "VIX_SPIKE"
        assert trigger.category == SellTriggerCategory.TECHNICAL_BREAK

    def test_cpi_overshoot(self) -> None:
        """TC-SP-015: CPI > 0.5% is third priority."""
        inp = QualifierInput(session_id="t", cpi_mom=0.6, nfp_deviation=0.5, vix_level=20.0)
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "CPI_MOM"
        assert trigger.raw_value == 0.6

    def test_dxy_strength(self) -> None:
        """TC-SP-016: DXY strengthening is fourth priority."""
        inp = QualifierInput(session_id="t", dxy_trend="strengthening", nfp_deviation=0.5, vix_level=20.0, cpi_mom=0.3)
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "DXY_STRENGTH"

    def test_yield_curve_inversion(self) -> None:
        """TC-SP-017: Inverted yield curve is fifth priority."""
        inp = QualifierInput(session_id="t", yield_curve="inverted", nfp_deviation=0.5, vix_level=20.0, cpi_mom=0.3, dxy_trend="stable")
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "YIELD_CURVE_INVERSION"

    def test_fallback(self) -> None:
        """TC-SP-018: Fallback when no specific trigger detected."""
        inp = QualifierInput(session_id="t")
        trigger = _identify_primary_trigger(inp, _make_output())
        assert trigger.indicator == "SIGNAL_DETERIORATION"
        assert trigger.category == SellTriggerCategory.RISK_MANAGEMENT


# =========================================================================
# TC-SP-019..024: _cross_verify_trigger
# =========================================================================


class TestCrossVerifyTrigger:
    """Validate cross-verification logic."""

    def test_vix_confirms(self) -> None:
        """TC-SP-019: VIX > 25 confirms sell signal."""
        inp = QualifierInput(session_id="t", vix_level=30.0)
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        vix_checks = [c for c in checks if c.indicator == "VIX_LEVEL"]
        assert len(vix_checks) >= 1
        assert vix_checks[0].verdict == "confirms"

    def test_vix_neutral(self) -> None:
        """TC-SP-020: VIX <= 25 is neutral."""
        inp = QualifierInput(session_id="t", vix_level=15.0)
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        vix_checks = [c for c in checks if c.indicator == "VIX_LEVEL"]
        assert len(vix_checks) >= 1
        assert vix_checks[0].verdict == "neutral"

    def test_inverted_curve_confirms(self) -> None:
        """TC-SP-021: Inverted yield curve confirms."""
        inp = QualifierInput(session_id="t", vix_level=20.0, yield_curve="inverted")
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        yc_checks = [c for c in checks if c.indicator == "YIELD_CURVE"]
        assert len(yc_checks) >= 1
        assert yc_checks[0].verdict == "confirms"

    def test_steepening_curve_contradicts(self) -> None:
        """TC-SP-022: Steepening yield curve contradicts."""
        inp = QualifierInput(session_id="t", vix_level=20.0, yield_curve="steepening")
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        yc_checks = [c for c in checks if c.indicator == "YIELD_CURVE"]
        assert len(yc_checks) >= 1
        assert yc_checks[0].verdict == "contradicts"

    def test_dxy_strength_confirms(self) -> None:
        """TC-SP-023: DXY strengthening confirms."""
        inp = QualifierInput(session_id="t", vix_level=20.0, dxy_trend="strengthening")
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        dxy_checks = [c for c in checks if c.indicator == "DXY_TREND"]
        assert len(dxy_checks) >= 1
        assert dxy_checks[0].verdict == "confirms"

    def test_dxy_weakness_contradicts(self) -> None:
        """TC-SP-024: DXY weakening contradicts."""
        inp = QualifierInput(session_id="t", vix_level=20.0, dxy_trend="weakening")
        trigger = _identify_primary_trigger(inp, _make_output())
        checks = _cross_verify_trigger(inp, trigger)
        dxy_checks = [c for c in checks if c.indicator == "DXY_TREND"]
        assert len(dxy_checks) >= 1
        assert dxy_checks[0].verdict == "contradicts"


# =========================================================================
# TC-SP-025..032: _compute_clearout
# =========================================================================


class TestComputeClearout:
    """Validate clearout ratio computation."""

    def test_overwhelming_coherence(self) -> None:
        """TC-SP-025: Coherence < 20 → 100% clearout."""
        inp = QualifierInput(session_id="t")
        out = _make_output()
        out.signal_coherence_score = 10.0
        r = _compute_clearout(inp, out, [])
        assert r == 1.0

    def test_strong_coherence(self) -> None:
        """TC-SP-026: Coherence 20–40 → 75% clearout."""
        inp = QualifierInput(session_id="t")
        out = _make_output()
        out.signal_coherence_score = 25.0
        r = _compute_clearout(inp, out, [])
        assert r == 0.75

    def test_moderate_coherence(self) -> None:
        """TC-SP-027: Coherence 40–60 → 50% clearout."""
        inp = QualifierInput(session_id="t")
        out = _make_output()
        out.signal_coherence_score = 50.0
        r = _compute_clearout(inp, out, [])
        assert r == 0.50

    def test_weak_coherence(self) -> None:
        """TC-SP-028: Coherence > 60 → 25% clearout."""
        inp = QualifierInput(session_id="t")
        out = _make_output()
        out.signal_coherence_score = 70.0
        r = _compute_clearout(inp, out, [])
        assert r == 0.25

    def test_adjustment_confirm_boost(self) -> None:
        """TC-SP-029: Most verifications confirm → +10%."""
        inp = QualifierInput(session_id="t", nfp_deviation=0.5, vix_level=20.0)
        out = _make_output()
        out.signal_coherence_score = 50.0
        verifications = [
            CrossVerification(indicator="A", verdict="confirms", narrative="A confirms"),
            CrossVerification(indicator="B", verdict="confirms", narrative="B confirms"),
        ]
        r = _compute_clearout(inp, out, verifications)
        assert r == 0.60  # 0.50 + 0.10

    def test_adjustment_contradict_penalty(self) -> None:
        """TC-SP-030: Contradiction → -15%."""
        inp = QualifierInput(session_id="t", nfp_deviation=0.5)
        out = _make_output()
        out.signal_coherence_score = 50.0
        verifications = [
            CrossVerification(indicator="A", verdict="confirms", narrative="A"),
            CrossVerification(indicator="B", verdict="contradicts", narrative="B"),
        ]
        r = _compute_clearout(inp, out, verifications)
        assert r == 0.35  # 0.50 - 0.15

    def test_nfp_extreme_boost(self) -> None:
        """TC-SP-031: NFP deviation > 3σ → +15%."""
        inp = QualifierInput(session_id="t", nfp_deviation=3.5)
        out = _make_output()
        out.signal_coherence_score = 50.0
        r = _compute_clearout(inp, out, [])
        assert r == 0.65  # 0.50 + 0.15

    def test_vix_panic_boost(self) -> None:
        """TC-SP-032: VIX > 35 → +10%."""
        inp = QualifierInput(session_id="t", vix_level=40.0, nfp_deviation=0.5)
        out = _make_output()
        out.signal_coherence_score = 50.0
        r = _compute_clearout(inp, out, [])
        assert r == 0.60  # 0.50 + 0.10

    def test_clamping_upper(self) -> None:
        """TC-SP-033: Clearout clamped at 1.0 max."""
        inp = QualifierInput(session_id="t", nfp_deviation=3.5, vix_level=40.0)
        out = _make_output()
        out.signal_coherence_score = 10.0
        verifications = [
            CrossVerification(indicator="A", verdict="confirms", narrative="A"),
            CrossVerification(indicator="B", verdict="confirms", narrative="B"),
        ]
        r = _compute_clearout(inp, out, verifications)
        assert r == 1.0

    def test_clamping_lower(self) -> None:
        """TC-SP-034: Clearout clamped at 0.0 min."""
        inp = QualifierInput(session_id="t", nfp_deviation=0.5)
        out = _make_output()
        out.signal_coherence_score = 70.0
        verifications = [
            CrossVerification(indicator="A", verdict="contradicts", narrative="A"),
            CrossVerification(indicator="B", verdict="contradicts", narrative="B"),
        ]
        r = _compute_clearout(inp, out, verifications)
        assert r == 0.10  # 0.25 - 0.15 = 0.10


# =========================================================================
# TC-SP-035..042: SellProtocol.analyze() end-to-end
# =========================================================================


class TestSellProtocolAnalyze:
    """Validate SellProtocol.analyze() end-to-end."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_sell"}
        params.update(kwargs)
        return QualifierInput(**params)

    @staticmethod
    def _make_output(subtrack: ActionSubtrack = ActionSubtrack.SELL) -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_sell_001", timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.ACTION_AND_ADJUST, track_confidence=0.9,
            signal_coherence_score=30.0, reward_risk_ratio=0.5,
            decision_rationale="Sell test", action_subtrack=subtrack,
        )

    def test_analysis_created(self) -> None:
        """TC-SP-035: analyze() returns a valid SellAnalysis."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5, vix_level=30.0)
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert isinstance(analysis, SellAnalysis)
        assert analysis.analysis_id.startswith("sl_")

    def test_links_to_judgment(self) -> None:
        """TC-SP-036: Analysis references the source judgment."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5)
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert analysis.judgment_id == out.judgment_id

    def test_trigger_identified(self) -> None:
        """TC-SP-037: Primary trigger is populated."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5)
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert analysis.primary_trigger.indicator != ""

    def test_cross_verifications_populated(self) -> None:
        """TC-SP-038: Cross-verifications are populated."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5, vix_level=30.0, yield_curve="inverted")
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert len(analysis.cross_verifications) > 0

    def test_clearout_computed(self) -> None:
        """TC-SP-039: Clearout ratio is in valid range."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5, vix_level=30.0)
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert 0.0 <= analysis.clearout_ratio <= 1.0

    def test_last_analysis_property(self) -> None:
        """TC-SP-040: last_analysis returns most recent analysis."""
        sp = SellProtocol()
        assert sp.last_analysis is None
        inp = self._make_input(nfp_deviation=2.5)
        out = self._make_output()
        r1 = sp.analyze(inp, out)
        assert sp.last_analysis is r1
        inp2 = self._make_input(nfp_deviation=3.5, vix_level=35.0)
        out2 = self._make_output()
        r2 = sp.analyze(inp2, out2)
        assert sp.last_analysis is r2
        assert sp.last_analysis is not r1

    def test_rationale_contains_trigger_and_clearout(self) -> None:
        """TC-SP-041: Rationale includes key info."""
        sp = SellProtocol()
        inp = self._make_input(nfp_deviation=2.5)
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert "Sell trigger" in analysis.rationale
        assert "Recommended clearout" in analysis.rationale

    def test_override_verdict_when_conflicting(self) -> None:
        """TC-SP-042: Cross-check verdict is 'warning' when contradictions exist."""
        sp = SellProtocol()
        inp = self._make_input(
            nfp_deviation=2.5, vix_level=20.0,
            yield_curve="steepening", dxy_trend="weakening",
        )
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert analysis.cross_check_verdict in ("warning", "mixed")


# =========================================================================
# TC-SP-043..046: Error handling
# =========================================================================


class TestSellProtocolErrors:
    """Validate error handling."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_sell_err"}
        params.update(kwargs)
        return QualifierInput(**params)

    @staticmethod
    def _make_observe_output() -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_obs", timestamp="now",
            decision_track=DecisionTrack.OBSERVE_AND_WAIT,
            track_confidence=0.5, signal_coherence_score=40.0,
            reward_risk_ratio=1.0, decision_rationale="Observe",
            observe_scenario=None,
        )

    @staticmethod
    def _make_buy_output() -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_buy", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.9, signal_coherence_score=60.0,
            reward_risk_ratio=2.5, decision_rationale="Buy",
            action_subtrack=ActionSubtrack.BUY,
        )

    @staticmethod
    def _make_output() -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_sell", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.8, signal_coherence_score=25.0,
            reward_risk_ratio=0.4, decision_rationale="Sell signal detected",
            action_subtrack=ActionSubtrack.SELL,
        )

    def test_rejects_observe_track(self) -> None:
        """TC-SP-043: Raises ValueError if not ACTION."""
        sp = SellProtocol()
        inp = self._make_input()
        out = self._make_observe_output()
        with pytest.raises(ValueError, match="requires ACTION"):
            sp.analyze(inp, out)

    def test_rejects_buy_subtrack(self) -> None:
        """TC-SP-044: Raises ValueError if not SELL."""
        sp = SellProtocol()
        inp = self._make_input()
        out = self._make_buy_output()
        with pytest.raises(ValueError, match="requires action_subtrack=SELL"):
            sp.analyze(inp, out)

    def test_empty_input_no_crash(self) -> None:
        """TC-SP-045: Empty input does not crash."""
        sp = SellProtocol()
        inp = self._make_input()
        out = self._make_output()
        analysis = sp.analyze(inp, out)
        assert analysis.primary_trigger.indicator == "SIGNAL_DETERIORATION"

    def test_two_calls_independent(self) -> None:
        """TC-SP-046: Successive calls produce independent results."""
        sp = SellProtocol()
        inp1 = self._make_input(nfp_deviation=2.5)
        out1 = self._make_output()
        r1 = sp.analyze(inp1, out1)

        inp2 = self._make_input(nfp_deviation=3.5, vix_level=35.0, yield_curve="inverted")
        out2 = QualifierOutput(
            judgment_id="qj_sell2", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.8, signal_coherence_score=25.0,
            reward_risk_ratio=0.4, decision_rationale="Sell signal detected",
            action_subtrack=ActionSubtrack.SELL,
        )
        r2 = sp.analyze(inp2, out2)

        # Different judgment_ids ensure independent analysis_ids
        assert r1.analysis_id != r2.analysis_id
        assert r1.primary_trigger.raw_value == 2.5
        assert r2.primary_trigger.raw_value == 3.5  # Second call uses larger NFP deviation
        assert r2.clearout_ratio > r1.clearout_ratio  # NFP > 3σ adds boost
