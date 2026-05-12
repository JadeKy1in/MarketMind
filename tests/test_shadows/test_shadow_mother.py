"""Tests for Shadow Mother — event detection and temp shadow lifecycle."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.shadow_mother import (
    ShadowMother, DetectedEvent, TempShadowSpec, ShadowOrchestrationResult
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAgent
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def mother(populated_db, settings):
    return ShadowMother(settings, populated_db)


@pytest.fixture
def cb_shock_news():
    """News items indicating a 50bp rate surprise."""
    return [
        {"headline": "Fed raises rates by 75bp vs 25bp expected",
         "source": "reuters", "timestamp": "2026-05-11T10:00:00Z"},
        {"headline": "Bond market in turmoil after surprise hike",
         "source": "bloomberg", "timestamp": "2026-05-11T10:05:00Z"},
    ]


@pytest.fixture
def vix_spike_news():
    """News items indicating geopolitical crisis with VIX spike."""
    return [
        {"headline": "VIX surges 60% as Middle East tensions escalate",
         "source": "cnbc", "timestamp": "2026-05-11T09:00:00Z"},
        {"headline": "Oil prices spike on supply disruption fears",
         "source": "reuters", "timestamp": "2026-05-11T09:10:00Z"},
    ]


@pytest.fixture
def normal_news():
    """Normal market news — no events."""
    return [
        {"headline": "Markets flat in quiet trading session",
         "source": "reuters", "timestamp": "2026-05-11T10:00:00Z"},
        {"headline": "Company X reports inline earnings",
         "source": "bloomberg", "timestamp": "2026-05-11T10:05:00Z"},
    ]


def test_mother_initialization(mother, populated_db):
    assert mother.state_db is populated_db
    assert len(mother.get_active_temp_shadows()) == 0


def test_detect_cb_shock_50bp_surprise(mother, cb_shock_news):
    events = mother.detect_cb_shock(cb_shock_news)
    assert len(events) >= 1
    assert events[0].event_type == "cb_shock"


def test_detect_geopolitical_vix_spike(mother, vix_spike_news):
    events = mother.detect_geopolitical(vix_spike_news)
    assert len(events) >= 1
    assert events[0].event_type == "geopolitical"


def test_no_false_positive_on_normal_news(mother, normal_news):
    events_cb = mother.detect_cb_shock(normal_news)
    events_geo = mother.detect_geopolitical(normal_news)
    assert len(events_cb) == 0
    assert len(events_geo) == 0


def test_prioritize_events(mother):
    events = [
        DetectedEvent(
            event_id="e1", event_type="cb_shock",
            description="Test 1", affected_assets=["SPY"],
            impact_score=0.3, detected_at="2026-05-11T10:00:00",
            vix_level=None, max_zscore=None, news_volume=None,
        ),
        DetectedEvent(
            event_id="e2", event_type="geopolitical",
            description="Test 2", affected_assets=["USO"],
            impact_score=0.9, detected_at="2026-05-11T10:00:00",
            vix_level=None, max_zscore=None, news_volume=None,
        ),
        DetectedEvent(
            event_id="e3", event_type="vol_shock",
            description="Test 3", affected_assets=["AAPL"],
            impact_score=0.5, detected_at="2026-05-11T10:00:00",
            vix_level=None, max_zscore=None, news_volume=None,
        ),
    ]
    prioritized = mother.prioritize_events(events, max_shadows=2)
    assert len(prioritized) == 2
    assert prioritized[0].event_id == "e2"  # highest impact
    assert prioritized[1].event_id == "e3"


@pytest.mark.asyncio
async def test_create_temp_shadow(mother, cb_shock_news):
    events = mother.detect_cb_shock(cb_shock_news)
    ids = await mother.create_temp_shadows(events)
    assert len(ids) > 0
    active = mother.get_active_temp_shadows()
    assert ids[0] in active


def test_check_destruction_not_for_new_shadow(mother, populated_db):
    """Brand new temp shadow should not be destroyed immediately."""
    config = ShadowConfig(
        shadow_id="temp_event:cb_shock:test_new",
        shadow_type="temp_event",
        display_name="Test New",
        methodology_prompt="You are a temporary analyst.",
        virtual_capital=15000.0,
        domain="macro",
    )
    populated_db.create_shadow(config)
    should_die = mother.check_destruction_conditions("temp_event:cb_shock:test_new")
    assert should_die is False


def test_check_destruction_non_temp_never_destroyed(mother, populated_db):
    """Non-temp shadows are never auto-destroyed."""
    config = ShadowConfig(
        shadow_id="expert:gold:permanent_agent",
        shadow_type="expert",
        display_name="Permanent",
        methodology_prompt="You are permanent.",
        virtual_capital=50000.0,
        domain="gold",
    )
    populated_db.create_shadow(config)
    should_die = mother.check_destruction_conditions("expert:gold:permanent_agent")
    assert should_die is False


def test_get_event_status(mother):
    status = mother.get_event_status("nonexistent")
    assert status == "unknown"
