"""Challenger Statistics — Statistical test helpers for challenger engine.

Wilcoxon signed-rank test, paired t-test, Calmar ratio computation,
and Calmar gate check. Extracted from challenger_engine.py to comply
with 500-line hard ceiling.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from scipy import stats

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB


def compute_wilcoxon(
    target_returns: list[float],
    challenger_returns: list[float],
) -> tuple[float, float]:
    """Wilcoxon signed-rank test (P2-3: non-parametric, handles fat tails).

    Tests H0: median difference = 0 vs H1: challenger > target.
    Uses normal approximation for sample sizes >= 20.
    """
    n = min(len(target_returns), len(challenger_returns))
    if n < 5:
        return (1.0, 0.0)

    # Compute paired differences
    diffs = [c - t for t, c in zip(target_returns[-n:], challenger_returns[-n:])]
    # Remove zeros (ties)
    diffs = [d for d in diffs if d != 0]
    if not diffs:
        return (1.0, 0.0)

    # Rank absolute differences
    abs_diffs = [abs(d) for d in diffs]
    ranked = sorted(range(len(abs_diffs)), key=lambda i: abs_diffs[i])
    ranks = [0] * len(abs_diffs)
    i = 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and abs_diffs[ranked[j]] == abs_diffs[ranked[i]]:
            j += 1
        avg_rank = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[ranked[k]] = avg_rank
        i = j

    # Sum of ranks for positive differences
    w_plus = sum(ranks[i] for i in range(len(diffs)) if diffs[i] > 0)
    n_eff = len(diffs)

    # Normal approximation
    mean_w = n_eff * (n_eff + 1) / 4
    std_w = (n_eff * (n_eff + 1) * (2 * n_eff + 1) / 24) ** 0.5

    if std_w == 0:
        return (1.0, float(w_plus))

    z = (w_plus - mean_w) / std_w
    # One-sided p-value: P(Z > z)
    pvalue = 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    return (max(0.0, min(1.0, pvalue)), float(w_plus))


def compute_paired_ttest(
    target_returns: list[float],
    challenger_returns: list[float],
    one_sided: bool = True,
) -> tuple[float, float, float]:
    """Compute paired t-test between target and challenger daily returns.

    Uses scipy.stats.ttest_rel for the calculation.

    Args:
        target_returns: Daily returns of the target shadow.
        challenger_returns: Daily returns of the challenger shadow.
        one_sided: If True, return one-sided p-value (H1: challenger > target).

    Returns:
        Tuple of (pvalue, t_statistic, mean_difference).
        pvalue is one-sided if one_sided=True.
    """
    if len(target_returns) != len(challenger_returns):
        raise ValueError(
            f"Return arrays must have same length: {len(target_returns)} vs {len(challenger_returns)}"
        )
    if len(target_returns) < 2:
        return (1.0, 0.0, 0.0)

    result = stats.ttest_rel(target_returns, challenger_returns)

    t_stat = result.statistic
    # ttest_rel computes target - challenger. Negative means challenger > target.
    pvalue_two_sided = result.pvalue

    if one_sided:
        if t_stat < 0:
            pvalue = pvalue_two_sided / 2.0
        else:
            pvalue = 1.0 - pvalue_two_sided / 2.0
    else:
        pvalue = pvalue_two_sided

    mean_diff = sum(target_returns) / len(target_returns) - sum(challenger_returns) / len(challenger_returns)

    return (pvalue, t_stat, mean_diff)


def compute_calmar_from_snapshots(
    state_db: "ShadowStateDB", shadow_id: str, days: int = 90
) -> float:
    """Compute Calmar ratio from snapshot history.

    Calmar = cumulative_return / max(|MDD|, 0.001), capped at 100.
    """
    snaps = state_db.get_snapshot_history(shadow_id, days=days)
    if not snaps:
        return 0.0

    # Use the most recent cumulative return
    latest = snaps[0]  # Most recent first (DESC order)
    cumulative_return = latest.cumulative_return_pct or 0.0
    max_drawdown = max(
        (s.max_drawdown_pct or 0.0 for s in snaps),
        default=0.001
    )

    mdd_floor = max(max_drawdown, 0.001)
    calmar = cumulative_return / mdd_floor
    return min(calmar, 100.0)


def check_calmar_gate(calmar: float, gate: float = 0.3) -> bool:
    """Check if a shadow's Calmar ratio passes the comparison gate.

    Args:
        calmar: The shadow's Calmar ratio.
        gate: Minimum Calmar threshold (default 0.3).

    Returns:
        True if Calmar > gate.
    """
    return calmar > gate
