"""Tests for stagnation detection — CUSUM, PSI, trend, composite."""
from marketmind.evolution.stagnation_detector import (
    compute_cusum, compute_psi, linear_trend_pvalue,
    composite_stagnation_score, stagnation_grade,
)


def test_cusum_stable_zero():
    assert compute_cusum([0.1, 0.1, 0.1, 0.1, 0.1]) < 0.1


def test_cusum_decline_detected():
    score = compute_cusum([0.5, 0.4, 0.3, 0.2, 0.1])
    assert score > 0.3


def test_psi_identical_zero():
    vals = [0.1, 0.2, 0.3, 0.1, 0.2]
    assert compute_psi(vals, vals) < 0.01


def test_psi_drift_detected():
    assert compute_psi([0.1] * 10, [0.5] * 10) > 0.25


def test_linear_trend_plateau():
    p = linear_trend_pvalue([0.5, 0.52, 0.48, 0.51, 0.49])
    assert p > 0.05


def test_trend_upward():
    p = linear_trend_pvalue([0.1, 0.2, 0.3, 0.4, 0.5])
    assert p < 0.05


def test_composite_low_scores_green():
    score = composite_stagnation_score(0.1, 0.05, 0.02)
    assert stagnation_grade(score) == "green"


def test_stagnation_grade_boundaries():
    assert stagnation_grade(0.1) == "green"
    assert stagnation_grade(0.5) == "yellow"
    assert stagnation_grade(0.8) == "red"
