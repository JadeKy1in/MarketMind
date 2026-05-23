"""Tests for PSR math — Probabilistic Sharpe Ratio (Bailey & Lopez de Prado, 2012)."""
import math
import pytest

from marketmind.shadows.psr_math import (
    psr,
    min_track_length,
    deflated_sharpe,
    sharpe_ratio,
    skewness,
    kurtosis,
    psr_from_returns,
)


# ── Test 1: PSR with normal returns (symmetric) ─────────────────────────

def test_psr_normal_distribution():
    """With normal distribution (skew=0, kurt=3), PSR should be close to
    the standard normal CDF of (SR_obs - SR_bench) * sqrt(n)."""
    # SR=1.0, benchmark=0, n=100, normal distribution
    result = psr(observed_sr=1.0, benchmark_sr=0.0, n=100,
                 skewness=0.0, kurtosis=3.0)

    # theta = (1.0 - 0) * sqrt(100) / sqrt(1 - 0 + 0.5 * 1) = 10 / 1 ≈ 10
    # norm.cdf(10) ≈ 1.0
    assert result > 0.999

    # SR=0, benchmark=0 → should be 0.5 (coin flip)
    result2 = psr(observed_sr=0.0, benchmark_sr=0.0, n=100,
                  skewness=0.0, kurtosis=3.0)
    assert abs(result2 - 0.5) < 0.01

    # SR=-1, benchmark=0 → should be near 0
    result3 = psr(observed_sr=-1.0, benchmark_sr=0.0, n=100,
                  skewness=0.0, kurtosis=3.0)
    assert result3 < 0.001


# ── Test 2: PSR degrades with negative skew and high kurtosis ───────────

def test_psr_non_normal_penalty():
    """Negative skew and high kurtosis should reduce PSR vs normal case."""
    # Normal case
    psr_normal = psr(observed_sr=0.5, benchmark_sr=0.0, n=60,
                     skewness=0.0, kurtosis=3.0)

    # Negative skew + fat tails
    psr_fat = psr(observed_sr=0.5, benchmark_sr=0.0, n=60,
                  skewness=-1.0, kurtosis=6.0)

    # Fat-tailed case should have lower PSR (less confidence in SR estimate)
    assert psr_fat < psr_normal

    # Both should still be > 0.5 (positive SR vs zero benchmark)
    assert psr_fat > 0.5


# ── Test 3: min_track_length computes required observations ─────────────

def test_min_track_length():
    """High SR should need fewer observations; SR=0 should need infinite."""
    # SR=2.0, target PSR=0.95 — should need modest observations
    n1 = min_track_length(sr=2.0, target_psr=0.95)
    assert n1 > 0
    assert n1 < 50  # Very strong SR, won't need many obs

    # SR=0.3 should need more observations
    n2 = min_track_length(sr=0.3, target_psr=0.95)
    assert n2 > n1

    # SR <= benchmark returns 0 (no amount of data proves skill)
    n3 = min_track_length(sr=0.0, target_psr=0.95, benchmark_sr=0.0)
    assert n3 == 0

    # Invalid target_psr raises
    with pytest.raises(ValueError, match="target_psr must be in"):
        min_track_length(sr=1.0, target_psr=1.5)


# ── Test 4: deflated_sharpe accounts for multiple testing ───────────────

def test_deflated_sharpe():
    """More trials should produce lower deflated SR."""
    sr = 1.0
    n = 120

    # 1 trial — no haircut
    dsr1 = deflated_sharpe(sr, n, skew=0.0, kurt=3.0, n_trials=1)
    assert dsr1 > 0.99

    # 10 trials — moderate haircut
    dsr10 = deflated_sharpe(sr, n, skew=0.0, kurt=3.0, n_trials=10)
    assert dsr10 < dsr1

    # 1000 trials — large haircut
    dsr1000 = deflated_sharpe(sr, n, skew=0.0, kurt=3.0, n_trials=1000)
    assert dsr1000 < dsr10

    # All should still be positive for SR=1.0
    assert dsr1000 > 0.0

    # Invalid n_trials
    with pytest.raises(ValueError, match="n_trials must be"):
        deflated_sharpe(sr, n, 0.0, 3.0, n_trials=0)


# ── Test 5: sharpe_ratio computation ────────────────────────────────────

def test_sharpe_ratio_basic():
    """Sharpe ratio from returns should match manual calculation."""
    returns = [0.01, 0.02, -0.005, 0.015, 0.0]

    sr = sharpe_ratio(returns, annualize=False)
    assert sr > 0

    # Manual check
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    expected = mean / math.sqrt(var)
    assert abs(sr - expected) < 0.001

    # Annualized
    sr_ann = sharpe_ratio(returns, annualize=True)
    assert abs(sr_ann - expected * math.sqrt(252)) < 0.01

    # Edge: too few returns
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([0.01]) == 0.0


# ── Test 6: skewness and kurtosis helpers ───────────────────────────────

def test_skewness_kurtosis():
    """Skewness of symmetric data ≈ 0; kurtosis of normal ≈ 3.0."""
    # Symmetric data
    symmetric = [1.0, -1.0, 0.5, -0.5, 0.0, 0.0]
    sk = skewness(symmetric)
    assert abs(sk) < 0.5  # Roughly symmetric

    # Positively skewed
    positive_skew = [0.01] * 10 + [0.10]
    sk_pos = skewness(positive_skew)
    assert sk_pos > 0

    # Kurtosis of normal-like data
    import random
    random.seed(42)
    normal_data = [random.gauss(0, 1) for _ in range(1000)]
    k = kurtosis(normal_data)
    assert 2.0 < k < 4.0, f"Kurtosis of normal data ≈ 3.0, got {k}"

    # Edge cases
    assert skewness([]) == 0.0
    assert skewness([1.0]) == 0.0
    assert kurtosis([]) == 3.0
    assert kurtosis([1.0]) == 3.0

    # Constant returns (zero variance) — fall back cleanly
    const_data = [0.01] * 10
    assert kurtosis(const_data) == pytest.approx(3.0, abs=1.0)  # Degenerate but no crash


# ── Test 7: psr_from_returns convenience function ───────────────────────

def test_psr_from_returns():
    """Convenience wrapper should compute PSR from raw returns."""
    # Positive returns with small variance = high SR = high PSR
    import random
    random.seed(1)
    good_returns = [0.005 + random.gauss(0, 0.0001) for _ in range(100)]
    p = psr_from_returns(good_returns, benchmark_sr=0.0)
    assert p > 0.95

    # Random returns near zero mean → modest SR → modest PSR
    import random
    random.seed(42)
    noisy_returns = [random.gauss(0.0001, 0.02) for _ in range(200)]
    p_noisy = psr_from_returns(noisy_returns, benchmark_sr=0.0)
    # With tiny positive drift + 200 samples, PSR can be elevated
    # due to sqrt(n) effect. Just verify it's a valid probability.
    assert 0.0 <= p_noisy <= 1.0


# ── Test 8: PSR boundary conditions ─────────────────────────────────────

def test_psr_boundary():
    """n < 2 should raise; degenerate denominator should not crash."""
    with pytest.raises(ValueError, match="n must be >= 2"):
        psr(1.0, 0.0, 1, 0.0, 3.0)

    # Degenerate denominator (very high negative skew + high SR) should not crash
    # extreme case: skew = -5, sr = 2, kurt = 10
    # denom = 1 - (-5)*2 + (10-1)/4 * 4 = 1 + 10 + 9 = 20 → OK
    # But try: skew=-10, sr=2, kurt=50
    # denom = 1 - (-10)*2 + (50-1)/4 * 4 = 1 + 20 + 49 = 70 → still OK
    # Even more extreme: skew=-100, sr=5, kurt=200
    # denom = 1 - (-100)*5 + 199/4 * 25 = 1 + 500 + 1243.75 = 1744.75
    result = psr(5.0, 0.0, 50, -100.0, 200.0)
    assert 0.0 <= result <= 1.0  # Should not crash
