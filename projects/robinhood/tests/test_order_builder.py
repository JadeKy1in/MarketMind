"""
test_order_builder.py — Phase 6 Unit Tests for OrderBuilder.

Covers all three routing paths plus error handling:
  1. OBSERVE_WAIT → ObserveWaitProtocol
  2. ACTION + SELL → SellProtocol
  3. ACTION + BUY → BuyProtocol (with optional AssetBasket)
  4. Unknown decision_track → error output
  5. Unknown action_subtrack → error output
  6. ExecutionOutput.to_dict() serialization
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from src.buy_protocol import OrderSuggestion, RiskProfile, RiskProfileLabel
from src.observe_wait import (
    ObserveAnalysis,
    MarketDriftAnalysis,
    TriggerThreshold,
)
from src.order_builder import ExecutionOutput, OrderBuilder
from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    ObserveScenario,
    QualifierInput,
    QualifierOutput,
)
from src.scout_types import AssetBasket
from src.sell_protocol import SellAnalysis, SellTrigger, SellTriggerCategory


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def base_input() -> QualifierInput:
    """Standard input fixture shared across test cases."""
    return QualifierInput(
        session_id="test-base",
        vix_level=15.0,
        dxy_trend="neutral",
        yield_curve="normal",
        market_regime="trending",
        nfp_deviation=0.5,
        cpi_mom=0.2,
        macro_tags=[],
    )


@pytest.fixture
def observe_input() -> QualifierInput:
    """Input that should trigger OBSERVE_WAIT."""
    return QualifierInput(
        session_id="test-observe",
        vix_level=12.0,
        dxy_trend="neutral",
        yield_curve="flat",
        market_regime="choppy",
        nfp_deviation=-0.3,
        cpi_mom=0.1,
        macro_tags=[],
    )


@pytest.fixture
def sell_input() -> QualifierInput:
    """Input with strong sell triggers."""
    return QualifierInput(
        session_id="test-sell",
        vix_level=32.0,
        dxy_trend="strengthening",
        yield_curve="inverted",
        market_regime="risk_off",
        nfp_deviation=-2.5,
        cpi_mom=0.6,
        macro_tags=[],
    )


@pytest.fixture
def buy_input() -> QualifierInput:
    """Input with strong buy signals."""
    return QualifierInput(
        session_id="test-buy",
        vix_level=18.0,
        dxy_trend="weakening",
        yield_curve="normal",
        market_regime="trending",
        nfp_deviation=1.0,
        cpi_mom=-0.1,
        macro_tags=[],
    )


@pytest.fixture
def observe_output(observe_input: QualifierInput) -> QualifierOutput:
    """A QualifierOutput routed to OBSERVE_WAIT."""
    return QualifierOutput(
        judgment_id="jg_obs_001",
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision_track=DecisionTrack.OBSERVE_AND_WAIT,
        track_confidence=0.3,
        signal_coherence_score=40.0,
        reward_risk_ratio=0.3,
        decision_rationale="Contradictory signals. Choppy regime. Stay sidelined.",
        action_subtrack=None,
        observe_scenario=ObserveScenario.CONTRADICTION,
    )


@pytest.fixture
def sell_output(sell_input: QualifierInput) -> QualifierOutput:
    """A QualifierOutput routed to ACTION + SELL."""
    return QualifierOutput(
        judgment_id="jg_sl_002",
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision_track=DecisionTrack.ACTION_AND_ADJUST,
        track_confidence=0.7,
        signal_coherence_score=25.0,
        reward_risk_ratio=0.5,
        decision_rationale="VIX spike + NFP miss. Risk-off confirmed across indicators.",
        action_subtrack=ActionSubtrack.SELL,
    )


@pytest.fixture
def buy_output(buy_input: QualifierInput) -> QualifierOutput:
    """A QualifierOutput routed to ACTION + BUY."""
    return QualifierOutput(
        judgment_id="jg_buy_003",
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision_track=DecisionTrack.ACTION_AND_ADJUST,
        track_confidence=0.85,
        signal_coherence_score=80.0,
        reward_risk_ratio=3.0,
        decision_rationale="Strong macro alignment. DXY weakening + low VIX.",
        action_subtrack=ActionSubtrack.BUY,
    )


@pytest.fixture
def asset_basket() -> AssetBasket:
    """Example AssetBasket for buy routing tests."""
    return AssetBasket(
        high_liquidity=["SPY", "TLT", "GLD"],
        high_beta=["GDX"],
        low_expense_ratio=["VDE"],
    )


# =========================================================================
# Route A: OBSERVE_WAIT
# =========================================================================


class TestObserveWaitRouting:
    """OrderBuilder routing to ObserveWait protocol."""

    def test_observe_output_type(self, observe_input: QualifierInput,
                                 observe_output: QualifierOutput) -> None:
        """Routing OBSERVE_WAIT should return an ExecutionOutput with observe_analysis."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)

        assert isinstance(output, ExecutionOutput)
        assert output.decision_track == "OBSERVE_WAIT"
        assert output.action_subtrack == "WAIT"
        assert output.observe_analysis is not None
        assert output.sell_analysis is None
        assert output.buy_order_suggestion is None
        assert output.error is None
        assert "THEORETICAL ONLY" in output.execution_disclaimer

    def test_observe_analysis_content(self, observe_input: QualifierInput,
                                      observe_output: QualifierOutput) -> None:
        """The observe_analysis field should be a valid ObserveAnalysis."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)

        analysis = output.observe_analysis
        assert isinstance(analysis, ObserveAnalysis)
        assert analysis.protocol == "OBSERVE_WAIT"
        assert "obs_" in output.order_id

    def test_observe_last_output(self, observe_input: QualifierInput,
                                 observe_output: QualifierOutput) -> None:
        """last_output should reflect the most recent execution."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)

        assert builder.last_output is output
        assert builder.last_output.decision_track == "OBSERVE_WAIT"

    def test_observe_to_dict(self, observe_input: QualifierInput,
                             observe_output: QualifierOutput) -> None:
        """to_dict should produce a serializable dict with observe_analysis key."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)
        d = output.to_dict()

        assert isinstance(d, dict)
        assert d["decision_track"] == "OBSERVE_WAIT"
        assert d["action_subtrack"] == "WAIT"
        assert "observe_analysis" in d
        assert d["sell_analysis"] is None
        assert d["buy_order_suggestion"] is None
        assert d["error"] is None
        assert "THEORETICAL ONLY" in d["execution_disclaimer"]

    def test_observe_empty_narrative(self, observe_input: QualifierInput,
                                     observe_output: QualifierOutput) -> None:
        """With no macro_tags, narrative_ref should be empty string."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)
        assert output.narrative_ref == ""


# =========================================================================
# Route B — SELL
# =========================================================================


class TestSellRouting:
    """OrderBuilder routing to SellProtocol."""

    def test_sell_output_type(self, sell_input: QualifierInput,
                              sell_output: QualifierOutput) -> None:
        """Routing ACTION + SELL should return ExecutionOutput with sell_analysis."""
        builder = OrderBuilder()
        output = builder.execute(sell_input, sell_output)

        assert isinstance(output, ExecutionOutput)
        assert output.decision_track == "ACTION_AND_ADJUST"
        assert output.action_subtrack == "SELL"
        assert output.sell_analysis is not None
        assert output.observe_analysis is None
        assert output.buy_order_suggestion is None
        assert output.error is None

    def test_sell_analysis_content(self, sell_input: QualifierInput,
                                   sell_output: QualifierOutput) -> None:
        """sell_analysis should be a valid SellAnalysis with trigger info."""
        builder = OrderBuilder()
        output = builder.execute(sell_input, sell_output)

        analysis = output.sell_analysis
        assert isinstance(analysis, SellAnalysis)
        assert isinstance(analysis.primary_trigger, SellTrigger)
        assert analysis.primary_trigger.category == SellTriggerCategory.MACRO_SURPRISE
        assert "sl_" in output.order_id

    def test_sell_to_dict(self, sell_input: QualifierInput,
                          sell_output: QualifierOutput) -> None:
        """to_dict should include sell_analysis key with nested trigger."""
        builder = OrderBuilder()
        output = builder.execute(sell_input, sell_output)
        d = output.to_dict()

        assert d["decision_track"] == "ACTION_AND_ADJUST"
        assert d["action_subtrack"] == "SELL"
        assert "sell_analysis" in d
        sa = d["sell_analysis"]
        assert sa["primary_trigger"]["category"] == "macro_surprise"

    def test_sell_last_output(self, sell_input: QualifierInput,
                              sell_output: QualifierOutput) -> None:
        """last_output tracks the sell execution."""
        builder = OrderBuilder()
        output = builder.execute(sell_input, sell_output)
        assert builder.last_output is output
        assert builder.last_output.action_subtrack == "SELL"


# =========================================================================
# Route B — BUY
# =========================================================================


class TestBuyRouting:
    """OrderBuilder routing to BuyProtocol."""

    def test_buy_output_type(self, buy_input: QualifierInput,
                             buy_output: QualifierOutput) -> None:
        """Routing ACTION + BUY should return ExecutionOutput with buy_order_suggestion."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)

        assert isinstance(output, ExecutionOutput)
        assert output.decision_track == "ACTION_AND_ADJUST"
        assert output.action_subtrack == "BUY"
        assert output.buy_order_suggestion is not None
        assert output.observe_analysis is None
        assert output.sell_analysis is None
        assert output.error is None

    def test_buy_with_asset_basket(self, buy_input: QualifierInput,
                                   buy_output: QualifierOutput,
                                   asset_basket: AssetBasket) -> None:
        """Passing an AssetBasket should populate penetration items."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output, asset_basket=asset_basket)

        order = output.buy_order_suggestion
        assert isinstance(order, OrderSuggestion)
        assert len(order.penetration_items) > 0
        assert order.risk_profile is not None
        assert order.total_notional_commitment > 0

    def test_buy_without_asset_basket(self, buy_input: QualifierInput,
                                      buy_output: QualifierOutput) -> None:
        """Without AssetBasket, should infer tickers from macro signals."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output, asset_basket=None)

        order = output.buy_order_suggestion
        assert isinstance(order, OrderSuggestion)
        assert len(order.penetration_items) > 0
        assert order.risk_profile is not None

    def test_buy_risk_profile(self, buy_input: QualifierInput,
                              buy_output: QualifierOutput) -> None:
        """Risk profile should be TREND_FOLLOWING (coherence 80 >= 70)."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)

        profile = output.buy_order_suggestion.risk_profile
        assert profile is not None
        assert profile.label == RiskProfileLabel.TREND_FOLLOWING
        assert profile.confidence_rating == "HIGH"

    def test_buy_to_dict(self, buy_input: QualifierInput,
                         buy_output: QualifierOutput) -> None:
        """to_dict should include buy_order_suggestion with nested risk_profile."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)
        d = output.to_dict()

        assert d["action_subtrack"] == "BUY"
        assert "buy_order_suggestion" in d
        bos = d["buy_order_suggestion"]
        assert bos["risk_profile"]["label"] == "trend_following"

    def test_buy_execution_disclaimer(self, buy_input: QualifierInput,
                                      buy_output: QualifierOutput) -> None:
        """The OrderSuggestion embedded disclaimer should be preserved."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)

        order = output.buy_order_suggestion
        assert "NO BROKERAGE API" in order.execution_disclaimer
        assert "THEORETICAL ONLY" in order.execution_disclaimer

    def test_buy_capital_summary(self, buy_input: QualifierInput,
                                 buy_output: QualifierOutput) -> None:
        """Capital summary should be populated with notionals."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)

        order = output.buy_order_suggestion
        assert order.total_notional_commitment > 0
        assert order.cash_reserve_after > 0
        assert order.cash_reserve_pct > 0

    def test_buy_custom_buying_power(self, buy_input: QualifierInput,
                                     buy_output: QualifierOutput) -> None:
        """Custom buying_power should affect notional commitment."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output, buying_power=50_000.0)

        order = output.buy_order_suggestion
        assert order.total_notional_commitment < 50_000

    def test_buy_last_output(self, buy_input: QualifierInput,
                             buy_output: QualifierOutput) -> None:
        """last_output reflects the buy execution."""
        builder = OrderBuilder()
        output = builder.execute(buy_input, buy_output)
        assert builder.last_output is output
        assert builder.last_output.action_subtrack == "BUY"


# =========================================================================
# Error handling
# =========================================================================


class TestErrorHandling:
    """OrderBuilder error routing and ExecutionOutput.error_output factory."""

    def test_unknown_decision_track(self, base_input: QualifierInput) -> None:
        """An invalid decision_track should produce an error ExecutionOutput."""
        bad_output = QualifierOutput(
            judgment_id="jg_bad_000",
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track="INVALID_TRACK",  # type: ignore[arg-type]
            track_confidence=0.5,
            signal_coherence_score=50.0,
            reward_risk_ratio=1.0,
            decision_rationale="Invalid track test.",
        )

        builder = OrderBuilder()
        output = builder.execute(base_input, bad_output)

        assert output.error is not None
        assert "Unknown decision_track" in output.error
        assert output.observe_analysis is None
        assert output.sell_analysis is None
        assert output.buy_order_suggestion is None

    def test_unknown_action_subtrack(self, base_input: QualifierInput) -> None:
        """An unknown action_subtrack for ACTION_AND_ADJUST should produce an error."""
        bad_output = QualifierOutput(
            judgment_id="jg_bad_sub_000",
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_track=DecisionTrack.ACTION_AND_ADJUST,
            track_confidence=0.5,
            signal_coherence_score=50.0,
            reward_risk_ratio=1.0,
            decision_rationale="Bad subtrack test.",
            action_subtrack="HODL",  # type: ignore[arg-type]
        )

        builder = OrderBuilder()
        output = builder.execute(base_input, bad_output)

        assert output.error is not None
        assert "Unknown action_subtrack" in output.error
        assert output.action_subtrack is None

    def test_error_output_factory(self) -> None:
        """ExecutionOutput.error_output class method should produce a valid error state."""
        output = ExecutionOutput.error_output(
            error_message="Something went wrong",
            decision_track="ACTION_AND_ADJUST",
        )

        assert isinstance(output, ExecutionOutput)
        assert output.error == "Something went wrong"
        assert output.decision_track == "ACTION_AND_ADJUST"
        assert output.observe_analysis is None
        assert output.sell_analysis is None
        assert output.buy_order_suggestion is None
        assert "err_" in output.order_id
        assert "THEORETICAL ONLY" in output.execution_disclaimer

    def test_error_to_dict(self) -> None:
        """Error ExecutionOutput should serialize correctly to dict."""
        output = ExecutionOutput.error_output(
            error_message="Test error",
            decision_track="OBSERVE_WAIT",
        )
        d = output.to_dict()

        assert d["error"] == "Test error"
        assert d["decision_track"] == "OBSERVE_WAIT"
        assert "observe_analysis" in d
        assert "sell_analysis" in d
        assert "buy_order_suggestion" in d
        assert d["observe_analysis"] is None

    def test_no_error_default(self) -> None:
        """A default ExecutionOutput should have error=None."""
        output = ExecutionOutput(
            order_id="test_001",
            created_at="2026-01-01T00:00:00",
            decision_track="OBSERVE_WAIT",
        )
        assert output.error is None

    def test_observe_to_dict_no_extra_props(self, observe_input: QualifierInput,
                                            observe_output: QualifierOutput) -> None:
        """Observe route dict should not contain unknown top-level keys."""
        builder = OrderBuilder()
        output = builder.execute(observe_input, observe_output)
        d = output.to_dict()

        expected_keys = {
            "order_id", "created_at", "decision_track", "action_subtrack",
            "narrative_ref", "execution_disclaimer", "error",
            "observe_analysis", "sell_analysis", "buy_order_suggestion",
        }
        assert set(d.keys()) == expected_keys


# =========================================================================
# ExecutionOutput structural integrity
# =========================================================================


class TestExecutionOutputIntegrity:
    """Structural guarantees of ExecutionOutput."""

    def test_disclaimer_always_present(self, observe_input: QualifierInput,
                                       observe_output: QualifierOutput) -> None:
        """All ExecutionOutputs must carry the physical isolation disclaimer."""
        builder = OrderBuilder()
        for _ in range(3):
            output = builder.execute(observe_input, observe_output)
            assert "THEORETICAL ONLY" in output.execution_disclaimer

    def test_routing_is_exclusive(self, sell_input: QualifierInput,
                                  sell_output: QualifierOutput,
                                  buy_input: QualifierInput,
                                  buy_output: QualifierOutput,
                                  observe_input: QualifierInput,
                                  observe_output: QualifierOutput) -> None:
        """Only the correct slot is populated for each route."""
        builder = OrderBuilder()

        # OBSERVE
        obs = builder.execute(observe_input, observe_output)
        assert obs.observe_analysis is not None
        assert obs.sell_analysis is None
        assert obs.buy_order_suggestion is None

        # SELL
        sl = builder.execute(sell_input, sell_output)
        assert sl.observe_analysis is None
        assert sl.sell_analysis is not None
        assert sl.buy_order_suggestion is None

        # BUY
        buy = builder.execute(buy_input, buy_output)
        assert buy.observe_analysis is None
        assert buy.sell_analysis is None
        assert buy.buy_order_suggestion is not None

    def test_order_ids_unique(self, observe_input: QualifierInput,
                              observe_output: QualifierOutput,
                              sell_input: QualifierInput,
                              sell_output: QualifierOutput,
                              buy_input: QualifierInput,
                              buy_output: QualifierOutput) -> None:
        """Different routing paths produce different order_id prefixes."""
        builder = OrderBuilder()

        obs = builder.execute(observe_input, observe_output)
        assert obs.order_id.startswith("obs_")

        sl = builder.execute(sell_input, sell_output)
        assert sl.order_id.startswith("sl_")

        buy = builder.execute(buy_input, buy_output)
        assert buy.order_id.startswith("ord_")