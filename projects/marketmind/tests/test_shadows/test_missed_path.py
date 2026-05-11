"""Tests for missed path tracking."""
import pytest

from projects.marketmind.shadows.missed_path import (
    MissedPathAgent, MissedPathReport, create_missed_path_report,
    _SURVIVORSHIP_WARNING
)
from projects.marketmind.shadows.shadow_state import ShadowConfig
from projects.marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def missed_path_config():
    return ShadowConfig(
        shadow_id="missed_path:gate1:test_01",
        shadow_type="missed_path",
        display_name="Missed Path Test",
        methodology_prompt="You are tracking the counterfactual path: LONG_ENERGY. "
                          "This path was rejected at Gate 1.",
        virtual_capital=0.0,
        max_positions=0,
    )


@pytest.fixture
def missed_agent(missed_path_config, temp_shadow_db, settings):
    return MissedPathAgent(missed_path_config, temp_shadow_db, settings)


@pytest.mark.asyncio
async def test_missed_path_produces_no_votes(missed_agent):
    output = await missed_agent._analyze([], {})
    assert len(output.votes) == 0


@pytest.mark.asyncio
async def test_missed_path_records_date(missed_agent):
    output = await missed_agent._analyze([], {})
    assert output.date is not None
    assert output.shadow_id == "missed_path:gate1:test_01"


def test_generate_report_with_no_data(missed_agent):
    report = missed_agent.generate_report(days_tracked=30)
    assert report.days_tracked == 0
    assert report.cumulative_return == 0.0


def test_report_includes_survivorship_warning(missed_agent):
    report = missed_agent.generate_report(days_tracked=30)
    assert "SURVIVORSHIP BIAS WARNING" in report.survivorship_bias_warning


def test_missed_path_does_not_trade(missed_agent):
    """Missed path has virtual_capital=0 and max_positions=0."""
    assert missed_agent.config.virtual_capital == 0.0
    assert missed_agent.config.max_positions == 0
