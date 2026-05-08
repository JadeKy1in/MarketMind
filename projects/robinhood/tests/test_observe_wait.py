"""
test_observe_wait.py — Unit tests for observe_wait.py (Phase 6, Track A)

Tests dataclass creation, threshold generation, undercurrent identification,
watchlist generation, and the ObserveWait.analyze() entry point.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.observe_wait import (
    ObserveWait,
    ObserveReport,
    TriggerThreshold,
    UnderCurrent,
    _generate_trigger_thresholds,
    _generate_undercurrents,
    _generate_watchlist,
    _get_scenario_detail,
)
from src.qualitative_judgment import (
    DecisionTrack,
    ObserveScenario,
    QualifierInput,
    QualifierOutput,
)
from src.scout_types import MacroTag, NarrativeTag, SourceRecord


# =========================================================================
# TC-OW-001..004: UnderCurrent dataclass
# =========================================================================


class TestUnderCurrent:
    """Validate UnderCurrent creation."""

    def test_minimal(self) -> None:
        """TC-OW-001: Minimal UnderCurrent with only required fields."""
        uc = UnderCurrent(name="Test", signal_type="macro", direction="bullish", intensity=0.5, description="Desc")
        assert uc.name == "Test"
        assert uc.related_indicators == []

    def test_full(self) -> None:
        """TC-OW-002: UnderCurrent with all fields."""
        uc = UnderCurrent(
            name="Dollar Weakness", signal_type="macro", direction="bullish",
            intensity=0.7, description="USD weakening supports EM.",
            related_indicators=["DXY", "UUP"],
        )
        assert len(uc.related_indicators) == 2

    def test_intensity_clamping(self) -> None:
        """TC-OW-003: Intensity is stored as-is (caller responsibility)."""
        uc = UnderCurrent(name="X", signal_type="t", direction="bullish", intensity=1.5, description="X")
        assert uc.intensity == 1.5  # raw

    def test_negative_intensity(self) -> None:
        """TC-OW-004: Negative intensity is permitted (deflation signal)."""
        uc = UnderCurrent(name="X", signal_type="t", direction="bearish", intensity=-0.2, description="X")
        assert uc.intensity == -0.2


# =========================================================================
# TC-OW-005..008: TriggerThreshold dataclass
# =========================================================================


class TestTriggerThreshold:
    """Validate TriggerThreshold creation."""

    def test_minimal(self) -> None:
        """TC-OW-005: Minimal TriggerThreshold."""
        tt = TriggerThreshold(indicator="CPI_MoM", direction="below", value=0.2, target_track="BUY", rationale="Low inflation")
        assert tt.priority == 1

    def test_with_priority(self) -> None:
        """TC-OW-006: With explicit priority."""
        tt = TriggerThreshold(indicator="VIX", direction="below", value=20.0, target_track="BUY", rationale="Panic over", priority=2)
        assert tt.priority == 2

    def test_sell_target(self) -> None:
        """TC-OW-007: SELL target track."""
        tt = TriggerThreshold(indicator="DXY", direction="above", value=105.0, target_track="SELL", rationale="Risk off")
        assert tt.target_track == "SELL"

    def test_rebalance_target(self) -> None:
        """TC-OW-008: REBALANCE target track."""
        tt = TriggerThreshold(indicator="PORTFOLIO_BETA", direction="crosses", value=1.2, target_track="REBALANCE", rationale="Re-risk")
        assert tt.target_track == "REBALANCE"


# =========================================================================
# TC-OW-009..012: ObserveReport dataclass
# =========================================================================


class TestObserveReport:
    """Validate ObserveReport creation."""

    def test_minimal(self) -> None:
        """TC-OW-009: Minimum required fields."""
        ts = datetime.now(timezone.utc).isoformat()
        r = ObserveReport(
            report_id="ow_test_001", judgment_id="qj_test_001",
            timestamp=ts, scenario=ObserveScenario.CONTRADICTION,
            scenario_detail="Mixed signals.",
        )
        assert r.underlying_currents == []
        assert r.trigger_thresholds == []
        assert r.watchlist_tickers == []
        assert r.narrative_extension == ""

    def test_full(self) -> None:
        """TC-OW-010: Report with all fields."""
        ts = datetime.now(timezone.utc).isoformat()
        r = ObserveReport(
            report_id="ow_test_002", judgment_id="qj_test_002",
            timestamp=ts, scenario=ObserveScenario.CHOPPY_REGIME,
            scenario_detail="Range-bound.",
            underlying_currents=[UnderCurrent(name="X", signal_type="t", direction="bullish", intensity=0.5, description="X")],
            trigger_thresholds=[TriggerThreshold(indicator="V", direction="above", value=1.0, target_track="BUY", rationale="R")],
            watchlist_tickers=["SPY", "QQQ"],
            narrative_extension="Watch for breakout.",
            confidence=0.7,
        )
        assert len(r.underlying_currents) == 1
        assert len(r.trigger_thresholds) == 1
        assert r.watchlist_tickers == ["SPY", "QQQ"]
        assert r.narrative_extension == "Watch for breakout."
        assert r.confidence == 0.7


# =========================================================================
# TC-OW-013..016: _get_scenario_detail
# =========================================================================


class TestGetScenarioDetail:
    """Validate scenario detail templates."""

    def test_contradiction(self) -> None:
        """TC-OW-013: CONTRADICTION returns correct template."""
        d = _get_scenario_detail(ObserveScenario.CONTRADICTION)
        assert "mixed messages" in d

    def test_poor_risk_reward(self) -> None:
        """TC-OW-014: POOR_RSK_REWARD returns correct template."""
        d = _get_scenario_detail(ObserveScenario.POOR_RSK_REWARD)
        assert "reward/risk" in d

    def test_choppy(self) -> None:
        """TC-OW-015: CHOPPY_REGIME returns correct template."""
        d = _get_scenario_detail(ObserveScenario.CHOPPY_REGIME)
        assert "range-bound" in d

    def test_unknown(self) -> None:
        """TC-OW-016: Unknown scenario returns fallback."""
        d = _get_scenario_detail(ObserveScenario.DATA_DROUGHT)  # type: ignore
        assert d != ""


# =========================================================================
# TC-OW-017..021: _generate_trigger_thresholds
# =========================================================================


class TestGenerateTriggerThresholds:
    """Validate threshold generation from macro context."""

    def test_nfp_surge_thresholds(self) -> None:
        """TC-OW-017: Large NFP deviation generates NFP threshold."""
        inp = QualifierInput(session_id="t", nfp_deviation=2.5)
        tts = _generate_trigger_thresholds(inp, ObserveScenario.CONTRADICTION)
        nfp_tts = [t for t in tts if t.indicator == "NFP_DEVIATION"]
        assert len(nfp_tts) == 1
        assert nfp_tts[0].target_track == "BUY"
        assert nfp_tts[0].priority == 1

    def test_no_nfp_threshold(self) -> None:
        """TC-OW-018: Small NFP deviation produces no NFP threshold."""
        inp = QualifierInput(session_id="t", nfp_deviation=0.5)
        tts = _generate_trigger_thresholds(inp, ObserveScenario.CONTRADICTION)
        assert all(t.indicator != "NFP_DEVIATION" for t in tts)

    def test_dollar_weakening_threshold(self) -> None:
        """TC-OW-019: Weakening dollar generates sell threshold."""
        inp = QualifierInput(session_id="t", dxy_trend="weakening")
        tts = _generate_trigger_thresholds(inp, ObserveScenario.CONTRADICTION)
        dxy_tts = [t for t in tts if t.indicator == "DXY_LEVEL"]
        assert len(dxy_tts) == 1
        assert dxy_tts[0].direction == "above"
        assert dxy_tts[0].value == 105.5

    def test_high_vix_thresholds(self) -> None:
        """TC-OW-020: VIX > 28 generates buy-on-panic-subsides threshold."""
        inp = QualifierInput(session_id="t", vix_level=35.0)
        tts = _generate_trigger_thresholds(inp, ObserveScenario.CONTRADICTION)
        vix_tts = [t for t in tts if t.indicator == "VIX_LEVEL"]
        assert len(vix_tts) == 1
        assert vix_tts[0].direction == "below"

    def test_choppy_regime_threshold(self) -> None:
        """TC-OW-021: Choppy regime generates Bollinger width threshold."""
        inp = QualifierInput(session_id="t", market_regime="choppy")
        tts = _generate_trigger_thresholds(inp, ObserveScenario.CHOPPY_REGIME)
        bw_tts = [t for t in tts if t.indicator == "SPX_BOLLINGER_WIDTH"]
        assert len(bw_tts) == 1


# =========================================================================
# TC-OW-022..026: _generate_undercurrents
# =========================================================================


class TestGenerateUndercurrents:
    """Validate undercurrent identification from macro context."""

    def test_dollar_weakening_current(self) -> None:
        """TC-OW-022: Weakening dollar produces bullish current."""
        inp = QualifierInput(session_id="t", dxy_trend="weakening")
        ucs = _generate_undercurrents(inp)
        names = [uc.name for uc in ucs]
        assert "Dollar Weakening Cycle" in names

    def test_dollar_strengthening_current(self) -> None:
        """TC-OW-023: Strengthening dollar produces bearish current."""
        inp = QualifierInput(session_id="t", dxy_trend="strengthening")
        ucs = _generate_undercurrents(inp)
        names = [uc.name for uc in ucs]
        assert "Dollar Strengthening Cycle" in names

    def test_inverted_yield_curve(self) -> None:
        """TC-OW-024: Inverted yield curve produces bearish current."""
        inp = QualifierInput(session_id="t", yield_curve="inverted")
        ucs = _generate_undercurrents(inp)
        names = [uc.name for uc in ucs]
        assert any("Inverted Yield" in n for n in names)

    def test_elevated_vix_current(self) -> None:
        """TC-OW-025: VIX > 25 produces elevated vol current."""
        inp = QualifierInput(session_id="t", vix_level=30.0)
        ucs = _generate_undercurrents(inp)
        names = [uc.name for uc in ucs]
        assert "Elevated Volatility Regime" in names

    def test_sticky_cpi_current(self) -> None:
        """TC-OW-026: CPI MoM > 0.4 produces sticky inflation current."""
        inp = QualifierInput(session_id="t", cpi_mom=0.5)
        ucs = _generate_undercurrents(inp)
        names = [uc.name for uc in ucs]
        assert "Sticky Inflation Pressure" in names


# =========================================================================
# TC-OW-027..030: _generate_watchlist
# =========================================================================


class TestGenerateWatchlist:
    """Validate watchlist generation from macro context."""

    def test_weakening_dollar_watchlist(self) -> None:
        """TC-OW-027: Weakening dollar includes GLD/SLV/DBC."""
        inp = QualifierInput(session_id="t", dxy_trend="weakening")
        wl = _generate_watchlist(inp)
        assert "GLD" in wl

    def test_strengthening_dollar_watchlist(self) -> None:
        """TC-OW-028: Strengthening dollar includes UUP."""
        inp = QualifierInput(session_id="t", dxy_trend="strengthening")
        wl = _generate_watchlist(inp)
        assert "UUP" in wl

    def test_inverted_curve_watchlist(self) -> None:
        """TC-OW-029: Inverted curve includes TLT."""
        inp = QualifierInput(session_id="t", yield_curve="inverted")
        wl = _generate_watchlist(inp)
        assert "TLT" in wl

    def test_steepening_curve_watchlist(self) -> None:
        """TC-OW-030: Steepening curve includes KRE."""
        inp = QualifierInput(session_id="t", yield_curve="steepening")
        wl = _generate_watchlist(inp)
        assert "KRE" in wl


# =========================================================================
# TC-OW-031..036: ObserveWait.analyze() end-to-end
# =========================================================================


class TestObserveWaitAnalyze:
    """Validate ObserveWait.analyze() end-to-end."""

    def _make_observe_output(
        self, scenario: ObserveScenario, coherence: float = 35.0, ror: float = 1.2
    ) -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_20260505_test_obs",
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.OBSERVE_AND_WAIT,
            track_confidence=min(1.0, coherence / 100.0),
            signal_coherence_score=coherence,
            reward_risk_ratio=ror,
            decision_rationale="Test observe",
            observe_scenario=scenario,
        )

    def test_observe_report_created(self) -> None:
        """TC-OW-031: analyze() returns a valid ObserveReport."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ow_001", dxy_trend="weakening", vix_level=30.0)
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert isinstance(report, ObserveReport)
        assert report.report_id.startswith("ow_")

    def test_report_links_to_judgment(self) -> None:
        """TC-OW-032: Report references the source judgment."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ow_002")
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert report.judgment_id == out.judgment_id

    def test_undercurrents_populated(self) -> None:
        """TC-OW-033: Undercurrents are populated from context."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ow_003", dxy_trend="weakening", vix_level=30.0, yield_curve="inverted")
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert len(report.underlying_currents) > 0

    def test_trigger_thresholds_populated(self) -> None:
        """TC-OW-034: Trigger thresholds are populated from context."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ow_004", dxy_trend="weakening", vix_level=35.0, nfp_deviation=2.5)
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert len(report.trigger_thresholds) > 0

    def test_watchlist_populated(self) -> None:
        """TC-OW-035: Watchlist tickers are populated."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ow_005", dxy_trend="weakening", yield_curve="inverted")
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert len(report.watchlist_tickers) > 0

    def test_last_report_property(self) -> None:
        """TC-OW-036: last_report returns most recent report."""
        ow = ObserveWait()
        assert ow.last_report is None
        inp1 = QualifierInput(session_id="test_a")
        out1 = self._make_observe_output(ObserveScenario.CONTRADICTION)
        r1 = ow.analyze(inp1, out1)
        assert ow.last_report is r1
        inp2 = QualifierInput(session_id="test_b", dxy_trend="strengthening")
        out2 = self._make_observe_output(ObserveScenario.CHOPPY_REGIME)
        r2 = ow.analyze(inp2, out2)
        assert ow.last_report is r2


# =========================================================================
# TC-OW-037..040: Edge cases and error handling
# =========================================================================


class TestObserveWaitEdgeCases:
    """Validate error handling and edge cases."""

    def test_rejects_action_track(self) -> None:
        """TC-OW-037: Raises ValueError if judgment is ACTION."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test")
        out = QualifierOutput(
            judgment_id="qj_action", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.9, signal_coherence_score=80.0,
            reward_risk_ratio=2.5, decision_rationale="Action!",
            action_subtrack=None,
        )
        with pytest.raises(ValueError, match="only process OBSERVE"):
            ow.analyze(inp, out)

    def test_empty_context_no_crash(self) -> None:
        """TC-OW-038: Empty macro context does not crash."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_empty")
        out = self._make_observe_output(ObserveScenario.DATA_DROUGHT)
        report = ow.analyze(inp, out)
        assert report.scenario == ObserveScenario.DATA_DROUGHT
        assert len(report.underlying_currents) == 0
        assert len(report.trigger_thresholds) == 0

    def test_confidence_propagated(self) -> None:
        """TC-OW-039: Report confidence matches judgment confidence."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_conf")
        out = self._make_observe_output(ObserveScenario.CONTRADICTION, coherence=42.0)
        report = ow.analyze(inp, out)
        assert report.confidence == pytest.approx(0.42)

    def test_narrative_extension_contains_triggers(self) -> None:
        """TC-OW-040: Narrative extension includes trigger info when present."""
        ow = ObserveWait()
        inp = QualifierInput(session_id="test_ext", dxy_trend="weakening", vix_level=35.0, nfp_deviation=2.5)
        out = self._make_observe_output(ObserveScenario.CONTRADICTION)
        report = ow.analyze(inp, out)
        assert "Key triggers" in report.narrative_extension
        assert "Watchlist" in report.narrative_extension

    # Helper to avoid code duplication
    @staticmethod
    def _make_observe_output(
        scenario: ObserveScenario, coherence: float = 35.0, ror: float = 1.2
    ) -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_20260505_test_obs",
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.OBSERVE_AND_WAIT,
            track_confidence=min(1.0, coherence / 100.0),
            signal_coherence_score=coherence,
            reward_risk_ratio=ror,
            decision_rationale="Test observe",
            observe_scenario=scenario,
        )