"""Tests for ActivityMonitor — grade change alerts."""
from marketmind.evolution.activity_monitor import ActivityMonitor


def test_first_seen_no_alert():
    am = ActivityMonitor()
    result = am.check_and_alert("shadow_01", "green", 0.2)
    assert result is None  # First time, no alert


def test_same_grade_no_alert():
    am = ActivityMonitor()
    am.check_and_alert("shadow_01", "green", 0.2)
    result = am.check_and_alert("shadow_01", "green", 0.15)
    assert result is None  # Same grade, no alert


def test_grade_downgrade_alerts():
    am = ActivityMonitor()
    am.check_and_alert("shadow_01", "green", 0.2)
    result = am.check_and_alert("shadow_01", "yellow", 0.4)
    assert result == "yellow"


def test_grade_downgrade_to_red():
    am = ActivityMonitor()
    am.check_and_alert("shadow_01", "yellow", 0.4)
    result = am.check_and_alert("shadow_01", "red", 0.7)
    assert result == "red"


def test_recovery_alert():
    am = ActivityMonitor()
    am.check_and_alert("shadow_01", "red", 0.7)
    result = am.check_and_alert("shadow_01", "green", 0.2)
    assert result == "green"
