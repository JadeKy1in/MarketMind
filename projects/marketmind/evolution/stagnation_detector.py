"""Stagnation detection: CUSUM, PSI, linear trend → composite score."""
from __future__ import annotations
import math


def compute_cusum(values: list[float], target_mean: float | None = None) -> float:
    """CUSUM deviation score (0-1). High = sustained shift detected."""
    if len(values) < 4:
        return 0.0
    mean = target_mean if target_mean is not None else sum(values) / len(values)
    cusum = 0.0
    max_deviation = 0.0
    for v in values:
        cusum += v - mean
        max_deviation = max(max_deviation, abs(cusum))
    if max_deviation == 0:
        return 0.0
    n = len(values)
    variance = sum((v - mean) ** 2 for v in values) / n
    if variance == 0:
        return 0.0
    std = math.sqrt(variance)
    expected_random_walk = std * math.sqrt(n)
    return min(max_deviation / expected_random_walk, 1.0)


def compute_psi(baseline: list[float], current: list[float], bins: int = 5) -> float:
    """Population Stability Index. PSI > 0.25 = significant drift."""
    if len(baseline) < 2 or len(current) < 2:
        return 0.0
    all_vals = baseline + current
    min_v, max_v = min(all_vals), max(all_vals)
    if max_v == min_v:
        return 0.0
    bin_width = (max_v - min_v) / bins
    psi = 0.0
    for i in range(bins):
        low = min_v + i * bin_width
        high = low + bin_width
        b_pct = sum(1 for v in baseline if low <= v < high) / len(baseline) + 0.0001
        c_pct = sum(1 for v in current if low <= v < high) / len(current) + 0.0001
        psi += (c_pct - b_pct) * math.log(c_pct / b_pct)
    return psi


def linear_trend_pvalue(values: list[float]) -> float:
    """Approximate two-tailed p-value for slope=0. p > 0.05 = plateau."""
    n = len(values)
    if n < 3:
        return 1.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    xy_cov = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    x_var = sum((i - x_mean) ** 2 for i in range(n))
    if x_var == 0:
        return 1.0
    slope = xy_cov / x_var
    residuals = [v - (slope * i + (y_mean - slope * x_mean)) for i, v in enumerate(values)]
    rss = sum(r ** 2 for r in residuals)
    se = math.sqrt(rss / (n - 2)) if n > 2 else 1.0
    if se < 1e-10:
        return 0.0 if abs(slope) > 1e-10 else 1.0
    t_stat = abs(slope) / (se / math.sqrt(x_var))
    df = n - 2
    if df <= 0:
        return 1.0
    # Approximation from t-distribution
    x = df / (df + t_stat ** 2)
    p = 1 - _reg_beta(x, df / 2, 0.5) if 0 < x < 1 else 1.0
    return p


def _reg_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta (approximate)."""
    if x <= 0 or x >= 1:
        return x
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x))
    return front / a


def composite_stagnation_score(cusum_score: float, psi_score: float, trend_pvalue: float) -> float:
    """Combine three signals into 0-1 score. Higher = less active."""
    trend_signal = 1.0 if trend_pvalue > 0.05 else 0.0
    psi_signal = min(psi_score / 0.25, 1.0)
    return cusum_score * 0.33 + psi_signal * 0.33 + trend_signal * 0.34


def stagnation_grade(score: float) -> str:
    """Return stagnation grade: "green" (active), "yellow" (stable), "red" (idle)."""
    if score < 0.3:
        return "green"
    elif score < 0.6:
        return "yellow"
    else:
        return "red"
