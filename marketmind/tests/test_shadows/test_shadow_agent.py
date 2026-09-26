"""Tests for ShadowAgent base class."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowDecision, PositionCheck
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
async def test_analyze_returns_output_with_mock_llm(agent):
    """Base _analyze() calls chat_with_integrity and produces output."""
    from unittest.mock import AsyncMock, patch
    mock_result = {"content": "VOTE_START\nticker: GLD\ndirection: long\nconfidence: 0.7\nthesis: test\nrisk_note: test\nVOTE_END", "latency_ms": 500}
    with patch("marketmind.gateway.async_client.chat_with_integrity", new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze([{"headline": "Gold rises"}], {"GLD": 180.0})
        assert output is not None
        assert output.shadow_id == "expert:gold:test_agent"


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


@pytest.mark.asyncio
async def test_analyze_exit_llm_says_exit(agent):
    """LLM returns exit -> should_exit=True"""
    from unittest.mock import AsyncMock, patch
    from marketmind.shadows.shadow_state import VirtualTradeOpen
    # First open a virtual position
    trade_id = agent.state_db.record_trade_open(agent.shadow_id, VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD", direction="long",
        entry_price=180.0, position_size_pct=0.10, entry_date="2026-04-20"
    ))

    mock_result = {
        "content": "EXIT_DECISION: exit\nEXIT_REASON: Momentum breakdown\nCONFIDENCE: 0.85",
        "latency_ms": 300,
    }
    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        results = await agent.analyze_position_exits()

    assert len(results) == 1
    assert results[0].should_exit is True
    assert results[0].exit_reason == "Momentum breakdown"
    assert results[0].confidence == 0.85


@pytest.mark.asyncio
async def test_analyze_exit_llm_says_hold(agent):
    """LLM returns hold -> should_exit=False"""
    from unittest.mock import AsyncMock, patch
    from marketmind.shadows.shadow_state import VirtualTradeOpen
    agent.state_db.record_trade_open(agent.shadow_id, VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD", direction="long",
        entry_price=180.0, position_size_pct=0.10, entry_date="2026-04-20"
    ))

    mock_result = {
        "content": "EXIT_DECISION: hold\nEXIT_REASON: Trend intact\nCONFIDENCE: 0.70",
        "latency_ms": 250,
    }
    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        results = await agent.analyze_position_exits()

    assert len(results) == 1
    assert results[0].should_exit is False


@pytest.mark.asyncio
async def test_analyze_exit_skips_fresh_positions(agent):
    """Position <5 days -> no LLM call, should_exit=False"""
    import datetime
    from marketmind.shadows.shadow_state import VirtualTradeOpen
    fresh_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    agent.state_db.record_trade_open(agent.shadow_id, VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="SLV", direction="short",
        entry_price=24.0, position_size_pct=0.15, entry_date=fresh_date
    ))

    results = await agent.analyze_position_exits()
    assert len(results) == 1
    assert results[0].should_exit is False
    assert results[0].days_held < 5


@pytest.mark.asyncio
async def test_analyze_exit_llm_failure_graceful(agent):
    """LLM call exception -> should_exit=False, does not crash"""
    from unittest.mock import AsyncMock, patch
    from marketmind.shadows.shadow_state import VirtualTradeOpen
    agent.state_db.record_trade_open(agent.shadow_id, VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD", direction="long",
        entry_price=180.0, position_size_pct=0.10, entry_date="2026-04-01"
    ))

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, side_effect=RuntimeError("Network down")):
        results = await agent.analyze_position_exits()

    assert len(results) == 1
    assert results[0].should_exit is False  # safe default: hold on error


def test_apply_ranking_to_snapshot_backfills_all_fields(agent):
    """apply_ranking_to_snapshot 写入所有7个排名字段到快照"""
    from unittest.mock import MagicMock

    ranking_result = MagicMock()
    ranking_result.composite_score = 0.85
    ranking_result.deflated_score = 0.72
    ranking_result.percentile_rank = 0.75
    ranking_result.achievement_tier = "excellent"
    ranking_result.component_scores = {
        "mppm": 0.82, "calmar": 0.65, "omega": 0.71, "win_rate": 0.58
    }

    agent.apply_ranking_to_snapshot(ranking_result)

    snap = agent.state_db.get_latest_snapshot(agent.shadow_id)
    assert snap is not None
    assert snap.composite_score == 0.85
    assert snap.deflated_score == 0.72
    assert snap.percentile_rank == 0.75
    assert snap.achievement_tier == "excellent"
    assert snap.mppm_score == 0.82
    assert snap.calmar_ratio == 0.65
    assert snap.omega_ratio == 0.71
    assert snap.win_rate_pct == 0.58


@pytest.mark.asyncio
async def test_analyze_exit_unparseable_output(agent):
    """LLM returns unparseable content -> should_exit=False"""
    from unittest.mock import AsyncMock, patch
    from marketmind.shadows.shadow_state import VirtualTradeOpen
    agent.state_db.record_trade_open(agent.shadow_id, VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD", direction="long",
        entry_price=180.0, position_size_pct=0.10, entry_date="2026-04-01"
    ))

    mock_result = {
        "content": "I think maybe you should consider doing something...",
        "latency_ms": 300,
    }
    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        results = await agent.analyze_position_exits()

    assert len(results) == 1
    assert results[0].should_exit is False
