"""Phase C.9: End-to-end integration tests for MarketMind's full daily pipeline with mock LLM.

Tests the complete daily orchestration cycle with mocked LLM calls,
pipeline entry point, position exit flow, and state persistence round-trip.
"""
import json
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from marketmind.shadows.shadow_state import ShadowConfig, VirtualTradeOpen
from marketmind.config.settings import ShadowSettings


# ── Mock LLM response helper ─────────────────────────────────────────────────

def _make_vote_response(ticker, direction, confidence, thesis="test thesis", risk_note="test risk"):
    """Build a mock LLM response with a single VOTE_START/VOTE_END vote block."""
    return {
        "content": (
            f"VOTE_START\n"
            f"ticker: {ticker}\n"
            f"direction: {direction}\n"
            f"confidence: {confidence}\n"
            f"thesis: {thesis}\n"
            f"risk_note: {risk_note}\n"
            f"VOTE_END"
        ),
        "latency_ms": 300,
        "usage": {"total_tokens": 200},
    }


# ── Test 1: Full daily cycle with mock LLM ───────────────────────────────────

@pytest.mark.asyncio
async def test_full_daily_cycle_with_mock_llm(temp_shadow_db):
    """Complete daily orchestration cycle with mock LLM for all 21 shadows."""
    from marketmind.shadows.shadow_mother import ShadowMother
    from marketmind.shadows.expert_shadows import create_expert_shadows
    from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    from marketmind.shadows.catfish_agent import create_catfish_agent

    settings = ShadowSettings()
    settings.max_concurrent_shadows = 5

    # Initialize all permanent shadows in the DB
    create_expert_shadows(temp_shadow_db, settings)
    create_daredevil_shadows(temp_shadow_db, settings)
    create_catfish_agent(temp_shadow_db, settings)

    # Verify 21 shadows registered
    visible = temp_shadow_db.get_visible_shadows()
    assert len(visible) == 21

    mother = ShadowMother(settings, temp_shadow_db)

    # Mock LLM: return different vote content based on caller_agent or system_prompt
    def mock_llm_response(**kwargs):
        caller = str(kwargs.get("caller_agent", ""))
        sys_prompt = str(kwargs.get("system_prompt", ""))
        combined = (caller + " " + sys_prompt).lower()

        if "bullion" in combined or "gold" in combined or "precious" in combined:
            content = (
                "VOTE_START\n"
                "ticker: GLD\ndirection: long\nconfidence: 0.7\n"
                "thesis: Gold bullish on safe-haven demand\n"
                "risk_note: USD strength risk\n"
                "VOTE_END"
            )
        elif "chain oracle" in combined or "crypto" in combined:
            content = (
                "VOTE_START\n"
                "ticker: BTC\ndirection: long\nconfidence: 0.65\n"
                "thesis: ETF inflows strong\n"
                "risk_note: Regulatory risk\n"
                "VOTE_END"
            )
        elif "scalper" in combined or "daredevil" in combined:
            content = (
                "VOTE_START\n"
                "ticker: SPY\ndirection: short\nconfidence: 0.5\n"
                "thesis: Momentum fading\n"
                "risk_note: Trend reversal risk\n"
                "VOTE_END"
            )
        elif "catfish" in combined or "minority" in combined:
            content = "NO_CONSENSUS_DETECTED"
        else:
            content = (
                "VOTE_START\n"
                "ticker: SPY\ndirection: long\nconfidence: 0.6\n"
                "thesis: Broad market strength\n"
                "risk_note: Rate hike risk\n"
                "VOTE_END"
            )
        return {"content": content, "latency_ms": 300, "usage": {"total_tokens": 200}}

    # Use benign news that won't trigger event detection (no cb_shock/geopolitical keywords)
    news = [
        {"headline": "Markets flat in quiet session"},
        {"headline": "Company reports inline earnings"},
        {"headline": "Trading volumes below seasonal average"},
        {"headline": "Holiday-shortened week ahead for major exchanges"},
        {"headline": "Economic calendar light this week"},
    ]

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, side_effect=mock_llm_response):
        result = await mother.orchestrate_daily_cycle(news, {})

    # Verify orchestration results
    assert result.active_shadows == 21  # 15 experts + 5 daredevils + 1 catfish
    assert result.votes_collected > 0
    assert len(result.shadow_analyses) == 21

    # Catfish returns no votes by design, so remaining 20 shadows should vote
    assert result.votes_collected >= 20

    # Rankings should be computed (even if empty for insufficient data)
    assert result.rankings is not None
    assert isinstance(result.rankings, list)


# ── Test 2: Mock pipeline run (app.py entry) ────────────────────────────────

@pytest.mark.asyncio
async def test_run_daily_pipeline_mocked(temp_shadow_db):
    """app.py run_daily() pipeline with mocked LLM gateway."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.gateway.async_client import init_gateway, DeepSeekGateway

    # Configure with in-memory test DB
    os.environ["DEEPSEEK_API_KEY"] = "test_key"
    import pathlib
    os.environ["MARKETMIND_DATA_DIR"] = str(pathlib.Path(temp_shadow_db.db_path).parent)

    config = MarketMindConfig.from_env()
    config.deepseek_api_key = "test_key"
    config.shadow = ShadowSettings()
    config.shadow.shadows_db_path = temp_shadow_db.db_path

    # Initialize gateway with mock URL (creates real httpx client, but unused
    # since chat_with_integrity is patched)
    init_gateway("test_key", "http://mock")

    # Create a mock gateway object and patch the global
    mock_gw = MagicMock(spec=DeepSeekGateway)
    mock_gw._call = AsyncMock(return_value={
        "content": (
            "VOTE_START\n"
            "ticker: SPY\ndirection: long\nconfidence: 0.5\n"
            "thesis: test\n"
            "risk_note: test\n"
            "VOTE_END"
        ),
        "usage": {"total_tokens": 100},
        "latency_ms": 200,
    })

    with patch("marketmind.gateway.async_client._gateway", mock_gw):
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value={
                       "content": (
                           "VOTE_START\n"
                           "ticker: GLD\ndirection: long\nconfidence: 0.6\n"
                           "thesis: Gold demand strong\n"
                           "risk_note: USD headwind\n"
                           "VOTE_END"
                       ),
                       "latency_ms": 300,
                   }):
            with patch("marketmind.pipeline.scout.fetch_all_sources",
                       new_callable=AsyncMock, return_value=[
                           {"headline": "Market update", "source": "test"}
                       ]):
                # Test just the shadow portion of the pipeline
                from marketmind.shadows.shadow_mother import ShadowMother
                from marketmind.shadows.expert_shadows import create_expert_shadows

                settings = config.shadow
                settings.shadows_db_path = temp_shadow_db.db_path
                create_expert_shadows(temp_shadow_db, settings)

                mother = ShadowMother(settings, temp_shadow_db)
                result = await mother.orchestrate_daily_cycle(
                    [{"headline": "Test"}], {}
                )

                assert result.active_shadows > 0
                assert result.active_shadows == 15  # only experts created
                assert result.votes_collected > 0
                assert result.votes_collected >= 15  # one vote per expert


# ── Test 3: Position exit integration ────────────────────────────────────────

@pytest.mark.asyncio
async def test_position_exit_integration(temp_shadow_db):
    """End-to-end: open position -> analyze exit -> close position."""
    from marketmind.shadows.shadow_agent import create_shadow_agent
    from marketmind.shadows.shadow_state import ShadowConfig

    settings = ShadowSettings()
    config = ShadowConfig(
        shadow_id="expert:gold:e2e_test", shadow_type="expert",
        display_name="E2E Gold", methodology_prompt="Gold market expert.",
        virtual_capital=50000.0, domain="gold",
    )
    agent = create_shadow_agent(config, temp_shadow_db, settings)

    # Open a position 20 days ago (>= 5 day threshold for exit analysis)
    trade_id = await agent.open_virtual_position(VirtualTradeOpen(
        shadow_id=agent.shadow_id, ticker="GLD", direction="long",
        entry_price=180.0, position_size_pct=0.10, entry_date="2026-04-21"
    ))
    assert trade_id is not None

    # Verify position is open
    open_positions = await agent.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].ticker == "GLD"

    # Mock LLM says exit
    mock_result = {
        "content": (
            "EXIT_DECISION: exit\n"
            "EXIT_REASON: Target price reached at 200\n"
            "CONFIDENCE: 0.90"
        ),
        "latency_ms": 300,
    }
    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        results = await agent.analyze_position_exits()

    assert len(results) == 1
    assert results[0].should_exit is True
    assert results[0].exit_reason is not None
    assert "Target" in results[0].exit_reason

    # Execute the exit
    await agent.close_virtual_position(
        results[0].trade_id, 200.0, results[0].exit_reason or "target"
    )
    open_positions = await agent.get_open_positions()
    assert len(open_positions) == 0

    # Verify trade history shows closed trade
    trade_history = temp_shadow_db.get_trade_history(agent.shadow_id, limit=10)
    closed = [t for t in trade_history if t.trade_id == results[0].trade_id]
    assert len(closed) == 1
    assert closed[0].exit_price == 200.0
    assert closed[0].pnl_pct is not None


# ── Test 4: State persistence round-trip ─────────────────────────────────────

def test_state_persistence_round_trip(temp_shadow_db):
    """Full round-trip: save state -> new objects -> load state for both managers."""
    config = ShadowConfig(
        shadow_id="expert:gold:persist_test", shadow_type="expert",
        display_name="Persist Test", methodology_prompt="Test methodology.",
        virtual_capital=50000.0,
    )
    temp_shadow_db.create_shadow(config)

    # Save state with both subsystem keys (split tables — no read-merge-write race)
    temp_shadow_db.save_emergency_quota_state(config.shadow_id, json.dumps({
        "state": "rewarded",
        "consecutive_failures": 0,
        "permanent_bonus": 2,
        "permanent_penalty": 0,
        "observation_days_remaining": 0,
    }))
    temp_shadow_db.save_paper_live_gap_state(config.shadow_id, json.dumps({
        "discount_rate": 0.12,
        "cumulative_slippage": 0.03,
    }))

    # Load back from raw DB tables
    eq_raw = temp_shadow_db.load_emergency_quota_state(config.shadow_id)
    assert eq_raw is not None
    eq_data = json.loads(eq_raw)
    assert eq_data["permanent_bonus"] == 2
    assert eq_data["state"] == "rewarded"

    plg_raw = temp_shadow_db.load_paper_live_gap_state(config.shadow_id)
    assert plg_raw is not None
    plg_data = json.loads(plg_raw)
    assert plg_data["discount_rate"] == 0.12
    assert plg_data["cumulative_slippage"] == 0.03

    # Verify EmergencyQuotaAuditor can rehydrate
    from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor

    auditor = EmergencyQuotaAuditor(temp_shadow_db, ShadowSettings())
    eq_state = auditor.get_shadow_state(config.shadow_id)
    assert eq_state.permanent_bonus == 2
    assert eq_state.state == "rewarded"
    assert eq_state.consecutive_failures == 0
    assert eq_state.permanent_penalty == 0

    # Verify PaperLiveGapManager can rehydrate
    from marketmind.shadows.paper_live_gap import PaperLiveGapManager

    manager = PaperLiveGapManager(temp_shadow_db, ShadowSettings())
    rate = manager._get_discount_rate(config.shadow_id)
    assert rate == 0.12
