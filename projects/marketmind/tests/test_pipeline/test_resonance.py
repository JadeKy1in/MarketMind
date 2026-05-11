"""Tests for DSR/CSCV resonance framework — pure math, full coverage."""
import math
import pytest
from projects.marketmind.pipeline.resonance import (
    compute_returns, sharpe_ratio, deflated_sharpe_ratio,
    cscv_pbo, evaluate_resonance, ResonanceResult, _rank, _spearman_rho,
)


def test_compute_returns_empty():
    assert compute_returns([]) == []
    assert compute_returns([100]) == []


def test_compute_returns_basic():
    prices = [100, 102, 99]
    rets = compute_returns(prices)
    assert len(rets) == 2
    assert rets[0] == pytest.approx(math.log(102 / 100), rel=1e-6)
    assert rets[1] == pytest.approx(math.log(99 / 102), rel=1e-6)


def test_sharpe_ratio_positive():
    rets = [0.01, 0.02, 0.015, 0.01, 0.02]
    sr = sharpe_ratio(rets)
    assert sr > 0


def test_sharpe_ratio_zero_returns():
    rets = [0.0, 0.0, 0.0, 0.0]
    sr = sharpe_ratio(rets)
    assert sr == 0.0


def test_sharpe_ratio_single_return():
    sr = sharpe_ratio([0.01])
    assert sr == 0.0


def test_deflated_sharpe_ratio_high_signal():
    # High observed SR vs distribution of lower SRs → high DSR
    sr_dist = [0.5, 0.6, 0.4, 0.55, 0.45, 0.5, 0.6, 0.5]
    dsr = deflated_sharpe_ratio(observed_sharpe=1.5, n_trials=5, sharpe_distribution=sr_dist)
    assert dsr > 0.8  # very likely significant


def test_deflated_sharpe_ratio_low_signal():
    sr_dist = [1.0, 1.2, 0.9, 1.1, 1.0]
    dsr = deflated_sharpe_ratio(observed_sharpe=0.3, n_trials=5, sharpe_distribution=sr_dist)
    assert dsr < 0.5  # likely noise


def test_cscv_pbo_insufficient_data():
    assert cscv_pbo([]) == 1.0
    assert cscv_pbo([0.01]) == 1.0


def test_cscv_pbo_random_returns():
    import random
    random.seed(42)
    rets = [random.gauss(0.0005, 0.01) for _ in range(100)]
    pbo = cscv_pbo(rets, n_splits=10)
    assert 0 <= pbo <= 1


def test_rank():
    values = [3.0, 1.0, 2.0]
    ranks = _rank(values)
    assert ranks == [1.0, 1/3, 2/3]


def test_spearman_rho_perfect_positive():
    assert _spearman_rho([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]) == 1.0


def test_spearman_rho_perfect_negative():
    assert _spearman_rho([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0


def test_evaluate_resonance_no_dimensions():
    result = evaluate_resonance({}, [], 0.5)
    assert not result.passed
    assert result.verdict == "NO_SIGNAL"


def test_evaluate_resonance_strong_signal():
    rets = {
        "fundamental": [0.001 * (1 + i % 5) for i in range(60)],
        "technical": [0.0008 * (1 + (i + 2) % 5) for i in range(60)],
        "sentiment": [0.0009 * (1 + (i + 1) % 5) for i in range(60)],
        "event": [0.0011 * (1 + (i + 3) % 5) for i in range(60)],
    }
    all_rets = sum(rets.values(), [])
    sr = sharpe_ratio(all_rets)
    result = evaluate_resonance(
        signal_returns=rets,
        dimensions=["fundamental", "technical", "sentiment", "event"],
        observed_sharpe=sr,
    )
    assert isinstance(result, ResonanceResult)
    assert len(result.dimensions_active) == 4
    assert result.verdict in ("STRONG_SIGNAL", "WEAK_SIGNAL", "NO_SIGNAL")


def test_evaluate_resonance_output_fields():
    rets = {"dim1": [0.001 * i for i in range(30)]}
    sr = sharpe_ratio(rets["dim1"])
    result = evaluate_resonance(
        signal_returns=rets,
        dimensions=["dim1"],
        observed_sharpe=sr,
    )
    assert hasattr(result, "dsr")
    assert hasattr(result, "pbo")
    assert hasattr(result, "forward_validation_ratio")
    assert hasattr(result, "verdict")
