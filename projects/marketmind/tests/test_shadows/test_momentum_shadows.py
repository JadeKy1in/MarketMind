"""Tests for MomentumShadow — 4 momentum trend-following shadows."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.shadows.momentum_shadows import (
    MomentumShadow, create_momentum_shadows, MOMENTUM_SHADOW_CONFIGS
)
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def momentum_config():
    return ShadowConfig(
        shadow_id="momentum:intraday:test_scalper",
        shadow_type="momentum",
        display_name="Test Scalper",
        methodology_prompt="You must pick a direction daily.",
        virtual_capital=25000.0,
        temperature=0.50,
    )


@pytest.fixture
def momentum_shadow(momentum_config, temp_shadow_db, settings):
    return MomentumShadow(momentum_config, temp_shadow_db, settings)


class TestMomentumShadow:
    @pytest.mark.asyncio
    async def test_momentum_produces_analysis(self, momentum_shadow):
        news = [{"headline": "Market trends higher on tech rally"}]
        mock_result = {
            "content": (
                "VOTE_START\n"
                "ticker: QQQ\ndirection: long\nconfidence: 0.65\n"
                "thesis: Tech momentum accelerating on AI earnings\n"
                "risk_note: Overbought signals may trigger pullback\n"
                "VOTE_END"
            ),
            "latency_ms": 400,
        }
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value=mock_result):
            output = await momentum_shadow.run_daily_analysis(news, {})
        assert output.shadow_id == "momentum:intraday:test_scalper"
        assert output.date is not None


def test_create_momentum_shadows_creates_4(temp_shadow_db):
    """Factory creates exactly 4 momentum shadows."""
    settings = ShadowSettings()
    shadows = create_momentum_shadows(temp_shadow_db, settings)
    assert len(shadows) == 4
    assert all(isinstance(s, MomentumShadow) for s in shadows)

    # Verify all registered in DB
    visible = temp_shadow_db.get_visible_shadows()
    momentum_ids = [c.shadow_id for c in MOMENTUM_SHADOW_CONFIGS]
    registered = [v for v in visible if v.shadow_id in momentum_ids]
    assert len(registered) == 4


def test_momentum_shadows_have_correct_types():
    """All 4 momentum configs have shadow_type='momentum'."""
    for config in MOMENTUM_SHADOW_CONFIGS:
        assert config.shadow_type == "momentum", (
            f"{config.shadow_id} has type '{config.shadow_type}', expected 'momentum'"
        )


def test_intraday_scalper_has_low_capital():
    """Intraday Scalper has the lowest virtual capital among momentum shadows."""
    scalper = [c for c in MOMENTUM_SHADOW_CONFIGS if "scalper" in c.shadow_id]
    assert len(scalper) == 1
    scalper = scalper[0]
    assert scalper.virtual_capital == 25000.0
    assert scalper.temperature == 0.50
    assert scalper.max_positions == 4
    assert scalper.display_name == "Intraday Scalper"


def test_all_4_momentum_configs_unique_ids():
    """No duplicate shadow IDs in momentum configs."""
    ids = [c.shadow_id for c in MOMENTUM_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 4


def test_momentum_configs_correct_names():
    """Verify the 4 momentum shadow display names match the plan."""
    expected_names = {"Intraday Scalper", "Trend Rider", "Event Hound", "Rotation Engine"}
    actual_names = {c.display_name for c in MOMENTUM_SHADOW_CONFIGS}
    assert actual_names == expected_names


def test_momentum_shadows_use_30pct_drawdown():
    """Momentum shadows have drawdown limit of 30% (per plan §3.2)."""
    for config in MOMENTUM_SHADOW_CONFIGS:
        assert config.max_drawdown_limit == 0.30, (
            f"{config.shadow_id} has drawdown {config.max_drawdown_limit}, expected 0.30"
        )


def test_momentum_shadows_min_50_trades():
    """Momentum shadows require min 50 trades for ranking (per plan §3.2)."""
    for config in MOMENTUM_SHADOW_CONFIGS:
        assert config.min_trades_for_ranking == 50, (
            f"{config.shadow_id} has min_trades {config.min_trades_for_ranking}, expected 50"
        )


# ── LLM integration tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_momentum_analyze_with_mock_llm_produces_votes(temp_shadow_db):
    """MomentumShadow._analyze() calls mock LLM and correctly parses votes."""
    from marketmind.shadows.momentum_shadows import MomentumShadow

    config = ShadowConfig(
        shadow_id="momentum:weekly:test_trend", shadow_type="momentum",
        display_name="Test Trend Rider", methodology_prompt="You find trends.",
        virtual_capital=30000.0, temperature=0.40, max_drawdown_limit=0.30,
        min_trades_for_ranking=50,
    )
    agent = MomentumShadow(config, temp_shadow_db, ShadowSettings())

    mock_result = {
        "content": (
            "VOTE_START\n"
            "ticker: SPY\ndirection: long\nconfidence: 0.70\n"
            "thesis: Uptrend intact with strong volume confirmation\n"
            "risk_note: Watch for trend exhaustion at resistance\n"
            "VOTE_END"
        ),
        "latency_ms": 400,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze(
            [{"headline": "Market continues uptrend on strong volume"}], {}
        )

    assert len(output.decisions) == 1
    assert output.decisions[0].ticker == "SPY"
    assert output.decisions[0].direction == "long"
    assert output.decisions[0].confidence == 0.70


@pytest.mark.asyncio
async def test_momentum_prompt_includes_trend_context(temp_shadow_db):
    """MomentumShadow._build_user_prompt includes trend-following guidance."""
    from marketmind.shadows.momentum_shadows import MomentumShadow

    config = ShadowConfig(
        shadow_id="momentum:intraday:test_prompt", shadow_type="momentum",
        display_name="Test Prompt", methodology_prompt="Momentum trader.",
        virtual_capital=25000.0, temperature=0.50,
    )
    agent = MomentumShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Strong rally in tech sector"}], {"QQQ": 450.0}
    )
    assert "Momentum strategy rules" in prompt
    assert "trend continuation" in prompt.lower()
    assert "VOTE_START/VOTE_END" in prompt
