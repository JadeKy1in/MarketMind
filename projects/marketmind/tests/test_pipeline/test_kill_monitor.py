"""Tests for kill_monitor.py — kill-criteria monitoring module."""

import pytest
from datetime import datetime, timezone, timedelta

from marketmind.pipeline.kill_monitor import (
    KillCriterion,
    KillMonitorReport,
    monitor_kill_criteria,
    extract_kill_criteria,
)


# ── Helpers ───────────────────────────────────────────────────────────────────────

def _make_hypothesis_result(**kwargs):
    """Create a minimal mock HypothesisResult for extraction tests."""
    defaults = {"bear_case": "", "hypothesis": "", "refined_hypothesis": ""}
    defaults.update(kwargs)

    class MockHypothesisResult:
        pass

    obj = MockHypothesisResult()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ── KillCriterion basics ──────────────────────────────────────────────────────────

def test_kill_criterion_default_status_monitoring():
    """New criterion should default to MONITORING status."""
    kc = KillCriterion(
        criterion_id="KC-001",
        description="Test criterion",
        observable="EUR/USD drops below 1.05",
        data_source="market_data:EUR/USD",
        threshold_value=1.05,
    )
    assert kc.status == "MONITORING"


# ── monitor_kill_criteria ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_detects_threshold_crossed():
    """Price threshold crossed → TRIGGERED."""
    kc = KillCriterion(
        criterion_id="KC-001",
        description="EUR/USD below 1.05",
        observable="EUR/USD close < 1.05",
        data_source="market_data:EUR/USD",
        threshold_value=1.05,
        threshold_direction="below",
    )
    market_data = {"EUR/USD": 1.0480}
    report = await monitor_kill_criteria([kc], market_data=market_data)
    assert kc.status == "TRIGGERED"
    assert len(report.triggered) == 1
    assert report.triggered[0].criterion_id == "KC-001"
    assert kc.last_value == 1.048


@pytest.mark.asyncio
async def test_monitor_expired_deadline():
    """Past deadline + still monitoring → EXPIRED."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    kc = KillCriterion(
        criterion_id="KC-002",
        description="Check ECB statement by yesterday",
        observable="ECB drops vigilance",
        data_source="news_search:ECB",
        deadline=yesterday,
    )
    report = await monitor_kill_criteria([kc])
    assert kc.status == "EXPIRED"
    assert len(report.expired) == 1
    assert report.expired[0].criterion_id == "KC-002"


@pytest.mark.asyncio
async def test_monitor_report_requires_attention_when_triggered():
    """Any TRIGGERED → requires_attention=True."""
    kc1 = KillCriterion(
        criterion_id="KC-001",
        description="Triggered",
        observable="Price below threshold",
        data_source="market_data:EUR/USD",
        threshold_value=1.10,
        threshold_direction="below",
    )
    kc2 = KillCriterion(
        criterion_id="KC-002",
        description="Not triggered",
        observable="Price above threshold",
        data_source="market_data:EUR/USD",
        threshold_value=0.90,
        threshold_direction="below",
    )
    market_data = {"EUR/USD": 1.05}
    report = await monitor_kill_criteria([kc1, kc2], market_data=market_data)
    assert report.requires_attention is True
    assert len(report.triggered) == 1


@pytest.mark.asyncio
async def test_no_false_triggers_on_normal_data():
    """Values far from threshold should not trigger."""
    kc = KillCriterion(
        criterion_id="KC-003",
        description="EUR/USD below 1.00",
        observable="EUR/USD < 1.00",
        data_source="market_data:EUR/USD",
        threshold_value=1.00,
        threshold_direction="below",
    )
    market_data = {"EUR/USD": 1.1050}
    report = await monitor_kill_criteria([kc], market_data=market_data)
    assert kc.status == "MONITORING"
    assert len(report.triggered) == 0
    assert report.requires_attention is False


# ── extract_kill_criteria ─────────────────────────────────────────────────────────

def test_extract_numeric_threshold_from_text():
    """'EUR/USD跌破1.05' → threshold=1.05, direction='below'."""
    obj = _make_hypothesis_result(bear_case="EUR/USD跌破1.05 → 退出")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    kc = criteria[0]
    assert kc.threshold_value == 1.05
    assert kc.threshold_direction == "below"


def test_extract_deadline_from_text():
    """'6月12日' → deadline parsed correctly."""
    obj = _make_hypothesis_result(bear_case="ECB下次会议（6月12日）放弃鸽派立场 → 终止持仓")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    kc = criteria[0]
    assert kc.deadline is not None
    year = datetime.now(timezone.utc).year
    assert kc.deadline == f"{year}-06-12"


def test_extract_consequence_from_text():
    """'终止持仓' → consequence='KILL'."""
    obj = _make_hypothesis_result(bear_case="德国CPI < 2.2% → 终止持仓")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    kc = criteria[0]
    assert kc.consequence == "KILL"


# ── extract_kill_criteria edge cases ──────────────────────────────────────────────

def test_extract_from_refined_hypothesis():
    """Extraction should also search refined_hypothesis field."""
    obj = _make_hypothesis_result(
        bear_case="",
        refined_hypothesis="黄金突破2100 → 减仓50%",
    )
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    assert criteria[0].consequence == "REDUCE_50"
    assert criteria[0].threshold_value == 2100.0
    assert criteria[0].threshold_direction == "above"


def test_extract_empty_text_returns_empty():
    """Empty fields → empty list, no crash."""
    obj = _make_hypothesis_result()
    criteria = extract_kill_criteria(obj)
    assert criteria == []


def test_extract_iso_date():
    """ISO date format (2026-06-12) should be parsed."""
    obj = _make_hypothesis_result(bear_case="CPI数据（2026-06-12）低于预期 → 审查")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    assert criteria[0].deadline == "2026-06-12"
    assert criteria[0].consequence == "REVIEW"


def test_extract_forex_data_source():
    """Forex pair → market_data source."""
    obj = _make_hypothesis_result(bear_case="EUR/USD跌破1.05 → 退出")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    assert criteria[0].data_source == "market_data:EUR/USD"


def test_extract_above_direction():
    """突破 → threshold_direction='above'."""
    obj = _make_hypothesis_result(bear_case="US10Y突破5.0% → 减仓")
    criteria = extract_kill_criteria(obj)
    assert len(criteria) >= 1
    assert criteria[0].threshold_direction == "above"
    assert criteria[0].threshold_value == 5.0
    assert criteria[0].consequence == "REDUCE_50"
