"""Tests for Daredevil shadows — 5 active + 2 env-locked + 1 short-biased."""
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
def active_config():
    return ShadowConfig(
        shadow_id="daredevil:intraday:test_scalper",
        shadow_type="daredevil",
        display_name="Test Scalper",
        methodology_prompt="You must pick a direction daily.",
        virtual_capital=25000.0,
        temperature=0.5,
    )


@pytest.fixture
def active_daredevil(active_config, temp_shadow_db, settings):
    return DaredevilShadow(active_config, temp_shadow_db, settings)


class TestDaredevilShadow:
    @pytest.mark.asyncio
    async def test_daredevil_produces_analysis(self, active_daredevil):
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
            output = await active_daredevil.run_daily_analysis(news, {})
        assert output.shadow_id == "daredevil:intraday:test_scalper"
        assert output.date is not None

    @pytest.mark.asyncio
    async def test_daredevil_higher_risk_tolerance(self, active_daredevil):
        assert active_daredevil.config.max_drawdown_limit == 0.35
        assert active_daredevil.config.min_trades_for_ranking == 50


def test_all_8_daredevil_configs_unique():
    ids = [c.shadow_id for c in DAREDEVIL_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 8


def test_all_8_config_types():
    """5 active + 2 env-locked + 1 short-biased = 8."""
    types = {c.shadow_id.split(":")[2] for c in DAREDEVIL_SHADOW_CONFIGS}
    assert types == {
        "scalper", "trend_rider", "news_hound", "fade_master", "rotation_engine",
        "sideways_scout", "vol_surfer", "hunter"
    }


def test_factory_creates_8_daredevils(temp_shadow_db):
    settings = ShadowSettings()
    shadows = create_daredevil_shadows(temp_shadow_db, settings)
    assert len(shadows) == 8
    assert all(isinstance(s, DaredevilShadow) for s in shadows)


def test_5_active_daredevil_ids():
    """Verify the 5 active daredevils exist in configs."""
    active_ids = [c.shadow_id for c in DAREDEVIL_SHADOW_CONFIGS
                  if c.shadow_id.split(":")[1] in ("intraday", "weekly", "event", "contrarian", "sector")]
    assert len(active_ids) == 5


def test_2_env_locked_daredevil_ids():
    """Verify the 2 environment-locked daredevils."""
    env_ids = [c.shadow_id for c in DAREDEVIL_SHADOW_CONFIGS
               if "environment locked" in c.methodology_prompt.lower()
               or "environment locked" in c.shadow_id]
    # Range-Bound and Panic are env-locked
    env_by_id = [c for c in DAREDEVIL_SHADOW_CONFIGS
                 if "range_bound" in c.shadow_id or "panic" in c.shadow_id]
    assert len(env_by_id) == 2


def test_1_short_biased_crash_hunter():
    """Verify the crash hunter is short-biased."""
    crash = [c for c in DAREDEVIL_SHADOW_CONFIGS if "crash" in c.shadow_id]
    assert len(crash) == 1
    assert "SHORT-BIASED" in crash[0].methodology_prompt


# ── Active daredevils always produce votes ──────────────────────────────

@pytest.mark.asyncio
async def test_active_daredevils_produce_daily_votes():
    """Verify 5 active daredevils always produce output regardless of environment."""
    from marketmind.shadows.shadow_state import ShadowStateDB
    import tempfile, os
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_active.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()

        settings = ShadowSettings()
        shadows = create_daredevil_shadows(db, settings)

        mock_result = {
            "content": (
                "VOTE_START\n"
                "ticker: SPY\ndirection: long\nconfidence: 0.60\n"
                "thesis: Active daredevil test thesis\n"
                "risk_note: Test risk note\n"
                "VOTE_END"
            ),
            "latency_ms": 400,
        }

        active_count = 0
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value=mock_result):
            for shadow in shadows:
                shadow_id = shadow.shadow_id
                # Active daredevils: intraday, weekly, event, contrarian, sector
                if any(k in shadow_id for k in ("intraday", "weekly", "event", "contrarian", "sector")):
                    output = await shadow.run_daily_analysis(
                        [{"headline": "Normal market day"}], {}
                    )
                    assert output is not None
                    assert output.shadow_id == shadow_id
                    assert len(output.votes) > 0, (
                        f"Active daredevil {shadow_id} produced no votes"
                    )
                    active_count += 1

        assert active_count == 5, f"Expected 5 active daredevils, got {active_count}"
        db.close()


# ── LLM integration tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daredevil_analyze_with_mock_llm(temp_shadow_db):
    """DaredevilShadow._analyze() calls mock LLM and parses results."""
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
    """Range-Bound constraint: _build_user_prompt includes ENVIRONMENT LOCKED."""
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
    assert "ENVIRONMENT LOCKED" in prompt
    assert "Range-bound" in prompt


@pytest.mark.asyncio
async def test_crash_hunter_mode(temp_shadow_db):
    """Crash Hunter constraint: _build_user_prompt includes SHORT-BIASED."""
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="daredevil:crash:hunter_test", shadow_type="daredevil",
        display_name="Test Crash Hunter", methodology_prompt="You hunt crash signals.",
        virtual_capital=30000.0, temperature=0.5,
    )
    agent = DaredevilShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Market at all-time highs"}], {"SPY": 500.0}
    )
    assert "SHORT-BIASED" in prompt
    assert "Crash Hunter" in prompt


@pytest.mark.asyncio
async def test_active_daredevil_no_env_lock_in_prompt(temp_shadow_db):
    """Active daredevil prompts do NOT contain environment-locked language."""
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="daredevil:intraday:test_active", shadow_type="daredevil",
        display_name="Test Active", methodology_prompt="You find trades daily.",
        virtual_capital=25000.0, temperature=0.5,
    )
    agent = DaredevilShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Normal market day"}], {"SPY": 450.0}
    )
    assert "ENVIRONMENT LOCKED" not in prompt
    assert "SHORT-BIASED" not in prompt
