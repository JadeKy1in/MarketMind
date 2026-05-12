"""Tests for position patrol."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from marketmind.pipeline.position_patrol import (
    PositionStatus, patrol_positions, _parse_patrol_response,
    _apply_protection_veto,
)
from marketmind.config.settings import MarketMindConfig


@pytest.fixture
def config():
    return MarketMindConfig(deepseek_api_key="test-key", position_protection_days=60)


def _sample_positions():
    return [
        {"ticker": "AAPL", "entry_price": 180, "current_price": 195, "entry_date": "2026-04-20"},
        {"ticker": "SPY", "entry_price": 500, "current_price": 510, "entry_date": "2026-05-09"},
    ]


def _sample_llm_response():
    return json.dumps([
        {"ticker": "AAPL", "status": "green", "logic_valid": True,
         "technical_breach": False, "time_expiry_reached": False,
         "opportunity_cost_signal": False, "cash_reframing_answer": "yes",
         "recommendation": "hold", "exit_conditions_met": [], "alternative_use": ""},
        {"ticker": "SPY", "status": "yellow", "logic_valid": True,
         "technical_breach": False, "time_expiry_reached": False,
         "opportunity_cost_signal": True, "cash_reframing_answer": "hesitate",
         "recommendation": "hold", "exit_conditions_met": ["opportunity_cost"],
         "alternative_use": "Reallocate to TLT"},
    ])


def test_parse_patrol_response_joins_input_data(config):
    """AF-3: Ground-truth fields come from input positions, not LLM output."""
    content = _sample_llm_response()
    results = _parse_patrol_response(content, _sample_positions(), config)
    assert len(results) == 2

    aapl = [r for r in results if r.ticker == "AAPL"][0]
    assert aapl.entry_price == 180.0
    assert aapl.current_price == 195.0
    assert aapl.pnl_pct == pytest.approx(8.33, rel=0.01)
    assert aapl.days_held > 0
    assert aapl.status == "green"
    assert aapl.recommendation == "hold"


def test_parse_patrol_response_marks_protection_active(config):
    """Positions held < 60 days should have protection_active=True."""
    recent_positions = [
        {"ticker": "NEW", "entry_price": 100, "current_price": 105, "entry_date": "2026-05-10"},
    ]
    content = json.dumps([{"ticker": "NEW", "status": "green", "recommendation": "hold"}])
    results = _parse_patrol_response(content, recent_positions, config)
    assert len(results) == 1
    assert results[0].protection_active is True


def test_parse_patrol_empty():
    assert _parse_patrol_response("[]", [], MarketMindConfig(deepseek_api_key="k")) == []
    assert _parse_patrol_response("invalid", [], MarketMindConfig(deepseek_api_key="k")) == []


def test_protection_veto_blocks_early_exit(config):
    """AF-3: Position with protection_active and only 1/2 exit conditions -> exit overridden."""
    ps = PositionStatus(
        ticker="TEST", entry_price=100, current_price=105, pnl_pct=5.0, days_held=15,
        protection_active=True, logic_valid=True, technical_breach=False,
        recommendation="exit",
    )
    results = _apply_protection_veto([ps], config.position_protection_days)
    assert results[0].recommendation_override == "hold"
    assert "60-day protection" in results[0].override_reason


def test_protection_veto_allows_exit_when_both_conditions_met(config):
    """With both logic falsified AND technical breach, exit is allowed even under protection."""
    ps = PositionStatus(
        ticker="TEST", entry_price=100, current_price=80, pnl_pct=-20.0, days_held=10,
        protection_active=True, logic_valid=False, technical_breach=True,
        recommendation="exit",
    )
    results = _apply_protection_veto([ps], config.position_protection_days)
    assert results[0].recommendation_override is None


def test_protection_veto_no_effect_when_not_active(config):
    """Positions past protection period are unaffected."""
    ps = PositionStatus(
        ticker="OLD", entry_price=100, current_price=120, pnl_pct=20.0, days_held=90,
        protection_active=False, logic_valid=True, technical_breach=False,
        recommendation="exit",
    )
    results = _apply_protection_veto([ps], config.position_protection_days)
    assert results[0].recommendation_override is None


@pytest.mark.asyncio
async def test_patrol_positions_empty():
    results, error = await patrol_positions([])
    assert results == []
    assert error is None


@pytest.mark.asyncio
async def test_patrol_positions_returns_results_with_input_join():
    mock_content = json.dumps([
        {"ticker": "SPY", "status": "yellow", "logic_valid": True,
         "technical_breach": False, "time_expiry_reached": False,
         "opportunity_cost_signal": True, "cash_reframing_answer": "hesitate",
         "recommendation": "reduce", "exit_conditions_met": ["opportunity_cost"],
         "alternative_use": "Reallocate to TLT for rate-cut play"},
    ])
    positions = [
        {"ticker": "SPY", "entry_price": 500, "current_price": 510, "entry_date": "2026-04-01"},
    ]
    with patch("marketmind.pipeline.position_patrol.chat_pro", AsyncMock(return_value={"content": mock_content})):
        results, error = await patrol_positions(positions)
        assert error is None
        assert len(results) == 1
        assert results[0].status == "yellow"
        assert results[0].opportunity_cost_signal
        # Ground-truth from input
        assert results[0].entry_price == 500.0
        assert results[0].current_price == 510.0


@pytest.mark.asyncio
async def test_patrol_positions_returns_error_on_failure():
    with patch("marketmind.pipeline.position_patrol.chat_pro", side_effect=RuntimeError("API down")):
        results, error = await patrol_positions([{"ticker": "SPY", "entry_price": 500}])
        assert results == []
        assert error is not None
        assert "API down" in error
