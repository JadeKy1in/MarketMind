"""Tests for L3 interactive module — technical analysis review loop."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.pipeline.l3_interactive import run_l3_interactive
from marketmind.pipeline.layer3_technical import Layer3Result, Layer3BatchResult
from marketmind.pipeline.session_context import SessionContext
from marketmind.config.settings import MarketMindConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_config() -> MarketMindConfig:
    """Return a config with a dummy API key (no real API calls in these tests)."""
    return MarketMindConfig(deepseek_api_key="sk-test")


def _make_green_batch(ticker: str = "AAPL") -> Layer3BatchResult:
    """Return a batch with one green-light result."""
    return Layer3BatchResult(results=[
        Layer3Result(
            ticker=ticker, light="green", recommendation="enter",
            above_200wma=True, daily_structure_intact=True,
            near_key_resistance=False, resistance_distance_pct=5.0,
            support_zone_low=140.0, support_zone_high=145.0,
            resistance_zone_low=160.0, resistance_zone_high=165.0,
            entry_zone_low=142.0, entry_zone_high=148.0,
            stop_loss=138.0, target_price=162.0,
            max_hold_days=30, reward_risk_ratio=2.5,
        ),
    ])


def _make_red_batch(ticker: str = "AAPL") -> Layer3BatchResult:
    """Return a batch with one red-light result (no green lights)."""
    return Layer3BatchResult(results=[
        Layer3Result(
            ticker=ticker, light="red", recommendation="avoid",
            above_200wma=False, daily_structure_intact=False,
            near_key_resistance=True, resistance_distance_pct=0,
            support_zone_low=0, support_zone_high=0,
            resistance_zone_low=0, resistance_zone_high=0,
            entry_zone_low=0, entry_zone_high=0,
            stop_loss=0, target_price=0,
            max_hold_days=0, reward_risk_ratio=0,
        ),
    ])


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l3_proceed_confirmed():
    """User types '好' when green lights are available — should return True."""
    ctx = SessionContext(config=_make_config(), selected_tickers=["AAPL"])
    mock_batch = _make_green_batch("AAPL")

    inputs = iter(["好"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    with patch("marketmind.pipeline.l3_interactive.analyze_layer3",
               AsyncMock(return_value=mock_batch)):
        confirmed = await run_l3_interactive(ctx, handler)

    assert confirmed is True
    assert ctx.l3_result is mock_batch


@pytest.mark.asyncio
async def test_l3_observe_exits():
    """User types 'observe' — should return False (skip trading)."""
    ctx = SessionContext(config=_make_config(), selected_tickers=["AAPL"])
    mock_batch = _make_red_batch("AAPL")

    inputs = iter(["observe"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    with patch("marketmind.pipeline.l3_interactive.analyze_layer3",
               AsyncMock(return_value=mock_batch)):
        confirmed = await run_l3_interactive(ctx, handler)

    assert confirmed is False


@pytest.mark.asyncio
async def test_l3_question_gets_response():
    """User asks a question first, then confirms — chat_pro mocked for question handling."""
    ctx = SessionContext(config=_make_config(), selected_tickers=["AAPL"])
    mock_batch = _make_green_batch("AAPL")

    inputs = iter(["为什么没信号", "好"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    mock_chat_pro = AsyncMock(return_value={"content": "这是对您技术面问题的回复。"})

    with patch("marketmind.pipeline.l3_interactive.analyze_layer3",
               AsyncMock(return_value=mock_batch)):
        with patch("marketmind.pipeline.l3_interactive.chat_pro", mock_chat_pro):
            confirmed = await run_l3_interactive(ctx, handler)

    assert confirmed is True
    # chat_pro should have been called once for the user question
    mock_chat_pro.assert_called_once()
