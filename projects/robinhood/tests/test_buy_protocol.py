"""
test_buy_protocol.py — Unit tests for buy_protocol.py (Phase 6 Track B BUY)

Tests data classes, risk-profile classification, penetration-matrix building,
price computation helpers, and the BuyProtocol.analyze() entry point.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.buy_protocol import (
    AssetPenetrationItem,
    BuyProtocol,
    OrderSuggestion,
    PenetrationLayer,
    RiskProfile,
    RiskProfileLabel,
    _build_penetration_matrix,
    _classify_risk_profile,
    _compute_limit_price,
    _compute_stop_loss,
    _compute_take_profit,
)
from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    MacroTag,
    QualifierInput,
    QualifierOutput,
)
from src.scout_types import AssetBasket


# =========================================================================
# TC-BP-001..004: RiskProfile dataclass
# =========================================================================


class TestRiskProfile:
    """Validate RiskProfile creation."""

    def test_minimal(self) -> None:
        """TC-BP-001: Minimal with required fields."""
        rp = RiskProfile(
            profile_id="rp_001", narrative_ref="macro_inflation",
            label=RiskProfileLabel.ASYMMETRIC, risk_reward_ratio=3.5,
            expected_upside_pct=30.0, expected_downside_pct=10.0,
            safety_margin_pct=35.0, confidence_rating="HIGH",
            rationale="Panic buy zone identified.",
        )
        assert rp.triggering_conditions == []
        assert rp.risk_warnings == []
        assert rp.time_horizon == "3–6 months"

    def test_full(self) -> None:
        """TC-BP-002: All fields populated."""
        rp = RiskProfile(
            profile_id="rp_002", narrative_ref="macro_vix",
            label=RiskProfileLabel.SPECULATIVE, risk_reward_ratio=1.5,
            expected_upside_pct=25.0, expected_downside_pct=15.0,
            safety_margin_pct=10.0, confidence_rating="MEDIUM",
            rationale="Event-driven opportunity.",
            triggering_conditions=["NFP deviation > 2σ"],
            risk_warnings=["Binary risk", "Short time horizon"],
            time_horizon="1–3 months",
        )
        assert len(rp.triggering_conditions) == 1
        assert "Binary risk" in rp.risk_warnings
        assert rp.time_horizon == "1–3 months"

    def test_all_labels_present(self) -> None:
        """TC-BP-003: All three RiskProfileLabel values exist."""
        assert RiskProfileLabel.ASYMMETRIC.value == "asymmetric"
        assert RiskProfileLabel.SPECULATIVE.value == "speculative"
        assert RiskProfileLabel.TREND_FOLLOWING.value == "trend_following"

    def test_confidence_values(self) -> None:
        """TC-BP-004: Confidence rating accepts standard strings."""
        for rating in ("HIGH", "MEDIUM", "LOW"):
            rp = RiskProfile(
                profile_id="x", narrative_ref="n", label=RiskProfileLabel.TREND_FOLLOWING,
                risk_reward_ratio=2.0, expected_upside_pct=15.0, expected_downside_pct=8.0,
                safety_margin_pct=20.0, confidence_rating=rating,
                rationale="Test confidence.",
            )
            assert rp.confidence_rating == rating


# =========================================================================
# TC-BP-005..007: AssetPenetrationItem dataclass
# =========================================================================


class TestAssetPenetrationItem:
    """Validate AssetPenetrationItem creation."""

    def test_minimal(self) -> None:
        """TC-BP-005: Only ticker required."""
        item = AssetPenetrationItem(ticker="GLD")
        assert item.direction == "BUY"
        assert item.layer == "core"
        assert item.suggested_weight_pct == 0.0

    def test_full(self) -> None:
        """TC-BP-006: All fields populated."""
        item = AssetPenetrationItem(
            ticker="GDX", direction="BUY", layer="upstream_leverage",
            layer_rationale="Gold miners with operational leverage",
            suggested_weight_pct=5.0, current_price=35.0,
            limit_price=34.8, stop_loss=31.5, take_profit=43.75,
            expected_return_pct=25.0, beta=1.5,
            correlation_warning=None, risk_note="High beta",
        )
        assert item.ticker == "GDX"
        assert item.stop_loss == 31.5
        assert item.beta == 1.5

    def test_default_layer(self) -> None:
        """TC-BP-007: Default layer is 'core'."""
        item = AssetPenetrationItem(ticker="SPY")
        assert item.layer == PenetrationLayer.CORE.value


# =========================================================================
# TC-BP-008..011: OrderSuggestion dataclass
# =========================================================================


class TestOrderSuggestion:
    """Validate OrderSuggestion creation."""

    def test_minimal(self) -> None:
        """TC-BP-008: Minimum required fields."""
        o = OrderSuggestion(order_id="ord_001", created_at="now")
        assert o.action_type == "BUY"
        assert o.penetration_items == []
        assert o.causal_audit_refs == []
        assert "THEORETICAL ONLY" in o.execution_disclaimer

    def test_with_risk_profile(self) -> None:
        """TC-BP-009: With RiskProfile attached."""
        rp = RiskProfile(
            profile_id="rp_001", narrative_ref="n", label=RiskProfileLabel.ASYMMETRIC,
            risk_reward_ratio=3.0, expected_upside_pct=30.0, expected_downside_pct=10.0,
            safety_margin_pct=35.0, confidence_rating="HIGH",
            rationale="Test.",
        )
        o = OrderSuggestion(order_id="ord_002", created_at="now", risk_profile=rp)
        assert o.risk_profile is not None
        assert o.risk_profile.label == RiskProfileLabel.ASYMMETRIC

    def test_physical_isolation_disclaimer(self) -> None:
        """TC-BP-010: Execution disclaimer is always present."""
        o = OrderSuggestion(order_id="ord_003", created_at="now")
        assert "NO BROKERAGE API CONNECTED" in o.execution_disclaimer

    def test_with_penetration_items(self) -> None:
        """TC-BP-011: Penetration items can be populated."""
        items = [
            AssetPenetrationItem(ticker="GLD", suggested_weight_pct=8.0),
            AssetPenetrationItem(ticker="GDX", suggested_weight_pct=4.0),
        ]
        o = OrderSuggestion(
            order_id="ord_004", created_at="now",
            penetration_items=items,
            total_notional_commitment=12000.0,
            cash_reserve_after=88000.0,
        )
        assert len(o.penetration_items) == 2
        assert o.total_notional_commitment == 12000.0


# =========================================================================
# TC-BP-012..015: _classify_risk_profile
# =========================================================================


class TestClassifyRiskProfile:
    """Validate risk-profile classification logic."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_buy"}
        params.update(kwargs)
        return QualifierInput(**params)

    @staticmethod
    def _make_output(coherence: float = 50.0, rr: float = 2.0) -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_buy_test", timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.ACTION_AND_ADJUST, track_confidence=0.85,
            signal_coherence_score=coherence, reward_risk_ratio=rr,
            decision_rationale="Test buy", action_subtrack=ActionSubtrack.BUY,
        )

    def test_asymmetric_vix_panic(self) -> None:
        """TC-BP-012: VIX > 35 → ASYMMETRIC."""
        inp = self._make_input(vix_level=40.0)
        out = self._make_output()
        rp = _classify_risk_profile(inp, out)
        assert rp.label == RiskProfileLabel.ASYMMETRIC
        assert rp.safety_margin_pct >= 30.0
        assert "VIX" in rp.triggering_conditions[0]

    def test_asymmetric_low_coherence(self) -> None:
        """TC-BP-013: Coherence < 25 → ASYMMETRIC."""
        inp = self._make_input(vix_level=20.0)
        out = self._make_output(coherence=15.0)
        rp = _classify_risk_profile(inp, out)
        assert rp.label == RiskProfileLabel.ASYMMETRIC
        assert "coherence" in rp.triggering_conditions[0].lower()

    def test_speculative_nfp_surprise(self) -> None:
        """TC-BP-014: NFP > 2σ → SPECULATIVE."""
        inp = self._make_input(nfp_deviation=2.8, vix_level=20.0)
        out = self._make_output(coherence=50.0)
        rp = _classify_risk_profile(inp, out)
        assert rp.label == RiskProfileLabel.SPECULATIVE
        assert "NFP" in rp.triggering_conditions[0]
        assert rp.risk_reward_ratio < 3.0

    def test_trend_following_default(self) -> None:
        """TC-BP-015: Clean inputs → TREND_FOLLOWING."""
        inp = self._make_input(
            nfp_deviation=0.5, vix_level=20.0,
            market_regime="trending", dxy_trend="stable",
        )
        out = self._make_output(coherence=75.0, rr=2.5)
        rp = _classify_risk_profile(inp, out)
        assert rp.label == RiskProfileLabel.TREND_FOLLOWING
        assert rp.confidence_rating == "HIGH"
        assert rp.risk_reward_ratio == 2.5  # uses the output's RR when > 0


# =========================================================================
# TC-BP-016..020: _build_penetration_matrix
# =========================================================================


class TestBuildPenetrationMatrix:
    """Validate penetration-matrix building logic."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_buy_pen"}
        params.update(kwargs)
        return QualifierInput(**params)

    @staticmethod
    def _make_profile(
        label: RiskProfileLabel = RiskProfileLabel.TREND_FOLLOWING,
        confidence: str = "HIGH",
    ) -> RiskProfile:
        return RiskProfile(
            profile_id="rp_test", narrative_ref="n",
            label=label, risk_reward_ratio=2.0,
            expected_upside_pct=15.0, expected_downside_pct=8.0,
            safety_margin_pct=20.0, confidence_rating=confidence,
            rationale="Test penetration.",
        )

    def test_with_basket(self) -> None:
        """TC-BP-016: Uses AssetBasket when provided."""
        basket = AssetBasket(
            high_liquidity=["GLD", "TLT", "SPY"],
            high_beta=["GDX", "XLE"],
            low_expense_ratio=["VDE"],
        )
        inp = self._make_input()
        profile = self._make_profile()
        items = _build_penetration_matrix(inp, profile, basket)
        assert len(items) == 6  # 3 core + 2 upstream + 1 downstream
        tickers = {i.ticker for i in items}
        assert "GLD" in tickers
        assert "GDX" in tickers
        assert "VDE" in tickers

    def test_inferred_from_dxy_weak(self) -> None:
        """TC-BP-017: DXY weakening → commodity bias."""
        inp = self._make_input(dxy_trend="weakening")
        profile = self._make_profile()
        items = _build_penetration_matrix(inp, profile, None)
        core_tickers = [i.ticker for i in items if i.layer == "core"]
        assert "GLD" in core_tickers
        assert "DBC" in core_tickers

    def test_inferred_from_dxy_strong(self) -> None:
        """TC-BP-018: DXY strengthening → USD cash bias."""
        inp = self._make_input(dxy_trend="strengthening")
        profile = self._make_profile()
        items = _build_penetration_matrix(inp, profile, None)
        core_tickers = [i.ticker for i in items if i.layer == "core"]
        assert "USFR" in core_tickers
        assert "SHY" in core_tickers

    def test_asymmetric_sizing(self) -> None:
        """TC-BP-019: ASYMMETRIC profile → larger position sizes."""
        inp = self._make_input(dxy_trend="weakening")
        profile = self._make_profile(label=RiskProfileLabel.ASYMMETRIC, confidence="HIGH")
        items = _build_penetration_matrix(inp, profile, None)
        total_weight = sum(i.suggested_weight_pct for i in items)
        assert total_weight > 15.0  # ASYMMETRIC + HIGH = aggressive

    def test_speculative_low_confidence_sizing(self) -> None:
        """TC-BP-020: SPECULATIVE + LOW confidence → minimal sizing."""
        inp = self._make_input(dxy_trend="weakening")
        profile = self._make_profile(label=RiskProfileLabel.SPECULATIVE, confidence="LOW")
        items = _build_penetration_matrix(inp, profile, None)
        total_weight = sum(i.suggested_weight_pct for i in items)
        assert total_weight < 8.0  # SPECULATIVE + LOW = very conservative


# =========================================================================
# TC-BP-021..024: Price computation helpers
# =========================================================================


class TestPriceComputation:
    """Validate limit-price / stop-loss / take-profit computation."""

    def test_limit_price_buy(self) -> None:
        """TC-BP-021: Buy limit is 0.5% below current price."""
        lp = _compute_limit_price(100.0, "BUY")
        assert lp == 99.50

    def test_limit_price_none(self) -> None:
        """TC-BP-022: Returns None when no current price."""
        lp = _compute_limit_price(None, "BUY")
        assert lp is None

    def test_stop_loss_by_profile(self) -> None:
        """TC-BP-023: Stop-loss varies by profile label."""
        asymmetric = _compute_stop_loss(
            100.0,
            RiskProfile(profile_id="x", narrative_ref="n", label=RiskProfileLabel.ASYMMETRIC,
                        risk_reward_ratio=3.0, expected_upside_pct=30.0,
                        expected_downside_pct=10.0, safety_margin_pct=35.0,
                        confidence_rating="HIGH", rationale="Test."),
        )
        speculative = _compute_stop_loss(
            100.0,
            RiskProfile(profile_id="x", narrative_ref="n", label=RiskProfileLabel.SPECULATIVE,
                        risk_reward_ratio=1.5, expected_upside_pct=25.0,
                        expected_downside_pct=15.0, safety_margin_pct=10.0,
                        confidence_rating="MEDIUM", rationale="Test."),
        )
        assert asymmetric == 90.00   # 10% below
        assert speculative == 95.00  # 5% below

    def test_take_profit_by_profile(self) -> None:
        """TC-BP-024: Take-profit varies by profile label."""
        asymmetric = _compute_take_profit(
            100.0,
            RiskProfile(profile_id="x", narrative_ref="n", label=RiskProfileLabel.ASYMMETRIC,
                        risk_reward_ratio=3.0, expected_upside_pct=30.0,
                        expected_downside_pct=10.0, safety_margin_pct=35.0,
                        confidence_rating="HIGH", rationale="Test."),
        )
        trend = _compute_take_profit(
            100.0,
            RiskProfile(profile_id="x", narrative_ref="n", label=RiskProfileLabel.TREND_FOLLOWING,
                        risk_reward_ratio=2.0, expected_upside_pct=15.0,
                        expected_downside_pct=8.0, safety_margin_pct=20.0,
                        confidence_rating="HIGH", rationale="Test."),
        )
        assert asymmetric == 125.00  # +25%
        assert trend == 115.00       # +15%


# =========================================================================
# TC-BP-025..030: BuyProtocol.analyze() end-to-end
# =========================================================================


class TestBuyProtocolAnalyze:
    """Validate BuyProtocol.analyze() end-to-end."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_buy_e2e"}
        params.update(kwargs)
        return QualifierInput(**params)

    @staticmethod
    def _make_output(coherence: float = 60.0, rr: float = 2.5) -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_buy_e2e", timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.ACTION_AND_ADJUST, track_confidence=0.85,
            signal_coherence_score=coherence, reward_risk_ratio=rr,
            decision_rationale="Buy test", action_subtrack=ActionSubtrack.BUY,
        )

    def test_order_created(self) -> None:
        """TC-BP-025: analyze() returns a valid OrderSuggestion."""
        bp = BuyProtocol()
        inp = self._make_input(nfp_deviation=0.5, vix_level=18.0)
        out = self._make_output()
        order = bp.analyze(inp, out)
        assert isinstance(order, OrderSuggestion)
        assert order.order_id.startswith("ord_")

    def test_links_to_judgment(self) -> None:
        """TC-BP-026: Order references the source judgment."""
        bp = BuyProtocol()
        inp = self._make_input()
        out = self._make_output()
        order = bp.analyze(inp, out)
        assert order.causal_audit_refs is not None

    def test_risk_profile_populated(self) -> None:
        """TC-BP-027: Layer 1 RiskProfile is populated."""
        bp = BuyProtocol()
        inp = self._make_input(nfp_deviation=0.5, vix_level=18.0)
        out = self._make_output(coherence=75.0)
        order = bp.analyze(inp, out)
        assert order.risk_profile is not None
        assert order.risk_profile.label in (
            RiskProfileLabel.TREND_FOLLOWING, RiskProfileLabel.SPECULATIVE,
        )

    def test_penetration_items_populated(self) -> None:
        """TC-BP-028: Layer 2 penetration items are populated."""
        bp = BuyProtocol()
        inp = self._make_input(dxy_trend="weakening")
        out = self._make_output()
        order = bp.analyze(inp, out)
        assert len(order.penetration_items) > 0
        # Should include core / upstream / downstream layers
        layers = {i.layer for i in order.penetration_items}
        assert len(layers) >= 2

    def test_capital_summary(self) -> None:
        """TC-BP-029: Capital summary is computed."""
        bp = BuyProtocol()
        inp = self._make_input(dxy_trend="weakening")
        out = self._make_output()
        order = bp.analyze(inp, out, buying_power=200_000.0)
        assert order.total_notional_commitment > 0
        assert order.cash_reserve_after > 0
        assert 0.0 < order.cash_reserve_pct < 100.0

    def test_last_order_property(self) -> None:
        """TC-BP-030: last_order and last_risk_profile track most recent."""
        bp = BuyProtocol()
        assert bp.last_order is None
        assert bp.last_risk_profile is None

        inp1 = self._make_input(nfp_deviation=0.5, vix_level=18.0)
        out1 = self._make_output()
        r1 = bp.analyze(inp1, out1)
        assert bp.last_order is r1
        assert bp.last_risk_profile is r1.risk_profile

        inp2 = self._make_input(vix_level=40.0)  # should trigger ASYMMETRIC
        out2 = self._make_output()
        r2 = bp.analyze(inp2, out2)
        assert bp.last_order is r2
        assert bp.last_order is not r1
        assert bp.last_risk_profile.label == RiskProfileLabel.ASYMMETRIC


# =========================================================================
# TC-BP-031..034: Error handling
# =========================================================================


class TestBuyProtocolErrors:
    """Validate error handling."""

    @staticmethod
    def _make_input(**kwargs) -> QualifierInput:
        params = {"session_id": "test_buy_err"}
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
    def _make_sell_output() -> QualifierOutput:
        return QualifierOutput(
            judgment_id="qj_sell", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.9, signal_coherence_score=30.0,
            reward_risk_ratio=0.5, decision_rationale="Sell",
            action_subtrack=ActionSubtrack.SELL,
        )

    def test_rejects_observe_track(self) -> None:
        """TC-BP-031: Raises ValueError if not ACTION."""
        bp = BuyProtocol()
        inp = self._make_input()
        out = self._make_observe_output()
        with pytest.raises(ValueError, match="requires ACTION"):
            bp.analyze(inp, out)

    def test_rejects_sell_subtrack(self) -> None:
        """TC-BP-032: Raises ValueError if not BUY."""
        bp = BuyProtocol()
        inp = self._make_input()
        out = self._make_sell_output()
        with pytest.raises(ValueError, match="requires action_subtrack=BUY"):
            bp.analyze(inp, out)

    def test_empty_input_no_crash(self) -> None:
        """TC-BP-033: Empty input does not crash."""
        bp = BuyProtocol()
        inp = self._make_input()
        out = QualifierOutput(
            judgment_id="qj_buy", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.85, signal_coherence_score=60.0,
            reward_risk_ratio=2.0, decision_rationale="Buy test",
            action_subtrack=ActionSubtrack.BUY,
        )
        order = bp.analyze(inp, out)
        assert order.risk_profile is not None
        assert len(order.penetration_items) > 0

    def test_two_calls_independent(self) -> None:
        """TC-BP-034: Successive calls produce independent results."""
        bp = BuyProtocol()

        inp1 = QualifierInput(session_id="t1", nfp_deviation=0.5, vix_level=18.0)
        out1 = QualifierOutput(
            judgment_id="qj_buy1", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.85, signal_coherence_score=75.0,
            reward_risk_ratio=2.5, decision_rationale="Buy trend",
            action_subtrack=ActionSubtrack.BUY,
        )
        r1 = bp.analyze(inp1, out1)

        inp2 = QualifierInput(session_id="t2", nfp_deviation=0.5, vix_level=40.0)
        out2 = QualifierOutput(
            judgment_id="qj_buy2", timestamp="now",
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.85, signal_coherence_score=60.0,
            reward_risk_ratio=2.0, decision_rationale="Buy panic",
            action_subtrack=ActionSubtrack.BUY,
        )
        r2 = bp.analyze(inp2, out2)

        assert r1.order_id != r2.order_id
        assert r1.risk_profile.label == RiskProfileLabel.TREND_FOLLOWING
        assert r2.risk_profile.label == RiskProfileLabel.ASYMMETRIC