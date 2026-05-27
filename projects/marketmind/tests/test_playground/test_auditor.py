"""Test playground auditor and upgrade gates."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from marketmind.playground.agent_manifest import AgentManifest
from marketmind.playground.playground_auditor import (
    audit_agent,
    AuditResult,
    _check_statistical_significance,
    MIN_OBSERVATION_DAYS,
    MIN_SETTLED_CALLS,
    MIN_DIRECTION_ACCURACY,
    MIN_SHARPE,
    MAX_DRAWDOWN_BPS,
)
from marketmind.playground.playground_tracker import AgentPerformance


class FakeShadowDB:
    def __init__(self, returns: dict | None = None):
        self._returns = returns or {}

    def get_next_day_return_sign(self, ticker: str, date: str) -> int | None:
        return self._returns.get(f"{ticker}:{date}")


def test_statistical_significance():
    """Large sample with high accuracy is significant."""
    perf = AgentPerformance(
        agent_id="test", computed_at="", total_calls=50,
        settled_calls=50, correct_calls=35, direction_accuracy=0.70,
        cumulative_pnl_bps=2000, win_rate=0.70,
    )
    assert _check_statistical_significance(perf) is True


def test_statistical_significance_not_significant():
    """Small sample with marginal accuracy is not significant."""
    perf = AgentPerformance(
        agent_id="test", computed_at="", total_calls=11,
        settled_calls=11, correct_calls=7, direction_accuracy=0.636,
        cumulative_pnl_bps=200, win_rate=0.636,
    )
    assert _check_statistical_significance(perf) is False


def test_statistical_significance_insufficient_samples():
    """Too few samples to test."""
    perf = AgentPerformance(
        agent_id="test", computed_at="", total_calls=5,
        settled_calls=5, correct_calls=4, direction_accuracy=0.80,
        cumulative_pnl_bps=300, win_rate=0.80,
    )
    assert _check_statistical_significance(perf) is False


def test_statistical_significance_below_50():
    """Accuracy at or below 50% is not significant regardless of sample."""
    perf = AgentPerformance(
        agent_id="test", computed_at="", total_calls=100,
        settled_calls=100, correct_calls=48, direction_accuracy=0.48,
        cumulative_pnl_bps=-200, win_rate=0.48,
    )
    assert _check_statistical_significance(perf) is False


def _make_manifest(**kwargs) -> AgentManifest:
    defaults = {
        "agent_id": "test-agent",
        "display_name": "Test Agent",
        "description": "Test",
        "output_character": "directional call",
        "min_sample_size": 20,
        "min_observation_days": 60,
        "primary_metric": "direction_accuracy",
    }
    defaults.update(kwargs)
    return AgentManifest(**defaults)


def _setup_playground_with_decisions(calls_data: list[tuple[str, str, float, int]],
                                     agent_id: str = "test-agent") -> tuple[Path, FakeShadowDB]:
    """Create a temp playground with decision log and return (pg_dir, shadow_db).

    calls_data: list of (ticker, direction, confidence, next_day_sign)
    """
    td = tempfile.mkdtemp()
    pg_dir = Path(td)
    (pg_dir / "data").mkdir(parents=True)
    (pg_dir / "agents" / agent_id).mkdir(parents=True)

    # Write manifest
    manifest = {
        "agent_id": agent_id,
        "display_name": "Test Agent",
        "description": "Test",
        "output_character": "directional call",
        "min_sample_size": 20,
        "min_observation_days": 60,
    }
    with open(pg_dir / "agents" / agent_id / "manifest.json", "w") as f:
        json.dump(manifest, f)

    # Write decisions spanning enough days (use datetime for valid dates)
    from datetime import date as dt_date, timedelta
    returns = {}
    decisions = []
    base_date = dt_date(2026, 1, 5)  # Start from a valid date
    for i, (ticker, direction, confidence, sign) in enumerate(calls_data):
        d = base_date + timedelta(days=i * 3)  # 3 days between each call
        date_str = d.strftime("%Y-%m-%d")
        decisions.append({
            "agent_id": agent_id,
            "run_id": f"run-{i}",
            "timestamp": f"{date_str}T14:00:00Z",
            "directional_calls": [{
                "ticker": ticker, "direction": direction,
                "confidence": confidence,
            }],
        })
        returns[f"{ticker}:{date_str}"] = sign

    with open(pg_dir / "data" / "playground_decisions.jsonl", "w") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")

    return pg_dir, FakeShadowDB(returns)


def test_audit_all_gates_pass():
    """Agent with strong performance passes all gates."""
    calls = []
    # 30 correct bullish calls out of 35 settled
    for i in range(35):
        sign = 1 if i < 28 else -1  # 28 correct, 7 wrong
        calls.append(("AXTI", "bullish", 0.8, sign))

    pg_dir, db = _setup_playground_with_decisions(calls)
    manifest = _make_manifest(agent_id="test-agent")

    result = audit_agent(manifest, pg_dir, db)
    assert result.recommendation == "CANDIDATE_FOR_UPGRADE"
    assert result.all_gates_passed
    assert result.accuracy_ok
    assert result.sufficient_samples


def test_audit_insufficient_history():
    """Agent with too few observation days gets KEEP_OBSERVING."""
    calls = [
        ("AXTI", "bullish", 0.8, 1),
        ("AXTI", "bullish", 0.8, 1),
        ("AXTI", "bullish", 0.8, 1),
    ]  # only 3 calls, 2 observation days

    pg_dir, db = _setup_playground_with_decisions(calls)
    manifest = _make_manifest(agent_id="test-agent")

    result = audit_agent(manifest, pg_dir, db)
    assert result.recommendation == "KEEP_OBSERVING"
    assert not result.sufficient_history
    assert not result.sufficient_samples


def test_audit_poor_performance():
    """Agent with consistently poor accuracy."""
    calls = []
    for i in range(30):
        sign = -1 if i < 25 else 1  # 25 wrong, 5 correct → ~17% accuracy
        calls.append(("TEST", "bullish", 0.8, sign))

    pg_dir, db = _setup_playground_with_decisions(calls)
    manifest = _make_manifest(agent_id="test-agent")
    result = audit_agent(manifest, pg_dir, db)
    assert not result.all_gates_passed
    assert not result.accuracy_ok


def test_audit_result_has_integration_path():
    """Passing audit suggests integration path."""
    calls = []
    for i in range(30):
        sign = -1 if i >= 25 else 1  # 25 correct, 5 wrong → ~83% accuracy, non-zero variance
        calls.append(("AXTI", "bullish", 0.8, sign))

    pg_dir, db = _setup_playground_with_decisions(calls)
    manifest = _make_manifest(
        agent_id="test-agent",
        target_pipeline_node="decision_signal_source",
    )
    result = audit_agent(manifest, pg_dir, db)
    assert result.recommendation == "CANDIDATE_FOR_UPGRADE"
    assert result.suggested_integration == "decision_signal_source"
    assert result.suggested_weight == 0.05


def test_audit_to_dict_format():
    """Audit result can be serialized for logging."""
    result = AuditResult(
        agent_id="test",
        audit_date="2026-05-27",
        performance=None,
        recommendation="KEEP_OBSERVING",
        notes=["Test note"],
    )
    d = {
        "agent_id": result.agent_id,
        "audit_date": result.audit_date,
        "recommendation": result.recommendation,
        "notes": result.notes,
    }
    assert d["agent_id"] == "test"
    assert d["recommendation"] == "KEEP_OBSERVING"
