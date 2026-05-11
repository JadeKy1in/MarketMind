"""Tests for Layer 3 technical review."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from projects.marketmind.pipeline.layer3_technical import (
    Layer3Result, Layer3BatchResult, analyze_layer3,
    _parse_layer3_response, _format_market_data,
)


def test_layer3_batch_result_green_lights():
    results = [
        Layer3Result(ticker="AAPL", light="green", recommendation="enter",
                     above_200wma=True, daily_structure_intact=True,
                     near_key_resistance=False, resistance_distance_pct=5.0,
                     support_zone_low=100, support_zone_high=102,
                     resistance_zone_low=110, resistance_zone_high=112,
                     entry_zone_low=100, entry_zone_high=102,
                     stop_loss=98, target_price=111,
                     max_hold_days=30, reward_risk_ratio=2.5),
        Layer3Result(ticker="MSFT", light="yellow", recommendation="wait",
                     above_200wma=True, daily_structure_intact=False,
                     near_key_resistance=True, resistance_distance_pct=2.0,
                     support_zone_low=0, support_zone_high=0,
                     resistance_zone_low=0, resistance_zone_high=0,
                     entry_zone_low=0, entry_zone_high=0,
                     stop_loss=0, target_price=0,
                     max_hold_days=0, reward_risk_ratio=0),
        Layer3Result(ticker="TSLA", light="red", recommendation="avoid",
                     above_200wma=False, daily_structure_intact=False,
                     near_key_resistance=True, resistance_distance_pct=0,
                     support_zone_low=0, support_zone_high=0,
                     resistance_zone_low=0, resistance_zone_high=0,
                     entry_zone_low=0, entry_zone_high=0,
                     stop_loss=0, target_price=0,
                     max_hold_days=0, reward_risk_ratio=0),
    ]
    batch = Layer3BatchResult(results=results)
    assert len(batch.green_lights) == 1
    assert batch.green_lights[0].ticker == "AAPL"
    assert len(batch.red_lights) == 1


def test_parse_layer3_response_clean_json():
    content = json.dumps([{
        "ticker": "SPY", "light": "green",
        "above_200wma": True, "daily_structure_intact": True,
        "near_key_resistance": False, "resistance_distance_pct": 8.5,
        "support_zone_low": 520, "support_zone_high": 530,
        "resistance_zone_low": 570, "resistance_zone_high": 580,
        "entry_zone_low": 525, "entry_zone_high": 535,
        "stop_loss": 515, "target_price": 575,
        "max_hold_days": 30, "reward_risk_ratio": 2.5,
        "recommendation": "enter"
    }])
    results = _parse_layer3_response(content)
    assert len(results) == 1
    assert results[0].ticker == "SPY"
    assert results[0].light == "green"
    assert results[0].reward_risk_ratio == 2.5


def test_parse_layer3_response_single_object():
    content = json.dumps({"ticker": "AAPL", "light": "red", "recommendation": "avoid"})
    results = _parse_layer3_response(content)
    assert len(results) == 1
    assert results[0].light == "red"


def test_parse_layer3_response_invalid():
    assert _parse_layer3_response("invalid") == []


def test_format_market_data():
    data = {"VIX": 18.5, "SPY_200wma": 480}
    formatted = _format_market_data(data)
    assert "VIX" in formatted
    assert "18.5" in formatted


def test_format_market_data_none():
    assert _format_market_data(None) == "No market data available."


@pytest.mark.asyncio
async def test_analyze_layer3_returns_results():
    mock_content = json.dumps([{
        "ticker": "SPY", "light": "green",
        "above_200wma": True, "daily_structure_intact": True,
        "near_key_resistance": False, "resistance_distance_pct": 5.0,
        "support_zone_low": 500, "support_zone_high": 510,
        "resistance_zone_low": 550, "resistance_zone_high": 560,
        "entry_zone_low": 505, "entry_zone_high": 515,
        "stop_loss": 495, "target_price": 555,
        "max_hold_days": 30, "reward_risk_ratio": 3.0,
        "recommendation": "enter"
    }])
    mock_result = {"content": mock_content, "usage": {}}
    with patch("projects.marketmind.pipeline.layer3_technical.chat_pro", AsyncMock(return_value=mock_result)):
        result = await analyze_layer3(["SPY", "AAPL"], {"VIX": 18})
        assert isinstance(result, Layer3BatchResult)
        assert len(result.results) >= 1


@pytest.mark.asyncio
async def test_analyze_layer3_empty_tickers():
    result = await analyze_layer3([])
    assert len(result.results) == 0
