"""Tests for missed path tracking."""
import pytest

from marketmind.shadows.missed_path import (
    MissedPathAgent, MissedPathReport, create_missed_path_report,
    _SURVIVORSHIP_WARNING
)
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


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


def test_generate_report_with_snapshots(temp_shadow_db):
    """有快照数据时生成完整报告"""
    from marketmind.shadows.missed_path import MissedPathAgent
    from marketmind.shadows.shadow_state import ShadowConfig, DailySnapshot

    settings = ShadowSettings()
    config = ShadowConfig(
        shadow_id="missed_path:gate1:test_report",
        shadow_type="missed_path",
        display_name="Test Missed Path",
        methodology_prompt="Rejected: long crypto",
        virtual_capital=0.0,
        max_positions=0,
    )
    temp_shadow_db.create_shadow(config)

    # 添加模拟快照（正收益）
    today = "2026-05-11"
    snap = DailySnapshot(
        shadow_id=config.shadow_id, date=today,
        virtual_capital=0.0, daily_return_pct=2.5,
    )
    temp_shadow_db.save_snapshot(config.shadow_id, snap)

    agent = MissedPathAgent(config, temp_shadow_db, settings)
    report = agent.generate_report(days_tracked=30)

    assert report is not None
    assert report.shadow_id == config.shadow_id
    assert report.days_tracked >= 1
    assert report.cumulative_return > 0
    assert report.would_have_been_profitable is True
    assert "SURVIVORSHIP BIAS" in report.survivorship_bias_warning


def test_generate_report_no_snapshots(temp_shadow_db):
    """无快照时返回默认报告"""
    from marketmind.shadows.missed_path import MissedPathAgent
    from marketmind.shadows.shadow_state import ShadowConfig

    settings = ShadowSettings()
    config = ShadowConfig(
        shadow_id="missed_path:gate1:test_empty",
        shadow_type="missed_path",
        display_name="Empty Missed Path",
        methodology_prompt="Rejected: short bonds",
        virtual_capital=0.0,
        max_positions=0,
    )
    temp_shadow_db.create_shadow(config)

    agent = MissedPathAgent(config, temp_shadow_db, settings)
    report = agent.generate_report(days_tracked=30)

    assert report.days_tracked == 0
    assert report.cumulative_return == 0.0
    assert report.would_have_been_profitable is False
