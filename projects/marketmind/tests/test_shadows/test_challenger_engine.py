"""Tests for ChallengerEngine — 3-stage elimination buffer, secret creation, paired t-test comparison."""
import pytest
from unittest.mock import MagicMock, patch

from projects.marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, DailySnapshot
)
from projects.marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings(
        challenger_stage1_periods=2,
        challenger_stage2_periods=3,
        challenger_stage3_weeks=2,
        challenger_trial_alpha=0.10,
        challenger_calmar_gate=0.3,
    )


@pytest.fixture
def engine(temp_shadow_db, settings):
    from projects.marketmind.shadows.challenger_engine import ChallengerEngine
    return ChallengerEngine(temp_shadow_db, settings)


def _create_shadow(db, shadow_id, shadow_type="expert", domain="gold", parent_id=None):
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Shadow {shadow_id}",
        methodology_prompt="You are a test analyst.",
        virtual_capital=50000.0,
        domain=domain,
        parent_shadow_id=parent_id,
    )
    db.create_shadow(config)
    return config


def _add_snapshot(db, shadow_id, date, composite_score, percentile_rank,
                  daily_return_pct=0.001, cumulative_return_pct=0.01,
                  max_drawdown_pct=0.05, calmar_ratio=0.5):
    snap = DailySnapshot(
        shadow_id=shadow_id,
        date=date,
        virtual_capital=50000.0,
        daily_return_pct=daily_return_pct,
        cumulative_return_pct=cumulative_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate_pct=50.0,
        sharpe_ratio=1.0,
        calmar_ratio=calmar_ratio,
        omega_ratio=1.2,
        mppm_score=0.5,
        composite_score=composite_score,
        deflated_score=composite_score * 0.9,
        percentile_rank=percentile_rank,
        achievement_tier="normal",
    )
    db.save_snapshot(shadow_id, snap)


# ── Stage 1: Warning ──────────────────────────────────────────────────────

def test_stage1_warning_2_consecutive_bottom_periods(engine, temp_shadow_db):
    """After 2 consecutive periods in bottom 20%, shadow enters stage 1 (warning)."""
    _create_shadow(temp_shadow_db, "expert:test:s1_warning", "expert", "gold")

    # Simulate 2 evaluation periods in bottom 20% (percentile_rank < 0.20)
    _add_snapshot(temp_shadow_db, "expert:test:s1_warning", "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, "expert:test:s1_warning", "2026-05-02", composite_score=0.2, percentile_rank=0.05)

    stage = engine.check_elimination_stage("expert:test:s1_warning")
    assert stage.current_stage == 1
    assert stage.consecutive_bottom_periods == 2
    assert stage.shadow_id == "expert:test:s1_warning"


def test_no_challenger_when_single_bad_period(engine, temp_shadow_db):
    """A single bad period does NOT trigger the elimination pipeline."""
    _create_shadow(temp_shadow_db, "expert:test:s1_single", "expert", "gold")

    _add_snapshot(temp_shadow_db, "expert:test:s1_single", "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    # Next period is NOT in bottom 20%
    _add_snapshot(temp_shadow_db, "expert:test:s1_single", "2026-05-02", composite_score=0.8, percentile_rank=0.60)

    stage = engine.check_elimination_stage("expert:test:s1_single")
    assert stage.current_stage == 0  # Not in elimination pipeline
    assert stage.consecutive_bottom_periods == 0


# ── Stage 2: Challenger creation ──────────────────────────────────────────

def test_stage2_challenger_created_3_consecutive_bottom(engine, temp_shadow_db):
    """After 3 consecutive periods in bottom 20%, a secret challenger is created."""
    _create_shadow(temp_shadow_db, "expert:test:s2_challenger", "expert", "gold")

    _add_snapshot(temp_shadow_db, "expert:test:s2_challenger", "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, "expert:test:s2_challenger", "2026-05-02", composite_score=0.2, percentile_rank=0.05)
    _add_snapshot(temp_shadow_db, "expert:test:s2_challenger", "2026-05-03", composite_score=0.1, percentile_rank=0.08)

    stage = engine.check_elimination_stage("expert:test:s2_challenger")
    assert stage.current_stage == 2
    assert stage.consecutive_bottom_periods == 3
    # Challenger should have been auto-created
    assert stage.challenger_id is not None
    assert "challenger" in stage.challenger_id

    # Verify challenger exists in DB
    challenger = temp_shadow_db.get_shadow(stage.challenger_id)
    assert challenger is not None
    assert challenger.shadow_type == "challenger"
    assert challenger.parent_shadow_id == "expert:test:s2_challenger"


def test_challenger_not_visible_in_rankings(engine, temp_shadow_db):
    """Challenger shadows must NOT appear in get_visible_shadows()."""
    _create_shadow(temp_shadow_db, "expert:test:s2_visible", "expert", "gold")

    _add_snapshot(temp_shadow_db, "expert:test:s2_visible", "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, "expert:test:s2_visible", "2026-05-02", composite_score=0.2, percentile_rank=0.05)
    _add_snapshot(temp_shadow_db, "expert:test:s2_visible", "2026-05-03", composite_score=0.1, percentile_rank=0.08)

    stage = engine.check_elimination_stage("expert:test:s2_visible")
    assert stage.challenger_id is not None

    visible = temp_shadow_db.get_visible_shadows()
    visible_ids = [s.shadow_id for s in visible]
    assert stage.challenger_id not in visible_ids
    assert "expert:test:s2_visible" in visible_ids  # Target still visible (not eliminated yet)


# ── Stage 3: Comparison trial ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage3_replacement_when_challenger_outperforms(engine, temp_shadow_db):
    """When challenger significantly outperforms target, verdict is REPLACE_TARGET."""
    target_id = "expert:test:s3_replace"
    _create_shadow(temp_shadow_db, target_id, "expert", "gold")

    # Create data that triggers stage 2 -> challenger created
    _add_snapshot(temp_shadow_db, target_id, "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, target_id, "2026-05-02", composite_score=0.2, percentile_rank=0.05)
    _add_snapshot(temp_shadow_db, target_id, "2026-05-03", composite_score=0.1, percentile_rank=0.08)

    stage = engine.check_elimination_stage(target_id)
    challenger_id = stage.challenger_id
    assert challenger_id is not None

    # Manually add snapshots for the challenger to simulate a 2-week trial
    # Challenger consistently outperforms target with higher daily returns
    for i in range(10):
        date = f"2026-05-{10 + i:02d}"
        # Target: low returns (0.001 per day)
        _add_snapshot(temp_shadow_db, target_id, date,
                      composite_score=0.2 + i * 0.005, percentile_rank=0.1,
                      daily_return_pct=0.001,
                      cumulative_return_pct=0.01 + i * 0.001,
                      calmar_ratio=0.2)
        # Challenger: higher returns (0.03 per day)
        _add_snapshot(temp_shadow_db, challenger_id, date,
                      composite_score=0.5 + i * 0.01, percentile_rank=0.5,
                      daily_return_pct=0.03,
                      cumulative_return_pct=0.10 + i * 0.03,
                      max_drawdown_pct=0.05,
                      calmar_ratio=0.8)

    # Run comparison trial
    result = await engine.run_comparison_trial(challenger_id, target_id)

    assert result.challenger_id == challenger_id
    assert result.target_id == target_id
    # Challenger should outperform with high confidence
    assert result.challenger_mean_return > result.target_mean_return
    # With challenger daily returns 30x target, t-test should detect it
    assert result.challenger_better is True
    # Calmar 0.8 > 0.3 gate and significant t-test → REPLACE_TARGET
    assert result.verdict == "REPLACE_TARGET"


@pytest.mark.asyncio
async def test_stage3_restore_when_challenger_underperforms(engine, temp_shadow_db):
    """When challenger underperforms target, verdict is RESTORE_TARGET."""
    target_id = "expert:test:s3_restore"
    _create_shadow(temp_shadow_db, target_id, "expert", "gold")

    _add_snapshot(temp_shadow_db, target_id, "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, target_id, "2026-05-02", composite_score=0.2, percentile_rank=0.05)
    _add_snapshot(temp_shadow_db, target_id, "2026-05-03", composite_score=0.1, percentile_rank=0.08)

    stage = engine.check_elimination_stage(target_id)
    challenger_id = stage.challenger_id

    # Add trial snapshots: target performs well, challenger does poorly
    for i in range(10):
        date = f"2026-06-{10 + i:02d}"
        _add_snapshot(temp_shadow_db, target_id, date,
                      composite_score=0.7, percentile_rank=0.7,
                      daily_return_pct=0.02,
                      cumulative_return_pct=0.15 + i * 0.02,
                      calmar_ratio=0.8)
        _add_snapshot(temp_shadow_db, challenger_id, date,
                      composite_score=0.15, percentile_rank=0.05,
                      daily_return_pct=-0.01,
                      cumulative_return_pct=-0.05 - i * 0.01,
                      max_drawdown_pct=0.20,
                      calmar_ratio=-0.1)

    result = await engine.run_comparison_trial(challenger_id, target_id)
    assert result.target_mean_return > result.challenger_mean_return
    assert result.verdict == "RESTORE_TARGET"


# ── Statistical and gate tests ────────────────────────────────────────────

def test_paired_ttest_statistical_gate(engine, temp_shadow_db):
    """Paired t-test correctly computes p-value for one-sided test at alpha=0.10."""
    target_id = "expert:test:s3_ttest"
    _create_shadow(temp_shadow_db, target_id, "expert", "gold")
    challenger_id = engine.create_challenger(target_id)
    # create_challenger already inserts into DB — no need to re-create

    # Add 10 daily snapshots for paired trial
    # Target daily returns (simulated via cumulative changes)
    target_returns = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
    challenger_returns = [0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02]

    # We need daily return values in snapshots for the t-test
    for i in range(10):
        date = f"2026-07-{10 + i:02d}"
        snap_t = DailySnapshot(
            shadow_id=target_id, date=date, virtual_capital=50000.0,
            daily_return_pct=target_returns[i],
            cumulative_return_pct=sum(target_returns[:i+1]) * 100 + 1.0,
            max_drawdown_pct=0.02, win_rate_pct=80.0,
            sharpe_ratio=1.2, calmar_ratio=0.8, omega_ratio=1.5,
            mppm_score=0.6, composite_score=0.6, deflated_score=0.54,
            percentile_rank=0.5, achievement_tier="normal",
        )
        snap_c = DailySnapshot(
            shadow_id=challenger_id, date=date, virtual_capital=50000.0,
            daily_return_pct=challenger_returns[i],
            cumulative_return_pct=sum(challenger_returns[:i+1]) * 100 + 1.0,
            max_drawdown_pct=0.01, win_rate_pct=90.0,
            sharpe_ratio=2.0, calmar_ratio=1.5, omega_ratio=2.0,
            mppm_score=0.8, composite_score=0.8, deflated_score=0.72,
            percentile_rank=0.8, achievement_tier="excellent",
        )
        temp_shadow_db.save_snapshot(target_id, snap_t)
        temp_shadow_db.save_snapshot(challenger_id, snap_c)

    # Run the internal paired t-test calculation
    pvalue, t_stat, mean_diff = engine._compute_paired_ttest(
        target_returns, challenger_returns, one_sided=True
    )
    # Challenger returns are higher, so p-value should be small
    assert pvalue < 0.10
    assert t_stat < 0  # negative because target - challenger is negative
    assert mean_diff < 0


def test_challenger_calmar_gate_enforced(engine, temp_shadow_db):
    """Challenger must have Calmar > 0.3 to pass comparison gate."""
    target_id = "expert:test:s3_calmar"
    _create_shadow(temp_shadow_db, target_id, "expert", "gold")

    # Create a challenger with poor Calmar
    challenger_id = engine.create_challenger(target_id)

    # Compute Calmar from snapshots
    # Low cumulative return, high drawdown -> low Calmar
    for i in range(10):
        date = f"2026-08-{10 + i:02d}"
        snap = DailySnapshot(
            shadow_id=challenger_id, date=date, virtual_capital=50000.0,
            daily_return_pct=-0.005,
            cumulative_return_pct=-0.05,
            max_drawdown_pct=0.30,
            win_rate_pct=30.0,
            sharpe_ratio=-0.5, calmar_ratio=-0.05 / 0.30, omega_ratio=0.5,
            mppm_score=-0.5, composite_score=0.1, deflated_score=0.09,
            percentile_rank=0.05, achievement_tier="endangered",
        )
        temp_shadow_db.save_snapshot(challenger_id, snap)

    # Calmar from these snapshots would be -0.05 / 0.30 ≈ -0.17, which is < 0.3
    calmar = engine._compute_calmar_from_snapshots(temp_shadow_db, challenger_id, 10)
    assert calmar < 0.3

    # Verify the calmar gate check works
    passes_gate = engine._check_calmar_gate(calmar)
    assert passes_gate is False


# ── Edge case tests ───────────────────────────────────────────────────────

def test_challenger_engine_idempotent_check(engine, temp_shadow_db):
    """Calling check_elimination_stage multiple times at stage 2 does NOT create
    multiple challengers."""
    _create_shadow(temp_shadow_db, "expert:test:idempotent", "expert", "gold")

    _add_snapshot(temp_shadow_db, "expert:test:idempotent", "2026-05-01", composite_score=0.3, percentile_rank=0.10)
    _add_snapshot(temp_shadow_db, "expert:test:idempotent", "2026-05-02", composite_score=0.2, percentile_rank=0.05)
    _add_snapshot(temp_shadow_db, "expert:test:idempotent", "2026-05-03", composite_score=0.1, percentile_rank=0.08)

    stage1 = engine.check_elimination_stage("expert:test:idempotent")
    challenger_id_1 = stage1.challenger_id
    assert challenger_id_1 is not None

    # Second call should return same stage (challenger already exists)
    stage2 = engine.check_elimination_stage("expert:test:idempotent")
    assert stage2.challenger_id == challenger_id_1

    # Check only one challenger exists
    challengers = temp_shadow_db.get_active_shadows("challenger")
    target_challengers = [c for c in challengers if c.parent_shadow_id == "expert:test:idempotent"]
    assert len(target_challengers) == 1


def test_challenger_created_from_existing_config(engine, temp_shadow_db):
    """create_challenger() returns a valid challenger_id even for shadows not in
    the elimination pipeline."""
    _create_shadow(temp_shadow_db, "expert:test:manual", "expert", "gold")
    challenger_id = engine.create_challenger("expert:test:manual")
    assert challenger_id is not None
    assert "challenger" in challenger_id

    challenger = temp_shadow_db.get_shadow(challenger_id)
    assert challenger.shadow_type == "challenger"
    assert challenger.parent_shadow_id == "expert:test:manual"
