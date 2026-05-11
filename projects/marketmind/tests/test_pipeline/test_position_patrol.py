"""Tests for position patrol."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from projects.marketmind.pipeline.position_patrol import (
    PositionStatus, patrol_positions, _parse_patrol_response,
)


def test_parse_patrol_response():
    content = json.dumps([{
        "ticker": "AAPL", "status": "green",
        "entry_price": 180, "current_price": 195, "pnl_pct": 8.3,
        "days_held": 15, "logic_valid": True, "technical_breach": False,
        "time_expiry_reached": False, "opportunity_cost_signal": False,
        "cash_reframing_answer": "yes", "recommendation": "hold",
        "exit_conditions_met": [], "alternative_use": ""
    }])
    results = _parse_patrol_response(content)
    assert len(results) == 1
    assert results[0].ticker == "AAPL"
    assert results[0].status == "green"
    assert results[0].pnl_pct == 8.3
    assert results[0].recommendation == "hold"


def test_parse_patrol_empty():
    assert _parse_patrol_response("[]") == []
    assert _parse_patrol_response("invalid") == []


@pytest.mark.asyncio
async def test_patrol_positions_empty():
    results = await patrol_positions([])
    assert results == []


@pytest.mark.asyncio
async def test_patrol_positions_returns_results():
    mock_content = json.dumps([{
        "ticker": "SPY", "status": "yellow",
        "entry_price": 500, "current_price": 510, "pnl_pct": 2.0,
        "days_held": 5, "logic_valid": True, "technical_breach": False,
        "time_expiry_reached": False, "opportunity_cost_signal": True,
        "cash_reframing_answer": "hesitate", "recommendation": "reduce",
        "exit_conditions_met": ["opportunity_cost"],
        "alternative_use": "Reallocate to TLT for rate-cut play"
    }])
    with patch("projects.marketmind.pipeline.position_patrol.chat_pro", AsyncMock(return_value={"content": mock_content})):
        results = await patrol_positions([
            {"ticker": "SPY", "entry_price": 500, "shares": 10}
        ])
        assert len(results) == 1
        assert results[0].status == "yellow"
        assert results[0].opportunity_cost_signal
