"""Test pipeline metrics recording."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from marketmind.pipeline.pipeline_metrics import (
    PipelineMetrics, record_metrics, load_recent_metrics,
    collect_metrics_from_session,
)


def test_pipeline_metrics_to_dict():
    m = PipelineMetrics(date="2026-05-27", run_mode="daily", mock=False)
    d = m.to_dict()
    assert d["date"] == "2026-05-27"
    assert d["run_mode"] == "daily"
    assert "flash_total_scored" in d
    assert "l1_grade" in d


def test_collect_from_session_empty():
    """Empty session produces zero-filled metrics."""
    m = collect_metrics_from_session()
    assert m.date
    assert m.flash_total_scored == 0
    assert m.l1_grade == ""


def test_collect_from_session_with_l1():
    """L1 result fields are extracted correctly."""

    class FakeL1:
        event_grade = "A"
        matrix_quadrant = "buy_high_confidence"
        sentiment_direction = "bullish"
        price_in_score = 0.75

    m = collect_metrics_from_session(l1_result=FakeL1())
    assert m.l1_grade == "A"
    assert m.l1_quadrant == "buy_high_confidence"
    assert m.l1_direction == "bullish"
    assert m.l1_price_in == 0.75


def test_collect_from_session_with_decision():
    class FakeCard:
        ticker = "AXTI"
        direction = "bullish"

    class FakeDecision:
        decision_cards = [FakeCard(), FakeCard()]
        no_trade_card = None

    m = collect_metrics_from_session(decision=FakeDecision())
    assert m.decision_cards == 2
    assert not m.decision_no_trade


def test_collect_from_session_with_no_trade():
    class FakeDecision:
        decision_cards = []
        no_trade_card = "present"

    m = collect_metrics_from_session(decision=FakeDecision())
    assert m.decision_cards == 0
    assert m.decision_no_trade


def test_collect_from_session_with_red_team():
    class FakeChallenge:
        severity = "high"

    class FakeRedTeam:
        challenges = [FakeChallenge(), FakeChallenge()]

    m = collect_metrics_from_session(red_team_report=FakeRedTeam())
    assert m.red_team_challenges == 2
    assert m.red_team_severe == 2


def test_collect_from_session_with_resonance():
    class FakeResonance:
        dsr = 0.85
        pbo = 0.03
        passed = True
        verdict = "signal_validated"

    m = collect_metrics_from_session(resonance=FakeResonance())
    assert m.resonance_dsr == 0.85
    assert m.resonance_pbo == 0.03
    assert m.resonance_passed
    assert m.resonance_verdict == "signal_validated"


def test_record_and_load_metrics():
    """Record metrics and load them back."""
    m = PipelineMetrics(
        date="2026-05-27", run_mode="daily",
        flash_total_scored=100, flash_high_impact=15,
        l1_grade="B", l2_ticker_candidates=5,
    )
    # We need to monkey-patch the metrics dir to use a temp dir
    import marketmind.pipeline.pipeline_metrics as pm
    with tempfile.TemporaryDirectory() as td:
        metrics_dir = Path(td)
        orig = pm._metrics_dir
        pm._metrics_dir = lambda: metrics_dir
        try:
            record_metrics(m)
            loaded = load_recent_metrics(days=7)
            assert len(loaded) == 1
            assert loaded[0]["date"] == "2026-05-27"
            assert loaded[0]["flash_total_scored"] == 100
        finally:
            pm._metrics_dir = orig
