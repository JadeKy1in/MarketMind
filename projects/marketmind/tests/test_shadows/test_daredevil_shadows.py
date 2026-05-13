"""Tests for Daredevil shadows."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.shadows.daredevil_shadows import (
    DaredevilShadow, create_daredevil_shadows, DAREDEVIL_SHADOW_CONFIGS
)
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def scalper_config():
    return ShadowConfig(
        shadow_id="daredevil:intraday:test_scalper",
        shadow_type="daredevil",
        display_name="Test Scalper",
        methodology_prompt="You must pick a direction daily.",
        virtual_capital=25000.0,
        temperature=0.5,
    )


@pytest.fixture
def scalper(scalper_config, temp_shadow_db, settings):
    return DaredevilShadow(scalper_config, temp_shadow_db, settings)


class TestDaredevilShadow:
    @pytest.mark.asyncio
    async def test_daredevil_produces_analysis(self, scalper):
        news = [{"headline": "Market volatility spikes"}]
        mock_result = {
            "content": (
                "VOTE_START\n"
                "ticker: SPY\ndirection: long\nconfidence: 0.60\n"
                "thesis: Test thesis\nrisk_note: Test risk\n"
                "VOTE_END"
            ),
            "latency_ms": 400,
        }
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value=mock_result):
            output = await scalper.run_daily_analysis(news, {})
        assert output.shadow_id == "daredevil:intraday:test_scalper"
        assert output.date is not None

    @pytest.mark.asyncio
    async def test_daredevil_higher_risk_tolerance(self, scalper):
        assert scalper.config.max_drawdown_limit == 0.35
        assert scalper.config.min_trades_for_ranking == 50


def test_all_8_daredevil_configs_unique():
    ids = [c.shadow_id for c in DAREDEVIL_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 8  # Phase 6: 7+1


def test_all_7_env_types_present():
    env_types = {c.shadow_id.split(":")[2] for c in DAREDEVIL_SHADOW_CONFIGS}
    assert env_types == {
        "range_bound", "panic", "leveraged", "contrarian",
        "momentum", "sector", "low_liq", "crash"
    }


def test_factory_creates_8_daredevils(temp_shadow_db):
    settings = ShadowSettings()
    shadows = create_daredevil_shadows(temp_shadow_db, settings)
    assert len(shadows) == 8  # Phase 6: 7+1
    assert all(isinstance(s, DaredevilShadow) for s in shadows)


# ── C.7 LLM integration tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daredevil_analyze_with_mock_llm(temp_shadow_db):
    """DaredevilShadow._analyze() 调用mock LLM并解析结果"""
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="daredevil:event:test_hound", shadow_type="daredevil",
        display_name="Test Hound", methodology_prompt="You are a news hound.",
        virtual_capital=25000.0, temperature=0.45,
    )
    agent = DaredevilShadow(config, temp_shadow_db, ShadowSettings())

    mock_result = {
        "content": (
            "VOTE_START\n"
            "ticker: SPY\ndirection: short\nconfidence: 0.55\n"
            "thesis: Event-driven selloff\n"
            "risk_note: Could bounce on positive data\n"
            "VOTE_END"
        ),
        "latency_ms": 400,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze(
            [{"headline": "Market drops on Fed surprise"}], {}
        )

    assert len(output.votes) == 1
    assert output.votes[0].ticker == "SPY"


@pytest.mark.asyncio
async def test_range_bound_mode(temp_shadow_db):
    """Range-Bound约束: _build_user_prompt 包含 RANGE-BOUND MODE"""
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="daredevil:range_bound:sideways_test", shadow_type="daredevil",
        display_name="Test Sideways", methodology_prompt="You trade ranges.",
        virtual_capital=25000.0, temperature=0.45,
    )
    agent = DaredevilShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Market flat"}], {"SPY": 450.0}
    )
    assert "RANGE-BOUND MODE" in prompt


@pytest.mark.asyncio
async def test_contrarian_mode(temp_shadow_db):
    """Contrarian约束: _build_user_prompt 包含 CONTRARIAN MODE"""
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="daredevil:contrarian:herd_test", shadow_type="daredevil",
        display_name="Test Herd Fader", methodology_prompt="You fade consensus.",
        virtual_capital=20000.0, temperature=0.55,
    )
    agent = DaredevilShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Everyone is bullish"}], {"SPY": 450.0}
    )
    assert "CONTRARIAN MODE" in prompt
