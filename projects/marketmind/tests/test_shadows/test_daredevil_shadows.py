"""Tests for Daredevil shadows."""
import pytest

from projects.marketmind.shadows.daredevil_shadows import (
    DaredevilShadow, create_daredevil_shadows, DAREDEVIL_SHADOW_CONFIGS
)
from projects.marketmind.shadows.shadow_state import ShadowConfig
from projects.marketmind.config.settings import ShadowSettings


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
        output = await scalper.run_daily_analysis(news, {})
        assert output.shadow_id == "daredevil:intraday:test_scalper"
        assert output.date is not None

    @pytest.mark.asyncio
    async def test_daredevil_higher_risk_tolerance(self, scalper):
        assert scalper.config.max_drawdown_limit == 0.35
        assert scalper.config.min_trades_for_ranking == 50


def test_all_5_daredevil_configs_unique():
    ids = [c.shadow_id for c in DAREDEVIL_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 5


def test_all_5_types_present():
    types = {c.shadow_id.split(":")[2] for c in DAREDEVIL_SHADOW_CONFIGS}
    assert types == {"scalper", "trend_rider", "news_hound", "fade_master", "rotation_engine"}


def test_factory_creates_5_daredevils(temp_shadow_db):
    settings = ShadowSettings()
    shadows = create_daredevil_shadows(temp_shadow_db, settings)
    assert len(shadows) == 5
    assert all(isinstance(s, DaredevilShadow) for s in shadows)
