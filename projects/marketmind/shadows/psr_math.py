"""Probabilistic Sharpe Ratio (PSR) — Bailey & Lopez de Prado (2012).

Pure Python implementation. Zero LLM calls. Uses scipy.stats.norm for the
standard normal CDF and inverse CDF.

PSR answers: "What is the probability that the observed Sharpe ratio exceeds
a given benchmark, accounting for non-normality (skewness, kurtosis)?"

References:
    Bailey, D. H., & Lopez de Prado, M. (2012).
    "The Sharpe Ratio Efficient Frontier." Journal of Risk, 15(2), 3-44.
"""
from __future__ import annotations

import math

from scipy.stats import norm


def psr(
    observed_sr: float,
    benchmark_sr: float,
    n: int,
    skewness: float,
    kurtosis: float,
) -> float:
    """Probabilistic Sharpe Ratio: Prob[SR > benchmark_SR].

    Computes the probability that the true Sharpe ratio exceeds the benchmark,
    accounting for non-normal return distributions via skewness and kurtosis.

    Formula (Bailey & Lopez de Prado, 2012, Eq. 14):
        θ = (SR̂ - SR*) * √n / √(1 - γ₃ * SR̂ + (γ₄ - 1)/4 * SR̂²)
        PSR = Φ(θ)

    where:
        SR̂  = observed Sharpe ratio
        SR*  = benchmark Sharpe ratio
        n    = number of observations
        γ₃   = skewness of returns
        γ₄   = kurtosis of returns (excess kurtosis + 3)
        Φ    = standard normal CDF

    Args:
        observed_sr: The sample Sharpe ratio (annualized).
        benchmark_sr: The benchmark Sharpe ratio to test against.
        n: Number of return observations.
        skewness: Sample skewness of the return distribution.
        kurtosis: Sample kurtosis of the return distribution
                  (NOT excess kurtosis — use regular kurtosis).

    Returns:
        Probability in [0.0, 1.0] that true SR exceeds benchmark SR.
        Returns 1.0 if observed_sr >> benchmark_sr (numerically).
        Returns 0.0 if observed_sr << benchmark_sr.
        Returns 0.5 if observed_sr ≈ benchmark_sr.

    Raises:
        ValueError: If n < 2 (need at least 2 observations).
    """
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")

    # Denominator: sqrt(1 - skew*SR̂ + (kurt-1)/4 * SR̂²)
    # This is the standard error adjustment for non-normality
    denominator_sq = 1.0 - skewness * observed_sr + (kurtosis - 1.0) / 4.0 * (observed_sr ** 2)

    if denominator_sq <= 0:
        # Degenerate case: distribution is too non-normal for valid PSR.
        # Fall back to what's numerically sensible.
        if observed_sr > benchmark_sr:
            return 1.0
        elif observed_sr < benchmark_sr:
            return 0.0
        return 0.5

    denominator = math.sqrt(denominator_sq)
    theta = (observed_sr - benchmark_sr) * math.sqrt(n) / denominator

    return float(norm.cdf(theta))


def min_track_length(
    sr: float,
    target_psr: float = 0.95,
    benchmark_sr: float = 0.0,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> int:
    """Minimum observations needed for PSR to exceed target_psr at given SR.

    Solves the PSR equation for n:
        Φ⁻¹(target_psr) = (SR - SR_bench) * √n / √(1 - γ₃*SR + (γ₄-1)/4 * SR²)
        => n = (z * √denom / (SR - SR_bench))²

    For daily returns, n represents trading days (~252/year).

    Args:
        sr: The annualized Sharpe ratio to test.
        target_psr: Desired PSR confidence level (default 0.95).
        benchmark_sr: Benchmark Sharpe ratio (default 0.0 = "better than zero skill").
        skewness: Expected skewness of returns (default 0.0 = symmetric).
        kurtosis: Expected kurtosis of returns (default 3.0 = normal).

    Returns:
        Minimum number of observations (rounded up to nearest integer).
        Returns 0 if sr <= benchmark_sr (no amount of data can prove skill).

    Raises:
        ValueError: If target_psr is not in (0, 1).
    """
    if not (0.0 < target_psr < 1.0):
        raise ValueError(f"target_psr must be in (0, 1), got {target_psr}")

    if sr <= benchmark_sr:
        return 0

    z = norm.ppf(target_psr)
    # Denominator adjustment for non-normality
    denom = 1.0 - skewness * sr + (kurtosis - 1.0) / 4.0 * (sr ** 2)

    if denom <= 0:
        return 0

    n = ((z * math.sqrt(denom)) / (sr - benchmark_sr)) ** 2
    return math.ceil(max(n, 2))


def deflated_sharpe(
    sr: float,
    n: int,
    skew: float,
    kurt: float,
    n_trials: int = 100,
) -> float:
    """Deflated Sharpe Ratio with haircut for multiple testing.

    When testing many strategies, the expected maximum SR under the null
    hypothesis grows with the number of trials. The Deflated SR applies a
    haircut based on extreme value theory to account for this selection bias.

    Formula (Bailey & Lopez de Prado, 2014):
        E[max(SR)] ≈ √(Var(SR)) * √(2 * log(N))
        SR_deflated = PSR(SR, E[max(SR)], n, skew, kurt)

    where E[max(SR)] is the expected maximum SR from N independent trials
    under the null of zero skill.

    Args:
        sr: Observed Sharpe ratio (annualized).
        n: Number of return observations.
        skew: Skewness of returns.
        kurt: Kurtosis of returns (NOT excess kurtosis).
        n_trials: Number of independent strategies/trials tested (default 100).

    Returns:
        Deflated Sharpe ratio confidence (0.0-1.0). This is the probability
        that the observed SR exceeds the expected maximum from n_trials trials
        of unskilled strategies. High values (>0.95) suggest genuine skill
        rather than selection bias.

    Raises:
        ValueError: If n_trials < 1.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")

    if n_trials == 1:
        # No multiple testing concern — use benchmark SR of 0
        return psr(sr, 0.0, n, skew, kurt)

    # Expected maximum SR under null (extreme value theory)
    # Var(SR) ≈ 1/n for i.i.d. normal returns
    # But we adjust for non-normality via the denominator from PSR
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * (sr ** 2)
    if denom <= 0:
        denom = 1.0

    # Standard error of SR estimate
    se_sr = math.sqrt(denom / n)

    # Expected maximum SR from N trials (extreme value theory approximation)
    # For large N: E[max] ≈ σ * √(2 * log(N))
    expected_max_sr = se_sr * math.sqrt(2.0 * math.log(n_trials))

    # PSR against the expected maximum of null trials
    return psr(sr, expected_max_sr, n, skew, kurt)


def sharpe_ratio(returns: list[float], annualize: bool = True,
                 periods_per_year: int = 252) -> float:
    """Compute Sharpe ratio from a list of periodic returns.

    Args:
        returns: List of periodic return values (e.g. daily returns).
        annualize: If True, multiply by sqrt(periods_per_year).
        periods_per_year: Number of periods in a year (default 252 for daily).

    Returns:
        Sharpe ratio. Returns 0.0 if fewer than 2 returns or zero variance.
    """
    if len(returns) < 2:
        return 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)

    if variance <= 0:
        return 0.0

    sr_period = mean / math.sqrt(variance)
    if annualize:
        return sr_period * math.sqrt(periods_per_year)
    return sr_period


def skewness(returns: list[float]) -> float:
    """Compute sample skewness of a return series.

    Args:
        returns: List of periodic returns.

    Returns:
        Sample skewness. Returns 0.0 if fewer than 3 returns or zero variance.
    """
    n = len(returns)
    if n < 3:
        return 0.0

    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m3 = sum((r - mean) ** 3 for r in returns) / n

    if m2 <= 0:
        return 0.0

    # Sample skewness (adjusted for bias)
    return (m3 / (m2 ** 1.5)) * math.sqrt(n * (n - 1)) / (n - 2)


def kurtosis(returns: list[float]) -> float:
    """Compute sample kurtosis of a return series (NOT excess kurtosis).

    For a normal distribution, kurtosis ≈ 3.0. Values > 3 indicate
    fat tails (leptokurtic).

    Args:
        returns: List of periodic returns.

    Returns:
        Sample kurtosis (pearson kurtosis, not excess).
        Returns 3.0 if fewer than 4 returns or zero variance.
    """
    n = len(returns)
    if n < 4:
        return 3.0

    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n

    if m2 <= 0:
        return 3.0

    # Sample kurtosis (pearson, NOT excess)
    # Bias-adjusted: G2 = ((n+1)*g2 + 6) * (n-1)/((n-2)*(n-3))
    # where g2 = m4/m2^2 - 3 (excess)
    excess_g2 = m4 / (m2 ** 2) - 3.0
    g2 = ((n + 1) * excess_g2 + 6.0) * (n - 1) / ((n - 2) * (n - 3))
    # Convert excess to pearson kurtosis
    return g2 + 3.0


def psr_from_returns(
    returns: list[float],
    benchmark_sr: float = 0.0,
    annualize: bool = True,
    periods_per_year: int = 252,
) -> float:
    """Convenience: compute PSR directly from a return series.

    Computes SR, skewness, and kurtosis from the returns, then calls psr().

    Args:
        returns: List of periodic returns (e.g. daily).
        benchmark_sr: Benchmark Sharpe ratio (default 0.0).
        annualize: If True, annualize the Sharpe ratio.
        periods_per_year: Periods per year (default 252).

    Returns:
        PSR probability in [0.0, 1.0].
    """
    sr = sharpe_ratio(returns, annualize=annualize, periods_per_year=periods_per_year)
    sk = skewness(returns)
    ku = kurtosis(returns)
    return psr(sr, benchmark_sr, len(returns), sk, ku)
