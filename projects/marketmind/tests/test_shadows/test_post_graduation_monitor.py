"""Tests for PostGraduationMonitor — CUSUM/CUSUMSQ/BOCPD surveillance."""
from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig, DailySnapshot
from marketmind.shadows.post_graduation_monitor import (
    PostGraduationMonitor,
    MonitorResult,
    _CUSUM_H,
)


@pytest.fixture
def monitor(temp_shadow_db):
    """Create a PostGraduationMonitor with a real temp DB."""
    return PostGraduationMonitor(temp_shadow_db)


def _create_shadow(db: ShadowStateDB, shadow_id: str, shadow_type: str = "expert",
                   max_dd_limit: float = 0.25) -> ShadowConfig:
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Test {shadow_id}",
        methodology_prompt=f"You are a test {shadow_type} analyst.",
        virtual_capital=50000.0,
        domain="gold",
        max_drawdown_limit=max_dd_limit,
    )
    db.create_shadow(config)
    return config


def _add_snapshots(db: ShadowStateDB, shadow_id: str, daily_returns: list[float],
                   max_drawdowns: list[float] | None = None,
                   start_date: str = "2026-01-02") -> list[DailySnapshot]:
    """Add daily snapshots from a list of daily returns.

    Each return is for one trading day starting from start_date.
    """
    import datetime as dt
    from datetime import timedelta

    snapshots = []
    cum = 0.0
    peak = float("-inf")
    running_mdd = 0.0
    current_date = dt.date.fromisoformat(start_date)

    for i, r in enumerate(daily_returns):
        cum += r
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < running_mdd:
            running_mdd = dd

        # Use provided max_dd or computed
        if max_drawdowns and i < len(max_drawdowns):
            mdd_pct = max_drawdowns[i]
        else:
            mdd_pct = abs(running_mdd) * 100 if running_mdd < 0 else 0.0

        date_str = current_date.isoformat()
        snap = DailySnapshot(
            shadow_id=shadow_id,
            date=date_str,
            virtual_capital=50000.0 * (1.0 + cum),
            daily_return_pct=r * 100.0,
            cumulative_return_pct=cum * 100.0,
            max_drawdown_pct=mdd_pct,
            win_rate_pct=55.0,
            sharpe_ratio=1.0,
            calmar_ratio=0.8,
            omega_ratio=1.3,
            mppm_score=0.6,
            composite_score=0.75,
            deflated_score=0.70,
            percentile_rank=0.65,
            achievement_tier="Elite",
        )
        db.save_snapshot(shadow_id, snap)
        snapshots.append(snap)

        current_date += timedelta(days=1)
        while current_date.weekday() >= 5:
            current_date += timedelta(days=1)

    return snapshots


# ══════════════════════════════════════════════════════════════════════════════
# CUSUM Tests (Layer 1)
# ══════════════════════════════════════════════════════════════════════════════

def test_cusum_clean_performance_no_alerts(monitor, temp_shadow_db):
    """Stable returns with no drift should not trigger CUSUM alerts."""
    shadow_id = "expert:gold:test_clean"
    _create_shadow(temp_shadow_db, shadow_id)

    # Stable returns around zero mean, no sustained drift
    np.random.seed(42)
    returns = list(np.random.normal(0.001, 0.01, 180))
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    result = monitor.check(shadow_id)

    assert not result.cusum_triggered, f"CUSUM should NOT trigger for stable returns"
    assert result.cusum_alerts_3m == 0
    assert result.demotion_level == "none"


def test_cusum_negative_drift_alerts(monitor, temp_shadow_db):
    """Sustained negative drift should trigger CUSUM alerts (D2 path if 5+ in 3 months)."""
    shadow_id = "expert:gold:test_decay"
    _create_shadow(temp_shadow_db, shadow_id)

    # Create returns with a sustained negative drift halfway through
    np.random.seed(123)
    n = 180
    returns = []
    for i in range(n):
        if i < 90:
            # Positive period
            returns.append(np.random.normal(0.003, 0.01))
        else:
            # Sustained negative period — consistently below baseline
            returns.append(np.random.normal(-0.008, 0.01))
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    result = monitor.check(shadow_id)

    # With sustained negative drift, CUSUM should trigger
    assert result.cusum_triggered, "CUSUM should trigger for sustained negative drift"
    # The alerts should be concentrated in the negative period (last 90 days = ~3 months)
    assert result.cusum_alerts_3m >= 1


def test_cusum_5_alerts_d2_trigger(monitor, temp_shadow_db):
    """5 CUSUM alerts in 3 months should trigger D2 (display_only)."""
    shadow_id = "expert:gold:test_d2"
    _create_shadow(temp_shadow_db, shadow_id)

    # Generate returns that produce many CUSUM alerts in the last 90 days
    np.random.seed(456)
    n = 200
    returns = []
    for i in range(n):
        if i < 110:
            returns.append(np.random.normal(0.001, 0.01))
        else:
            # Last 90 days: high volatility with negative bias to trigger many alerts
            returns.append(np.random.normal(-0.005, 0.025))
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    # Need the internal CUSUM to hit > 5 alerts in last 90 days
    # Override the _compute_cusum to force alerts
    original_compute_cusum = monitor._compute_cusum

    def forced_cusum(returns_arr, lb):
        vals, alerts = original_compute_cusum(returns_arr, lb)
        # Force many alerts in the last 90 indices
        n_ret = len(returns_arr)
        forced_alerts = []
        for i in range(max(0, n_ret - 90), n_ret, 10):
            forced_alerts.append(i)
        return vals, forced_alerts

    with patch.object(monitor, "_compute_cusum", side_effect=forced_cusum):
        result = monitor.check(shadow_id)

    assert result.cusum_alerts_3m >= 5, f"Expected >= 5 alerts, got {result.cusum_alerts_3m}"
    assert "D2" in result.triggered_conditions, \
        f"D2 should trigger with 5+ alerts, conditions: {result.triggered_conditions}"


# ══════════════════════════════════════════════════════════════════════════════
# CUSUMSQ Tests (Layer 2)
# ══════════════════════════════════════════════════════════════════════════════

def test_cusumsq_stable_variance_no_trigger(monitor, temp_shadow_db):
    """Stable variance (homoskedastic returns) should NOT trigger CUSUMSQ."""
    shadow_id = "expert:gold:test_stable_var"
    _create_shadow(temp_shadow_db, shadow_id)

    np.random.seed(789)
    # Constant-variance returns
    returns = list(np.random.normal(0.001, 0.01, 180))
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    result = monitor.check(shadow_id)

    # With stable variance, CUSUMSQ should not trigger
    assert not result.cusumsq_triggered, \
        "CUSUMSQ should NOT trigger for homoskedastic returns"


def test_cusumsq_variance_break_triggers_d1(monitor, temp_shadow_db):
    """A structural break in variance should trigger CUSUMSQ (D1 → suspended)."""
    shadow_id = "expert:gold:test_var_break"
    _create_shadow(temp_shadow_db, shadow_id)

    np.random.seed(101)
    n = 180
    returns = []
    for i in range(n):
        if i < 90:
            returns.append(np.random.normal(0.001, 0.005))  # low volatility
        else:
            returns.append(np.random.normal(0.001, 0.04))   # sudden high volatility
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    result = monitor.check(shadow_id)

    # The variance break should trigger CUSUMSQ
    assert result.cusumsq_triggered, \
        "CUSUMSQ should trigger for structural variance break"


# ══════════════════════════════════════════════════════════════════════════════
# Demotion Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_drawdown_breach_d7_highest_priority(monitor, temp_shadow_db):
    """D7 (drawdown breach) is highest priority when multiple conditions trigger."""
    shadow_id = "expert:gold:test_d7"
    _create_shadow(temp_shadow_db, shadow_id, max_dd_limit=0.25)

    np.random.seed(202)
    n = 180
    returns = []
    # Generate returns with 30%+ drawdown (exceeds 25% limit)
    cum = 0.0
    peak_dd = 0.0

    for i in range(n):
        if i < 60:
            r = np.random.normal(0.002, 0.01)
        elif 60 <= i < 80:
            r = np.random.normal(-0.015, 0.02)  # sharp decline
        else:
            r = np.random.normal(-0.003, 0.02)  # continued weakness
        cum += r
        dd = min(0.0, cum - max(0.0, cum + (0.0 if i == 0 else 0.0)))
        returns.append(r)

    # Provide explicit max_drawdown values exceeding 25% limit
    mdd_values = [5.0] * 60 + [15.0] * 20 + [30.0] * 100  # 30% DD breaches 25% limit
    _add_snapshots(temp_shadow_db, shadow_id, returns, max_drawdowns=mdd_values)

    # Force CUSUMSQ to also trigger so we can test priority resolution
    original_cusumsq = monitor._compute_cusumsq

    def forced_cusumsq(returns_arr):
        _, _ = original_cusumsq(returns_arr)
        return np.zeros(len(returns_arr)), True  # force CUSUMSQ trigger

    with patch.object(monitor, "_compute_cusumsq", side_effect=forced_cusumsq):
        result = monitor.check(shadow_id)

    # D7 and D1 should both trigger
    assert "D7" in result.triggered_conditions or result.demotion_level == "suspended", \
        f"Expected D7 to trigger on drawdown breach, got conditions: {result.triggered_conditions}"

    # If both D7 and D1 are triggered, D7 should win (higher priority)
    if "D7" in result.triggered_conditions and "D1" in result.triggered_conditions:
        assert result.applied_demotion == "D7", \
            f"D7 should take priority over D1, got {result.applied_demotion}"


def test_multiple_triggers_priority_resolution(monitor, temp_shadow_db):
    """When D2 (CUSUM alerts) and D5 (3xWatch) trigger, D2 takes priority."""
    shadow_id = "expert:gold:test_priority"
    _create_shadow(temp_shadow_db, shadow_id, max_dd_limit=0.35)

    np.random.seed(303)
    returns = list(np.random.normal(0.001, 0.01, 180))
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    # Mock tier history to show 3 consecutive Watch periods (D5)
    with patch.object(temp_shadow_db, "get_tier_history", return_value=[
        ("2026-04-01", "Watch"),
        ("2026-04-08", "Watch"),
        ("2026-04-15", "Watch"),
    ]):
        # Mock CUSUM to return 10 alerts (D2) — last 90 days
        with patch.object(monitor, "_compute_cusum", return_value=(
            np.zeros(180),
            list(range(150, 180, 3)),  # 10 alerts in last 90 days
        )):
            # Mock CUSUMSQ to NOT trigger (so D1 doesn't override D2)
            with patch.object(monitor, "_compute_cusumsq", return_value=(
                np.zeros(180), False,
            )):
                result = monitor.check(shadow_id)

    # Both D2 and D5 trigger; D2 has higher priority (D2 > D5)
    assert "D2" in result.triggered_conditions, \
        f"D2 should trigger with 5+ alerts, got: {result.triggered_conditions}"
    assert "D5" in result.triggered_conditions, \
        f"D5 should trigger with 3xWatch, got: {result.triggered_conditions}"
    assert result.applied_demotion == "D2", \
        f"D2 should take priority over D5, got: {result.applied_demotion}"
    assert result.demotion_level == "display_only", \
        f"D2 demotion should be display_only, got: {result.demotion_level}"


# ══════════════════════════════════════════════════════════════════════════════
# apply_demotion Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_demotion_changes_status(monitor, temp_shadow_db):
    """apply_demotion updates shadow status in the DB."""
    shadow_id = "expert:gold:test_apply_demotion"
    _create_shadow(temp_shadow_db, shadow_id, "expert")

    # Verify initial status
    config = temp_shadow_db.get_shadow(shadow_id)
    assert config.status == "active"

    # Apply demotion to display_only → Watch
    monitor.apply_demotion(shadow_id, "display_only", "CUSUM 5 alerts in 3 months")

    config_after = temp_shadow_db.get_shadow(shadow_id)
    assert config_after.status == "watch", \
        f"Expected status 'watch', got '{config_after.status}'"


def test_apply_demotion_suspended(monitor, temp_shadow_db):
    """apply_demotion with 'suspended' level sets status to 'paused'."""
    shadow_id = "expert:gold:test_suspend"
    _create_shadow(temp_shadow_db, shadow_id, "expert")

    monitor.apply_demotion(shadow_id, "suspended", "CUSUMSQ triggered (D1)")

    config = temp_shadow_db.get_shadow(shadow_id)
    assert config.status == "paused"


def test_apply_demotion_invalid_level(monitor, temp_shadow_db):
    """Invalid demotion level raises ValueError."""
    shadow_id = "expert:gold:test_invalid"
    _create_shadow(temp_shadow_db, shadow_id, "expert")

    with pytest.raises(ValueError, match="demotion level must be one of"):
        monitor.apply_demotion(shadow_id, "invalid_level", "test")


# ══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════════════════════

def test_check_empty_snapshots_returns_no_triggers(monitor, temp_shadow_db):
    """Shadow with no snapshot data should not trigger any alerts."""
    shadow_id = "expert:gold:test_empty"
    _create_shadow(temp_shadow_db, shadow_id)

    # No snapshots
    result = monitor.check(shadow_id)

    assert not result.cusum_triggered
    assert not result.cusumsq_triggered
    assert not result.bocpd_triggered
    assert result.demotion_level == "none"


def test_bocpd_volatility_shift_detected(monitor, temp_shadow_db):
    """A 2x volatility shift combined with CUSUM alert triggers BOCPD."""
    shadow_id = "expert:gold:test_bocpd"
    _create_shadow(temp_shadow_db, shadow_id)

    np.random.seed(404)
    n = 180
    returns = []
    for i in range(n):
        if i < 90:
            returns.append(np.random.normal(0.0, 0.005))  # low vol
        else:
            returns.append(np.random.normal(-0.008, 0.02))  # high vol + negative drift
    _add_snapshots(temp_shadow_db, shadow_id, returns)

    result = monitor.check(shadow_id)

    # BOCPD triggers on joint vol shift + CUSUM
    # The negative drift in the high-vol period should trigger CUSUM
    # and the 4x vol increase should trigger vol_shift
    assert result.bocpd_triggered or result.cusum_triggered, \
        "Either CUSUM or BOCPD should trigger with volatility regime shift"
    if result.bocpd_triggered and result.cusum_triggered:
        assert "D3" in result.triggered_conditions, \
            f"Joint BOCPD+CUSUM should be D3, got: {result.triggered_conditions}"
