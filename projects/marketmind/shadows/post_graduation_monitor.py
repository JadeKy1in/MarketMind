"""Post-graduation monitoring — CUSUM/CUSUMSQ/BOCPD surveillance.

3-layer monitoring after a shadow graduates. Any trigger → demotion.
No tenure principle: even 300-day Elite gets suspended on D1 trigger.

Phase F Module 2 — Final plan §10.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from marketmind.shadows.shadow_state import ShadowStateDB, DailySnapshot

logger = logging.getLogger("marketmind.shadows.post_graduation_monitor")

# ── Demotion conditions (final plan §10.2) ──────────────────────────────────

# Priority: D7 > D1 > D3 > D4 > D2 > D8 > D5 > D6
_DEMOTION_PRIORITY = ["D7", "D1", "D3", "D4", "D2", "D8", "D5", "D6"]

_DEMOTION_CONDITIONS = {
    "D1": {
        "label": "CUSUMSQ triggered",
        "severity": "critical",
        "demotion_level": "suspended",
        "recovery": "methodology_correction_plus_30d_backtest",
    },
    "D2": {
        "label": "CUSUM 5 alerts in 3 months",
        "severity": "high",
        "demotion_level": "display_only",
        "recovery": "20d_no_alerts_plus_alpha_positive",
    },
    "D3": {
        "label": "BOCPD + CUSUM joint trigger",
        "severity": "high",
        "demotion_level": "suspended",
        "recovery": "new_strategy_better_than_old",
    },
    "D4": {
        "label": "Dropped to Endangered",
        "severity": "high",
        "demotion_level": "suspended",
        "recovery": "challenger_wins",
    },
    "D5": {
        "label": "3 consecutive Watch periods",
        "severity": "medium",
        "demotion_level": "display_only",
        "recovery": "tier2_recheck",
    },
    "D6": {
        "label": "Style drift > 2 sigma for 3 months",
        "severity": "medium",
        "demotion_level": "display_only",
        "recovery": "methodology_explanation_plus_reversion",
    },
    "D7": {
        "label": "Drawdown hit limit",
        "severity": "critical",
        "demotion_level": "suspended",
        "recovery": "full_requalification",
    },
    "D8": {
        "label": "Factor alpha < 0 (t < -1.65)",
        "severity": "high",
        "demotion_level": "display_only",
        "recovery": "alpha_positive_for_2_months",
    },
}

# ── CUSUM parameters ────────────────────────────────────────────────────────

_CUSUM_K = 0.5       # reference value (drift allowance in std units)
_CUSUM_H = 5.0       # decision interval (alert threshold)
_CUSUM_WINDOW_DAYS = 90  # 3-month rolling window for D2

# ── Data types ───────────────────────────────────────────────────────────────


@dataclass
class MonitorResult:
    """Post-graduation monitoring check result for one shadow."""
    shadow_id: str
    date: str
    cusum_triggered: bool
    cusumsq_triggered: bool
    bocpd_triggered: bool
    demotion_level: str  # "none", "display_only", "suspended"
    cusum_alerts_3m: int = 0
    cusum_latest_value: float = 0.0
    cusumsq_latest_value: float = 0.0
    bocpd_change_detected: bool = False
    triggered_conditions: list[str] = field(default_factory=list)
    applied_demotion: str | None = None  # D1-D8 code
    demotion_reason: str = ""


# ── Monitor ──────────────────────────────────────────────────────────────────


class PostGraduationMonitor:
    """3-layer post-graduation surveillance system.

    Layer 1: CUSUM on P&L — 5 alerts in 3 months → reassessment
    Layer 2: CUSUMSQ on residuals → IMMEDIATE Gate 2 suspension
    Layer 3: BOCPD + CUSUM jointly → strategy re-optimization

    No tenure principle: even 300-day Elite gets suspended on D1 trigger.
    """

    def __init__(self, state_db: ShadowStateDB):
        self.state_db = state_db

    # ── Public API ────────────────────────────────────────────────────────

    def check(self, shadow_id: str, lookback_days: int = 180) -> MonitorResult:
        """Run 3-layer check for one shadow.

        Args:
            shadow_id: The shadow to monitor.
            lookback_days: Lookback window for CUSUM/CUSUMSQ/BOCPD computation.

        Returns:
            MonitorResult with triggered conditions and recommended demotion level.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        snapshots = self.state_db.get_snapshot_history(shadow_id, days=lookback_days)
        daily_returns = np.array([
            (s.daily_return_pct or 0.0) / 100.0
            for s in snapshots
            if s.daily_return_pct is not None
        ], dtype=float)

        n = len(daily_returns)

        # Layer 1: CUSUM on P&L
        cusum_values, cusum_alerts = self._compute_cusum(daily_returns, lookback_days)
        cusum_triggered = len(cusum_alerts) > 0

        # Layer 2: CUSUMSQ on residuals (residuals from mean)
        cusumsq_values, cusumsq_triggered = self._compute_cusumsq(daily_returns)

        # Layer 3: BOCPD (simplified: joint CUSUM + volatility shift)
        bocpd_triggered = self._compute_bocpd(daily_returns, cusum_values)

        # Count CUSUM alerts in last 3 months (D2)
        cusum_alerts_3m = self._count_alerts_in_window(
            cusum_alerts, daily_returns, window_days=_CUSUM_WINDOW_DAYS
        )

        # Determine triggered conditions and demotion level
        triggered, demotion_level, applied_demotion, reason = self._resolve_demotion(
            shadow_id=shadow_id,
            cusum_triggered=cusum_triggered,
            cusum_alerts_3m=cusum_alerts_3m,
            cusumsq_triggered=cusumsq_triggered,
            bocpd_triggered=bocpd_triggered,
            snapshots=snapshots,
            config=self.state_db.get_shadow(shadow_id),
        )

        return MonitorResult(
            shadow_id=shadow_id,
            date=today,
            cusum_triggered=cusum_triggered,
            cusumsq_triggered=cusumsq_triggered,
            bocpd_triggered=bocpd_triggered,
            demotion_level=demotion_level,
            cusum_alerts_3m=cusum_alerts_3m,
            cusum_latest_value=float(cusum_values[-1]) if len(cusum_values) > 0 else 0.0,
            cusumsq_latest_value=float(cusumsq_values[-1]) if len(cusumsq_values) > 0 else 0.0,
            bocpd_change_detected=bocpd_triggered,
            triggered_conditions=triggered,
            applied_demotion=applied_demotion,
            demotion_reason=reason,
        )

    def apply_demotion(self, shadow_id: str, level: str, reason: str) -> None:
        """Apply demotion per the 8-condition priority table (D1-D8).

        Priority when multiple triggers: D7 > D1 > D3 > D4 > D2 > D8 > D5 > D6

        Args:
            shadow_id: The shadow to demote.
            level: Target demotion level ("display_only" or "suspended").
            reason: Human-readable reason for audit trail.
        """
        valid_levels = ("display_only", "suspended")
        if level not in valid_levels:
            raise ValueError(f"demotion level must be one of {valid_levels}, got '{level}'")

        config = self.state_db.get_shadow(shadow_id)
        if config is None:
            logger.warning("Cannot demote shadow '%s': not found in state DB", shadow_id)
            return

        # Map demotion level to shadow status
        status_map = {
            "display_only": "watch",
            "suspended": "paused",
        }
        new_status = status_map.get(level, "watch")

        # Update shadow status in DB
        self.state_db.update_shadow_status(shadow_id, new_status)
        # Log the reason for audit trail (status update doesn't store reason)
        logger.info(
            "Post-graduation demotion reason for '%s': %s",
            shadow_id, reason,
        )

        logger.info(
            "Shadow '%s' demoted: %s → %s. Reason: %s",
            shadow_id, config.status, new_status, reason,
        )

    # ── CUSUM (Layer 1) ────────────────────────────────────────────────────

    def _compute_cusum(
        self, returns: np.ndarray, lookback_days: int
    ) -> tuple[np.ndarray, list[int]]:
        """Compute one-sided upper CUSUM on P&L (cumulative returns).

        CUSUM detects sustained positive drift away from expected zero-mean
        returns. For post-graduation monitoring, we detect *negative* drift
        (performance deterioration) using a lower CUSUM.

        S_t = max(0, S_{t-1} + z_t - k),  alert when S_t > h
        where z_t is the standardized return.

        Returns:
            (cusum_values: np.ndarray, alert_indices: list[int])
        """
        n = len(returns)
        if n == 0:
            return np.array([]), []

        std = float(np.std(returns, ddof=1))
        if std < 1e-10:
            std = 0.01  # floor to avoid division by zero

        # Standardize returns
        z_scores = (returns - np.mean(returns)) / std

        # Two-sided CUSUM: upper (positive shift) and lower (negative shift)
        # We monitor the lower CUSUM for performance deterioration
        cusum_pos = np.zeros(n)
        cusum_neg = np.zeros(n)
        alerts: list[int] = []

        for i in range(n):
            if i == 0:
                cusum_pos[i] = max(0.0, z_scores[i] - _CUSUM_K)
                cusum_neg[i] = max(0.0, -z_scores[i] - _CUSUM_K)
            else:
                cusum_pos[i] = max(0.0, cusum_pos[i - 1] + z_scores[i] - _CUSUM_K)
                cusum_neg[i] = max(0.0, cusum_neg[i - 1] - z_scores[i] - _CUSUM_K)

            if cusum_pos[i] > _CUSUM_H or cusum_neg[i] > _CUSUM_H:
                alerts.append(i)

        # Return the max of pos/neg at each point (combined signal)
        combined = np.maximum(cusum_pos, cusum_neg)
        return combined, alerts

    def _count_alerts_in_window(
        self, alerts: list[int], returns: np.ndarray, window_days: int = 90
    ) -> int:
        """Count CUSUM alerts within the most recent window_days observations."""
        if not alerts:
            return 0
        n = len(returns)
        cutoff = max(0, n - window_days)
        return sum(1 for idx in alerts if idx >= cutoff)

    # ── CUSUMSQ (Layer 2) ──────────────────────────────────────────────────

    def _compute_cusumsq(self, returns: np.ndarray) -> tuple[np.ndarray, bool]:
        """Compute CUSUMSQ on residuals (Brown-Durbin-Evans, 1975).

        CUSUMSQ detects structural breaks in variance / model stability.
        Residuals are computed as deviations from the mean return.

        W_r = sum(r_i^2) / sum(r_n^2) for cumulative sums of squares.
        Trigger if |W_r - expected(r/n)| exceeds critical boundary.

        Returns:
            (cusumsq_statistic: np.ndarray, triggered: bool)
        """
        n = len(returns)
        if n < 10:
            return np.zeros(1) if n == 0 else np.zeros(n), False

        # Residuals = deviations from mean
        mean_ret = float(np.mean(returns))
        residuals = returns - mean_ret

        # Cumulative sum of squares
        cum_sq = np.cumsum(residuals ** 2)
        total_sq = cum_sq[-1]

        if total_sq < 1e-10:
            return np.zeros(n), False

        # CUSUMSQ statistic: s_r = cum_sq[r] / total_sq
        # Expected under H0 (no break): r/n
        # Critical boundary: r/n ± c_alpha (constant-width band, BDE test)
        # For n>60 at 5% significance: c_alpha ≈ 0.149 (Brown-Durbin-Evans 1975)
        # We use 0.20 for raw returns (more conservative than regression residuals)
        c_alpha = 0.20 if n > 60 else 0.25  # wider band for small samples

        cusumsq_values = np.zeros(n)
        triggered = False

        for r in range(1, n + 1):
            observed = cum_sq[r - 1] / total_sq
            expected = r / n
            cusumsq_values[r - 1] = observed - expected

            # Brown-Durbin-Evans constant-width critical band
            if abs(observed - expected) > c_alpha:
                triggered = True

        return cusumsq_values, triggered

    # ── BOCPD (Layer 3) ────────────────────────────────────────────────────

    def _compute_bocpd(
        self, returns: np.ndarray, cusum_values: np.ndarray
    ) -> bool:
        """Simplified Bayesian Online Change Point Detection.

        Joint signal: CUSUM alert + volatility regime shift.
        A true BOCPD would use a probabilistic run-length model with
        conjugate priors (Tsaknaki et al., 2025). This simplified version
        detects joint CUSUM + volatility shift as a proxy.

        Returns True if joint signal is triggered.
        """
        n = len(returns)
        if n < 30:
            return False

        # Check for volatility shift in recent window
        half = n // 2
        recent = returns[half:]
        early = returns[:half]

        std_recent = float(np.std(recent, ddof=1))
        std_early = float(np.std(early, ddof=1))

        if std_early < 1e-10:
            return False

        vol_ratio = std_recent / std_early
        vol_shift = vol_ratio > 2.0 or vol_ratio < 0.5

        # CUSUM alert in recent half
        cusum_recent = cusum_values[half:] if len(cusum_values) > half else np.array([])
        cusum_alert = False
        if len(cusum_recent) > 0:
            cusum_alert = bool(np.any(cusum_recent > _CUSUM_H))

        # Joint trigger: CUSUM + vol shift
        return vol_shift and cusum_alert

    # ── Demotion Resolution ────────────────────────────────────────────────

    def _resolve_demotion(
        self,
        shadow_id: str,
        cusum_triggered: bool,
        cusum_alerts_3m: int,
        cusumsq_triggered: bool,
        bocpd_triggered: bool,
        snapshots: list[DailySnapshot],
        config,
    ) -> tuple[list[str], str, str | None, str]:
        """Determine which demotion conditions are triggered and pick the highest priority.

        Priority: D7 > D1 > D3 > D4 > D2 > D8 > D5 > D6

        Returns:
            (triggered_conditions, demotion_level, applied_demotion_code, reason)
        """
        active_conditions: dict[str, dict] = {}

        # D1: CUSUMSQ triggered
        if cusumsq_triggered:
            active_conditions["D1"] = _DEMOTION_CONDITIONS["D1"]

        # D2: CUSUM 3-month 5 alerts
        if cusum_alerts_3m >= 5:
            active_conditions["D2"] = _DEMOTION_CONDITIONS["D2"]

        # D3: BOCPD + CUSUM joint
        if bocpd_triggered and cusum_triggered:
            active_conditions["D3"] = _DEMOTION_CONDITIONS["D3"]

        # D4: Dropped to Endangered — check tier history
        if self._check_endangered(shadow_id):
            active_conditions["D4"] = _DEMOTION_CONDITIONS["D4"]

        # D5: 3 consecutive Watch periods
        if self._check_consecutive_watch(shadow_id):
            active_conditions["D5"] = _DEMOTION_CONDITIONS["D5"]

        # D6: Style drift — requires factor exposure data (stub)
        # Not implemented; requires monthly factor exposure tracking

        # D7: Drawdown hit limit
        if self._check_drawdown_breach(snapshots, config):
            active_conditions["D7"] = _DEMOTION_CONDITIONS["D7"]

        # D8: Factor alpha negative — requires alpha computation (stub)
        # Not implemented; requires Carhart factor regression

        # Pick highest priority
        triggered = list(active_conditions.keys())
        applied_demotion = None
        demotion_level = "none"
        reason = ""

        if triggered:
            # Sort by priority order
            triggered_sorted = sorted(
                triggered,
                key=lambda d: _DEMOTION_PRIORITY.index(d) if d in _DEMOTION_PRIORITY else 999,
            )
            applied_demotion = triggered_sorted[0]
            condition = active_conditions[applied_demotion]
            demotion_level = condition["demotion_level"]
            reason = f"{applied_demotion}: {condition['label']}"

        return triggered, demotion_level, applied_demotion, reason

    # ── Condition Checkers ─────────────────────────────────────────────────

    def _check_endangered(self, shadow_id: str) -> bool:
        """Check if shadow has dropped to Endangered tier."""
        tier_history = self.state_db.get_tier_history(shadow_id, days=30)
        if not tier_history:
            return False
        # Check most recent tier
        latest_date, latest_tier = tier_history[-1]
        return latest_tier == "Endangered"

    def _check_consecutive_watch(self, shadow_id: str) -> bool:
        """Check for 3 consecutive Watch periods."""
        tier_history = self.state_db.get_tier_history(shadow_id, days=120)
        if len(tier_history) < 3:
            return False
        # Look for 3 consecutive Watch entries
        watch_streak = 0
        for _, tier in reversed(tier_history):
            if tier == "Watch":
                watch_streak += 1
                if watch_streak >= 3:
                    return True
            else:
                watch_streak = 0
        return False

    def _check_drawdown_breach(
        self, snapshots: list[DailySnapshot], config
    ) -> bool:
        """Check if drawdown has hit the shadow's limit (D7)."""
        if config is None:
            return False
        max_dd_limit = config.max_drawdown_limit
        # Check latest snapshots for drawdown exceedance
        for s in snapshots:
            if s.max_drawdown_pct is not None:
                if abs(s.max_drawdown_pct) / 100.0 >= max_dd_limit:
                    return True
        return False
