"""Statistical computations — ranking metrics, walk-forward validation, reset checks.

Zero LLM calls. All computation is deterministic mathematical formulas.
Extracted from ranking_engine.py per modular architecture rules.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from scipy import stats as scipy_stats

logger = logging.getLogger("marketmind.shadows.ranking_stats")


# ── Ranking metrics (extracted from RankingEngine) ────────────────────


def compute_mppm(returns: list[float], gamma: float = 3.0) -> float:
    """Goetzmann et al. MPPM: (1/(1-gamma)) * ln((1/T) * sum((1+r_t)^(1-gamma)))."""
    if not returns or gamma == 1.0:
        return 0.0
    T = len(returns)
    exponent = 1.0 - gamma
    powered = [(1.0 + r) ** exponent for r in returns]
    avg = sum(powered) / T
    if avg <= 0:
        return float("-inf") if avg == 0 else float("nan")
    return (1.0 / exponent) * math.log(avg)


def compute_calmar(cumulative_return: float, max_drawdown: float) -> float:
    """Calmar = cumulative_return / max(|MDD|, 0.001). Capped at 100."""
    mdd_floor = max(max_drawdown, 0.001)
    calmar = cumulative_return / mdd_floor
    return min(calmar, 100.0)


def compute_omega(returns: list[float], threshold: float = 0.0) -> float:
    """Omega(L=0) = sum(gains) / sum(|losses|). Capped at 10."""
    if not returns:
        return 1.0
    gains = sum(max(r - threshold, 0) for r in returns)
    losses = sum(abs(min(r - threshold, 0)) for r in returns)
    if losses == 0:
        return 10.0
    omega = gains / losses
    return min(omega, 10.0)


def compute_cagr(cumulative_return: float, days: int) -> float:
    """Annualize cumulative return over N trading days."""
    if days <= 0:
        return 0.0
    return cumulative_return * 252 / days


def _mean_abs_correlation(daily_returns: dict[str, list[float]]) -> float | None:
    """Mean absolute pairwise correlation of shadow returns."""
    ids = list(daily_returns.keys())
    if len(ids) < 2:
        return None
    min_len = min(len(r) for r in daily_returns.values())
    if min_len < 5:
        return None
    corrs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ri = daily_returns[ids[i]][-min_len:]
            rj = daily_returns[ids[j]][-min_len:]
            mean_i = sum(ri) / min_len
            mean_j = sum(rj) / min_len
            cov = sum((a - mean_i) * (b - mean_j) for a, b in zip(ri, rj)) / min_len
            std_i = (sum((a - mean_i) ** 2 for a in ri) / min_len) ** 0.5
            std_j = (sum((b - mean_j) ** 2 for b in rj) / min_len) ** 0.5
            if std_i > 0 and std_j > 0:
                corrs.append(abs(cov / (std_i * std_j)))
    return sum(corrs) / len(corrs) if corrs else None


def compute_haircut(n_shadows: int, evaluation_days: int,
                    daily_returns: dict[str, list[float]] | None = None) -> float:
    """Witzany (2021) Bayesian overfitting haircut with Effective-N correction.

    If daily_returns is provided, estimates effective N from correlation matrix:
        Neff = N / (1 + (N-1) * mean_abs_corr)
    """
    if n_shadows < 1:
        n_shadows = 1
    n_eff = float(n_shadows)
    if daily_returns and len(daily_returns) >= 3:
        mean_corr = _mean_abs_correlation(daily_returns)
        if mean_corr is not None:
            n_eff = n_shadows / (1.0 + (n_shadows - 1) * mean_corr)
            n_eff = max(1.5, min(n_eff, float(n_shadows)))
    return evaluation_days / (evaluation_days + 8.0 + 24.0 * math.log(max(n_eff, 1.5)))


def apply_bayesian_haircut(composite_score: float, n_shadows: int,
                           evaluation_days: int) -> float:
    """C_deflated = C_raw * h(N,T)."""
    return composite_score * compute_haircut(n_shadows, evaluation_days)


def _empirical_percentiles(score_list: list[float]) -> dict[float, float]:
    """Fraction of scores <= x (with continuity correction)."""
    n = len(score_list)
    sorted_scores = sorted(score_list)
    result = {}
    for score in score_list:
        count_le = sum(1 for s in sorted_scores if s <= score)
        result[score] = (count_le - 0.5) / n
    return result


def _parametric_percentiles(score_list: list[float]) -> dict[float, float]:
    """Logistic-normal parametric percentile estimation for small N."""
    n = len(score_list)
    sorted_scores = sorted(score_list)
    result = {}
    for score in score_list:
        rank = sum(1 for s in sorted_scores if s <= score)
        p = (rank - 0.5) / n
        result[score] = 1.0 / (1.0 + math.exp(-2.0 * (p - 0.5) * math.sqrt(n)))
    return result


def compute_percentile_ranks(scores: dict[str, float],
                              parametric_threshold_n: int = 30) -> dict[str, float]:
    """Map each shadow_id to its percentile rank (0-1) within the cohort.

    Hybrid: parametric for N <= 15, empirical for N >= threshold, blend between.
    """
    if not scores:
        return {}
    n = len(scores)
    score_list = list(scores.values())
    if n >= parametric_threshold_n:
        pct_map = _empirical_percentiles(score_list)
        return {sid: pct_map[scores[sid]] for sid in scores}
    elif n <= 15:
        pct_map = _parametric_percentiles(score_list)
        return {sid: pct_map[scores[sid]] for sid in scores}
    else:
        alpha = n / parametric_threshold_n
        emp = _empirical_percentiles(score_list)
        par = _parametric_percentiles(score_list)
        return {
            sid: alpha * emp[scores[sid]] + (1 - alpha) * par[scores[sid]]
            for sid in scores
        }


# ── Sharpe estimation ────────────────────────────────────────────────


@dataclass
class WFValidationResult:
    """Walk-forward validation result for a single shadow."""
    shadow_id: str
    is_overfit: bool
    wfe_ratio: float
    mean_is_deflated: float
    mean_oos_deflated: float
    oos_directional_accuracy: float
    binomial_p_value: float
    total_windows: int
    skipped: bool
    skip_reason: str = ""


class WalkForwardValidator:
    """AlgoXpert IS-WFA-OOS protocol (Pham, Mar 2026) + HypoDriven (Deep et al., Dec 2025).

    Detects overfitting by comparing in-sample vs out-of-sample performance
    using rolling walk-forward windows. A WFE ratio < 0.5 indicates the shadow's
    historical performance does not generalize -- it is likely overfit.
    """

    def __init__(self, train_days: int = 90, purge_days: int = 2, test_days: int = 20,
                 overfit_threshold: float = 0.5, min_career_days: int = 120):
        self.train_days = train_days
        self.purge_days = purge_days
        self.test_days = test_days
        self.window_size = train_days + purge_days + test_days
        self.overfit_threshold = overfit_threshold
        self.min_career_days = min_career_days

    def validate(self, shadow_id: str,
                 snapshots: list["DailySnapshot"],
                 market_returns: dict[str, float] | None = None) -> WFValidationResult:
        """Run walk-forward validation on a shadow's snapshot history.

        Requires snapshots to have `date`, `deflated_score`, and `daily_return_pct`.

        If market_returns is provided (P2-4 audit fix: breaks circularity),
        directional accuracy is measured against actual market returns instead
        of the shadow's own virtual PnL. Without it, directional accuracy is
        based on the shadow's own returns (internal consistency only).
        """
        if len(snapshots) < self.min_career_days:
            return WFValidationResult(
                shadow_id=shadow_id, is_overfit=False, wfe_ratio=1.0,
                mean_is_deflated=0.0, mean_oos_deflated=0.0,
                oos_directional_accuracy=0.5, binomial_p_value=1.0,
                total_windows=0, skipped=True,
                skip_reason=f"insufficient_career: {len(snapshots)} < {self.min_career_days}"
            )

        if len(snapshots) < self.window_size:
            return WFValidationResult(
                shadow_id=shadow_id, is_overfit=False, wfe_ratio=1.0,
                mean_is_deflated=0.0, mean_oos_deflated=0.0,
                oos_directional_accuracy=0.5, binomial_p_value=1.0,
                total_windows=0, skipped=True,
                skip_reason=f"insufficient_data: {len(snapshots)} < {self.window_size} window"
            )

        # Sort snapshots by date ascending
        sorted_snaps = sorted(snapshots, key=lambda s: s.date)

        is_deflated_means: list[float] = []
        oos_deflated_means: list[float] = []
        oos_directions: list[int] = []  # 1=positive return, 0=negative

        start = 0
        while start + self.window_size <= len(sorted_snaps):
            is_window = sorted_snaps[start:start + self.train_days]
            # purge window is skipped to avoid data leakage
            oos_start = start + self.train_days + self.purge_days
            oos_window = sorted_snaps[oos_start:start + self.window_size]

            is_scores = [s.deflated_score for s in is_window
                        if s.deflated_score is not None]
            oos_scores = [s.deflated_score for s in oos_window
                         if s.deflated_score is not None]

            if is_scores and oos_scores:
                is_deflated_means.append(sum(is_scores) / len(is_scores))
                oos_deflated_means.append(sum(oos_scores) / len(oos_scores))
                # P2-4 audit fix: use market returns for directional accuracy
                # when available, to break circularity with shadow's own PnL
                for s in oos_window:
                    if market_returns and s.date in market_returns:
                        mr = market_returns[s.date]
                        oos_directions.append(1 if mr > 0 else 0)
                    elif s.daily_return_pct is not None:
                        oos_directions.append(1 if s.daily_return_pct > 0 else 0)

            start += 1  # Walk forward 1 day at a time

        if not is_deflated_means:
            return WFValidationResult(
                shadow_id=shadow_id, is_overfit=False, wfe_ratio=1.0,
                mean_is_deflated=0.0, mean_oos_deflated=0.0,
                oos_directional_accuracy=0.5, binomial_p_value=1.0,
                total_windows=0, skipped=True,
                skip_reason="no_valid_windows"
            )

        mean_is = sum(is_deflated_means) / len(is_deflated_means)
        mean_oos = sum(oos_deflated_means) / len(oos_deflated_means)

        # Skip check if IS deflated near zero (shadow has negligible signal)
        if abs(mean_is) <= 0.001:
            safe_denom = max(abs(mean_is), 0.001)
            return WFValidationResult(
                shadow_id=shadow_id, is_overfit=False,
                wfe_ratio=mean_oos / safe_denom,
                mean_is_deflated=mean_is, mean_oos_deflated=mean_oos,
                oos_directional_accuracy=0.5, binomial_p_value=1.0,
                total_windows=len(is_deflated_means), skipped=True,
                skip_reason="near_zero_is"
            )

        wfe_ratio = mean_oos / mean_is if mean_is != 0 else float("inf")
        is_overfit = wfe_ratio < self.overfit_threshold

        oos_accuracy = (sum(oos_directions) / len(oos_directions)
                       if oos_directions else 0.5)
        p_value = self._binomial_sign_test(oos_directions)

        return WFValidationResult(
            shadow_id=shadow_id, is_overfit=is_overfit, wfe_ratio=wfe_ratio,
            mean_is_deflated=mean_is, mean_oos_deflated=mean_oos,
            oos_directional_accuracy=oos_accuracy, binomial_p_value=p_value,
            total_windows=len(is_deflated_means), skipped=False, skip_reason=""
        )

    @staticmethod
    def _binomial_sign_test(successes: list[int]) -> float:
        """Two-sided binomial test: probability of >= observed under H0: p=0.5.

        Uses scipy.stats.binomtest for exact computation.
        """
        if not successes:
            return 1.0
        n = len(successes)
        k = sum(successes)
        result = scipy_stats.binomtest(k, n, p=0.5, alternative="two-sided")
        return float(result.pvalue)


def estimate_sharpe(returns: list[float]) -> float:
    """Estimate annualized Sharpe from daily returns."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    daily_sharpe = mean / math.sqrt(variance)
    return daily_sharpe * math.sqrt(252)


def check_reset_eligibility(
    config,  # ShadowSettings
    tier_history: list[tuple[str, str]],     # (date, tier)
    wr_history: list[tuple[str, float]],      # (date, win_rate)
    insight_dates: list[str],                  # dates with insights
) -> tuple[bool, str]:
    """Check if a shadow should be reset to baseline methodology.

    Three conditions must ALL be met:
    1. No EXCELLENT or higher in reset_no_excellent_months
    2. Win rate fluctuation < +-5% for reset_flat_wr_months
    3. No insight produced in reset_no_insight_months

    Returns (should_reset, reason).
    """
    today = datetime.now(timezone.utc).date()
    months_ago_6 = today - timedelta(days=config.reset_no_excellent_months * 30)
    months_ago_3 = today - timedelta(days=config.reset_flat_wr_months * 30)
    insight_cutoff = today - timedelta(days=config.reset_no_insight_months * 30)

    # Condition 1: No EXCELLENT in N months
    has_excellent = False
    for date_str, tier in tier_history:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d >= months_ago_6 and tier in ("excellent", "elite"):
                has_excellent = True
                break
        except ValueError:
            continue

    if has_excellent:
        return False, ""

    # Condition 2: WR flat for N months
    recent_wr: list[float] = []
    for date_str, wr in wr_history:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d >= months_ago_3:
                recent_wr.append(wr)
        except ValueError:
            continue

    wr_range = 0.0
    if recent_wr and len(recent_wr) >= 5:
        wr_range = max(recent_wr) - min(recent_wr)
        if wr_range > 0.05:
            return False, ""

    # Condition 3: No insight in N months
    has_insight = any(
        datetime.strptime(d, "%Y-%m-%d").date() >= insight_cutoff
        for d in insight_dates
    )

    if not has_insight and (not recent_wr or len(recent_wr) < 5 or wr_range <= 0.05):
        return True, (
            f"No EXCELLENT tier in {config.reset_no_excellent_months} months, "
            f"WR range {max(recent_wr)-min(recent_wr):.2%} in "
            f"{config.reset_flat_wr_months} months, "
            f"no insight in {config.reset_no_insight_months} months"
        )

    return False, ""
