"""Tests for P3-4 partial-state recovery — cycle_checkpoints CRUD and resume logic."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_mother import ShadowMother, ShadowOrchestrationResult
from marketmind.shadows.shadow_agent import ShadowAnalysisOutput, ShadowVote
from marketmind.config.settings import ShadowSettings


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def today_str():
    return "2026-05-21"


@pytest.fixture
def sample_shadows():
    """Create 5 sample ShadowConfig objects for testing."""
    return [
        ShadowConfig(
            shadow_id=f"expert:domain_{i}:agent_{i:02d}",
            shadow_type="expert",
            display_name=f"Expert {i}",
            methodology_prompt=f"You are expert {i}.",
            virtual_capital=50000.0,
            domain=f"domain_{i}",
        )
        for i in range(5)
    ]


@pytest.fixture
def sample_output():
    """Create a sample ShadowAnalysisOutput."""
    return ShadowAnalysisOutput(
        shadow_id="expert:domain_0:agent_00",
        date="2026-05-21",
        votes=[
            ShadowVote(
                shadow_id="expert:domain_0:agent_00",
                shadow_type="expert",
                date="2026-05-21",
                ticker="AAPL",
                direction="long",
                confidence=0.75,
                thesis="Strong momentum",
                risk_note="Valuation risk",
            )
        ],
        insights=["AAPL breakout above resistance", "Sector rotation into tech"],
        methodology_notes="Standard analysis",
        quota_used=2,
        latency_ms=450,
    )


# ── Test 1: Save and retrieve checkpoint ───────────────────────────────────

def test_save_and_get_checkpoint(temp_shadow_db, today_str):
    """Write a checkpoint then read it back — round-trip verification."""
    temp_shadow_db.save_checkpoint(
        date=today_str, shadow_id="expert:domain_0:agent_00",
        status="completed", step=4,
        analysis_json='{"vote_count": 2, "quota_used": 1}',
    )
    cp = temp_shadow_db.get_checkpoint(today_str, "expert:domain_0:agent_00")
    assert cp is not None
    assert cp["status"] == "completed"
    assert cp["step_completed"] == 4
    assert cp["analysis_json"] == '{"vote_count": 2, "quota_used": 1}'
    assert cp["completed_at"] is not None


def test_get_checkpoint_missing_returns_none(temp_shadow_db, today_str):
    """Querying a nonexistent checkpoint returns None."""
    cp = temp_shadow_db.get_checkpoint(today_str, "nonexistent:shadow")
    assert cp is None


# ── Test 2: Incomplete shadow detection for resume ─────────────────────────

def test_incomplete_cycle_resume(temp_shadow_db, today_str, sample_shadows):
    """3 completed + 2 pending -> get_incomplete_shadows returns 2."""
    # Save 3 completed checkpoints
    for i in range(3):
        temp_shadow_db.save_checkpoint(
            date=today_str, shadow_id=sample_shadows[i].shadow_id,
            status="completed", step=4,
        )
    # Save 2 pending checkpoints (crashed before completion)
    for i in range(3, 5):
        temp_shadow_db.save_checkpoint(
            date=today_str, shadow_id=sample_shadows[i].shadow_id,
            status="pending", step=4,
        )

    incomplete = temp_shadow_db.get_incomplete_shadows(today_str)
    assert len(incomplete) == 2
    assert sample_shadows[3].shadow_id in incomplete
    assert sample_shadows[4].shadow_id in incomplete
    # Completed shadows should NOT appear
    assert sample_shadows[0].shadow_id not in incomplete


def test_incomplete_includes_failed(temp_shadow_db, today_str):
    """Failed checkpoints are also treated as incomplete for retry."""
    temp_shadow_db.save_checkpoint(
        date=today_str, shadow_id="expert:test:failed",
        status="failed", step=4, error_message="LLM timeout",
    )
    incomplete = temp_shadow_db.get_incomplete_shadows(today_str)
    assert "expert:test:failed" in incomplete


# ── Test 3: Completed shadows skipped on resume (integration) ──────────────

@pytest.mark.asyncio
async def test_completed_skip(temp_shadow_db, today_str, sample_shadows):
    """If a checkpoint exists and is 'completed', the shadow is skipped."""
    # Pre-populate: shadow[0] already completed
    for config in sample_shadows:
        temp_shadow_db.create_shadow(config)
    temp_shadow_db.save_checkpoint(
        date=today_str, shadow_id=sample_shadows[0].shadow_id,
        status="completed", step=4,
    )

    settings = ShadowSettings()
    mother = ShadowMother(settings, temp_shadow_db)
    news_items = [{"headline": "Test news", "source": "test"}]
    market_data = {"SPY": 520.0}

    mock_output = ShadowAnalysisOutput(
        shadow_id=sample_shadows[1].shadow_id,
        date=today_str,
        votes=[],
        insights=[],
        quota_used=1,
        latency_ms=100,
    )

    with patch(
        "marketmind.shadows.shadow_agent.create_shadow_agent"
    ) as mock_create:
        mock_agent = MagicMock()
        mock_agent.run_daily_analysis = AsyncMock(return_value=mock_output)
        mock_create.return_value = mock_agent

        result = ShadowOrchestrationResult(date=today_str)
        # visible includes all 5 shadows, but shadow[0] should be skipped
        visible = [temp_shadow_db.get_shadow(s.shadow_id) for s in sample_shadows]
        all_votes = await mother._step_collect_votes(
            news_items, market_data, visible, today_str, result
        )

    # Only 4 shadows ran (shadow[0] was skipped)
    assert mock_create.call_count == 4
    # Verify shadow[0] was NOT called
    called_ids = [call[0][0].shadow_id for call in mock_create.call_args_list]
    assert sample_shadows[0].shadow_id not in called_ids


# ── Test 4: Failed checkpoint triggers retry ───────────────────────────────

@pytest.mark.asyncio
async def test_failed_retry(temp_shadow_db, today_str, sample_shadows):
    """Failed checkpoint -> shadow is re-run on resume."""
    for config in sample_shadows[:2]:
        temp_shadow_db.create_shadow(config)

    # Shadow[0] had a failed run previously
    temp_shadow_db.save_checkpoint(
        date=today_str, shadow_id=sample_shadows[0].shadow_id,
        status="failed", step=4, error_message="Connection timeout",
    )

    settings = ShadowSettings()
    mother = ShadowMother(settings, temp_shadow_db)
    news_items = [{"headline": "Test news", "source": "test"}]
    market_data = {"SPY": 520.0}

    mock_output = ShadowAnalysisOutput(
        shadow_id=sample_shadows[0].shadow_id,
        date=today_str, votes=[], insights=[], quota_used=1, latency_ms=100,
    )

    with patch(
        "marketmind.shadows.shadow_agent.create_shadow_agent"
    ) as mock_create:
        mock_agent = MagicMock()
        mock_agent.run_daily_analysis = AsyncMock(return_value=mock_output)
        mock_create.return_value = mock_agent

        result = ShadowOrchestrationResult(date=today_str)
        visible = [temp_shadow_db.get_shadow(s.shadow_id) for s in sample_shadows[:2]]
        all_votes = await mother._step_collect_votes(
            news_items, market_data, visible, today_str, result
        )

    # Both shadows should run — failed shadow is NOT skipped
    assert mock_create.call_count == 2
    # After re-run, checkpoint should now be 'completed'
    cp = temp_shadow_db.get_checkpoint(today_str, sample_shadows[0].shadow_id)
    assert cp is not None
    assert cp["status"] == "completed"


# ── Test 5: Per-shadow checkpoint saves N checkpoints ──────────────────────

@pytest.mark.asyncio
async def test_per_shadow_checkpoint(temp_shadow_db, today_str, sample_shadows):
    """N shadows analyzed -> N checkpoints saved."""
    for config in sample_shadows:
        temp_shadow_db.create_shadow(config)

    settings = ShadowSettings()
    mother = ShadowMother(settings, temp_shadow_db)
    news_items = [{"headline": "Test news", "source": "test"}]
    market_data = {"SPY": 520.0}

    mock_output = ShadowAnalysisOutput(
        shadow_id="test", date=today_str,
        votes=[], insights=[], quota_used=1, latency_ms=100,
    )

    with patch(
        "marketmind.shadows.shadow_agent.create_shadow_agent"
    ) as mock_create:
        mock_agent = MagicMock()
        mock_agent.run_daily_analysis = AsyncMock(return_value=mock_output)
        mock_create.return_value = mock_agent

        result = ShadowOrchestrationResult(date=today_str)
        visible = [temp_shadow_db.get_shadow(s.shadow_id) for s in sample_shadows]
        await mother._step_collect_votes(
            news_items, market_data, visible, today_str, result
        )

    # Verify exactly N checkpoints were saved
    conn = temp_shadow_db._connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM cycle_checkpoints WHERE date = ?",
            (today_str,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == len(sample_shadows)

    # All should be 'completed' (no failures injected)
    for s in sample_shadows:
        cp = temp_shadow_db.get_checkpoint(today_str, s.shadow_id)
        assert cp is not None
        assert cp["status"] == "completed"
        assert cp["step_completed"] == 4
        assert cp["analysis_json"] is not None


# ── Test 6: Clear date checkpoints ─────────────────────────────────────────

def test_clear_date_checkpoints(temp_shadow_db, today_str, sample_shadows):
    """clear_date_checkpoints removes all checkpoints for a given date."""
    # Save checkpoints for today
    for s in sample_shadows:
        temp_shadow_db.save_checkpoint(
            date=today_str, shadow_id=s.shadow_id,
            status="completed", step=4,
        )
    # Save a checkpoint for a different date (should survive cleanup)
    other_date = "2026-05-20"
    temp_shadow_db.save_checkpoint(
        date=other_date, shadow_id="expert:test:other",
        status="completed", step=4,
    )

    # Verify pre-cleanup state
    assert len(temp_shadow_db.get_incomplete_shadows(today_str)) == 0
    cp_other = temp_shadow_db.get_checkpoint(other_date, "expert:test:other")
    assert cp_other is not None

    # Clean up today's checkpoints
    temp_shadow_db.clear_date_checkpoints(today_str)

    # Today's checkpoints should be gone
    for s in sample_shadows:
        assert temp_shadow_db.get_checkpoint(today_str, s.shadow_id) is None

    # Other date's checkpoints should survive
    cp_other = temp_shadow_db.get_checkpoint(other_date, "expert:test:other")
    assert cp_other is not None


# ── Test 7: Crash safety — failed analysis saves 'failed' checkpoint ───────

@pytest.mark.asyncio
async def test_crash_safety(temp_shadow_db, today_str, sample_shadows):
    """When a shadow analysis raises, a 'failed' checkpoint is saved."""
    for config in sample_shadows[:2]:
        temp_shadow_db.create_shadow(config)

    settings = ShadowSettings()
    mother = ShadowMother(settings, temp_shadow_db)
    news_items = [{"headline": "Test news", "source": "test"}]
    market_data = {"SPY": 520.0}

    # Shadow[0] succeeds, shadow[1] raises
    success_output = ShadowAnalysisOutput(
        shadow_id=sample_shadows[0].shadow_id,
        date=today_str, votes=[], insights=[], quota_used=1, latency_ms=100,
    )

    with patch(
        "marketmind.shadows.shadow_agent.create_shadow_agent"
    ) as mock_create:
        mock_agent_ok = MagicMock()
        mock_agent_ok.run_daily_analysis = AsyncMock(return_value=success_output)

        mock_agent_fail = MagicMock()
        mock_agent_fail.run_daily_analysis = AsyncMock(
            side_effect=RuntimeError("LLM API timeout after 60s")
        )

        mock_create.side_effect = [mock_agent_ok, mock_agent_fail]

        result = ShadowOrchestrationResult(date=today_str)
        visible = [temp_shadow_db.get_shadow(s.shadow_id) for s in sample_shadows[:2]]
        all_votes = await mother._step_collect_votes(
            news_items, market_data, visible, today_str, result
        )

    # Shadow[0] should have completed checkpoint
    cp_ok = temp_shadow_db.get_checkpoint(today_str, sample_shadows[0].shadow_id)
    assert cp_ok is not None
    assert cp_ok["status"] == "completed"
    assert cp_ok["analysis_json"] is not None

    # Shadow[1] should have failed checkpoint with error message
    cp_fail = temp_shadow_db.get_checkpoint(today_str, sample_shadows[1].shadow_id)
    assert cp_fail is not None
    assert cp_fail["status"] == "failed"
    assert "LLM API timeout" in (cp_fail["error_message"] or "")

    # get_incomplete_shadows should return the failed shadow
    incomplete = temp_shadow_db.get_incomplete_shadows(today_str)
    assert sample_shadows[1].shadow_id in incomplete
