"""
test_layer3.py - Comprehensive pytest suite for Layer 3 modules.

Covers:
  - src/resonance_aggregator.py: normalization, weighted score, soft veto,
    state machine, full compute_resonance
  - src/capital_manager.py: position sizing, portfolio analysis,
    exit suggestions, edge cases
  - src/pro_model_deep_dive.py: prompt building, response formatting,
    schema spec integrity
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.capital_manager import (
    MAX_SINGLE_POSITION_RATIO,
    NUKE_EXIT_THRESHOLD,
    PARTIAL_EXIT_FRACTION,
    PARTIAL_EXIT_THRESHOLD,
    RESERVE_RATIO,
    SIGNAL_MAX_PORTION,
    compute_full_portfolio,
    compute_position_sizing,
)
from src.pro_model_deep_dive import (
    OUTPUT_SCHEMA_SPEC,
    build_pro_model_prompt,
    format_pro_model_response,
)
from src.resonance_aggregator import (
    RESONANCE_THRESHOLD,
    SOFT_VETO_DISCOUNT,
    SOFT_VETO_THRESHOLD,
    normalize_sentiment,
    compute_resonance,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def sample_engine_outputs() -> dict[str, dict[str, Any]]:
    """Baseline BUY scenario: all four engines score >= 70."""
    return {
        "fundamental": {"score": 75, "reasoning": "Strong earnings growth."},
        "technical": {"score": 80, "reasoning": "Bullish MACD crossover."},
        "event_driven": {"score": 72, "reasoning": "Positive earnings catalyst."},
        "sentiment_engine_output": {
            "sentiment": "Positive",
            "magnitude": 70,
            "reasoning": "Strong bullish sentiment.",
        },
    }


# ======================================================================
# Tests: Resonance Aggregator Core (Task 3.1)
# ======================================================================


class TestNormalizeSentiment:
    """Sentiment normalization mapping accuracy."""

    def test_positive_max(self):
        result = normalize_sentiment(
            {"sentiment": "Positive", "magnitude": 100}
        )
        assert result == 100

    def test_positive_min(self):
        result = normalize_sentiment(
            {"sentiment": "Positive", "magnitude": 0}
        )
        assert result == 50

    def test_positive_mid(self):
        result = normalize_sentiment(
            {"sentiment": "Positive", "magnitude": 50}
        )
        # 50 + 50 * 0.5 = 75
        assert result == 75

    def test_neutral_min(self):
        result = normalize_sentiment(
            {"sentiment": "Neutral", "magnitude": 0}
        )
        assert result == 40

    def test_neutral_max(self):
        result = normalize_sentiment(
            {"sentiment": "Neutral", "magnitude": 100}
        )
        # 40 + 100 * 0.2 = 60
        assert result == 60

    def test_negative_min(self):
        result = normalize_sentiment(
            {"sentiment": "Negative", "magnitude": 0}
        )
        assert result == 50

    def test_negative_max(self):
        result = normalize_sentiment(
            {"sentiment": "Negative", "magnitude": 100}
        )
        # 50 - 100 * 0.5 = 0
        assert result == 0

    def test_negative_mid(self):
        result = normalize_sentiment(
            {"sentiment": "Negative", "magnitude": 60}
        )
        # 50 - 60 * 0.5 = 20
        assert result == 20

    def test_clamp_above_100(self):
        result = normalize_sentiment(
            {"sentiment": "Positive", "magnitude": 200}
        )
        assert result == 100

    def test_clamp_below_0(self):
        result = normalize_sentiment(
            {"sentiment": "Negative", "magnitude": 200}
        )
        assert result == 0

    def test_default_sentiment(self):
        result = normalize_sentiment({})
        assert isinstance(result, int)
        assert 40 <= result <= 60  # Neutral default


class TestWeightedScore:
    """Weighted score computation accuracy."""

    def test_all_equal(self):
        """All 50 -> weighted = 50."""
        scores = {
            "fundamental": 50,
            "technical": 50,
            "event_driven": 50,
            "sentiment": 50,
        }
        result = compute_resonance(
            fundamental={"score": 50, "reasoning": "N"},
            technical={"score": 50, "reasoning": "N"},
            event_driven={"score": 50, "reasoning": "N"},
            sentiment_engine_output=50,
        )
        assert result["weighted_score"] == 50.0

    def test_all_max(self):
        """All 100 -> weighted = 100."""
        result = compute_resonance(
            fundamental={"score": 100, "reasoning": "N"},
            technical={"score": 100, "reasoning": "N"},
            event_driven={"score": 100, "reasoning": "N"},
            sentiment_engine_output=100,
        )
        assert result["weighted_score"] == 100.0

    def test_uneven_weights(self):
        """Hand-calc: F=80 T=60 E=90 S=70."""
        # 80*0.20 + 60*0.25 + 90*0.30 + 70*0.25
        # = 16 + 15 + 27 + 17.5 = 75.5
        result = compute_resonance(
            fundamental={"score": 80, "reasoning": "N"},
            technical={"score": 60, "reasoning": "N"},
            event_driven={"score": 90, "reasoning": "N"},
            sentiment_engine_output=70,
        )
        assert result["weighted_score"] == pytest.approx(75.5, abs=0.1)

    def test_event_driven_dominance(self):
        """Event-driven has highest weight (0.30), but F=0 triggers soft veto."""
        # F=0 (< 30) triggers soft veto.
        # Raw weighted = 100*0.30 = 30.0
        # After 15% discount = 30.0 * 0.85 = 25.5
        result = compute_resonance(
            fundamental={"score": 0, "reasoning": "N"},
            technical={"score": 0, "reasoning": "N"},
            event_driven={"score": 100, "reasoning": "N"},
            sentiment_engine_output=0,
        )
        assert result["weighted_score"] == 25.5


class TestSoftVeto:
    """Soft veto logic correctness."""

    def test_no_veto_all_above_30(self):
        """All dimensions >= 30 -> no veto."""
        result = compute_resonance(
            fundamental={"score": 50, "reasoning": "N"},
            technical={"score": 60, "reasoning": "N"},
            event_driven={"score": 70, "reasoning": "N"},
            sentiment_engine_output=80,
        )
        assert result["soft_veto_triggered"] is False
        assert result["override_available"] is False

    def test_veto_single_dimension_low(self):
        """Fundamental score 20 < 30 -> veto triggered."""
        result = compute_resonance(
            fundamental={"score": 20, "reasoning": "Weak earnings."},
            technical={"score": 80, "reasoning": "N"},
            event_driven={"score": 80, "reasoning": "N"},
            sentiment_engine_output=80,
        )
        assert result["soft_veto_triggered"] is True
        assert result["override_available"] is True

    def test_veto_discount_applied(self):
        """With fundamental=20, technical=event=sentiment=80:
        raw weighted = 20*0.20 + 80*0.25 + 80*0.30 + 80*0.25
                     = 4 + 20 + 24 + 20 = 68
        after 15% discount = 68 * 0.85 = 57.8
        """
        result = compute_resonance(
            fundamental={"score": 20, "reasoning": "N"},
            technical={"score": 80, "reasoning": "N"},
            event_driven={"score": 80, "reasoning": "N"},
            sentiment_engine_output=80,
        )
        expected_weighted = 68.0 * (1.0 - SOFT_VETO_DISCOUNT)
        assert result["weighted_score"] == pytest.approx(expected_weighted, abs=0.1)
        assert result["soft_veto_triggered"] is True

    def test_veto_multiple_dimensions(self):
        """Two dimensions below 30."""
        result = compute_resonance(
            fundamental={"score": 20, "reasoning": "N"},
            technical={"score": 25, "reasoning": "N"},
            event_driven={"score": 80, "reasoning": "N"},
            sentiment_engine_output=80,
        )
        assert result["soft_veto_triggered"] is True

    def test_veto_dimension_details(self):
        """Vetoed dimensions should appear in reasoning."""
        result = compute_resonance(
            fundamental={"score": 15, "reasoning": "N"},
            technical={"score": 85, "reasoning": "N"},
            event_driven={"score": 85, "reasoning": "N"},
            sentiment_engine_output=85,
        )
        reason = result["reasoning"]
        assert "Soft veto triggered" in reason
        assert "fundamental" in reason


class TestSignalStateMachine:
    """Signal determination state machine correctness."""

    def test_strong_buy(self):
        """>= 85, no veto, resonance met."""
        result = compute_resonance(
            fundamental={"score": 90, "reasoning": "N"},
            technical={"score": 88, "reasoning": "N"},
            event_driven={"score": 85, "reasoning": "N"},
            sentiment_engine_output={"sentiment": "Positive", "magnitude": 90},
        )
        assert result["signal"] == "STRONG_BUY"

    def test_buy(self):
        """>= 70, resonance met."""
        result = compute_resonance(
            fundamental={"score": 75, "reasoning": "N"},
            technical={"score": 72, "reasoning": "N"},
            event_driven={"score": 70, "reasoning": "N"},
            sentiment_engine_output={"sentiment": "Positive", "magnitude": 60},
        )
        assert result["signal"] == "BUY"

    def test_sell_low_weighted(self):
        """weighted <= 30."""
        result = compute_resonance(
            fundamental={"score": 10, "reasoning": "N"},
            technical={"score": 20, "reasoning": "N"},
            event_driven={"score": 15, "reasoning": "N"},
            sentiment_engine_output={"sentiment": "Negative", "magnitude": 90},
        )
        assert result["signal"] == "SELL"

    def test_sell_two_below_threshold(self):
        """>= 2 dimensions <= 30."""
        result = compute_resonance(
            fundamental={"score": 20, "reasoning": "N"},
            technical={"score": 25, "reasoning": "N"},
            event_driven={"score": 70, "reasoning": "N"},
            sentiment_engine_output=75,
        )
        assert result["signal"] == "SELL"

    def test_wait_veto(self):
        """Soft veto + resonance met -> WAIT."""
        result = compute_resonance(
            fundamental={"score": 20, "reasoning": "N"},
            technical={"score": 80, "reasoning": "N"},
            event_driven={"score": 75, "reasoning": "N"},
            sentiment_engine_output=70,
        )
        assert result["signal"] == "WAIT"

    def test_wait_no_resonance(self):
        """Resonance condition NOT met."""
        result = compute_resonance(
            fundamental={"score": 60, "reasoning": "N"},
            technical={"score": 65, "reasoning": "N"},
            event_driven={"score": 55, "reasoning": "N"},
            sentiment_engine_output=50,
        )
        assert result["signal"] == "WAIT"

    def test_hold(self):
        """Resonance met (3/4 >= 70) but weighted < 70, no veto -> HOLD.
        F=75*0.20 + T=72*0.25 + E=70*0.30 + S=50*0.25 = 15+18+21+12.5 = 66.5
        """
        result = compute_resonance(
            fundamental={"score": 75, "reasoning": "N"},
            technical={"score": 72, "reasoning": "N"},
            event_driven={"score": 70, "reasoning": "N"},
            sentiment_engine_output=50,
        )
        assert result["signal"] == "HOLD"


class TestComputeResonanceOutputStructure:
    """Full compute_resonance output contract verification."""

    def test_required_keys(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        required_keys = {
            "signal", "weighted_score", "dimension_scores",
            "dimension_details", "soft_veto_triggered",
            "override_available", "resonance_condition_met", "reasoning",
        }
        assert required_keys.issubset(result.keys())

    def test_signal_in_valid_set(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        assert result["signal"] in ("STRONG_BUY", "BUY", "SELL", "HOLD", "WAIT")

    def test_weighted_score_range(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        assert 0 <= result["weighted_score"] <= 100

    def test_dimension_scores_four_keys(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        assert set(result["dimension_scores"].keys()) == {
            "fundamental", "technical", "event_driven", "sentiment",
        }

    def test_dimension_details_has_reasoning(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        for dim in ("fundamental", "technical", "event_driven", "sentiment"):
            detail = result["dimension_details"][dim]
            assert "score" in detail
            assert "reasoning" in detail
            assert isinstance(detail["score"], int)

    def test_resonance_met_with_baseline(self, sample_engine_outputs):
        result = compute_resonance(**sample_engine_outputs)
        # F=75, T=80, E=72, S=85 -> F >= 70, T >= 70, E >= 70, S >= 70 => met
        assert result["resonance_condition_met"] is True

    def test_resonance_not_met(self):
        result = compute_resonance(
            fundamental={"score": 60, "reasoning": "N"},
            technical={"score": 60, "reasoning": "N"},
            event_driven={"score": 60, "reasoning": "N"},
            sentiment_engine_output=50,
        )
        # Only 0 dimensions >= 70
        assert result["resonance_condition_met"] is False

    def test_dimension_details_sentiment_reasoning_from_dict(self):
        result = compute_resonance(
            fundamental={"score": 80, "reasoning": "F reason"},
            technical={"score": 80, "reasoning": "T reason"},
            event_driven={"score": 80, "reasoning": "E reason"},
            sentiment_engine_output={
                "sentiment": "Positive",
                "magnitude": 50,
                "reasoning": "S reason",
            },
        )
        assert result["dimension_details"]["sentiment"]["reasoning"] == "S reason"

    def test_dimension_details_sentiment_reasoning_pre_normalized(self):
        result = compute_resonance(
            fundamental={"score": 80, "reasoning": "N"},
            technical={"score": 80, "reasoning": "N"},
            event_driven={"score": 80, "reasoning": "N"},
            sentiment_engine_output=75,
        )
        assert "Pre-normalized" in result["dimension_details"]["sentiment"]["reasoning"]


# ======================================================================
# Tests: Capital Manager (Task 3.2)
# ======================================================================


class FakePosition:
    """Minimal Position-compatible class for testing."""
    def __init__(self, ticker: str, shares: int, avg_cost: float,
                 current_price: float):
        self.ticker = ticker
        self.shares = shares
        self.avg_cost = avg_cost
        self.current_price = current_price


class FakeAccount:
    """Minimal AccountState-compatible class for testing."""
    def __init__(self, cash: float, buying_power: float,
                 positions: list[FakePosition]):
        self.cash = cash
        self.buying_power = buying_power
        self.positions = positions


class TestComputePositionSizing:
    """Position sizing logic correctness."""

    @pytest.fixture
    def sample_account(self):
        return FakeAccount(
            cash=10000.0,
            buying_power=8000.0,
            positions=[
                FakePosition("AAPL", 10, 150.0, 160.0),
            ],
        )

    def test_buy_sizing(self, sample_account):
        """BUY signal should compute max_shares."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="BUY",
            account=sample_account,
        )
        assert result["action"] == "BUY"
        assert result["max_shares"] > 0
        assert result["max_notional"] > 0
        assert result["cash_reserve_kept"] > 0

    def test_buy_notional_formula(self):
        """BUY notional = min(25% cash, 25% buying_power, remaining capacity)."""
        account = FakeAccount(
            cash=100000.0,
            buying_power=50000.0,
            positions=[FakePosition("AAPL", 100, 150.0, 180.0)],
        )
        result = compute_position_sizing(
            ticker="AAPL",
            signal="STRONG_BUY",
            account=account,
            current_price=180.0,
        )
        # Cash reserve kept = 10%
        deployable_cash = 100000.0 * (1.0 - RESERVE_RATIO)
        # 25% of deployable cash
        expected_cash_portion = deployable_cash * SIGNAL_MAX_PORTION
        # 25% of buying_power
        expected_bp_portion = 50000.0 * SIGNAL_MAX_PORTION * (1.0 - RESERVE_RATIO)
        # Remaining capacity (portfolio = 100000 + 100*180)
        portfolio_value = 100000.0 + 18000.0
        max_position = portfolio_value * MAX_SINGLE_POSITION_RATIO
        existing = 100 * 180.0
        remaining_capacity = max(0.0, max_position - existing)
        expected = min(expected_cash_portion, expected_bp_portion,
                       remaining_capacity)
        assert result["max_notional"] == pytest.approx(
            int(expected // 180.0) * 180.0, abs=1.0
        )
        assert result["max_shares"] == int(expected // 180.0)

    def test_sell_signal(self, sample_account):
        """SELL signal should produce AVOID with exit suggestion."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="SELL",
            account=sample_account,
        )
        assert result["action"] == "SELL"
        assert result["max_shares"] == 0
        assert result["exit_suggestion"] is not None
        assert result["exit_suggestion"]["type"] == "FULL_EXIT"

    def test_wait_signal(self, sample_account):
        """WAIT signal should produce AVOID."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="WAIT",
            account=sample_account,
        )
        assert result["action"] == "AVOID"
        assert result["max_shares"] == 0

    def test_hold_signal(self, sample_account):
        """HOLD signal should produce HOLD."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="HOLD",
            account=sample_account,
        )
        assert result["action"] == "HOLD"

    def test_strong_buy_add_to_position(self, sample_account):
        """STRONG_BUY with existing position should suggest ADD_TO_POSITION."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="STRONG_BUY",
            account=sample_account,
        )
        assert result["action"] == "BUY"
        assert result["position_adjustment"] is not None
        assert result["position_adjustment"]["type"] == "ADD_TO_POSITION"

    def test_sell_full_liquidate(self, sample_account):
        """SELL signal should suggest FULL_LIQUIDATE on existing position."""
        result = compute_position_sizing(
            ticker="AAPL",
            signal="SELL",
            account=sample_account,
        )
        assert result["position_adjustment"] is not None
        assert result["position_adjustment"]["type"] == "FULL_LIQUIDATE"

    def test_no_price_raises(self):
        """Missing current_price and no existing position raises ValueError."""
        account = FakeAccount(cash=1000.0, buying_power=1000.0, positions=[])
        with pytest.raises(ValueError):
            compute_position_sizing(
                ticker="UNKNOWN",
                signal="BUY",
                account=account,
            )

    def test_avoid_when_notional_below_price(self):
        """BUY when max_notional < current_price -> AVOID."""
        account = FakeAccount(
            cash=100.0,
            buying_power=50.0,
            positions=[],
        )
        result = compute_position_sizing(
            ticker="AAPL",
            signal="BUY",
            account=account,
            current_price=500.0,
        )
        assert result["action"] == "AVOID"
        assert result["max_shares"] == 0

    def test_buy_no_existing_position(self):
        """BUY with no existing position -> no position_adjustment."""
        account = FakeAccount(
            cash=100000.0,
            buying_power=50000.0,
            positions=[],
        )
        result = compute_position_sizing(
            ticker="AAPL",
            signal="BUY",
            account=account,
            current_price=180.0,
        )
        assert result["action"] == "BUY"
        # No exit suggestion since no existing position
        assert result["exit_suggestion"] is None

    def test_partial_exit(self):
        """Unrealized PnL > 15% of portfolio -> PARTIAL_EXIT."""
        # Portfolio: cash=5000, position value=100*180=18000, total 23000
        # PnL = (180 - 100) * 100 = 8000
        # PnL ratio = 8000/23000 = 34.8% > 15%
        account = FakeAccount(
            cash=5000.0,
            buying_power=5000.0,
            positions=[FakePosition("AAPL", 100, 100.0, 180.0)],
        )
        result = compute_position_sizing(
            ticker="AAPL",
            signal="BUY",
            account=account,
            current_price=180.0,
        )
        assert result["exit_suggestion"] is not None
        assert result["exit_suggestion"]["type"] == "PARTIAL_EXIT"
        expected_shares = int(100 * PARTIAL_EXIT_FRACTION)
        assert result["exit_suggestion"]["shares_to_sell"] == expected_shares

    def test_nuke_exit(self):
        """Unrealized loss > 25% of portfolio -> NUKE_EXIT."""
        # Portfolio: cash=50000, position value=100*80=8000, total 58000
        # Loss = (80 - 150) * 100 = -7000
        # Loss ratio = -7000/58000 = -12.1% (not enough)
        # Let's make it bigger: position=200 shares, cost=200, price=80
        # Portfolio: cash=50000, position=200*80=16000, total=66000
        # Loss = (80 - 200) * 200 = -24000
        # Loss ratio = -24000/66000 = -36.4% < -25%
        account = FakeAccount(
            cash=50000.0,
            buying_power=50000.0,
            positions=[FakePosition("AAPL", 200, 200.0, 80.0)],
        )
        result = compute_position_sizing(
            ticker="AAPL",
            signal="BUY",
            account=account,
            current_price=80.0,
        )
        assert result["exit_suggestion"] is not None
        assert result["exit_suggestion"]["type"] == "NUKE_EXIT"
        expected_shares = int(200 * 0.75)
        assert result["exit_suggestion"]["shares_to_sell"] == expected_shares

    def test_output_structure(self, sample_account):
        """Ensure all required keys in output."""
        result = compute_position_sizing(
            ticker="AAPL", signal="BUY", account=sample_account,
        )
        required_keys = {
            "ticker", "action", "max_shares", "max_notional",
            "cash_reserve_kept", "reasoning", "position_adjustment",
            "exit_suggestion",
        }
        assert required_keys.issubset(result.keys())


class TestComputeFullPortfolio:
    """Full portfolio analysis logic."""

    @pytest.fixture
    def sample_account(self):
        return FakeAccount(
            cash=50000.0,
            buying_power=40000.0,
            positions=[
                FakePosition("AAPL", 50, 155.0, 170.0),
                FakePosition("GOOGL", 20, 140.0, 150.0),
            ],
        )

    @pytest.fixture
    def buy_resonance(self):
        return {
            "signal": "BUY",
            "weighted_score": 75.0,
        }

    def test_full_portfolio_structure(self, sample_account, buy_resonance):
        result = compute_full_portfolio(sample_account, buy_resonance)
        assert "position_actions" in result
        assert "cash_summary" in result
        assert "overall_strategy" in result
        assert len(result["position_actions"]) == 2

    def test_cash_summary(self, sample_account, buy_resonance):
        result = compute_full_portfolio(sample_account, buy_resonance)
        cash = result["cash_summary"]
        assert cash["total_cash"] == 50000.0
        assert cash["reserved_cash"] == pytest.approx(50000.0 * RESERVE_RATIO)
        assert cash["deployable_cash"] == pytest.approx(
            50000.0 * (1.0 - RESERVE_RATIO)
        )

    def test_bullish_cash_strategy(self, sample_account, buy_resonance):
        result = compute_full_portfolio(sample_account, buy_resonance)
        assert "Bullish" in result["overall_strategy"]
        assert "BUY" in result["overall_strategy"]

    def test_sell_cash_strategy(self, sample_account):
        sell_resonance = {"signal": "SELL"}
        result = compute_full_portfolio(sample_account, sell_resonance)
        assert "Bearish" in result["overall_strategy"]

    def test_neutral_cash_strategy(self, sample_account):
        neutral_resonance = {"signal": "HOLD"}
        result = compute_full_portfolio(sample_account, neutral_resonance)
        assert "Neutral" in result["overall_strategy"]


# ======================================================================
# Tests: Pro Model Deep Dive (Task 3.3)
# ======================================================================


class TestBuildProModelPrompt:
    """Prompt building correctness."""

    @pytest.fixture
    def sample_resonance(self):
        return {
            "signal": "BUY",
            "weighted_score": 75.5,
            "dimension_scores": {
                "fundamental": 80,
                "technical": 70,
                "event_driven": 75,
                "sentiment": 78,
            },
            "dimension_details": {
                "fundamental": {"score": 80, "reasoning": "F reason"},
                "technical": {"score": 70, "reasoning": "T reason"},
                "event_driven": {"score": 75, "reasoning": "E reason"},
                "sentiment": {"score": 78, "reasoning": "S reason"},
            },
            "soft_veto_triggered": False,
            "override_available": False,
            "resonance_condition_met": True,
            "reasoning": "Test reasoning",
        }

    def test_returns_system_and_user(self, sample_resonance):
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            ticker="AAPL",
        )
        assert "system_prompt" in result
        assert "user_prompt" in result
        assert isinstance(result["system_prompt"], str)
        assert isinstance(result["user_prompt"], str)

    def test_system_prompt_contains_override_protocol(self, sample_resonance):
        """System prompt should mention override availability."""
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            ticker="AAPL",
        )
        assert "Override is NOT available" in result["system_prompt"]

    def test_system_prompt_override_available(self):
        """When override available, system prompt should say so."""
        resonance_with_veto = {
            "signal": "WAIT",
            "weighted_score": 50.0,
            "dimension_scores": {
                "fundamental": 20,
                "technical": 80,
                "event_driven": 75,
                "sentiment": 70,
            },
            "dimension_details": {
                "fundamental": {"score": 20, "reasoning": "Low"},
                "technical": {"score": 80, "reasoning": "OK"},
                "event_driven": {"score": 75, "reasoning": "OK"},
                "sentiment": {"score": 70, "reasoning": "OK"},
            },
            "soft_veto_triggered": True,
            "override_available": True,
            "resonance_condition_met": True,
            "reasoning": "Veto test",
        }
        result = build_pro_model_prompt(
            resonance_result=resonance_with_veto,
            ticker="AAPL",
        )
        assert "Override IS available" in result["system_prompt"]

    def test_system_prompt_contains_json_schema(self, sample_resonance):
        """System prompt should include the JSON schema spec."""
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            ticker="AAPL",
        )
        # Schema spec should be stringified in the prompt
        assert "executive_summary" in result["system_prompt"]
        assert "trading_decision" in result["system_prompt"]
        assert "deep_research" in result["system_prompt"]

    def test_user_prompt_contains_dimensions(self, sample_resonance):
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            ticker="AAPL",
        )
        assert "Four-Dimensional Resonance Analysis" in result["user_prompt"]
        assert "fundamental" in result["user_prompt"]
        assert "technical" in result["user_prompt"]

    def test_user_prompt_contains_account_state(self, sample_resonance):
        account_state = {
            "cash": 50000.0,
            "buying_power": 40000.0,
            "positions": [
                {"ticker": "AAPL", "shares": 50,
                 "avg_cost": 155.0, "current_price": 170.0},
            ],
        }
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            ticker="AAPL",
            account_state=account_state,
        )
        assert "50000.00" in result["user_prompt"]
        assert "AAPL" in result["user_prompt"]

    def test_user_prompt_contains_capital_summary(self, sample_resonance):
        capital_result = {
            "position_actions": [],
            "cash_summary": {
                "total_cash": 50000.0,
                "reserved_cash": 5000.0,
                "deployable_cash": 45000.0,
            },
            "overall_strategy": "Bullish signal (BUY): deploy up to $11250.00",
        }
        result = build_pro_model_prompt(
            resonance_result=sample_resonance,
            capital_result=capital_result,
            ticker="AAPL",
        )
        assert "Capital Management Analysis" in result["user_prompt"]
        assert "Bullish" in result["user_prompt"]


class TestFormatProModelResponse:
    """Response formatting and validation."""

    def test_clean_json(self):
        """Valid JSON without fences."""
        raw = '{"signal": "BUY"}'
        result = format_pro_model_response(raw)
        assert result == {"signal": "BUY"}

    def test_code_fences(self):
        """JSON wrapped in markdown code fences."""
        raw = '```json\n{"signal": "BUY"}\n```'
        result = format_pro_model_response(raw)
        assert result == {"signal": "BUY"}

    def test_code_fences_no_lang(self):
        """Code fences without language specifier."""
        raw = '```\n{"signal": "BUY"}\n```'
        result = format_pro_model_response(raw)
        assert result == {"signal": "BUY"}

    def test_invalid_json(self):
        """Invalid JSON returns error dict."""
        raw = "this is not json"
        result = format_pro_model_response(raw)
        assert "error" in result
        assert "raw" in result


class TestOutputSchemaSpec:
    """Schema specification integrity."""

    def test_has_all_required_sections(self):
        """Top-level required fields."""
        required = [
            "executive_summary", "trading_decision", "position_management",
            "deep_research", "risk_assessment", "action_plan",
        ]
        for field in required:
            assert field in OUTPUT_SCHEMA_SPEC["required"]

    def test_deep_research_has_all_subfields(self):
        """Deep research subfield requirements."""
        subfields = OUTPUT_SCHEMA_SPEC["properties"]["deep_research"]["required"]
        expected = [
            "macro_analysis", "fundamental_deep_dive", "technical_context",
            "sentiment_landscape", "event_risk_calendar", "scenario_analysis",
            "final_reasoning",
        ]
        for field in expected:
            assert field in subfields

    def test_executive_summary_enums(self):
        """Executive summary signal enum values."""
        signal_enum = (
            OUTPUT_SCHEMA_SPEC["properties"]["executive_summary"]
            ["properties"]["signal"]["enum"]
        )
        assert "STRONG_BUY" in signal_enum
        assert "SELL" in signal_enum
        assert "HOLD" in signal_enum
        assert "WAIT" in signal_enum

    def test_trading_decision_has_action_enum(self):
        """Trading decision action enum values."""
        action_enum = (
            OUTPUT_SCHEMA_SPEC["properties"]["trading_decision"]
            ["properties"]["action"]["enum"]
        )
        assert "BUY" in action_enum
        assert "SELL" in action_enum
        assert "HOLD" in action_enum
        assert "AVOID" in action_enum

    def test_risk_assessment_rating_enum(self):
        """Risk assessment overall_risk_rating enum."""
        rating_enum = (
            OUTPUT_SCHEMA_SPEC["properties"]["risk_assessment"]
            ["properties"]["overall_risk_rating"]["enum"]
        )
        assert "LOW" in rating_enum
        assert "MEDIUM" in rating_enum
        assert "HIGH" in rating_enum
        assert "EXTREME" in rating_enum
