"""Tests for fragility scanner — pure computation, zero LLM calls."""

from datetime import datetime, timedelta, timezone

import pytest

from marketmind.config.fragility_thresholds import (
    FragilityThreshold,
    THRESHOLD_LIBRARY,
    validate_thresholds,
)
from marketmind.pipeline.fragility_scanner import (
    FragilityAlert,
    FragilityReport,
    _compute_distance,
    _classify_alert,
    _compute_fragility_score,
    scan_fragility,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_threshold(
    metric: str = "bank_reserves",
    threshold_value: float = 2.7,
    direction: str = "below",
    is_active: bool = True,
    last_validated: str | None = None,
) -> FragilityThreshold:
    if last_validated is None:
        last_validated = datetime.now(timezone.utc).isoformat()
    return FragilityThreshold(
        metric=metric,
        name_zh=metric,
        threshold_value=threshold_value,
        unit="USD_trillion",
        direction=direction,
        mechanism="test mechanism",
        cascade=["cascade_1"],
        data_source="TEST:source",
        last_validated=last_validated,
        source_document="test doc",
        is_active=is_active,
    )


# ── Tests: _compute_distance ────────────────────────────────────────────────

def test_distance_below_safe():
    """Value at 2.9T, threshold 2.7T, direction=below → ~7.4% distance (safe)."""
    dist = _compute_distance(2.9, 2.7, "below")
    assert dist == pytest.approx(7.41, rel=0.1)


def test_distance_below_crossed():
    """Value at 2.5T, threshold 2.7T, direction=below → negative (crossed)."""
    dist = _compute_distance(2.5, 2.7, "below")
    assert dist < 0
    assert dist == pytest.approx(-7.41, rel=0.1)


def test_distance_above_safe():
    """Value at 4.3%, threshold 4.5%, direction=above → positive (safe)."""
    dist = _compute_distance(4.3, 4.5, "above")
    assert dist > 0
    assert dist == pytest.approx(4.44, rel=0.1)


def test_distance_above_crossed():
    """Value at 4.8%, threshold 4.5%, direction=above → negative (crossed)."""
    dist = _compute_distance(4.8, 4.5, "above")
    assert dist < 0
    assert dist == pytest.approx(-6.67, rel=0.1)


def test_distance_at_threshold():
    """Value equals threshold → 0.0 distance."""
    assert _compute_distance(2.7, 2.7, "below") == 0.0
    assert _compute_distance(4.5, 4.5, "above") == 0.0


def test_distance_zero_threshold():
    """Zero threshold should return 0.0 to avoid division by zero."""
    assert _compute_distance(5.0, 0.0, "above") == 0.0


# ── Tests: _classify_alert ──────────────────────────────────────────────────

def test_classify_crossed():
    assert _classify_alert(-1.0) == ("CRITICAL", True)
    assert _classify_alert(-20.0) == ("CRITICAL", True)


def test_classify_warning():
    assert _classify_alert(0.0) == ("WARNING", False)
    assert _classify_alert(2.5) == ("WARNING", False)
    assert _classify_alert(4.99) == ("WARNING", False)


def test_classify_monitor():
    assert _classify_alert(5.0) == ("MONITOR", False)
    assert _classify_alert(10.0) == ("MONITOR", False)
    assert _classify_alert(14.99) == ("MONITOR", False)


def test_classify_clear():
    assert _classify_alert(15.0) == ("CLEAR", False)
    assert _classify_alert(50.0) == ("CLEAR", False)


# ── Tests: _compute_fragility_score ─────────────────────────────────────────

def test_score_zero_when_all_clear():
    alerts = [
        FragilityAlert(
            threshold=_make_threshold("a"), current_value=3.0,
            distance_pct=20.0, crossed=False, severity="CLEAR",
        ),
        FragilityAlert(
            threshold=_make_threshold("b"), current_value=3.0,
            distance_pct=20.0, crossed=False, severity="CLEAR",
        ),
    ]
    assert _compute_fragility_score(alerts) == 0.0


def test_score_one_when_all_crossed():
    alerts = [
        FragilityAlert(
            threshold=_make_threshold("a"), current_value=2.0,
            distance_pct=-10.0, crossed=True, severity="CRITICAL",
        ),
        FragilityAlert(
            threshold=_make_threshold("b"), current_value=2.0,
            distance_pct=-10.0, crossed=True, severity="CRITICAL",
        ),
    ]
    assert _compute_fragility_score(alerts) == 1.0


def test_score_mixed():
    alerts = [
        FragilityAlert(
            threshold=_make_threshold("a"), current_value=2.0,
            distance_pct=-10.0, crossed=True, severity="CRITICAL",
        ),
        FragilityAlert(
            threshold=_make_threshold("b"), current_value=3.0,
            distance_pct=2.0, crossed=False, severity="WARNING",
        ),
        FragilityAlert(
            threshold=_make_threshold("c"), current_value=3.0,
            distance_pct=20.0, crossed=False, severity="CLEAR",
        ),
    ]
    # (1.0 + 0.5 + 0.0) / 3 = 0.5
    assert _compute_fragility_score(alerts) == 0.5


def test_score_empty_alerts():
    assert _compute_fragility_score([]) == 0.0


# ── Tests: validate_thresholds ──────────────────────────────────────────────

def test_staleness_warning(monkeypatch):
    """Threshold with last_validated >90 days ago → warning."""
    from marketmind.config import fragility_thresholds as ft

    old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    original_library = ft.THRESHOLD_LIBRARY
    stale_threshold = _make_threshold(
        metric="test_stale", last_validated=old_date,
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [stale_threshold])
    try:
        warnings = validate_thresholds()
        assert any("STALE" in w for w in warnings)
        assert any("120" in w for w in warnings)
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


def test_all_stale_critical_warning(monkeypatch):
    """When all thresholds are stale, a CRITICAL message is added."""
    from marketmind.config import fragility_thresholds as ft

    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    original_library = ft.THRESHOLD_LIBRARY
    stale_thresholds = [
        _make_threshold(metric=f"stale_{i}", last_validated=old_date)
        for i in range(3)
    ]
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", stale_thresholds)
    try:
        warnings = validate_thresholds()
        assert any("CRITICAL" in w and "ALL" in w for w in warnings)
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


def test_invalid_date_warning(monkeypatch):
    """Unparseable last_validated → INVALID_DATE warning."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    bad_threshold = _make_threshold(
        metric="test_bad_date", last_validated="not-a-date",
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [bad_threshold])
    try:
        warnings = validate_thresholds()
        assert any("INVALID_DATE" in w for w in warnings)
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


# ── Tests: scan_fragility (integration) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_threshold_crossed_detection(monkeypatch):
    """Bank reserves at 2.5T with 2.7T 'below' threshold → crossed."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    threshold = _make_threshold(
        metric="bank_reserves", threshold_value=2.7, direction="below",
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [threshold])
    try:
        report = await scan_fragility({"bank_reserves": 2.5})
        assert len(report.crossed) == 1
        assert report.crossed[0].crossed is True
        assert report.crossed[0].severity == "CRITICAL"
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_overall_score_zero_when_all_clear(monkeypatch):
    """All values far from thresholds → score near 0."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    thresholds = [
        _make_threshold(metric="bank_reserves", threshold_value=2.7, direction="below"),
        _make_threshold(metric="us10y_yield", threshold_value=4.5, direction="above"),
    ]
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", thresholds)
    try:
        report = await scan_fragility({
            "bank_reserves": 3.5,   # far above 2.7 → safe
            "us10y_yield": 3.5,     # far below 4.5 → safe
        })
        assert report.overall_fragility_score == 0.0
        assert len(report.crossed) == 0
        assert len(report.warnings) == 0
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_overall_score_high_when_multiple_crossed(monkeypatch):
    """Multiple thresholds crossed → score near 1."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    thresholds = [
        _make_threshold(metric="bank_reserves", threshold_value=2.7, direction="below"),
        _make_threshold(metric="us10y_yield", threshold_value=4.5, direction="above"),
        _make_threshold(metric="vix", threshold_value=35, direction="above"),
    ]
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", thresholds)
    try:
        report = await scan_fragility({
            "bank_reserves": 2.3,   # crossed (below 2.7)
            "us10y_yield": 4.8,     # crossed (above 4.5)
            "vix": 40,              # crossed (above 35)
        })
        assert report.overall_fragility_score == 1.0
        assert len(report.crossed) == 3
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_missing_market_data_skipped(monkeypatch):
    """Metrics not in market_data are skipped gracefully."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    thresholds = [
        _make_threshold(metric="bank_reserves", threshold_value=2.7, direction="below"),
        _make_threshold(metric="vix", threshold_value=35, direction="above"),
    ]
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", thresholds)
    try:
        report = await scan_fragility({"bank_reserves": 3.0})
        assert len(report.alerts) == 1
        assert report.alerts[0].threshold.metric == "bank_reserves"
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_inactive_threshold_skipped(monkeypatch):
    """Inactive thresholds should not produce alerts."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    threshold = _make_threshold(
        metric="bank_reserves", threshold_value=2.7,
        direction="below", is_active=False,
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [threshold])
    try:
        report = await scan_fragility({"bank_reserves": 2.5})
        assert len(report.alerts) == 0 or all(not a.crossed for a in report.alerts)
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_staleness_warnings_in_report(monkeypatch):
    """Staleness warnings are included in the report."""
    from marketmind.config import fragility_thresholds as ft

    old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    original_library = ft.THRESHOLD_LIBRARY
    threshold = _make_threshold(
        metric="bank_reserves", threshold_value=2.7,
        direction="below", last_validated=old_date,
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [threshold])
    try:
        report = await scan_fragility({"bank_reserves": 3.0})
        assert len(report.staleness_warnings) >= 1
        assert any("STALE" in w for w in report.staleness_warnings)
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_summary_reflects_state(monkeypatch):
    """Summary string matches report state."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    thresholds = [
        _make_threshold(metric="bank_reserves", threshold_value=2.7, direction="below"),
        _make_threshold(metric="vix", threshold_value=35, direction="above"),
    ]
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", thresholds)
    try:
        report = await scan_fragility({
            "bank_reserves": 2.5,  # crossed
            "vix": 30,             # safe
        })
        assert "CRITICAL" in report.summary
        assert "1 CRITICAL" in report.summary
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_empty_market_data(monkeypatch):
    """Empty market_data → no alerts, staleness warnings still checked."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    threshold = _make_threshold(
        metric="bank_reserves", threshold_value=2.7, direction="below",
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [threshold])
    try:
        report = await scan_fragility({})
        assert len(report.alerts) == 0 or all(not a.crossed for a in report.alerts)
        assert report.overall_fragility_score == 0.0
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)


@pytest.mark.asyncio
async def test_warning_severity_near_threshold(monkeypatch):
    """Value within 5% of threshold → WARNING severity, not crossed."""
    from marketmind.config import fragility_thresholds as ft

    original_library = ft.THRESHOLD_LIBRARY
    threshold = _make_threshold(
        metric="bank_reserves", threshold_value=2.7, direction="below",
    )
    monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", [threshold])
    try:
        report = await scan_fragility({"bank_reserves": 2.75})  # ~1.85% from threshold
        assert len(report.alerts) == 1
        assert report.alerts[0].severity == "WARNING"
        assert report.alerts[0].crossed is False
        assert len(report.warnings) == 1
    finally:
        monkeypatch.setattr(ft, "THRESHOLD_LIBRARY", original_library)
