"""Tests for P3-1: Challenger Learns from Predecessor Failures.

Covers: AEL debrief failure pattern injection, graceful degradation,
deduplication, crystallization retirements, and cap-at-5 enforcement.
"""
import pytest
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings(
        challenger_stage1_periods=2,
        challenger_stage2_periods=3,
        challenger_stage3_weeks=2,
        challenger_trial_alpha=0.10,
        challenger_calmar_gate=0.3,
    )


@pytest.fixture
def engine(temp_shadow_db, settings):
    from marketmind.shadows.challenger_engine import ChallengerEngine
    return ChallengerEngine(temp_shadow_db, settings)


def _create_shadow(db, shadow_id, shadow_type="expert", domain="gold"):
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Shadow {shadow_id}",
        methodology_prompt="You are a test analyst.",
        virtual_capital=50000.0,
        domain=domain,
    )
    db.create_shadow(config)
    return config


def _add_retired_insight(db, shadow_id, insight, offset_seconds=0):
    """Add a retired insight to methodology_changes for testing."""
    conn = db._connect()
    try:
        from datetime import timedelta
        ts = (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()
        conn.execute(
            """INSERT INTO methodology_changes
               (shadow_id, change_type, old_prompt, new_prompt, reason, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (shadow_id, "update", "old_prompt_placeholder", "new_prompt_placeholder",
             f"Retired invalidated insight: {insight}", ts)
        )
        conn.commit()
    finally:
        conn.close()


def _make_mock_ael_engine(state_db, shadow_id, failure_patterns):
    """Create a mock AELEvolutionEngine with pre-populated debrief history."""
    from marketmind.shadows.ael_evolution import AELEvolutionEngine, AELDebriefResult

    mock_ael = AELEvolutionEngine(state_db=state_db)
    debrief = AELDebriefResult(
        shadow_id=shadow_id,
        month="2026-05",
        win_rate=0.35,
        cumulative_return=-0.10,
        total_trades=25,
        failure_patterns=failure_patterns,
        success_patterns=["Good entry timing"],
        lessons_learned="Reduce trade frequency during low conviction.",
    )
    mock_ael._debrief_history[shadow_id] = [debrief]
    return mock_ael


# ── Test 1: patterns injected ─────────────────────────────────────────────────

def test_patterns_injected(engine, temp_shadow_db):
    """Failure patterns from AEL debriefs are injected into challenger methodology."""
    _create_shadow(temp_shadow_db, "expert:test:p3_1_inject", "expert", "gold")

    mock_ael = _make_mock_ael_engine(
        temp_shadow_db, "expert:test:p3_1_inject",
        ["Overtrading during low volatility", "Ignoring macro risk signals"]
    )

    # Verify _collect_predecessor_failures returns the AEL patterns
    failures = engine._collect_predecessor_failures(
        "expert:test:p3_1_inject", _ael_engine=mock_ael
    )
    assert len(failures) == 2
    assert "Overtrading during low volatility" in failures
    assert "Ignoring macro risk signals" in failures

    # End-to-end via methodology_changes: retired insights are injected into prompt
    _create_shadow(temp_shadow_db, "expert:test:p3_1_e2e", "expert", "gold")
    _add_retired_insight(
        temp_shadow_db, "expert:test:p3_1_e2e",
        "Position sizing too aggressive in choppy markets"
    )

    challenger_id = engine.create_challenger("expert:test:p3_1_e2e")
    challenger = temp_shadow_db.get_shadow(challenger_id, caller_id="system")
    assert challenger is not None
    assert "[FAILURE PATTERNS TO AVOID" in challenger.methodology_prompt
    assert "Position sizing too aggressive in choppy markets" in challenger.methodology_prompt


# ── Test 2: no AEL data ok ───────────────────────────────────────────────────

def test_no_ael_data_graceful_degradation(engine, temp_shadow_db):
    """Gracefully handles missing AEL data — no crash, empty patterns list."""
    _create_shadow(temp_shadow_db, "expert:test:p3_1_noael", "expert", "gold")

    # No AEL debrief data, no methodology_changes entries -> empty list
    failures = engine._collect_predecessor_failures("expert:test:p3_1_noael")
    assert failures == []

    # create_challenger must succeed without error
    challenger_id = engine.create_challenger("expert:test:p3_1_noael")
    challenger = temp_shadow_db.get_shadow(challenger_id, caller_id="system")
    assert challenger is not None
    assert challenger.shadow_type == "challenger"
    assert challenger.parent_shadow_id == "expert:test:p3_1_noael"


# ── Test 3: deduplication ─────────────────────────────────────────────────────

def test_deduplication_across_sources(engine, temp_shadow_db):
    """Duplicate patterns from AEL debriefs + methodology_changes are removed."""
    _create_shadow(temp_shadow_db, "expert:test:p3_1_dedup", "expert", "gold")

    # Add retired insight that matches one of the AEL failure patterns
    _add_retired_insight(
        temp_shadow_db, "expert:test:p3_1_dedup",
        "Chasing momentum in range-bound markets"  # DUPLICATE with AEL
    )

    mock_ael = _make_mock_ael_engine(
        temp_shadow_db, "expert:test:p3_1_dedup",
        [
            "Chasing momentum in range-bound markets",      # DUPLICATE
            "Entering trades during FOMC blackouts",         # UNIQUE
        ]
    )

    failures = engine._collect_predecessor_failures(
        "expert:test:p3_1_dedup", _ael_engine=mock_ael
    )

    # Should have exactly 2 unique patterns (duplicate removed)
    assert len(failures) == 2
    assert "Chasing momentum in range-bound markets" in failures
    assert "Entering trades during FOMC blackouts" in failures


# ── Test 4: crystallization retirements ───────────────────────────────────────

def test_crystallization_retirements_pulled_in(engine, temp_shadow_db):
    """Retired insights from methodology_changes table are pulled in as failures."""
    _create_shadow(temp_shadow_db, "expert:test:p3_1_crystal", "expert", "gold")

    insights = [
        "Overweight energy sector during crude oil contango",
        "Ignoring earnings season implied volatility crush",
        "Late entry after parabolic move extensions",
    ]
    for insight in insights:
        _add_retired_insight(temp_shadow_db, "expert:test:p3_1_crystal", insight)

    failures = engine._collect_predecessor_failures("expert:test:p3_1_crystal")
    assert len(failures) == 3
    for insight in insights:
        assert insight in failures

    # End-to-end: create_challenger injects these into the methodology prompt
    challenger_id = engine.create_challenger("expert:test:p3_1_crystal")
    challenger = temp_shadow_db.get_shadow(challenger_id, caller_id="system")
    assert challenger is not None
    assert "[FAILURE PATTERNS TO AVOID" in challenger.methodology_prompt
    for insight in insights:
        assert insight in challenger.methodology_prompt


# ── Test 5: cap at 5 ──────────────────────────────────────────────────────────

def test_cap_at_five_patterns(engine, temp_shadow_db):
    """Maximum of 5 failure patterns to avoid prompt bloat."""
    _create_shadow(temp_shadow_db, "expert:test:p3_1_cap", "expert", "gold")

    # 4 patterns from AEL
    mock_ael = _make_mock_ael_engine(
        temp_shadow_db, "expert:test:p3_1_cap",
        [
            "Pattern A: Overtrading in low conviction",
            "Pattern B: Failing to cut losses quickly",
            "Pattern C: Adding to losing positions",
            "Pattern D: Trading against the trend",
        ]
    )

    # 3 more from crystallization retirements (total would be 7)
    # Use distinct timestamps so ORDER BY changed_at DESC is deterministic
    extra_insights = [
        ("Pattern E: Premature profit taking", 0),
        ("Pattern F: Inadequate sector diversification", -1),
        ("Pattern G: Front-running unconfirmed catalysts", -2),
    ]
    for insight, offset in extra_insights:
        _add_retired_insight(temp_shadow_db, "expert:test:p3_1_cap", insight, offset)

    failures = engine._collect_predecessor_failures(
        "expert:test:p3_1_cap", _ael_engine=mock_ael
    )

    # Capped at exactly 5
    assert len(failures) == 5

    # First 4 from AEL should be present
    assert "Pattern A: Overtrading in low conviction" in failures
    assert "Pattern B: Failing to cut losses quickly" in failures
    assert "Pattern C: Adding to losing positions" in failures
    assert "Pattern D: Trading against the trend" in failures

    # 5th spot from crystallization (one of E, F, G depending on collection order)
    crystallization_patterns = {failures[4]}  # the 5th spot
    assert crystallization_patterns & {
        "Pattern E: Premature profit taking",
        "Pattern F: Inadequate sector diversification",
        "Pattern G: Front-running unconfirmed catalysts",
    }, f"5th pattern should be from crystallization, got: {failures[4]}"

    # Only 2 of 3 crystallization patterns should be excluded (cap at 5 total)
    excluded_count = sum(
        1 for p in ["Pattern E: Premature profit taking",
                     "Pattern F: Inadequate sector diversification",
                     "Pattern G: Front-running unconfirmed catalysts"]
        if p not in failures
    )
    assert excluded_count == 2
