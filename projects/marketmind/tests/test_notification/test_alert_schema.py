"""Tests for Alert schema — dataclass, enums, dedup key."""
from marketmind.notification.alert_schema import Alert, Severity, ImpactScope


def test_alert_has_default_id():
    a = Alert(Severity.INFO, "test", ImpactScope.NONE, "title")
    assert len(a.id) == 12


def test_alert_dedup_key():
    a1 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Content empty, JSON extracted from reasoning")
    a2 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Content empty, JSON extracted from reasoning — extra text")
    assert a1.dedup_key == a2.dedup_key


def test_alert_dedup_key_different_source():
    a1 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Same title")
    a2 = Alert(Severity.WARN, "shadow_03", ImpactScope.SHADOW_SYSTEM, "Same title")
    assert a1.dedup_key != a2.dedup_key


def test_severity_enum_values():
    assert Severity.INFO.value == "INFO"
    assert Severity.WARN.value == "WARN"
    assert Severity.ERROR.value == "ERROR"
    assert Severity.CRITICAL.value == "CRITICAL"


def test_impact_scope_enum_values():
    assert ImpactScope.MAIN_PIPELINE.value == "MAIN_PIPELINE"
    assert ImpactScope.SHADOW_SYSTEM.value == "SHADOW_SYSTEM"
    assert ImpactScope.INFRASTRUCTURE.value == "INFRASTRUCTURE"
    assert ImpactScope.NONE.value == "NONE"
