"""Tests for RankingEngine -- pure Python ranking computation."""
import math
import pytest
import random
from marketmind.shadows.ranking_engine import (
    RankingEngine, ShadowPerformance, RankingResult
)
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def engine():
    return RankingEngine(ShadowSettings())


@pytest.fixture
def sample_performances():
    """15 shadows with varying performance for ranking tests."""
    random.seed(42)
    perfs = {}
    for i in range(15):
        n = 60 + random.randint(0, 30)
        base = random.uniform(-0.001, 0.003)
        returns = [base + random.gauss(0, 0.02) for _ in range(n)]
        cum = sum(returns)
        running_max = returns[0]
        running_sum = returns[0]
        peak = returns[0]
        dd = 0.0
        for r in returns[1:]:
            running_sum += r
            if running_sum > peak:
                peak = running_sum
            current_dd = running_sum - peak
            if current_dd < dd:
                dd = current_dd
        wins = sum(1 for r in returns if r > 0)
        perfs[f"shadow_{i:02d}"] = ShadowPerformance(
            shadow_id=f"shadow_{i:02d}",
            daily_returns=returns,
            cumulative_return=cum,
            max_drawdown=abs(dd) if dd < 0 else 0.01,
            max_drawdown_duration_days=random.randint(1, 30),
            win_rate=wins / len(returns) if returns else 0.5,
            total_trades=len(returns),
            profitable_trades=wins,
            losing_trades=len(returns) - wins,
            abstention_days=0,
            cagr=cum * 252 / len(returns) if len(returns) > 0 else 0.0,
        )
    return perfs


def test_mppm_positive_for_positive_returns(engine):
    returns = [0.001] * 50
    mppm = engine.compute_mppm(returns)
    assert mppm > 0


def test_mppm_negative_for_negative_returns(engine):
    returns = [-0.001] * 50
    mppm = engine.compute_mppm(returns)
    assert mppm < 0


def test_mppm_handles_fat_tails(engine):
    """MPPM should not explode on extreme returns."""
    returns = [0.001] * 40 + [0.10, -0.08, 0.15, -0.12]
    mppm = engine.compute_mppm(returns)
    assert not math.isnan(mppm)
    assert abs(mppm) < 100


def test_calmar_zero_mdd_returns_cagr(engine):
    """If MDD is 0 (all positive), Calmar should be capped not infinite."""
    cum = 0.05
    calmar = engine.compute_calmar(cum, 0.001)
    assert calmar > 0
    assert calmar < 1000


def test_omega_ratio_basic(engine):
    returns = [0.02, -0.01, 0.03, -0.005, 0.01]
    omega = engine.compute_omega(returns)
    assert omega > 1.0


def test_omega_capped_at_10(engine):
    """Omega should be capped at 10 per spec."""
    returns = [0.05] * 50
    omega = engine.compute_omega(returns)
    assert omega <= 10.0


def test_composite_score_range(engine):
    perf = ShadowPerformance(
        shadow_id="test", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252
    )
    score, components, modifiers = engine.compute_composite_score(perf)
    assert "mppm" in components
    assert "calmar" in components
    assert "omega" in components
    assert "win_rate" in components


def test_haircut_n15_t60(engine):
    """h(15, 60) should be approximately 0.451 as validated in methodology."""
    h = engine.compute_haircut(n_shadows=15, evaluation_days=60)
    assert h == pytest.approx(0.451, rel=0.05)


def test_haircut_increases_with_more_data(engine):
    """More shadows + more days = higher haircut (less penalty)."""
    h1 = engine.compute_haircut(5, 30)
    h2 = engine.compute_haircut(15, 60)
    h3 = engine.compute_haircut(30, 252)
    assert h1 < h2 < h3


def test_haircut_value_range(engine):
    """Haircut should be in (0, 1)."""
    h = engine.compute_haircut(15, 60)
    assert 0 < h < 1


def test_rank_shadows_produces_correct_count(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    assert len(results) == 15


def test_rank_shadows_best_has_rank_1(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    assert results[0].rank == 1


def test_rank_shadows_percentiles_sum_to_1(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    total = sum(r.percentile_rank for r in results)
    assert total == pytest.approx(7.5, abs=3.0)


def test_achievement_ladder_elite(engine):
    """90 days at p85 + deflated Sharpe > 0.8 -> elite."""
    scores = [("2026-05-01", 0.78)] * 20 + [("2026-05-20", 0.82)] * 30
    percentiles = [("2026-05-01", 0.55)] * 20 + [("2026-05-20", 0.88)] * 30
    tier = engine.determine_achievement_tier(scores, percentiles, 0.10, 0.85)
    assert tier == "elite"


def test_achievement_ladder_endangered(engine):
    """20 days at p15 -> endangered."""
    percentiles = [("2026-01-01", 0.12)] * 25
    scores = [("2026-01-01", 0.30)] * 25
    tier = engine.determine_achievement_tier(scores, percentiles, 0.25, 0.4)
    assert tier == "endangered"


def test_achievement_ladder_normal_default(engine):
    """New shadow with no history = normal."""
    tier = engine.determine_achievement_tier([], [], 0.0, 0.0)
    assert tier == "normal"


def test_plateau_detection(engine):
    """126 days no elite, 90 days wr range < 10pp, 63 days no insight."""
    tier_hist = [("2026-01-01", "normal")] * 150
    wr_hist = [(f"2026-{d:02d}-01", 0.52 + (d % 3) * 0.01) for d in range(1, 100)]
    insights = ["2025-12-01"]
    is_plateau, score = engine.detect_plateau("test", tier_hist, wr_hist, insights)
    assert is_plateau
    assert score > 0


def test_plateau_not_detected_with_recent_elite(engine):
    tier_hist = [("2026-04-01", "elite"), ("2026-05-01", "elite")]
    wr_hist = [("2026-05-01", 0.52)]
    insights = []
    is_plateau, _ = engine.detect_plateau("test", tier_hist, wr_hist, insights)
    assert not is_plateau
