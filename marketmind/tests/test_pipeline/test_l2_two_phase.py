"""Tests for L2 two-phase interactive module — sector selection + strategy group drill-down.

Covers the Phase B two-phase flow: sector selection → drill-down → strategy group choice.
Tests both success paths and fallback/observe branches.
"""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.pipeline.l2_interactive import (
    _run_two_phase_l2,
    _display_strategy_groups,
    _select_strategy_group,
    _run_sector_drilldown,
    _confirm_single_phase,
)
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.session_context import SessionContext
from marketmind.config.settings import MarketMindConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_config() -> MarketMindConfig:
    """Return a config with a dummy API key (no real API calls in these tests)."""
    return MarketMindConfig(deepseek_api_key="sk-test")


def _make_l2_with_sectors() -> Layer2Result:
    """Return a Layer2Result with sector_directions populated for two-phase flow."""
    return Layer2Result(
        macro_quadrant="expansion",
        macro_direction="risk_on",
        sector_directions=[
            {
                "sector": "科技",
                "direction": "bullish",
                "momentum": "accelerating",
                "rationale": "AI技术突破推动行业增长",
            },
            {
                "sector": "消费",
                "direction": "neutral",
                "momentum": "stable",
                "rationale": "消费复苏缓慢",
            },
            {
                "sector": "能源",
                "direction": "bearish",
                "momentum": "decelerating",
                "rationale": "油价下行压力",
            },
        ],
        ticker_candidates=["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"],
        raw_analysis="test",
    )


def _make_drill_result() -> dict:
    """Return a valid sector drill-down JSON with tool_matrix and strategy_groups."""
    return {
        "sector": "科技",
        "direction": "bullish",
        "tool_matrix": {
            "direct_exposure": {
                "tickers": ["AAPL"],
                "weights": {"AAPL": 1.0},
                "description": "直接暴露科技龙头",
            },
            "equity_proxies": {
                "tickers": ["QQQ"],
                "weights": {"QQQ": 1.0},
                "description": "纳斯达克ETF代理",
            },
            "related_assets": {
                "tickers": ["SMH"],
                "weights": {"SMH": 1.0},
                "description": "半导体ETF关联资产",
            },
        },
        "strategy_groups": {
            "conservative": {
                "tickers": ["AAPL"],
                "weights": {"AAPL": 1.0},
                "thesis": "保守策略：选择市值最大、波动最低的标的",
            },
            "neutral": {
                "tickers": ["AAPL", "MSFT"],
                "weights": {"AAPL": 0.6, "MSFT": 0.4},
                "thesis": "中性策略：分散两个龙头以降低单点风险",
            },
            "aggressive": {
                "tickers": ["MSFT", "NVDA"],
                "weights": {"MSFT": 0.6, "NVDA": 0.4},
                "thesis": "激进策略：重仓高beta标的追求超额收益",
            },
        },
    }


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_phase_sector_selection():
    """Scripted input picks sector 1, mock drill-down returns valid JSON with
    strategy groups. Verify ctx.selected_tickers is populated and
    ctx.selected_strategy is set."""
    ctx = SessionContext(config=_make_config())
    l2_result = _make_l2_with_sectors()
    drill_result = _make_drill_result()

    # Inputs: "1" for sector 1 (科技), then "neutral" for strategy group
    inputs = iter(["1", "neutral"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    with patch("marketmind.pipeline.l2_interactive._run_sector_drilldown",
               AsyncMock(return_value=drill_result)):
        confirmed = await _run_two_phase_l2(ctx, l2_result, handler)

    assert confirmed is True
    assert ctx.selected_tickers == ["AAPL", "MSFT"]
    assert ctx.selected_strategy == "neutral"


@pytest.mark.asyncio
async def test_two_phase_all_sectors_fallback():
    """User types '全部' at sector selection -> falls back to single-phase.
    Verify old path works: ctx.selected_tickers populated from ticker_candidates."""
    ctx = SessionContext(config=_make_config())
    l2_result = _make_l2_with_sectors()

    # Inputs: "全部" for all sectors, then "好" to confirm in single-phase
    inputs = iter(["全部", "好"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    confirmed = await _run_two_phase_l2(ctx, l2_result, handler)

    assert confirmed is True
    assert ctx.selected_tickers == l2_result.ticker_candidates[:10]


@pytest.mark.asyncio
async def test_two_phase_drilldown_failure():
    """Mock drill-down returns None -> verify fallback to single-phase.
    Even when drill-down fails, the user can confirm and proceed."""
    ctx = SessionContext(config=_make_config())
    l2_result = _make_l2_with_sectors()

    # Inputs: "1" for sector, then "好" to confirm in single-phase fallback
    inputs = iter(["1", "好"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    with patch("marketmind.pipeline.l2_interactive._run_sector_drilldown",
               AsyncMock(return_value=None)):
        confirmed = await _run_two_phase_l2(ctx, l2_result, handler)

    assert confirmed is True
    assert ctx.selected_tickers == l2_result.ticker_candidates[:10]


@pytest.mark.asyncio
async def test_two_phase_observe_at_sector():
    """User types 'observe' at sector selection -> verify returns False."""
    ctx = SessionContext(config=_make_config())
    l2_result = _make_l2_with_sectors()

    inputs = iter(["observe"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    confirmed = await _run_two_phase_l2(ctx, l2_result, handler)

    assert confirmed is False


@pytest.mark.asyncio
async def test_two_phase_observe_at_strategy():
    """User types 'observe' at strategy group selection -> verify returns False.
    Sector selection succeeds, drill-down succeeds, but user observes at strategy."""
    ctx = SessionContext(config=_make_config())
    l2_result = _make_l2_with_sectors()
    drill_result = _make_drill_result()

    # Inputs: "1" for sector, then "observe" at strategy group selection
    inputs = iter(["1", "observe"])

    async def handler(prompt: str) -> str:
        return next(inputs)

    with patch("marketmind.pipeline.l2_interactive._run_sector_drilldown",
               AsyncMock(return_value=drill_result)):
        confirmed = await _run_two_phase_l2(ctx, l2_result, handler)

    assert confirmed is False
