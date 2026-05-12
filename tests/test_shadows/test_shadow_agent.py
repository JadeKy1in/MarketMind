"""Tests for ShadowAgent base class."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote, PositionCheck
)
from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, DailySnapshot
)
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def agent_config():
    return ShadowConfig(
        shadow_id="expert:gold:test_agent",
        shadow_type="expert",
        display_name="Test Gold Agent",
        methodology_prompt="You are a test gold analyst.",
        virtual_capital=50000.0,
        domain="gold",
    )


@pytest.fixture
def agent(temp_shadow_db, agent_config, settings):
    return ShadowAgent(agent_config, temp_shadow_db, settings)


def test_agent_stores_config(temp_shadow_db, agent_config, settings):
    agent = ShadowAgent(agent_config, temp_shadow_db, settings)
    assert agent.shadow_id == "expert:gold:test_agent"
    assert agent.config.shadow_type == "expert"
    assert agent.state_db is temp_shadow_db


def test_agent_created_in_db(agent, temp_shadow_db):
    retrieved = temp_shadow_db.get_shadow("expert:gold:test_agent")
    assert retrieved is not None
    assert retrieved.display_name == "Test Gold Agent"


@pytest.mark.asyncio
async def test_receive_status_card_returns_structure(agent):
    card = await agent.receive_status_card()
    assert "shadow_id" in card
    assert card["shadow_id"] == "expert:gold:test_agent"
    assert "tier" in card
    assert "daily_quota" in card


@pytest.mark.asyncio
async def test_open_virtual_position(agent):
    trade = VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD",
        direction="long", entry_price=180.0,
        position_size_pct=0.10, entry_date="2026-05-11"
    )
    trade_id = await agent.open_virtual_position(trade)
    assert trade_id > 0
    open_trades = await agent.get_open_positions()
    assert len(open_trades) == 1
    assert open_trades[0].ticker == "GLD"


@pytest.mark.asyncio
async def test_close_virtual_position(agent):
    trade = VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="SLV",
        direction="long", entry_price=24.0,
        position_size_pct=0.15, entry_date="2026-05-11"
    )
    trade_id = await agent.open_virtual_position(trade)
    await agent.close_virtual_position(trade_id, 26.0, "target")
    open_trades = await agent.get_open_positions()
    assert len(open_trades) == 0


@pytest.mark.asyncio
async def test_run_daily_analysis_raises_not_implemented(agent):
    with pytest.raises(NotImplementedError):
        await agent._analyze([], {})


@pytest.mark.asyncio
async def test_save_daily_snapshot_persists(agent):
    await agent.save_daily_snapshot()
    snap = agent.state_db.get_latest_snapshot(agent.shadow_id)
    assert snap is not None
    assert snap.date is not None


def test_get_daily_quota_default(agent):
    quota = agent.get_daily_quota()
    assert quota == 5


def test_get_pro_quota_default(agent):
    quota = agent.get_pro_quota()
    assert quota == 1


def test_get_integrity_score_default(agent):
    score = agent.get_integrity_score()
    assert score == 100


def test_report_integrity_violation(agent):
    from marketmind.shadows.shadow_state import IntegrityEvent
    event = IntegrityEvent(
        shadow_id=agent.shadow_id, date="2026-05-11",
        event_type="verified_true", claim_detail='{"claim": "test"}',
        score_change=1, new_score=101
    )
    agent.report_integrity_event(event)
    score = agent.get_integrity_score()
    assert score == 101
