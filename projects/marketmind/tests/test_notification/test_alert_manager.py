"""Tests for AlertManager — emit, dedup, rate-limit, escalation."""
from marketmind.notification.alert_schema import Alert, Severity, ImpactScope
from marketmind.notification.alert_manager import AlertManager


def test_emit_adds_alert():
    am = AlertManager()
    am.emit(Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
                   "Test alert", "detail here"))
    recent = am.recent()
    assert len(recent) >= 1
    assert recent[-1]["title"] == "Test alert"


def test_dedup_suppresses_duplicate():
    am = AlertManager()
    a1 = Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
               "Repeated message that is more than forty chars long for matching")
    a2 = Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
               "Repeated message that is more than forty chars long for matching — diff suffix")
    am.emit(a1)
    am.emit(a2)
    recent = am.recent()
    matches = [a for a in recent if "Repeated" in a.get("title", "")]
    assert len(matches) == 1
    assert matches[0]["repeat_count"] == 2


def test_different_severity_not_deduped():
    am = AlertManager()
    am.emit(Alert(Severity.WARN, "src", ImpactScope.MAIN_PIPELINE, "Title text"))
    am.emit(Alert(Severity.ERROR, "src", ImpactScope.MAIN_PIPELINE, "Title text"))
    assert len(am.recent()) >= 2


def test_frequency_escalation():
    am = AlertManager()
    for _ in range(6):
        am.emit(Alert(Severity.WARN, "src", ImpactScope.MAIN_PIPELINE,
                       "Repeated warning message for escalation test"))
    recent = am.recent()
    errors = [a for a in recent if a.get("severity") == "ERROR" and "[ESCALATED]" in a.get("title", "")]
    assert len(errors) == 1


def test_alert_eviction():
    am = AlertManager()
    for i in range(250):
        am.emit(Alert(Severity.INFO, f"src_{i}", ImpactScope.NONE, f"Info alert {i}"))
    assert len(am._alerts) <= 200
