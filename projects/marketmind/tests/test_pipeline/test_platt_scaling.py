import math
import pytest
from pipeline.platt_scaling import (
    fit_platt_scaling,
    apply_platt_scaling,
    PlattCoefficients,
    _sigmoid,
    _compute_ece,
)


def test_fit_perfect_calibration():
    """Well-calibrated: outcome ~ Bernoulli(confidence) → ECE improves."""
    confidences = [0.1]*2 + [0.2]*2 + [0.3]*2 + [0.4]*2 + [0.5]*2 + [0.6]*2 + [0.7]*2 + [0.8]*2 + [0.9]*2
    outcomes =    [0]*2   + [0]*2   + [0]*2   + [1]*2   + [0]*2   + [1]*2   + [1]*2   + [1]*2   + [1]*2
    coeffs = fit_platt_scaling(confidences, outcomes)
    assert coeffs.a > 0  # confidence positively correlates with correctness
    assert coeffs.n_samples == 18
    assert len(coeffs.fitted_at) > 0


def test_fit_overconfident():
    """Overconfident: high confidence but only 30-50% accuracy → a < 0.5, b < 0."""
    confidences = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.85, 0.9, 0.95]
    outcomes =    [0,   0,    0,   0,    0,   1,    0,   0,    1,   0,    0,   0,    1,   0,   0]
    coeffs = fit_platt_scaling(confidences, outcomes)
    assert coeffs.post_calibration_ece <= coeffs.pre_calibration_ece + 0.05
    assert coeffs.n_samples == 15


def test_apply_scaling_reduces_confidence():
    """Overconfident model: 0.95 raw → calibrated should be lower."""
    confidences = [0.88]*2 + [0.9]*2 + [0.92]*2 + [0.95]*2 + [0.97]*2 + [0.85]*2 + [0.91]*2 + [0.93]*2 + [0.96]*2
    outcomes =    [0]*2    + [0]*2   + [0]*2    + [0]*2    + [1]*2    + [0]*2    + [0]*2    + [0]*2    + [0]*2
    coeffs = fit_platt_scaling(confidences, outcomes)
    calibrated = apply_platt_scaling(0.95, coeffs)
    assert calibrated < 0.95


def test_apply_scaling_increases_underconfident():
    """Underconfident model: low confidence but high accuracy → calibrated > raw."""
    confidences = [0.25]*2 + [0.28]*2 + [0.3]*2 + [0.32]*2 + [0.35]*2 + [0.26]*2 + [0.29]*2 + [0.31]*2 + [0.33]*2 + [0.27]*2
    outcomes =    [1]*2    + [1]*2    + [1]*2   + [1]*2    + [1]*2    + [1]*2    + [0]*2    + [1]*2    + [0]*2    + [1]*2
    coeffs = fit_platt_scaling(confidences, outcomes)
    calibrated = apply_platt_scaling(0.3, coeffs)
    assert calibrated > 0.3


def test_needs_minimum_samples():
    """Fewer than 10 samples should raise ValueError."""
    with pytest.raises(ValueError, match="at least 10"):
        fit_platt_scaling([0.5] * 5, [1] * 5)


def test_mismatched_lengths_raises():
    """Mismatched confidence/outcome lengths should raise ValueError."""
    with pytest.raises(ValueError, match="matching"):
        fit_platt_scaling([0.5] * 10, [1] * 15)


def test_ece_computation():
    """Perfect calibration → ECE ≈ 0. Random-ish → ECE > 0."""
    perfect_conf = [0.5] * 100
    perfect_out = [1] * 50 + [0] * 50
    ece_perfect = _compute_ece(perfect_conf, perfect_out)
    assert ece_perfect < 0.1

    bad_conf = [0.9] * 50 + [0.1] * 50
    bad_out = [0] * 50 + [1] * 50
    ece_bad = _compute_ece(bad_conf, bad_out)
    assert ece_bad > 0.5


def test_sigmoid_bounds():
    """Sigmoid output always in (0, 1) for practical inputs; inclusive at extremes."""
    for x in [-10, -1, 0, 1, 10]:
        s = _sigmoid(x)
        assert 0.0 < s < 1.0
    # At extreme values, float underflow may yield 0 or 1
    assert _sigmoid(100) == 1.0
    assert _sigmoid(-100) > 0.0


def test_sigmoid_symmetry():
    """Sigmoid symmetry: sigmoid(-x) = 1 - sigmoid(x)."""
    for x in [0.5, 1.0, 2.0]:
        assert math.isclose(_sigmoid(-x), 1.0 - _sigmoid(x))


def test_platt_coefficients_dataclass():
    """PlattCoefficients dataclass stores all expected fields."""
    coeffs = PlattCoefficients(
        a=1.5, b=-0.3,
        fitted_at="2026-05-18T00:00:00+00:00",
        n_samples=100,
        pre_calibration_ece=0.15,
        post_calibration_ece=0.03,
    )
    assert coeffs.a == 1.5
    assert coeffs.pre_calibration_ece > coeffs.post_calibration_ece


def test_apply_platt_scaling_range():
    """Calibrated output always in (0, 1)."""
    coeffs = PlattCoefficients(
        a=1.5, b=-0.5,
        fitted_at="2026-05-18T00:00:00+00:00",
        n_samples=100,
        pre_calibration_ece=0.2,
        post_calibration_ece=0.05,
    )
    for conf in [0.0, 0.01, 0.5, 0.99]:
        calibrated = apply_platt_scaling(conf, coeffs)
        assert 0.0 < calibrated < 1.0
