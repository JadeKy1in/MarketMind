"""Tests for P3-1: Challenger Learns from Predecessor Failures.

Verifies that challenger shadows receive failure pattern injection from
AEL debriefs and crystallization retirements when created.
"""
import pytest
from unittest.mock import MagicMock

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.methodology_injector import MethodologyInjector
from marketmind.config.settings import ShadowSettings


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _create_shadow(db, shadow_id, shadow_type="expert", domain="gold",
                   methodology_prompt="You are a test analyst."):
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Shadow {shadow_id}",
        methodology_prompt=methodology_prompt,
        virtual_capital=50000.0,
        domain=domain,
    )
    db.create_shadow(config)
    return config


def _insert_debrief(db, shadow_id, changed_at, failure_reason):
    """Insert a debrief entry into methodology_changes directly."""
    from datetime import datetime, timezone
    conn = db._connect()
    try:
        conn.execute(
            """INSERT INTO methodology_changes
               (shadow_id, change_type, old_prompt, new_prompt, reason, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (shadow_id, "debrief", "", "",
             failure_reason,
             changed_at if isinstance(changed_at, str)
             else changed_at.isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def _insert_retirement(db, shadow_id, changed_at, insight):
    """Insert a crystallization_retire entry into methodology_changes."""
    from datetime import datetime, timezone
    conn = db._connect()
    try:
        conn.execute(
            """INSERT INTO methodology_changes
               (shadow_id, change_type, old_prompt, new_prompt, reason, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (shadow_id, "crystallization_retire", "", "",
             insight,
             changed_at if isinstance(changed_at, str)
             else changed_at.isoformat())
        )
        conn.commit()
    finally:
        conn.close()


# ── Test 1: patterns_injected ─────────────────────────────────────────────────

def test_patterns_injected(engine, temp_shadow_db):
    """Challenger methodology prompt contains failure pattern keywords after injection."""
    from datetime import datetime, timezone, timedelta

    target_id = "expert:gold:test_inject"
    _create_shadow(temp_shadow_db, target_id, "expert", "gold",
                   methodology_prompt="You are a gold market expert. Use momentum signals.")

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=30)).isoformat()
    _insert_debrief(temp_shadow_db, target_id, recent,
                    "Over-relied on momentum in sideways markets")
    _insert_debrief(temp_shadow_db, target_id,
                    (now - timedelta(days=15)).isoformat(),
                    "Failed to exit before FOMC volatility events")

    # Create challenger — should inject debrief patterns
    challenger_id = engine.create_challenger(target_id)
    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger is not None

    prompt = challenger.methodology_prompt
    # Should contain the failure patterns section
    assert "FAILURE PATTERNS TO AVOID" in prompt
    assert "momentum in sideways markets" in prompt
    assert "FOMC volatility" in prompt
    # Original methodology should still be present (appended after patterns)
    assert "gold market expert" in prompt
    assert "momentum signals" in prompt


# ── Test 2: no_ael_data_ok ────────────────────────────────────────────────────

def test_no_ael_data_ok(engine, temp_shadow_db):
    """When no AEL debrief data exists, challenger is created normally without crash."""
    target_id = "expert:energy:test_no_data"
    _create_shadow(temp_shadow_db, target_id, "expert", "energy",
                   methodology_prompt="You are an energy market analyst.")

    # No debrief entries inserted — should gracefully create challenger
    challenger_id = engine.create_challenger(target_id)
    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger is not None

    prompt = challenger.methodology_prompt
    # Should NOT have failure patterns section (no data)
    assert "FAILURE PATTERNS TO AVOID" not in prompt
    # Should have the original methodology verbatim
    assert "energy market analyst" in prompt


# ── Test 3: deduplication ─────────────────────────────────────────────────────

def test_deduplication():
    """Duplicate failure patterns are deduplicated in the formatted output."""
    prompt = "You are a test analyst."
    failures = [
        "Exit too late after earnings",
        "Exit too late after earnings",  # exact duplicate
        "Over-trade in low-volume periods",
        "Exit too late after earnings",  # third duplicate
    ]

    result = MethodologyInjector.format_failure_patterns(prompt, failures)

    # "Exit too late after earnings" should appear exactly ONCE
    assert result.count("Exit too late after earnings") == 1
    assert "Over-trade in low-volume periods" in result
    # Should have exactly 2 unique patterns
    assert result.count("- Exit too late after earnings") == 1
    assert result.count("- Over-trade") == 1


# ── Test 4: crystallization_retirements ───────────────────────────────────────

def test_crystallization_retirements(engine, temp_shadow_db):
    """Retired insights from crystallization are included in challenger prompt."""
    from datetime import datetime, timezone, timedelta

    target_id = "expert:crypto:test_retire"
    _create_shadow(temp_shadow_db, target_id, "expert", "crypto",
                   methodology_prompt="You are a crypto market expert.")

    now = datetime.now(timezone.utc)
    # Insert a debrief and a crystallization retirement
    _insert_debrief(temp_shadow_db, target_id,
                    (now - timedelta(days=30)).isoformat(),
                    "Debrief: entered too early on breakouts")
    _insert_retirement(temp_shadow_db, target_id,
                       (now - timedelta(days=10)).isoformat(),
                       "Retired: BTC dominance correlation assumed stable")

    challenger_id = engine.create_challenger(target_id)
    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger is not None

    prompt = challenger.methodology_prompt
    assert "FAILURE PATTERNS TO AVOID" in prompt
    # Both debrief pattern and retired insight should appear
    assert "entered too early on breakouts" in prompt
    assert "BTC dominance" in prompt


# ── Test 5: cap_at_5 ──────────────────────────────────────────────────────────

def test_cap_at_5(engine, temp_shadow_db):
    """More than 5 patterns (debriefs + retirements) gets capped to 5."""
    from datetime import datetime, timezone, timedelta

    target_id = "expert:bonds:test_cap"
    _create_shadow(temp_shadow_db, target_id, "expert", "bonds",
                   methodology_prompt="You are a bond market analyst.")

    now = datetime.now(timezone.utc)
    # Insert 4 debriefs and 3 retirements = 7 total patterns
    for i in range(4):
        _insert_debrief(temp_shadow_db, target_id,
                        (now - timedelta(days=30 + i)).isoformat(),
                        f"Debrief failure #{i}")
    for i in range(3):
        _insert_retirement(temp_shadow_db, target_id,
                           (now - timedelta(days=10 + i)).isoformat(),
                           f"Retired insight #{i}")

    challenger_id = engine.create_challenger(target_id)
    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger is not None

    prompt = challenger.methodology_prompt
    assert "FAILURE PATTERNS TO AVOID" in prompt

    # Count the bullet points — should be exactly 5 (capped)
    bullet_count = prompt.count("\n- ")
    assert bullet_count == 5, f"Expected 5 bullets (capped), got {bullet_count}"

    # First debrief should be present
    assert "Debrief failure #0" in prompt
    # Items beyond index 4 should NOT be present (capped at 5)
    # Since we have 4 debriefs + 3 retirements, items after position 4 are cut
    # The 5th item (index 4) is "Retired insight #1" (after 4 debriefs)
    assert "Retired insight #2" not in prompt


# ── Edge case: empty failures list ────────────────────────────────────────────

def test_format_failure_patterns_empty_list():
    """format_failure_patterns with empty list returns prompt unchanged (no section)."""
    prompt = "You are a test analyst."
    result = MethodologyInjector.format_failure_patterns(prompt, [])
    assert "FAILURE PATTERNS TO AVOID" not in result
    assert result == prompt


# ── Edge case: old debrief data outside 90-day window is ignored ─────────────

def test_old_debrief_ignored(engine, temp_shadow_db):
    """Debrief entries older than 90 days are not injected."""
    from datetime import datetime, timezone, timedelta

    target_id = "expert:metals:test_old"
    _create_shadow(temp_shadow_db, target_id, "expert", "metals",
                   methodology_prompt="You are a metals analyst.")

    now = datetime.now(timezone.utc)
    # Insert a debrief from 120 days ago (outside 90-day window)
    old_date = (now - timedelta(days=120)).isoformat()
    _insert_debrief(temp_shadow_db, target_id, old_date,
                    "Very old failure pattern from 4 months ago")

    challenger_id = engine.create_challenger(target_id)
    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger is not None

    prompt = challenger.methodology_prompt
    # Old pattern should NOT be injected (outside 90-day window)
    assert "FAILURE PATTERNS TO AVOID" not in prompt
    assert "4 months ago" not in prompt
