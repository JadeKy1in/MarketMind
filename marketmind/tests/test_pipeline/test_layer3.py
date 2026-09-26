"""Tests for Layer 3 technical review (code-computed, no LLM)."""
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.pipeline.layer3_technical import (
    Layer3BatchResult, Layer3Result, analyze_layer3, unavailable_result,
)
from marketmind.tests.test_pipeline.test_l3_indicators import make_history, uptrend


def _r(ticker: str, light: str) -> Layer3Result:
    r = unavailable_result(ticker)
    r.light = light
    r.data_available = True
    return r


def test_layer3_batch_result_green_lights_and_get():
    batch = Layer3BatchResult(results=[_r("SPY", "green"), _r("QQQ", "red"), _r("GLD", "yellow")])
    assert [r.ticker for r in batch.green_lights] == ["SPY"]
    assert [r.ticker for r in batch.red_lights] == ["QQQ"]
    assert batch.get("GLD").light == "yellow"
    assert batch.get("NOPE") is None


@pytest.mark.asyncio
async def test_analyze_layer3_uses_code_not_llm():
    histories = {"UP": make_history(uptrend(), ticker="UP"),
                 "DOWN": make_history(list(reversed(uptrend())), ticker="DOWN")}
    with patch("marketmind.pipeline.layer3_technical.get_price_histories",
               AsyncMock(return_value=histories)):
        batch = await analyze_layer3(["UP", "DOWN"], {})
    up, down = batch.get("UP"), batch.get("DOWN")
    assert up.light == "green" and up.data_available
    assert up.close and up.stop_loss < up.close < up.target_price
    assert "200WMA" in up.raw_analysis
    assert down.light != "green" and down.recommendation != "enter"


@pytest.mark.asyncio
async def test_analyze_layer3_marks_missing_data_instead_of_guessing():
    with patch("marketmind.pipeline.layer3_technical.get_price_histories",
               AsyncMock(return_value={"GHOST": None})):
        batch = await analyze_layer3(["GHOST"])
    r = batch.get("GHOST")
    assert r.data_available is False
    assert r.light == "red" and r.recommendation == "avoid"
    assert r.stop_loss == 0.0 and "unavailable" in r.raw_analysis


@pytest.mark.asyncio
async def test_analyze_layer3_empty_and_dedup():
    assert (await analyze_layer3([])).results == []
    mock = AsyncMock(return_value={"SPY": None})
    with patch("marketmind.pipeline.layer3_technical.get_price_histories", mock):
        batch = await analyze_layer3(["SPY", "SPY", ""])
    assert len(batch.results) == 1
    mock.assert_awaited_once_with(["SPY"])
