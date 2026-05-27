"""Test playground performance tracker."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from marketmind.playground.playground_tracker import (
    settle_calls,
    compute_agent_performance,
    _compute_sharpe,
    _compute_max_drawdown,
    _compute_profit_factor,
    record_performance,
    load_performance_history,
    AgentPerformance,
)


def _make_decisions(agent_id: str, calls: list[dict]) -> list[dict]:
    """Helper to build decision records for testing."""
    decisions = []
    for i, call in enumerate(calls):
        decisions.append({
            "agent_id": agent_id,
            "run_id": f"test-run-{i}",
            "timestamp": f"2026-05-{20+i:02d}T14:00:00Z",
            "directional_calls": [call],
            "output": {},
        })
    return decisions


class FakeShadowDB:
    """Fake shadow DB that returns predetermined return signs."""
    def __init__(self, returns: dict | None = None):
        self._returns = returns or {}

    def get_next_day_return_sign(self, ticker: str, date: str) -> int | None:
        key = f"{ticker}:{date}"
        return self._returns.get(key)


def test_settle_calls_correct_bullish():
    """Settles a correct bullish call."""
    db = FakeShadowDB({"AXTI:2026-05-20": 1})  # positive return
    decisions = _make_decisions("test", [
        {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8},
    ])
    settled = settle_calls(decisions, db)
    assert len(settled) == 1
    assert settled[0].correct is True
    assert settled[0].pnl_bps == 80  # 100 * 0.8


def test_settle_calls_wrong_bullish():
    """Settles an incorrect bullish call."""
    db = FakeShadowDB({"AXTI:2026-05-20": -1})  # negative return
    decisions = _make_decisions("test", [
        {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8},
    ])
    settled = settle_calls(decisions, db)
    assert settled[0].correct is False
    assert settled[0].pnl_bps == -80


def test_settle_calls_correct_bearish():
    """Settles a correct bearish call."""
    db = FakeShadowDB({"AXTI:2026-05-20": -1})  # negative return
    decisions = _make_decisions("test", [
        {"ticker": "AXTI", "direction": "bearish", "confidence": 0.7},
    ])
    settled = settle_calls(decisions, db)
    assert settled[0].correct is True


def test_settle_calls_neutral_skipped():
    """Neutral calls are skipped in settlement."""
    db = FakeShadowDB({})
    decisions = _make_decisions("test", [
        {"ticker": "AXTI", "direction": "neutral", "confidence": 0.5},
    ])
    settled = settle_calls(decisions, db)
    assert len(settled) == 0


def test_settle_calls_no_shadow_db():
    """Settlement without shadow DB produces None correct values."""
    decisions = _make_decisions("test", [
        {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8},
    ])
    settled = settle_calls(decisions, None)
    assert len(settled) == 1
    assert settled[0].correct is None


def test_settle_calls_no_directional_calls():
    """Decisions without directional calls produce no settled calls."""
    decisions = [{
        "agent_id": "test",
        "run_id": "test-0",
        "timestamp": "2026-05-20T14:00:00Z",
        "directional_calls": [],
        "output": {"some_other_output": "value"},
    }]
    settled = settle_calls(decisions, None)
    assert len(settled) == 0


def test_compute_sharpe():
    """Computes annualized Sharpe ratio from PnL series."""
    # Consistent positive returns with slight variation -> high Sharpe
    good = [10.0, 12.0, 9.0, 11.0, 10.0, 13.0, 8.0, 12.0, 10.0, 11.0,
            9.0, 14.0, 10.0, 8.0, 12.0, 11.0, 9.0, 13.0, 10.0, 12.0]
    sharpe_good = _compute_sharpe(good)
    assert sharpe_good is not None
    assert sharpe_good > 0

    # Mixed returns -> lower Sharpe
    mixed = [15.0, -12.0, 12.0, -10.0, 10.0, -15.0, 13.0, -8.0, 11.0, -14.0,
             9.0, -11.0, 14.0, -9.0, 8.0, -13.0, 10.0, -10.0, 12.0, -12.0]
    sharpe_mixed = _compute_sharpe(mixed)
    assert sharpe_mixed is not None
    assert abs(sharpe_mixed) < abs(sharpe_good)


def test_compute_sharpe_insufficient_data():
    """Returns None with too few data points."""
    assert _compute_sharpe([10.0]) is None
    assert _compute_sharpe([]) is None


def test_compute_max_drawdown():
    """Computes maximum drawdown from PnL series."""
    pnl = [10, 10, -30, 10, 10]  # peak=20, trough=-10, dd=30
    dd = _compute_max_drawdown(pnl)
    assert dd == 30


def test_compute_max_drawdown_empty():
    assert _compute_max_drawdown([]) == 0.0


def test_compute_profit_factor():
    """Ratio of gross profit to gross loss."""
    pnl = [10, 10, -5, 10, -5]  # profit=30, loss=10, pf=3.0
    pf = _compute_profit_factor(pnl)
    assert pf == 3.0


def test_compute_profit_factor_no_losses():
    pf = _compute_profit_factor([10, 10, 10])
    assert pf == float('inf')


def test_compute_agent_performance():
    """Computes full performance record."""
    db = FakeShadowDB({
        "AXTI:2026-05-20": 1,
        "TEST:2026-05-21": -1,
        "CHIP:2026-05-22": 1,
    })
    with tempfile.TemporaryDirectory() as td:
        pg_dir = Path(td)
        (pg_dir / "data").mkdir()
        # Write some decisions
        decisions = _make_decisions("serenity_reply", [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8},  # correct
            {"ticker": "TEST", "direction": "bullish", "confidence": 0.7},  # wrong
            {"ticker": "CHIP", "direction": "bullish", "confidence": 0.9},  # correct
        ])
        from marketmind.playground.playground_tracker import _load_decisions
        log_path = pg_dir / "data" / "playground_decisions.jsonl"
        with open(log_path, "w") as f:
            for d in decisions:
                f.write(json.dumps(d) + "\n")

        perf = compute_agent_performance("serenity_reply", pg_dir, db)
        assert perf.total_calls == 3
        assert perf.settled_calls == 3
        assert perf.correct_calls == 2
        assert perf.direction_accuracy == 2/3


def test_record_and_load_performance():
    """Records and loads performance history."""
    with tempfile.TemporaryDirectory() as td:
        pg_dir = Path(td)
        (pg_dir / "data").mkdir()

        perf = AgentPerformance(
            agent_id="test",
            computed_at=datetime.now(timezone.utc).isoformat(),
            total_calls=10,
            settled_calls=10,
            correct_calls=7,
            direction_accuracy=0.7,
            cumulative_pnl_bps=500,
            win_rate=0.7,
            sharpe_ratio=1.2,
            max_drawdown_bps=300,
            observation_days=45,
            first_call_date="2026-05-01",
            last_call_date="2026-05-20",
        )
        record_performance(perf, pg_dir)

        history = load_performance_history("test", pg_dir)
        assert len(history) == 1
        assert history[0]["agent_id"] == "test"
        assert history[0]["direction_accuracy"] == 0.7
        assert history[0]["sharpe_ratio"] == 1.2
