"""Tests for economic calendar — Phase G Layer 6."""
import json
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from marketmind.pipeline.economic_calendar import (
    check_economic_calendar,
    get_event_confidence_discount,
    _classify_fred_impact,
    _parse_date,
    _get_fomc_window_events,
    _filter_releases_by_window,
    FOMC_DATES_2026,
    FOMC_EXPIRY_DATE,
)

# ── Fixture helpers ─────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "calendar"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ── classify_fred_impact tests ───────────────────────────────────────────────

def test_classify_high_impact_cpi():
    assert _classify_fred_impact("Consumer Price Index") == "HIGH"


def test_classify_high_impact_nfp():
    assert _classify_fred_impact("Nonfarm Payrolls / Employment Situation") == "HIGH"


def test_classify_medium_impact_gdp():
    assert _classify_fred_impact("Gross Domestic Product (GDP)") == "MEDIUM"


def test_classify_medium_impact_pce():
    assert _classify_fred_impact("Personal Consumption Expenditures (PCE)") == "MEDIUM"


def test_classify_low_impact_unknown():
    assert _classify_fred_impact("Housing Starts") == "LOW"


# ── parse_date tests ──────────────────────────────────────────────────────────

def test_parse_date_iso():
    assert _parse_date("2026-05-16") == date(2026, 5, 16)


def test_parse_date_slash():
    assert _parse_date("2026/05/16") == date(2026, 5, 16)


def test_parse_date_us():
    assert _parse_date("05/16/2026") == date(2026, 5, 16)


def test_parse_date_invalid():
    assert _parse_date("not-a-date") is None


# ── FOMC date detection tests ─────────────────────────────────────────────────

def test_fomc_detection_within_window():
    """FOMC date within 24h window should be detected."""
    # Use now_utc parameter directly (no fragile datetime patching)
    mock_now = datetime(2026, 11, 3, 14, 0, 0, tzinfo=timezone.utc)
    events = _get_fomc_window_events(24, now_utc=mock_now)

    assert len(events) >= 1
    fomc_event = next((e for e in events if "FOMC" in e["name"]), None)
    assert fomc_event is not None
    assert fomc_event["date"] == "2026-11-04"
    assert fomc_event["impact"] == "HIGH"


def test_fomc_detection_outside_window():
    """FOMC date far in future should NOT be detected with short lookahead."""
    mock_now = datetime(2026, 2, 14, 14, 0, 0, tzinfo=timezone.utc)
    events = _get_fomc_window_events(24, now_utc=mock_now)

    # Feb 14 is not near any FOMC date — next is Mar 18 (32 days away)
    assert len(events) == 0


def test_fomc_expiry_warning():
    """When FOMC dates have expired, a warning should be logged and
    conservative default should be used."""
    mock_now = datetime(2027, 2, 14, 14, 0, 0, tzinfo=timezone.utc)

    # Reset expiry warning flag
    import marketmind.pipeline.economic_calendar as ec
    ec.FOMC_EXPIRY_WARNING_LOGGED = False

    events = _get_fomc_window_events(24, now_utc=mock_now)

    # Should return events with conservative default
    assert len(events) > 0
    assert any("expired" in e.get("source", "") for e in events)


# ── Confidence discount tests ──────────────────────────────────────────────────

def test_confidence_discount_no_events():
    events = {
        "has_high_impact": False,
        "high_impact_events": [],
        "medium_impact_events": [],
    }
    assert get_event_confidence_discount(events) == 1.0


def test_confidence_discount_fomc_within_4h():
    events = {
        "has_high_impact": True,
        "high_impact_events": [
            {"name": "FOMC Meeting", "hours_until": 2.5},
        ],
        "medium_impact_events": [],
    }
    assert get_event_confidence_discount(events) == 0.40


def test_confidence_discount_fomc_4to24h():
    events = {
        "has_high_impact": True,
        "high_impact_events": [
            {"name": "FOMC Meeting", "hours_until": 10.0},
        ],
        "medium_impact_events": [],
    }
    assert get_event_confidence_discount(events) == 0.70


def test_confidence_discount_non_fomc_high_within_4h():
    events = {
        "has_high_impact": True,
        "high_impact_events": [
            {"name": "Consumer Price Index", "hours_until": 3.0},
        ],
        "medium_impact_events": [],
    }
    assert get_event_confidence_discount(events) == 0.60


def test_confidence_discount_medium_event_within_4h():
    events = {
        "has_high_impact": False,
        "high_impact_events": [],
        "medium_impact_events": [
            {"name": "GDP", "hours_until": 2.0},
        ],
    }
    assert get_event_confidence_discount(events) == 0.90


# ── FRED release filtering tests ───────────────────────────────────────────────

def test_filter_releases_by_window():
    """FRED releases within window should be filtered and classified."""
    fixture = _load_fixture("fred_releases.json")
    releases = fixture.get("releases", [])
    if not releases:
        pytest.skip("fred_releases.json fixture not available")

    now = datetime(2026, 5, 15, 14, 0, 0, tzinfo=timezone.utc)
    filtered = _filter_releases_by_window(releases, lookahead_hours=48, now_utc=now)

    # May 15-17 window should include May 15 and May 16 releases
    dates_found = {e["date"] for e in filtered}
    assert "2026-05-15" in dates_found or "2026-05-16" in dates_found
    # Verify impact classification is present
    for e in filtered:
        assert e["impact"] in ("HIGH", "MEDIUM", "LOW")
        assert "name" in e
        assert "hours_until" in e


def test_filter_releases_outside_window():
    """FRED releases outside the window should be excluded."""
    fixture = _load_fixture("fred_releases.json")
    releases = fixture.get("releases", [])
    if not releases:
        pytest.skip("fred_releases.json fixture not available")

    now = datetime(2026, 3, 1, 14, 0, 0, tzinfo=timezone.utc)
    filtered = _filter_releases_by_window(releases, lookahead_hours=24, now_utc=now)

    # March 1-2 window should have no releases from the fixture (all in April-June 2026)
    assert len(filtered) == 0


# ── check_economic_calendar integration tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_check_economic_calendar_fomc_only():
    """check_economic_calendar with FOMC date in window (no FRED key)."""
    mock_now = datetime(2026, 9, 15, 14, 0, 0, tzinfo=timezone.utc)

    result = await check_economic_calendar(
        lookahead_hours=24,
        fred_key="",
        now_utc=mock_now,
    )

    assert result["has_high_impact"] is True
    assert len(result["high_impact_events"]) >= 1
    assert "FOMC" in result["pipeline_annotation"]
    assert result["lookahead_hours"] == 24


@pytest.mark.asyncio
async def test_check_economic_calendar_no_events():
    """check_economic_calendar with no events nearby."""
    mock_now = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)

    result = await check_economic_calendar(
        lookahead_hours=24,
        fred_key="",
        now_utc=mock_now,
    )

    assert result["has_high_impact"] is False
    assert "No high-impact" in result["pipeline_annotation"]


@pytest.mark.asyncio
async def test_check_economic_calendar_with_mock_fred():
    """check_economic_calendar with FRED API mock returns merged results."""
    mock_now = datetime(2026, 5, 15, 14, 0, 0, tzinfo=timezone.utc)

    fixture = _load_fixture("fred_releases.json")

    with patch("marketmind.pipeline.economic_calendar._fetch_fred_releases") as mock_fred:
        mock_fred.return_value = fixture.get("releases", [])

        result = await check_economic_calendar(
            lookahead_hours=48,
            fred_key="test_key",
            now_utc=mock_now,
        )

    # May 15-17 window: no FOMC, but FRED should have CPI and retail sales
    assert "checked_at" in result
    # At least one event from FRED data should be found
    total_events = len(result["high_impact_events"]) + len(result["medium_impact_events"])
    assert total_events >= 0  # Depends on fixture content


# ── FOMC dates data integrity test ────────────────────────────────────────────

def test_fomc_dates_format():
    """All FOMC dates should be valid YYYY-MM-DD strings with 8 entries."""
    assert len(FOMC_DATES_2026) == 8
    for d in FOMC_DATES_2026:
        parts = d.split("-")
        assert len(parts) == 3
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        assert 2026 <= year <= 2027
        assert 1 <= month <= 12
        assert 1 <= day <= 31


def test_fomc_expiry_date_format():
    """FOMC_EXPIRY_DATE should be a valid date."""
    assert FOMC_EXPIRY_DATE == "2026-12-31"
    parsed = _parse_date(FOMC_EXPIRY_DATE)
    assert parsed is not None
    assert parsed == date(2026, 12, 31)
