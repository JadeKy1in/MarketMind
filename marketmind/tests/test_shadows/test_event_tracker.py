"""Tests for EventTracker — continuous event monitoring tracks."""
import pytest

from marketmind.shadows.event_tracker import (
    EventTracker,
    STATUS_ACTIVE,
    STATUS_MONITORING,
    STATUS_CLOSED,
)


@pytest.fixture
def tracker(populated_db):
    """Create an EventTracker backed by populated DB (shadows exist)."""
    return EventTracker(populated_db.db_path)


# ── Test 1: Start, update, and close a track ────────────────────────────

def test_start_update_close_track(tracker):
    """Full lifecycle: start → update notes → close with outcome."""
    # Start a track
    track_id = tracker.start_track(
        shadow_id="expert:gold:agent_00",
        topic="Gold breakout above $2100",
        category="technical_breakout",
        key_metric="gold_spot_price",
    )
    assert track_id >= 1

    # Verify track exists
    track = tracker.get_track(track_id)
    assert track is not None
    assert track["topic"] == "Gold breakout above $2100"
    assert track["category"] == "technical_breakout"
    assert track["key_metric"] == "gold_spot_price"
    assert track["status"] == STATUS_ACTIVE

    # Update notes and status
    tracker.update_track(track_id, status=STATUS_MONITORING,
                         notes="Retesting $2100 support level")
    track = tracker.get_track(track_id)
    assert track["status"] == STATUS_MONITORING
    assert "Retesting $2100" in track["notes"]

    # Close with outcome
    tracker.close_track(track_id, outcome="Confirmed breakout: closed above $2150")
    track = tracker.get_track(track_id)
    assert track["status"] == STATUS_CLOSED
    assert track["outcome"] == "Confirmed breakout: closed above $2150"
    assert track["closed_at"] is not None


# ── Test 2: Get active tracks filters out closed ────────────────────────

def test_get_active_tracks_excludes_closed(tracker):
    """Active tracks query should exclude closed tracks."""
    # Create 3 tracks for same shadow
    tracker.start_track(
        shadow_id="expert:energy:agent_02",
        topic="Oil supply disruption",
        category="macro_event",
        key_metric="WTI",
    )
    tracker.start_track(
        shadow_id="expert:energy:agent_02",
        topic="OPEC+ meeting outcome",
        category="macro_event",
        key_metric="Brent",
    )
    t3 = tracker.start_track(
        shadow_id="expert:energy:agent_02",
        topic="Natural gas storage draw",
        category="inventory",
        key_metric="NG_F",
    )

    # Close one track
    tracker.close_track(t3, outcome="Resolved: storage draw within expectations")

    # Get active tracks — should have 2, not 3
    active = tracker.get_active_tracks("expert:energy:agent_02")
    assert len(active) == 2

    active_topics = [t["topic"] for t in active]
    assert "Oil supply disruption" in active_topics
    assert "OPEC+ meeting outcome" in active_topics
    assert "Natural gas storage draw" not in active_topics


# ── Test 3: Validation and edge cases ───────────────────────────────────

def test_validation_errors(tracker):
    """Empty shadow_id and topic should raise ValueError."""
    with pytest.raises(ValueError, match="shadow_id must not be empty"):
        tracker.start_track(
            shadow_id="", topic="Test", category="test",
        )

    with pytest.raises(ValueError, match="topic must not be empty"):
        tracker.start_track(
            shadow_id="s1", topic="", category="test",
        )

    with pytest.raises(ValueError, match="status must be one of"):
        tracker.update_track(1, status="invalid_status")


def test_get_active_empty_shadow(tracker):
    """Empty shadow_id returns empty list."""
    active = tracker.get_active_tracks("")
    assert active == []


def test_count_active(tracker):
    """Count active tracks for a shadow."""
    tracker.start_track(
        shadow_id="expert:tech:agent_06",
        topic="NVDA earnings preview",
        category="earnings",
    )
    tracker.start_track(
        shadow_id="expert:tech:agent_06",
        topic="Semiconductor sector rotation",
        category="sector_rotation",
    )

    assert tracker.count_active("expert:tech:agent_06") == 2
    assert tracker.count_active("nonexistent_shadow") == 0
