"""Statistical tests -- walk-forward validation, Sharpe estimation, reset eligibility checks.

Zero LLM calls. All computation is deterministic mathematical formulas.
Extracted from ranking_engine.py to comply with 500-line hard ceiling.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from scipy import stats as scipy_stats

logger = logging.getLogger("marketmind.shadows.ranking_stats")


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
