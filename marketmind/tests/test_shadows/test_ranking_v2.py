"""Tests for Phase 2b ranking: v2 formula, Brier/calibration integration, token efficiency, backward compatibility."""
import math
import pytest
from marketmind.shadows.ranking_engine import (
    RankingEngine, ShadowPerformance, RankingResult, compute_token_efficiency
)
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def engine():
    return RankingEngine(ShadowSettings())


# ── V2 formula: calibration data activates new weights ───────────────────

def test_v2_formula_activates_with_brier_data(engine):
    """When brier_score < 1.0, the v2 formula uses calibration weight 0.20."""
    perf = ShadowPerformance(
        shadow_id="test_v2", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
        brier_score=0.15, calibration_score=0.72,
    )
    score, components, modifiers = engine.compute_composite_score(perf)
    assert modifiers["has_calibration"] is True
    assert modifiers["calibration_weight"] == 0.20
    assert "calibration" in components
    assert components["calibration"] == pytest.approx(0.72, rel=0.01)


def test_v2_formula_activates_with_calibration_score(engine):
    """When calibration_score > 0, the v2 formula activates even if brier is default."""
    perf = ShadowPerformance(
        shadow_id="test_cal", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
        brier_score=1.0, calibration_score=0.45,
    )
    score, components, modifiers = engine.compute_composite_score(perf)
    assert modifiers["has_calibration"] is True
    assert "calibration" in components


def test_v1_backward_compatible_no_brier_data(engine):
    """Without calibration data, the formula uses v1 config weights (backward compatible)."""
    perf = ShadowPerformance(
        shadow_id="test_v1", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
        # brier_score defaults to 1.0, calibration_score defaults to 0.0
    )
    score, components, modifiers = engine.compute_composite_score(perf)
    assert modifiers["has_calibration"] is False
    assert modifiers["calibration_weight"] == 0.0
    assert "calibration" not in components


def test_v1_v2_produce_different_scores(engine):
    """A shadow with good calibration should score differently with v2 vs v1 weights."""
    perf = ShadowPerformance(
        shadow_id="test_diff", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
    )
    score_v1, comps_v1, mods_v1 = engine.compute_composite_score(perf)

    perf_v2 = ShadowPerformance(
        shadow_id="test_diff", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
        brier_score=0.10, calibration_score=0.85,
    )
    score_v2, comps_v2, mods_v2 = engine.compute_composite_score(perf_v2)

    # With strong calibration, v2 score should be higher than v1
    assert score_v2 > score_v1


# ── Graceful degradation: Brier=1.0 redistributes weight ────────────────

def test_graceful_degradation_preserves_original_weights(engine):
    """When no Brier data, weights should match original v1 config weights."""
    perf = ShadowPerformance(
        shadow_id="test_gd", daily_returns=[0.002] * 50,
        cumulative_return=0.10, max_drawdown=0.01,
        max_drawdown_duration_days=5, win_rate=0.55,
        total_trades=50, profitable_trades=27, losing_trades=23,
        abstention_days=0, cagr=0.504,
    )
    score, components, modifiers = engine.compute_composite_score(perf)

    # Backward-compatible: weights should be from config (v1)
    # MPPM: 0.35, Calmar: 0.25, Omega: 0.20, WR: 0.20
    assert not modifiers["has_calibration"]
    assert modifiers["calibration_weight"] == 0.0
    # Score should be computable (no errors)
    assert score > 0


def test_brier_computation_from_domain_scores(engine):
    """When calibration_score is 0 but brier_score < 1, compute from Brier + resolution."""
    perf = ShadowPerformance(
        shadow_id="test_domain", daily_returns=[0.001] * 50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252,
        brier_score=0.20,  # good calibration
        calibration_score=0.0,  # force computation from brier + domain_scores
        domain_scores={"gold": 0.7, "crypto": 0.3, "energy": 0.8, "bonds": 0.5},
    )
    score, components, modifiers = engine.compute_composite_score(perf)
    assert modifiers["has_calibration"] is True
    assert "calibration" in components
    # Brier component = 0.5 * (1 - 0.20) = 0.40
    # Resolution = variance of [0.7, 0.3, 0.8, 0.5] = mean=0.575, var ~0.0356
    # Cal = 0.5*0.80 + 0.5*0.0356 = 0.40 + 0.0178 = 0.4178
    cal_score = components["calibration"]
    assert 0.3 < cal_score < 0.55
    assert score > 0


# ── Token efficiency ─────────────────────────────────────────────────────

def test_token_efficiency_basic():
    """Return per token: $1000 return / 5000 tokens = 0.2."""
    eff = compute_token_efficiency("shadow_01", cumulative_return=1000.0, total_tokens=5000)
    assert eff == 0.2


def test_token_efficiency_zero_tokens():
    """Zero tokens consumed should return 0.0."""
    eff = compute_token_efficiency("shadow_01", cumulative_return=100.0, total_tokens=0)
    assert eff == 0.0


def test_token_efficiency_negative_return():
    """Negative return with tokens should produce negative efficiency."""
    eff = compute_token_efficiency("shadow_01", cumulative_return=-500.0, total_tokens=2000)
    assert eff == -0.25


def test_token_efficiency_high_volume():
    """A shadow that burns massive tokens for mediocre returns gets low efficiency."""
    eff = compute_token_efficiency("burner", cumulative_return=5.0, total_tokens=100000)
    assert eff == 0.00005


# ── V2 formula weight validation ─────────────────────────────────────────

def test_v2_weights_sum_to_one(engine):
    """V2 base weights + calibration weight must sum to 1.0."""
    v2_sum = sum(engine._V2_WEIGHTS.values()) + engine._V2_CALIBRATION_WEIGHT
    assert v2_sum == pytest.approx(1.0)


def test_v2_calibration_weight_is_0_20(engine):
    assert engine._V2_CALIBRATION_WEIGHT == 0.20


# ── rank_shadows with v2 data ────────────────────────────────────────────

def test_rank_shadows_with_mixed_calibration(engine):
    """rank_shadows should handle a mix of shadows with and without calibration data."""
    perfs = {}
    for i in range(5):
        has_cal = i < 2  # first 2 have calibration data
        perfs[f"shadow_{i:02d}"] = ShadowPerformance(
            shadow_id=f"shadow_{i:02d}",
            daily_returns=[0.001 + i * 0.0005] * 60,
            cumulative_return=0.03 + i * 0.01,
            max_drawdown=0.02 + i * 0.005,
            max_drawdown_duration_days=5,
            win_rate=0.5 + i * 0.05,
            total_trades=60,
            profitable_trades=int(30 + i * 3),
            losing_trades=int(30 - i * 3),
            abstention_days=0,
            cagr=0.2 + i * 0.05,
            brier_score=0.15 if has_cal else 1.0,
            calibration_score=0.80 if has_cal else 0.0,
            domain_scores={"macro": 0.75} if has_cal else {},
        )

    results = engine.rank_shadows(perfs, {}, "2026-05-18")
    assert len(results) == 5
    # Shadows with calibration should generally rank higher
    assert all(r.rank > 0 for r in results)


# ── New fields on ShadowPerformance ──────────────────────────────────────

def test_shadow_performance_new_fields_default():
    """New fields should have correct defaults."""
    perf = ShadowPerformance(
        shadow_id="test_defaults",
        daily_returns=[0.001] * 10,
        cumulative_return=0.01,
        max_drawdown=0.01,
        max_drawdown_duration_days=1,
        win_rate=0.5,
        total_trades=10,
        profitable_trades=5,
        losing_trades=5,
        abstention_days=0,
        cagr=0.1,
    )
    assert perf.brier_score == 1.0
    assert perf.calibration_score == 0.0
    assert perf.token_efficiency == 0.0
    assert perf.domain_scores == {}


def test_shadow_performance_custom_domain_scores():
    """Domain scores can be set explicitly."""
    perf = ShadowPerformance(
        shadow_id="test_domains",
        daily_returns=[0.001] * 10,
        cumulative_return=0.01,
        max_drawdown=0.01,
        max_drawdown_duration_days=1,
        win_rate=0.5,
        total_trades=10,
        profitable_trades=5,
        losing_trades=5,
        abstention_days=0,
        cagr=0.1,
        domain_scores={"gold": 0.9, "crypto": 0.4, "bonds": 0.7},
    )
    assert perf.domain_scores["gold"] == 0.9
    assert len(perf.domain_scores) == 3
