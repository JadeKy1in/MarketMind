"""Signal resonance: DSR/CSCV statistical framework — pure Python computation, no LLM."""
from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class ResonanceResult:
    passed: bool
    dsr: float                     # Deflated Sharpe Ratio
    pbo: float                     # Probability of Backtest Overfitting
    forward_validation_ratio: float  # out-of-sample / in-sample performance
    signal_count: int
    dimensions_active: list[str]   # which dimensions contributed
    verdict: str                   # "STRONG_SIGNAL" | "WEAK_SIGNAL" | "NO_SIGNAL" | "INSUFFICIENT_DATA"


def compute_returns(price_series: list[float]) -> list[float]:
    """Compute log returns from price series."""
    if len(price_series) < 2:
        return []
    return [math.log(price_series[i] / price_series[i - 1]) for i in range(1, len(price_series))]


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if not returns or len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns) - risk_free / 252
    variance = sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    daily_sr = mean_ret / math.sqrt(variance)
    return daily_sr * math.sqrt(252)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    sharpe_distribution: list[float],
) -> float:
    """DSR = Φ((SR_obs - E[max(SR)]) / std(max(SR)))

    Corrects for selection bias from trying multiple strategies.
    Returns probability that observed Sharpe is statistically significant.
    """
    if not sharpe_distribution or len(sharpe_distribution) < 2:
        return 0.5
    max_sharpes = sorted(sharpe_distribution, reverse=True)[:n_trials]
    if not max_sharpes:
        return 0.5
    e_max = sum(max_sharpes) / len(max_sharpes)
    var_max = sum((s - e_max) ** 2 for s in max_sharpes) / (len(max_sharpes) - 1) if len(max_sharpes) > 1 else 1.0
    std_max = math.sqrt(var_max) if var_max > 0 else 1.0
    z_score = (observed_sharpe - e_max) / std_max
    # Normal CDF approximation
    return 0.5 * (1 + math.erf(z_score / math.sqrt(2)))


def cscv_pbo(
    returns: list[float],
    n_splits: int = 10,
) -> float:
    """Combinatorially Symmetric Cross-Validation — Probability of Backtest Overfitting.

    Splits returns into train/test combinations, measures rank correlation
    between in-sample and out-of-sample performance.
    PBO > 0.10 is treated as "no signal" per design spec §4.0.
    """
    n = len(returns)
    if n < 4:
        return 1.0  # insufficient data → likely overfit

    split_size = n // 2
    if split_size < 2:
        return 1.0

    is_sharpes: list[float] = []
    os_sharpes: list[float] = []

    for trial_idx in range(min(n_splits, n - split_size)):
        # Simple sequential split with rotation
        start = trial_idx % (n - split_size + 1)
        in_sample = returns[start:start + split_size]
        out_sample = returns[:start] + returns[start + split_size:]
        if len(in_sample) >= 2 and len(out_sample) >= 2:
            is_sharpes.append(sharpe_ratio(in_sample))
            os_sharpes.append(sharpe_ratio(out_sample))

    if len(is_sharpes) < 2:
        return 1.0

    # Spearman rank correlation between IS and OOS Sharpe
    is_ranks = _rank(is_sharpes)
    os_ranks = _rank(os_sharpes)
    rho = _spearman_rho(is_ranks, os_ranks)

    # PBO = proportion of trials where IS rank negatively correlates with OOS
    # High negative correlation → overfitting
    if rho < -0.3:
        return 0.7 + abs(rho) * 0.3
    elif rho < 0:
        return 0.5 + abs(rho) * 0.3
    else:
        return max(0.0, 0.5 - rho * 0.5)


def _rank(values: list[float]) -> list[float]:
    """Return percentile ranks [0, 1]."""
    if not values:
        return []
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return [(sorted_vals.index(v) + 1) / n for v in values]


def _spearman_rho(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation."""
    n = len(x)
    if n < 2:
        return 0.0
    d2 = sum((x[i] - y[i]) ** 2 for i in range(n))
    return 1 - (6 * d2) / (n * (n ** 2 - 1))


def evaluate_resonance(
    signal_returns: dict[str, list[float]],
    dimensions: list[str],
    observed_sharpe: float,
    n_trials: int = 100,
) -> ResonanceResult:
    """Evaluate signal resonance through DSR and CSCV/PBO framework.

    Args:
        signal_returns: {dimension_name: historical_returns} for each active dimension
        dimensions: which dimensions are contributing to this signal
        observed_sharpe: the Sharpe ratio of the combined signal
        n_trials: number of trials for multiplicity correction
    """
    if not dimensions:
        return ResonanceResult(
            passed=False, dsr=0, pbo=1.0, forward_validation_ratio=0,
            signal_count=0, dimensions_active=[], verdict="NO_SIGNAL"
        )

    # Build Sharpe distribution from individual dimensions for DSR
    sharpe_dist: list[float] = []
    all_returns: list[float] = []
    for dim in dimensions:
        rets = signal_returns.get(dim, [])
        if rets:
            sharpe_dist.append(sharpe_ratio(rets))
            all_returns.extend(rets)

    dsr = deflated_sharpe_ratio(observed_sharpe, n_trials, sharpe_dist)
    pbo = cscv_pbo(all_returns, n_splits=min(10, len(all_returns) // 2))

    # Forward validation: compare last 30 days (OOS) vs earlier (IS)
    split = max(1, len(all_returns) - 30)
    is_rets = all_returns[:split]
    os_rets = all_returns[split:]
    is_sharpe = sharpe_ratio(is_rets) if len(is_rets) >= 2 else 0
    os_sharpe = sharpe_ratio(os_rets) if len(os_rets) >= 2 else 0
    fwd_ratio = (os_sharpe / is_sharpe) if is_sharpe > 0 else 0

    # Verdict
    passed = dsr > 0 and pbo <= 0.10 and fwd_ratio >= 0.5
    if passed and dsr > 0.5 and pbo < 0.05:
        verdict = "STRONG_SIGNAL"
    elif passed:
        verdict = "WEAK_SIGNAL"
    else:
        verdict = "NO_SIGNAL"

    return ResonanceResult(
        passed=passed,
        dsr=round(dsr, 4),
        pbo=round(pbo, 4),
        forward_validation_ratio=round(fwd_ratio, 4),
        signal_count=len(dimensions),
        dimensions_active=dimensions,
        verdict=verdict,
    )
