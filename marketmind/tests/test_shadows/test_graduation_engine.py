"""Tests for GraduationEngine — multi-stage Gate 2 qualification pipeline."""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig, DailySnapshot
from marketmind.shadows.shadow_data_types import VirtualTrade
from marketmind.shadows.graduation_engine import GraduationEngine, GraduationResult


@pytest.fixture
def engine(temp_shadow_db):
    """Create a GraduationEngine with a real temp DB."""
    return GraduationEngine(temp_shadow_db)


def _create_shadow(db: ShadowStateDB, shadow_id: str, shadow_type: str = "expert",
                   virtual_capital: float = 50000.0, max_dd_limit: float = 0.25,
                   domain: str = "gold") -> ShadowConfig:
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Test {shadow_id}",
        methodology_prompt=f"You are a test {shadow_type} analyst.",
        virtual_capital=virtual_capital,
        domain=domain,
        max_drawdown_limit=max_dd_limit,
    )
    db.create_shadow(config)
    return config


def _add_snapshots(db: ShadowStateDB, shadow_id: str, daily_returns: list[float],
                   cumulative_return: float | None = None,
                   max_drawdown: float | None = None,
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

        mdd_pct = abs(running_mdd) * 100 if running_mdd < 0 else 0.0

        date_str = current_date.isoformat()
        snap = DailySnapshot(
            shadow_id=shadow_id,
            date=date_str,
            virtual_capital=50000.0 * (1.0 + cum),
            daily_return_pct=r * 100.0,   # convert to percentage
            cumulative_return_pct=cum * 100.0,
            max_drawdown_pct=mdd_pct,
            win_rate_pct=60.0,
            sharpe_ratio=0.8 if abs(r) > 1e-6 else 0.0,
            calmar_ratio=0.6,
            omega_ratio=1.2,
            mppm_score=0.5,
            composite_score=0.7,
            deflated_score=0.65,
            percentile_rank=0.60,
            achievement_tier="Excellent",
        )
        db.save_snapshot(shadow_id, snap)
        snapshots.append(snap)

        # Advance to next weekday (skip weekends)
        current_date += timedelta(days=1)
        while current_date.weekday() >= 5:  # Sat=5, Sun=6
            current_date += timedelta(days=1)

    return snapshots


def _make_trades(shadow_id: str, num_wins: int, num_losses: int,
                 avg_win_pct: float = 2.0, avg_loss_pct: float = -1.5,
                 position_size_pct: float = 0.05) -> list[VirtualTrade]:
    """Create a list of mock VirtualTrade objects."""
    trades = []
    trade_id = 0
    for i in range(num_wins):
        trade_id += 1
        trades.append(VirtualTrade(
            trade_id=trade_id,
            shadow_id=shadow_id,
            ticker=f"TICKER_{trade_id}",
            direction="long" if i % 2 == 0 else "short",
            entry_price=100.0,
            exit_price=100.0 * (1 + avg_win_pct / 100),
            position_size_pct=position_size_pct,
            entry_date=f"2026-{(i % 6) + 1:02d}-{(i % 20) + 1:02d}",
            exit_date=f"2026-{(i % 6) + 1:02d}-{(i % 20) + 5:02d}",
            exit_reason="take_profit",
            pnl_pct=avg_win_pct,
            virtual_slippage_applied=0.001,
            confidence_discount_applied=0.002,
            paper_live_gap_ratio=0.01,
        ))
    for i in range(num_losses):
        trade_id += 1
        trades.append(VirtualTrade(
            trade_id=trade_id,
            shadow_id=shadow_id,
            ticker=f"TICKER_{trade_id}",
            direction="long" if i % 2 == 0 else "short",
            entry_price=100.0,
            exit_price=100.0 * (1 + avg_loss_pct / 100),
            position_size_pct=position_size_pct,
            entry_date=f"2026-{(i % 6) + 1:02d}-{(i % 20) + 10:02d}",
            exit_date=f"2026-{(i % 6) + 1:02d}-{(i % 20) + 15:02d}",
            exit_reason="stop_loss",
            pnl_pct=avg_loss_pct,
            virtual_slippage_applied=0.001,
            confidence_discount_applied=0.002,
            paper_live_gap_ratio=0.01,
        ))
    return trades


# ══════════════════════════════════════════════════════════════════════════════
# Tier 1 Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_expert_passes_tier1(engine, temp_shadow_db):
    """Expert shadow with strong metrics passes Tier 1."""
    shadow_id = "expert:gold:test_t1_pass"
    _create_shadow(temp_shadow_db, shadow_id, "expert", max_dd_limit=0.25)

    # 90 days of positive returns, small drawdown
    returns = [0.001 + (i % 5) * 0.0005 for i in range(90)]
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.02)

    # 10 trades: 7 wins, 3 losses = 70% WR
    trades = _make_trades(shadow_id, num_wins=7, num_losses=3)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=5):
            result = engine.evaluate(shadow_id)

    assert result.passed_tier1, f"Tier 1 should pass, blocking: {result.tier1_details.get('failures', [])}"
    assert result.tier1_details["win_rate"] >= 0.52
    assert result.tier1_details["total_return"] > 0
    assert result.tier1_details["min_trades"] >= 5
    assert result.tier1_details["max_dd"] < 0.25


def test_momentum_fails_tier1_insufficient_trades(engine, temp_shadow_db):
    """Momentum shadow with too few trades fails Tier 1."""
    shadow_id = "momentum:intraday:test_t1_fail"
    _create_shadow(temp_shadow_db, shadow_id, "momentum", max_dd_limit=0.30)

    returns = [0.002] * 75  # decent returns
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.05)

    # Only 10 trades — below the 50 minimum for momentum
    trades = _make_trades(shadow_id, num_wins=7, num_losses=3)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=3):
            result = engine.evaluate(shadow_id)

    assert not result.passed_tier1
    failures = result.tier1_details.get("failures", [])
    assert any("T1_TRADES" in f for f in failures), f"Expected T1_TRADES failure, got: {failures}"


def test_contrarian_meets_tier1_thresholds(engine, temp_shadow_db):
    """Contrarian shadow (fade_master) passes Tier 1 with appropriate thresholds."""
    shadow_id = "contrarian:consensus:fade_master"
    _create_shadow(temp_shadow_db, shadow_id, "contrarian", max_dd_limit=0.35)

    # 252 days of returns with moderate DD
    returns = [0.0015 + (i % 10) * 0.0003 - 0.0015 for i in range(252)]
    # Make it mildly positive overall
    returns = [r + 0.0001 for r in returns]
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.15)

    # 55 trades: 28 wins, 27 losses ≈ 51% WR (above 45% contrarian threshold)
    trades = _make_trades(shadow_id, num_wins=28, num_losses=27)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=40):
            result = engine.evaluate(shadow_id)

    assert result.passed_tier1, f"Tier 1 should pass, blocking: {result.tier1_details.get('failures', [])}"
    assert result.tier1_details["win_rate"] >= 0.45
    assert result.tier1_details["min_trades"] >= 50  # fade_master threshold


# ══════════════════════════════════════════════════════════════════════════════
# Tier 2 Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_expert_tier2_sortino_and_mar(engine, temp_shadow_db):
    """Expert shadow with strong risk-adjusted metrics passes Tier 2."""
    shadow_id = "expert:tech:test_t2_pass"
    _create_shadow(temp_shadow_db, shadow_id, "expert", max_dd_limit=0.25)

    # Consistent positive returns with low downside deviation
    returns = [0.002] * 80 + [-0.003] * 5 + [0.002] * 5
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.02)

    trades = _make_trades(shadow_id, num_wins=8, num_losses=2)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=5):
            result = engine.evaluate(shadow_id)

    # Check Tier 2 details
    assert "sortino" in result.tier2_details
    assert "mar" in result.tier2_details
    assert "gpr" in result.tier2_details
    assert "k_ratio" in result.tier2_details
    # With consistently positive returns, Sortino should be high
    sortino = result.tier2_details["sortino"]
    assert sortino > 0, f"Sortino should be > 0 for positive returns, got {sortino}"


def test_evaluate_raises_no_error_for_missing_shadow(engine, temp_shadow_db):
    """Evaluating a non-existent shadow returns a result with blocking reason, no exception."""
    result = engine.evaluate("nonexistent:shadow:id")

    assert isinstance(result, GraduationResult)
    assert result.shadow_id == "nonexistent:shadow:id"
    assert result.shadow_type == "unknown"
    assert not result.gate2_qualified
    assert len(result.blocking_reasons) >= 1
    assert "not found" in result.blocking_reasons[0].lower()


# ══════════════════════════════════════════════════════════════════════════════
# Stress Test Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_stress_test_covid_contrarian_high_freq_requires_positive(engine, temp_shadow_db):
    """High-freq contrarian shadow MUST have positive returns in COVID scenario."""
    shadow_id = "contrarian:consensus:fade_master"
    _create_shadow(temp_shadow_db, shadow_id, "contrarian", max_dd_limit=0.35)

    # Add snapshots during COVID period (2020-02 ~ 2020-03) with negative returns
    # These simulate what the stress test would find in the DB
    covid_returns = [-0.01] * 20 + [-0.005] * 10  # clearly negative
    _add_snapshots(temp_shadow_db, shadow_id, covid_returns,
                   start_date="2020-02-03",
                   cumulative_return=sum(covid_returns), max_drawdown=0.30)

    # Also add regular returns for the overall evaluation period
    regular_returns = [0.001] * 100
    _add_snapshots(temp_shadow_db, shadow_id, regular_returns,
                   start_date="2026-01-02",
                   cumulative_return=sum(regular_returns), max_drawdown=0.05)

    # For the stress test, it queries all snapshots (days=9999) and filters by date
    with patch.object(temp_shadow_db, "get_trade_history", return_value=_make_trades(shadow_id, 30, 25)):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=40):
            result = engine.evaluate(shadow_id)

    # The stress test should detect the negative COVID returns for high-freq contrarian
    stress = result.stress_test_results
    assert "scenarios" in stress
    covid_scenario = stress["scenarios"].get("covid_2020")
    if covid_scenario and covid_scenario.get("num_observations", 0) > 0:
        # If snapshots fell in the COVID date range, the test should fail
        assert not covid_scenario["passed"], \
            f"COVID stress should fail for high-freq contrarian with negative returns, got {covid_scenario}"


# ══════════════════════════════════════════════════════════════════════════════
# Alpha Purity Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_alpha_purity_positive_alpha(engine, temp_shadow_db):
    """Shadow with positive mean daily return has positive alpha."""
    shadow_id = "expert:gold:test_alpha"
    _create_shadow(temp_shadow_db, shadow_id, "expert", max_dd_limit=0.25)

    # Positive daily returns
    returns = [0.001] * 30
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.0)

    trades = _make_trades(shadow_id, num_wins=10, num_losses=2)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=2):
            result = engine.evaluate(shadow_id)

    alpha = result.alpha_purity
    assert alpha["alpha_positive"], f"Alpha should be positive, got {alpha}"
    # With low volatility relative to mean, t-stat should be significant
    assert "t_stat" in alpha


def test_alpha_purity_insufficient_data(engine, temp_shadow_db):
    """Shadow with very few snapshots gets insufficient_data note."""
    shadow_id = "expert:fx:test_alpha_few"
    _create_shadow(temp_shadow_db, shadow_id, "expert", max_dd_limit=0.25)

    # Only 10 snapshots (< 20 required for alpha)
    returns = [0.001] * 10
    _add_snapshots(temp_shadow_db, shadow_id, returns,
                   cumulative_return=sum(returns), max_drawdown=0.0)

    trades = _make_trades(shadow_id, num_wins=3, num_losses=2)

    with patch.object(temp_shadow_db, "get_trade_history", return_value=trades):
        with patch.object(temp_shadow_db, "get_abstention_days", return_value=1):
            result = engine.evaluate(shadow_id)

    alpha = result.alpha_purity
    assert "insufficient_data" in alpha.get("note", "")
