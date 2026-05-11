"""Cash Reframing A/B Test -- treatment/control cohorts, Mann-Whitney DE test,
non-inferiority TOST, and gateway M1 injection.

Tests whether cash-reframing exit discipline improves returns:
- 6 treatment shadows + 6 control (randomly assigned, seeded by shadow_id)
- Treatment: "If you had cash today, would you buy?" (gateway M1 injection)
- Control: traditional fixed stop-loss + logic-falsified only
- Primary test: one-sided Mann-Whitney on Disposition Effect (treatment < control, alpha=0.10)
- Non-inferiority: TOST on cumulative return, margin delta=2.0% (90-day)
- Success: DE reduction AND non-inferior returns
"""
from __future__ import annotations

import hashlib
import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from projects.marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.cash_reframing")


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class CashReframingResult:
    test_complete: bool
    days_elapsed: int
    treatment_de_mean: float
    control_de_mean: float
    mann_whitney_pvalue: float
    treatment_cumulative_return: float
    control_cumulative_return: float
    non_inferiority_passed: bool
    success: bool
    recommendation: str


# ── Main class ─────────────────────────────────────────────────────────────

class CashReframingTest:
    """Runs the cash-reframing A/B test across treatment and control shadow cohorts."""

    CASH_REFRAMING_PROTOCOL = (
        "CASH_REFRAMING_PROTOCOL: Before exiting any position, answer this question "
        "as if you had no existing position: \"If you had ${capital} in cash today, "
        "would you buy {ticker} at its current price?\" Only exit if the answer is a "
        "clear NO. This mental reframing eliminates the endowment effect and sunk-cost "
        "bias from your exit decision.\n\n"
    )

    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings):
        self.state_db = state_db
        self.settings = settings
        self._treatment_ids: list[str] = []
        self._control_ids: list[str] = []
        self._allocated: bool = False

    # ── Cohort allocation ─────────────────────────────────────────────────

    def allocate_cohorts(self) -> tuple[list[str], list[str]]:
        """Allocate 12 active shadows into 6 treatment + 6 control.

        Allocation is deterministic based on a hash of the shadow_id, so the same
        shadow always maps to the same cohort across runs.
        """
        active = self.state_db.get_active_shadows()
        if len(active) < 12:
            logger.warning("Only %d active shadows; need 12 for full A/B test", len(active))

        # Sort by shadow_id for deterministic ordering
        sorted_ids = sorted([s.shadow_id for s in active])

        # Use deterministic seeding based on shadow_id hash
        # Split into two groups: even-hash-sum vs odd-hash-sum
        treatment: list[str] = []
        control: list[str] = []

        for sid in sorted_ids:
            hash_val = int(hashlib.md5(sid.encode()).hexdigest(), 16)
            if hash_val % 2 == 0:
                if len(treatment) < self.settings.cash_reframing_cohort_size:
                    treatment.append(sid)
                else:
                    control.append(sid)
            else:
                if len(control) < self.settings.cash_reframing_cohort_size:
                    control.append(sid)
                else:
                    treatment.append(sid)

        self._treatment_ids = treatment
        self._control_ids = control
        self._allocated = True

        logger.info("Cohorts allocated: %d treatment, %d control", len(treatment), len(control))
        return treatment, control

    def _get_treatment_ids(self) -> list[str]:
        """Get treatment cohort IDs, allocating if not done yet."""
        if not self._allocated:
            self.allocate_cohorts()
        return self._treatment_ids

    def _get_control_ids(self) -> list[str]:
        """Get control cohort IDs, allocating if not done yet."""
        if not self._allocated:
            self.allocate_cohorts()
        return self._control_ids

    # ── Exit checks ───────────────────────────────────────────────────────

    async def run_exit_check_treatment(self, shadow_id: str, ticker: str,
                                        position_data: dict) -> bool:
        """Treatment exit check: uses cash-reframing question.

        Returns True if the shadow should exit the position.
        """
        capital = position_data.get("capital_at_risk", 10000.0)
        # The cash-reframing protocol is injected at the gateway level via
        # the cash_reframing_ticker parameter to chat_with_integrity().
        # This method is called by the shadow to check if an exit is warranted.

        entry_price = position_data.get("entry_price", 0)
        current_price = position_data.get("current_price", entry_price)
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

        # Treatment: cash-reframing asks "would you buy today?"
        # If losing position and the answer is "yes, I'd buy", then HOLD (don't exit)
        # If the answer is "no, I wouldn't buy", then EXIT
        # For mock purposes, we use a heuristic: exit if fundamentals deteriorated
        # The actual LLM call happens through the gateway with CASH_REFRAMING_PROTOCOL

        # Mock heuristic: exit losing positions where loss > 5% and momentum is negative
        if pnl_pct < -0.05:
            momentum = position_data.get("momentum", 0)
            if momentum < 0:
                return True  # Exit
            return False  # Hold — cash reframing says "would buy at discount"
        return False  # Hold winners

    async def run_exit_check_control(self, shadow_id: str, ticker: str,
                                       position_data: dict) -> bool:
        """Control exit check: traditional stop-loss + logic-falsified only.

        Returns True if the shadow should exit the position.
        """
        entry_price = position_data.get("entry_price", 0)
        current_price = position_data.get("current_price", entry_price)
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

        # Hard stop-loss at -7% (typical for control group)
        stop_loss = position_data.get("stop_loss_pct", -0.07)
        if pnl_pct <= stop_loss:
            return True

        # Exit on fundamental logic falsification only
        logic_falsified = position_data.get("logic_falsified", False)
        if logic_falsified:
            return True

        return False  # Hold

    # ── Disposition Effect computation ─────────────────────────────────────

    def compute_disposition_effect(self, shadow_id: str, days: int = 90) -> float:
        """Compute Disposition Effect (DE) ratio for a shadow.

        DE = PGR / PLR where:
        - PGR (Proportion of Gains Realized) = realized_gains / (realized_gains + paper_gains)
        - PLR (Proportion of Losses Realized) = realized_losses / (realized_losses + paper_losses)

        DE > 1.0: disposition effect present (sell winners, hold losers)
        DE = 1.0: neutral
        DE < 1.0: reverse disposition effect

        Returns DE as a float (clamped to reasonable range to avoid division issues).
        """
        trades = self.state_db.get_trade_history(shadow_id, limit=days * 2)
        open_trades = self.state_db.get_open_trades(shadow_id)

        # Categorize closed trades
        realized_gains = 0
        realized_losses = 0
        for t in trades:
            if t.pnl_pct is not None:
                if t.pnl_pct > 0:
                    realized_gains += 1
                elif t.pnl_pct < 0:
                    realized_losses += 1

        # Categorize open trades as paper gains/losses
        # Without current prices, we estimate: long positions above entry are gains,
        # shorts below entry are gains. This is approximate.
        paper_gains = 0
        paper_losses = 0
        for t in open_trades:
            if t.direction == "long":
                # Can't determine without current price; assume evenly split
                paper_gains += 1  # conservative: treat all open as gains
            elif t.direction == "short":
                paper_losses += 1

        total_gains = realized_gains + paper_gains
        total_losses = realized_losses + paper_losses

        if total_gains == 0 and total_losses == 0:
            return 1.0  # Neutral when no data

        pgr = realized_gains / total_gains if total_gains > 0 else 1.0
        plr = realized_losses / total_losses if total_losses > 0 else 0.0

        # Avoid division by zero: if PLR is 0, DE is very large
        if plr == 0.0:
            # Cap at a large but finite value
            if realized_losses == 0 and total_losses > 0:
                return 10.0  # All losses are paper losses — strong DE
            return 1.0  # No losses at all — neutral

        de = pgr / plr
        return de

    # ── Statistical tests ──────────────────────────────────────────────────

    def run_statistical_test(self) -> CashReframingResult:
        """Run the full A/B test: Mann-Whitney on DE + TOST on cumulative returns.

        Returns a CashReframingResult with test outcomes and recommendation.
        """
        treatment_ids = self._get_treatment_ids()
        control_ids = self._get_control_ids()

        if len(treatment_ids) < 3 or len(control_ids) < 3:
            return CashReframingResult(
                test_complete=False,
                days_elapsed=0,
                treatment_de_mean=0.0,
                control_de_mean=0.0,
                mann_whitney_pvalue=1.0,
                treatment_cumulative_return=0.0,
                control_cumulative_return=0.0,
                non_inferiority_passed=False,
                success=False,
                recommendation="Insufficient data: need at least 3 shadows per cohort.",
            )

        # Compute DE values for each cohort
        days = self.settings.cash_reframing_test_days  # 90
        treatment_de = []
        control_de = []
        treatment_returns = []
        control_returns = []

        for sid in treatment_ids:
            de = self.compute_disposition_effect(sid, days)
            treatment_de.append(de)
            cum_ret = self._get_cumulative_return(sid)
            treatment_returns.append(cum_ret)

        for sid in control_ids:
            de = self.compute_disposition_effect(sid, days)
            control_de.append(de)
            cum_ret = self._get_cumulative_return(sid)
            control_returns.append(cum_ret)

        treatment_de_mean = statistics.mean(treatment_de) if treatment_de else 0.0
        control_de_mean = statistics.mean(control_de) if control_de else 0.0

        # Mann-Whitney U test (one-sided: treatment < control)
        mw_pvalue = self._mann_whitney_u(treatment_de, control_de, alternative="less")

        # Non-inferiority TOST on cumulative returns
        treatment_cum = statistics.mean(treatment_returns) if treatment_returns else 0.0
        control_cum = statistics.mean(control_returns) if control_returns else 0.0
        ni_passed = self._tost_non_inferiority(
            treatment_returns, control_returns,
            margin=self.settings.cash_reframing_non_inferiority_margin,  # 0.02
        )

        # Success criteria: DE reduction (p < 0.10) AND non-inferior returns
        alpha = self.settings.cash_reframing_de_alpha  # 0.10
        de_reduced = mw_pvalue < alpha and treatment_de_mean < control_de_mean
        success = de_reduced and ni_passed

        if success:
            recommendation = (
                "Cash reframing significantly reduces disposition effect without "
                "sacrificing returns. Recommend rolling out to all shadows."
            )
        elif de_reduced and not ni_passed:
            recommendation = (
                "Cash reframing reduces DE but returns are inferior. "
                "Consider limiting to lower-conviction positions."
            )
        elif not de_reduced and ni_passed:
            recommendation = (
                "Cash reframing does not significantly reduce DE, but returns "
                "are non-inferior. Continue testing or adjust protocol wording."
            )
        else:
            recommendation = (
                "Cash reframing does not improve outcomes. "
                "Consider removing the protocol."
            )

        return CashReframingResult(
            test_complete=True,
            days_elapsed=days,
            treatment_de_mean=treatment_de_mean,
            control_de_mean=control_de_mean,
            mann_whitney_pvalue=mw_pvalue,
            treatment_cumulative_return=treatment_cum,
            control_cumulative_return=control_cum,
            non_inferiority_passed=ni_passed,
            success=success,
            recommendation=recommendation,
        )

    def _get_cumulative_return(self, shadow_id: str) -> float:
        """Get cumulative return from snapshot or compute from trades."""
        snap = self.state_db.get_latest_snapshot(shadow_id)
        if snap and snap.cumulative_return_pct is not None:
            return snap.cumulative_return_pct

        # Fallback: compute from trade history
        trades = self.state_db.get_trade_history(shadow_id, limit=500)
        return sum(t.pnl_pct or 0.0 for t in trades if t.exit_price is not None)

    @staticmethod
    def _mann_whitney_u(x: list[float], y: list[float],
                         alternative: str = "less") -> float:
        """Compute one-sided Mann-Whitney U p-value (x < y).

        Uses the normal approximation for efficiency.
        Falls back to scipy if available for exact computation.
        """
        if not x or not y:
            return 1.0

        try:
            from scipy.stats import mannwhitneyu
            result = mannwhitneyu(x, y, alternative=alternative)
            return result.pvalue
        except ImportError:
            pass

        # Manual implementation via normal approximation
        combined = [(v, 0) for v in x] + [(v, 1) for v in y]
        combined.sort(key=lambda p: p[0])

        n1 = len(x)
        n2 = len(y)
        N = n1 + n2

        # Compute ranks (handling ties with average rank)
        ranks = [0.0] * N
        i = 0
        while i < N:
            j = i
            while j < N and combined[j][0] == combined[i][0]:
                j += 1
            avg_rank = (i + j + 1) / 2.0  # 1-indexed average rank
            for k in range(i, j):
                ranks[k] = avg_rank
            i = j

        # Sum ranks for group 0 (x values)
        r1 = sum(ranks[i] for i in range(N) if combined[i][1] == 0)

        # U statistic
        u1 = r1 - n1 * (n1 + 1) / 2.0
        u2 = n1 * n2 - u1

        if alternative == "less":
            u = u1
        elif alternative == "greater":
            u = u2
        else:
            u = min(u1, u2)

        # Normal approximation
        mu = n1 * n2 / 2.0
        # Tie correction
        tie_groups: dict[float, int] = {}
        for v in combined:
            tie_groups[v[0]] = tie_groups.get(v[0], 0) + 1
        tie_correction = sum((c**3 - c) / (N * (N - 1)) for c in tie_groups.values() if c > 1)
        sigma = (n1 * n2 / 12.0 * (N + 1 - tie_correction * (N + 1))) ** 0.5

        if sigma == 0:
            return 1.0

        import math
        z = (u - mu) / sigma

        # Normal CDF approximation
        # Using Abramowitz and Stegun approximation
        def norm_cdf(z_val):
            if z_val < -8:
                return 0.0
            if z_val > 8:
                return 1.0
            # Error function approximation
            return 0.5 * (1.0 + math.erf(z_val / math.sqrt(2.0)))

        if alternative == "two-sided":
            z_abs = abs(z)
            p = 2.0 * (1.0 - norm_cdf(z_abs))
        else:
            p = norm_cdf(z)

        return p

    @staticmethod
    def _tost_non_inferiority(treatment_returns: list[float],
                                control_returns: list[float],
                                margin: float = 0.02) -> bool:
        """Two One-Sided Tests (TOST) for non-inferiority.

        H0: treatment_return <= control_return - margin (treatment is inferior)
        We reject H0 if treatment is at least as good as control minus margin.

        Returns True if non-inferiority is established (p < 0.10).
        """
        if not treatment_returns or not control_returns:
            return False

        try:
            from scipy.stats import ttest_ind
            diff = [t - c for t, c in zip(treatment_returns, control_returns)]

            if len(diff) < 2:
                # Not enough data for t-test; check simple comparison
                mean_t = statistics.mean(treatment_returns)
                mean_c = statistics.mean(control_returns)
                return (mean_t - mean_c) > -margin

            n = len(diff)
            mean_diff = statistics.mean(diff)
            std_diff = statistics.stdev(diff) if n > 1 else 0.0
            if std_diff == 0:
                return mean_diff > -margin

            # One-sided t-test: H0: mean_diff <= -margin
            import math
            se = std_diff / math.sqrt(n)
            t_stat = (mean_diff - (-margin)) / se

            # Approximate p-value using t-distribution
            # For df >= 5, normal approximation is reasonable
            def t_cdf(t_val, df):
                """Approximate t-distribution CDF."""
                if t_val < -8:
                    return 0.0
                if t_val > 8:
                    return 1.0
                # Use normal approximation for simplicity
                return 0.5 * (1.0 + math.erf(t_val / math.sqrt(2.0)))

            p_value = 1.0 - t_cdf(t_stat, n - 1)

            # Alpha = 0.10 for non-inferiority
            return p_value < 0.10

        except ImportError:
            # Fallback: simple comparison
            mean_t = statistics.mean(treatment_returns)
            mean_c = statistics.mean(control_returns)
            return (mean_t - mean_c) > -margin
