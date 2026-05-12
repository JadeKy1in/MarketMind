"""Challenger Engine — 3-stage elimination buffer, secret challenger creation, paired t-test comparison.

Stage 1 (WARNING): 2 consecutive evaluation periods in bottom 20%
Stage 2 (CHALLENGER): 3 periods → secret challenger shadow created (invisible to rankings)
Stage 3 (COMPARISON): 2-week paired trial → paired t-test (one-sided, alpha=0.10) + Calmar gate (challenger > 0.3)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from scipy import stats

from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, DailySnapshot
)
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.challenger_engine")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class EliminationStage:
    """Current position in the 3-stage elimination pipeline."""
    shadow_id: str
    current_stage: int            # 0=none, 1=warning, 2=observation+challenger, 3=comparison
    consecutive_bottom_periods: int
    challenger_id: str | None = None


@dataclass
class ChallengerTrialResult:
    """Outcome of a challenger vs. target comparison trial."""
    challenger_id: str
    target_id: str
    challenger_mean_return: float
    target_mean_return: float
    paired_t_pvalue: float
    challenger_calmar: float
    target_calmar: float
    challenger_better: bool
    verdict: str  # "REPLACE_TARGET" | "RESTORE_TARGET" | "INCONCLUSIVE"


# ── Engine ──────────────────────────────────────────────────────────────────

class ChallengerEngine:
    """Manages the 3-stage elimination buffer for underperforming shadows.

    Stage 1: Warning (2 consecutive bottom-20% periods)
    Stage 2: Secret challenger created (3 consecutive bottom-20% periods)
    Stage 3: 2-week paired comparison trial with statistical gates

    Challenger opacity: created as shadow_type="challenger" with parent_shadow_id.
    get_visible_shadows() already excludes challengers (verified in B.0 tests).
    """

    # Bottom 20% threshold for elimination pipeline entry
    BOTTOM_PERCENTILE_THRESHOLD = 0.20

    # Stage transition thresholds
    STAGE1_PERIODS = 2   # 2 periods → warning
    STAGE2_PERIODS = 3   # 3 periods → challenger created
    STAGE3_WEEKS = 2     # 2-week paired trial

    # Default trial day count
    TRIAL_DAYS = 10      # 2 trading weeks

    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings):
        self.state_db = state_db
        self.settings = settings
        # Apply settings overrides if configured
        if settings.challenger_stage1_periods:
            self.STAGE1_PERIODS = settings.challenger_stage1_periods
        if settings.challenger_stage2_periods:
            self.STAGE2_PERIODS = settings.challenger_stage2_periods
        if settings.challenger_stage3_weeks:
            self.STAGE3_WEEKS = settings.challenger_stage3_weeks
        self.trial_alpha = settings.challenger_trial_alpha
        self.calmar_gate = settings.challenger_calmar_gate
        self.TRIAL_DAYS = self.STAGE3_WEEKS * 5  # trading days

    # ── Stage detection ──────────────────────────────────────────────────

    def check_elimination_stage(self, shadow_id: str) -> EliminationStage:
        """Determine a shadow's position in the 3-stage elimination pipeline.

        Reads snapshot history to count consecutive bottom-20% periods.
        If at stage 2+, creates or retrieves the challenger shadow.

        Args:
            shadow_id: The shadow to check.

        Returns:
            EliminationStage with current stage, consecutive count, and challenger_id if active.
        """
        snapshots = self.state_db.get_snapshot_history(shadow_id, days=365)
        if not snapshots:
            return EliminationStage(
                shadow_id=shadow_id,
                current_stage=0,
                consecutive_bottom_periods=0,
            )

        # Sort by date ascending to count consecutive from most recent
        sorted_snaps = sorted(snapshots, key=lambda s: s.date)
        consecutive = 0
        for snap in reversed(sorted_snaps):
            if snap.percentile_rank is not None and snap.percentile_rank < self.BOTTOM_PERCENTILE_THRESHOLD:
                consecutive += 1
            else:
                break

        # Determine stage from consecutive count
        if consecutive >= self.STAGE2_PERIODS:
            # Stage 2: challenger created (or stage 3 if already in trial)
            challenger_id = self._get_or_create_challenger(shadow_id)

            # Check if already in comparison phase (challenger has enough snapshots)
            if challenger_id:
                challenger_snaps = self.state_db.get_snapshot_history(challenger_id, days=365)
                trial_snaps = [s for s in challenger_snaps if s.daily_return_pct is not None]
                if len(trial_snaps) >= self.TRIAL_DAYS:
                    return EliminationStage(
                        shadow_id=shadow_id,
                        current_stage=3,
                        consecutive_bottom_periods=consecutive,
                        challenger_id=challenger_id,
                    )
                return EliminationStage(
                    shadow_id=shadow_id,
                    current_stage=2,
                    consecutive_bottom_periods=consecutive,
                    challenger_id=challenger_id,
                )

            return EliminationStage(
                shadow_id=shadow_id,
                current_stage=2,
                consecutive_bottom_periods=consecutive,
            )

        elif consecutive >= self.STAGE1_PERIODS:
            return EliminationStage(
                shadow_id=shadow_id,
                current_stage=1,
                consecutive_bottom_periods=consecutive,
            )

        return EliminationStage(
            shadow_id=shadow_id,
            current_stage=0,
            consecutive_bottom_periods=consecutive,
        )

    def _get_or_create_challenger(self, target_shadow_id: str) -> str | None:
        """Get existing challenger for a target, or create one if at stage 2+.

        Returns None if the target shadow doesn't exist in the DB.
        """
        target = self.state_db.get_shadow(target_shadow_id)
        if target is None:
            logger.warning("Cannot create challenger: target shadow '%s' not found", target_shadow_id)
            return None

        # Check if a challenger already exists for this target
        all_challengers = self.state_db.get_active_shadows("challenger")
        for c in all_challengers:
            if c.parent_shadow_id == target_shadow_id:
                return c.shadow_id

        # Create new challenger
        return self.create_challenger(target_shadow_id)

    def create_challenger(self, target_shadow_id: str) -> str:
        """Create a secret challenger shadow for a target under evaluation.

        The challenger inherits the target's methodology but is invisible to rankings
        (shadow_type="challenger" is excluded by get_visible_shadows()).

        Args:
            target_shadow_id: The shadow being challenged.

        Returns:
            The challenger's shadow_id.

        Raises:
            ValueError: If target shadow does not exist.
        """
        target = self.state_db.get_shadow(target_shadow_id)
        if target is None:
            raise ValueError(f"Target shadow '{target_shadow_id}' does not exist")

        # Generate a unique challenger ID
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        challenger_id = f"challenger:{target.domain or 'general'}:{ts}"

        # Build challenger config — inherits target methodology with challenger marker
        challenger_config = ShadowConfig(
            shadow_id=challenger_id,
            shadow_type="challenger",
            display_name=f"Challenger[{target.display_name}]",
            methodology_prompt=target.methodology_prompt,
            virtual_capital=target.virtual_capital,
            max_positions=target.max_positions,
            model=target.model,
            temperature=target.temperature + 0.05,  # Slightly higher exploration
            reasoning_effort=target.reasoning_effort,
            domain=target.domain,
            max_drawdown_limit=target.max_drawdown_limit,
            min_trades_for_ranking=target.min_trades_for_ranking,
            parent_shadow_id=target_shadow_id,
            generation=target.generation + 1,
            status="active",
        )

        try:
            self.state_db.create_shadow(challenger_config)
            logger.info(
                "Challenger '%s' created for target '%s' (gen %d -> %d)",
                challenger_id, target_shadow_id, target.generation, target.generation + 1
            )
        except ValueError as e:
            # If challenger already exists (race condition), find it
            if "already exists" in str(e):
                all_challengers = self.state_db.get_active_shadows("challenger")
                for c in all_challengers:
                    if c.parent_shadow_id == target_shadow_id:
                        return c.shadow_id
            raise

        return challenger_id

    # ── Comparison trial ─────────────────────────────────────────────────

    async def run_comparison_trial(
        self, challenger_id: str, target_id: str
    ) -> ChallengerTrialResult:
        """Run the 2-week paired comparison trial between challenger and target.

        Collects daily return snapshots for both shadows during the trial period,
        then applies:
        1. Paired t-test (one-sided, alpha from settings) — is challenger better?
        2. Calmar ratio gate — is challenger's Calmar > gate threshold?
        3. Composite verdict: REPLACE_TARGET, RESTORE_TARGET, or INCONCLUSIVE.

        Args:
            challenger_id: The secret challenger shadow.
            target_id: The original shadow being challenged.

        Returns:
            ChallengerTrialResult with full statistics and verdict.
        """
        # Fetch recent snapshots for both shadows
        target_snaps = self.state_db.get_snapshot_history(target_id, days=90)
        challenger_snaps = self.state_db.get_snapshot_history(challenger_id, days=90)

        # Filter to trial period: use the overlapping dates
        target_dates = {s.date for s in target_snaps if s.daily_return_pct is not None}
        challenger_dates = {s.date for s in challenger_snaps if s.daily_return_pct is not None}
        common_dates = sorted(target_dates & challenger_dates)[-self.TRIAL_DAYS:]

        if len(common_dates) < 5:
            logger.warning(
                "Insufficient paired data: %d common dates for challenger=%s target=%s",
                len(common_dates), challenger_id, target_id
            )
            return ChallengerTrialResult(
                challenger_id=challenger_id,
                target_id=target_id,
                challenger_mean_return=0.0,
                target_mean_return=0.0,
                paired_t_pvalue=1.0,
                challenger_calmar=0.0,
                target_calmar=0.0,
                challenger_better=False,
                verdict="INCONCLUSIVE",
            )

        # Extract paired daily returns
        target_returns = []
        challenger_returns = []
        for date in common_dates:
            t_snap = next((s for s in target_snaps if s.date == date), None)
            c_snap = next((s for s in challenger_snaps if s.date == date), None)
            if t_snap and c_snap and t_snap.daily_return_pct is not None and c_snap.daily_return_pct is not None:
                target_returns.append(t_snap.daily_return_pct)
                challenger_returns.append(c_snap.daily_return_pct)

        n = len(target_returns)
        if n < 5:
            return ChallengerTrialResult(
                challenger_id=challenger_id,
                target_id=target_id,
                challenger_mean_return=0.0,
                target_mean_return=0.0,
                paired_t_pvalue=1.0,
                challenger_calmar=0.0,
                target_calmar=0.0,
                challenger_better=False,
                verdict="INCONCLUSIVE",
            )

        # Compute means
        challenger_mean = sum(challenger_returns) / n
        target_mean = sum(target_returns) / n

        # Paired t-test (one-sided: H0: challenger <= target, H1: challenger > target)
        pvalue, t_stat, _ = self._compute_paired_ttest(
            target_returns, challenger_returns, one_sided=True
        )

        # Calmar ratios
        challenger_calmar = self._compute_calmar_from_snapshots(
            self.state_db, challenger_id, days=90
        )
        target_calmar = self._compute_calmar_from_snapshots(
            self.state_db, target_id, days=90
        )

        # Statistical gate: p-value < alpha (one-sided)
        passes_ttest = pvalue < self.trial_alpha

        # Calmar gate: challenger Calmar > gate
        passes_calmar = challenger_calmar > self.calmar_gate

        # Composite verdict
        challenger_better = challenger_mean > target_mean
        if passes_ttest and passes_calmar and challenger_better:
            verdict = "REPLACE_TARGET"
        elif not challenger_better and target_mean > challenger_mean:
            verdict = "RESTORE_TARGET"
        else:
            verdict = "INCONCLUSIVE"

        logger.info(
            "Trial result: challenger=%s vs target=%s | t-test p=%.4f calmar_c=%.3f calmar_t=%.3f | verdict=%s",
            challenger_id, target_id, pvalue, challenger_calmar, target_calmar, verdict
        )

        return ChallengerTrialResult(
            challenger_id=challenger_id,
            target_id=target_id,
            challenger_mean_return=challenger_mean,
            target_mean_return=target_mean,
            paired_t_pvalue=pvalue,
            challenger_calmar=challenger_calmar,
            target_calmar=target_calmar,
            challenger_better=challenger_better,
            verdict=verdict,
        )

    # ── Statistical helpers ──────────────────────────────────────────────

    def _compute_paired_ttest(
        self,
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
            # For one-sided H1: challenger > target, i.e., (target - challenger) < 0
            # If the difference mean is negative (challenger wins), halve the p-value
            if t_stat < 0:
                pvalue = pvalue_two_sided / 2.0
            else:
                # Difference mean is positive (target wins), p-value > 0.5
                pvalue = 1.0 - pvalue_two_sided / 2.0
        else:
            pvalue = pvalue_two_sided

        mean_diff = sum(target_returns) / len(target_returns) - sum(challenger_returns) / len(challenger_returns)

        return (pvalue, t_stat, mean_diff)

    @staticmethod
    def _compute_calmar_from_snapshots(
        state_db: ShadowStateDB, shadow_id: str, days: int = 90
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

    @staticmethod
    def _check_calmar_gate(calmar: float, gate: float = 0.3) -> bool:
        """Check if a shadow's Calmar ratio passes the comparison gate.

        Args:
            calmar: The shadow's Calmar ratio.
            gate: Minimum Calmar threshold (default 0.3).

        Returns:
            True if Calmar > gate.
        """
        return calmar > gate
