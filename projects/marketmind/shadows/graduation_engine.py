"""Graduation engine — multi-stage qualification for Gate 2 interaction.

Shadows graduate through: Tier 1 (basic competence) → Tier 2 (type-specific
excellence) → Stress Tests → Gate 2 qualification.

Graduation is NOT automatic — Elite status is prerequisite but does not
guarantee graduation. Post-graduation monitoring continues daily.

Phase F Module 1 — Final plan §8.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, DailySnapshot
from marketmind.shadows.graduation_stress_tests import (
    StressTestRunner,
    check_alpha_purity,
)
from marketmind.shadows.graduation_metrics import (
    compute_win_rate,
    compute_total_return,
    compute_max_dd,
    annualized_return,
    compute_sortino,
    compute_mar,
    compute_gpr,
    compute_k_ratio,
    compute_min_bet_ratio,
    check_single_trade_dependency,
    get_benchmark_return,
    contrarian_trade_dd,
    default_lookback,
    estimate_brier_type,
)

logger = logging.getLogger("marketmind.shadows.graduation_engine")

# ── Type-specific Tier 1 thresholds ──────────────────────────────────────────

_TIER1_THRESHOLDS = {
    "expert": {
        "win_rate": 0.52,
        "min_trades": 5,
        "max_dd": 0.25,
        "max_abstention": 0.20,
    },
    "momentum": {
        "win_rate": 0.48,
        "min_trades": 50,
        "max_dd": 0.30,
        "max_abstention": 0.15,
    },
    "contrarian": {
        "win_rate": 0.45,
        "min_trades_default": 25,    # floor; per-subtype adjusted in code
        "max_dd_default": 0.35,      # floor; per-subtype adjusted in code
        "max_abstention": 0.25,
    },
}

# ── Type-specific Tier 2 thresholds ──────────────────────────────────────────

_TIER2_THRESHOLDS = {
    "expert": {
        "sortino": 0.5,
        "mar": 0.8,
        "gpr": 1.5,
        "k_ratio": 0.4,
    },
    "momentum": {
        "sortino": 0.3,
        "mar": 0.5,
        "gpr": 1.2,
        "k_ratio": 0.3,
    },
    "contrarian": {
        "sortino": 0.25,
        "mar": 0.4,
        "gpr": 1.0,
        "k_ratio": 0.25,
    },
}

# ── Data types ───────────────────────────────────────────────────────────────


@dataclass
class GraduationResult:
    """Complete graduation evaluation for one shadow."""
    shadow_id: str
    shadow_type: str
    passed_tier1: bool
    passed_tier2: bool
    passed_stress_test: bool
    gate2_qualified: bool
    tier1_details: dict  # win_rate, total_return, brier_type, min_trades, max_dd, abstention_rate
    tier2_details: dict  # sortino, mar, gpr, k_ratio, beat_benchmark, beat_main_pipeline
    blocking_reasons: list[str] = field(default_factory=list)
    stress_test_results: dict = field(default_factory=dict)  # gfc_2008, covid_2020, rate_hike_2022
    alpha_purity: dict = field(default_factory=dict)  # alpha, t_stat, alpha_positive, t_significant
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Engine ───────────────────────────────────────────────────────────────────


class GraduationEngine:
    """Multi-stage qualification engine for Gate 2 interaction rights.

    Shadows graduate through a 4-stage pipeline:
      1. Tier 1 — Basic competence (win rate, return, Brier, trades, DD, abstention)
      2. Tier 2 — Type-specific excellence (Sortino, MAR, GPR, K-Ratio, benchmarks)
      3. Stress Tests — Historical crisis scenarios (GFC, COVID, rate hikes)
      4. Alpha Purity — Carhart 4-factor alpha significance

    Graduation is NOT automatic — Elite status is a prerequisite (checked upstream
    by the orchestrator), and even Elite shadows must pass all tiers to qualify.
    """

    def __init__(self, state_db: ShadowStateDB):
        self.state_db = state_db
        self._risk_free_rate_annual = 0.04  # 4% annual risk-free rate assumption

    # ── Public API ────────────────────────────────────────────────────────

    def evaluate(self, shadow_id: str, lookback_days: int | None = None) -> GraduationResult:
        """Run full graduation pipeline for one shadow.

        Args:
            shadow_id: The shadow to evaluate.
            lookback_days: Override default lookback. If None, uses type-specific window
                           (Expert=90, Momentum=75, Contrarian=252).

        Returns:
            GraduationResult with all tier results, stress test outcomes, and qualification status.
        """
        config = self.state_db.get_shadow(shadow_id)
        if config is None:
            return GraduationResult(
                shadow_id=shadow_id,
                shadow_type="unknown",
                passed_tier1=False,
                passed_tier2=False,
                passed_stress_test=False,
                gate2_qualified=False,
                tier1_details={},
                tier2_details={},
                blocking_reasons=[f"Shadow '{shadow_id}' not found in state DB"],
            )

        shadow_type = config.shadow_type
        if lookback_days is None:
            lookback_days = default_lookback(shadow_type)

        snapshots = self.state_db.get_snapshot_history(shadow_id, days=lookback_days)
        trades = self.state_db.get_trade_history(shadow_id, limit=9999)

        blocking_reasons: list[str] = []

        # Tier 1: Basic competence
        t1_result = self._evaluate_tier1(shadow_id, shadow_type, snapshots, trades, lookback_days)
        tier1_passed = len(t1_result.get("failures", [])) == 0
        if not tier1_passed:
            blocking_reasons.extend(t1_result.get("failures", []))

        # Tier 2: Type-specific excellence
        t2_result = self._evaluate_tier2(shadow_id, shadow_type, snapshots, trades)
        tier2_passed = len(t2_result.get("failures", [])) == 0
        if not tier2_passed:
            blocking_reasons.extend(t2_result.get("failures", []))

        # Stress tests — delegated to StressTestRunner
        stress_runner = StressTestRunner(self.state_db)
        stress_result = stress_runner.run_stress_tests(shadow_id)
        stress_passed = not stress_result.get("any_failed", True)

        # Alpha purity — delegated to check_alpha_purity()
        alpha_result = check_alpha_purity(snapshots)
        if not alpha_result.get("alpha_positive", False):
            blocking_reasons.append(f"ALPHA: Carhart alpha <= 0 ({alpha_result.get('alpha', 0):.4f})")
        if not alpha_result.get("t_significant", False):
            blocking_reasons.append(
                f"ALPHA: t-stat {alpha_result.get('t_stat', 0):.2f} <= 1.65"
            )

        gate2_qualified = tier1_passed and tier2_passed and stress_passed and alpha_result.get("alpha_positive", False)

        return GraduationResult(
            shadow_id=shadow_id,
            shadow_type=shadow_type,
            passed_tier1=tier1_passed,
            passed_tier2=tier2_passed,
            passed_stress_test=stress_passed,
            gate2_qualified=gate2_qualified,
            tier1_details=t1_result,
            tier2_details=t2_result,
            blocking_reasons=blocking_reasons,
            stress_test_results=stress_result,
            alpha_purity=alpha_result,
        )

    # ── Tier 1: Basic Competence ───────────────────────────────────────────

    def _evaluate_tier1(
        self,
        shadow_id: str,
        shadow_type: str,
        snapshots: list[DailySnapshot],
        trades: list,
        lookback_days: int,
    ) -> dict:
        """Evaluate Tier 1: win rate, total return, Brier, min trades, max DD, abstention."""
        failures: list[str] = []
        thresholds = _TIER1_THRESHOLDS.get(shadow_type, _TIER1_THRESHOLDS["expert"])

        # Compute win rate
        win_rate = compute_win_rate(trades)
        wr_threshold = thresholds["win_rate"]

        # Compute total return
        total_return = compute_total_return(snapshots)

        # Determine min trades for this shadow type/subtype
        min_trades_threshold = thresholds.get("min_trades", 5)
        max_dd_threshold = thresholds.get("max_dd", 0.25)
        if shadow_type == "contrarian":
            min_trades_threshold, max_dd_threshold = contrarian_trade_dd(shadow_id)

        # Compute max drawdown
        max_dd = compute_max_dd(snapshots)

        # Compute abstention rate
        abstention_days = self.state_db.get_abstention_days(shadow_id, days=lookback_days)
        abstention_rate = abstention_days / max(lookback_days, 1)
        max_abstention = thresholds.get("max_abstention", 0.25)

        # Brier decomposition (approximate from available calibration data)
        brier_type = estimate_brier_type(shadow_id, trades)

        details = {
            "win_rate": round(win_rate, 4),
            "wr_threshold": wr_threshold,
            "total_return": round(total_return, 4),
            "brier_type": brier_type,
            "min_trades": len(trades),
            "min_trades_threshold": min_trades_threshold,
            "max_dd": round(max_dd, 4),
            "max_dd_threshold": max_dd_threshold,
            "abstention_rate": round(abstention_rate, 4),
            "max_abstention": max_abstention,
        }

        if win_rate < wr_threshold:
            failures.append(
                f"T1_WR: win_rate={win_rate:.4f} < {wr_threshold}"
            )
        if total_return <= 0:
            failures.append(
                f"T1_RETURN: total_return={total_return:.4f} <= 0"
            )
        if len(trades) < min_trades_threshold:
            failures.append(
                f"T1_TRADES: {len(trades)} < {min_trades_threshold}"
            )
        if max_dd >= max_dd_threshold:
            failures.append(
                f"T1_DD: max_dd={max_dd:.4f} >= {max_dd_threshold}"
            )
        if abstention_rate > max_abstention:
            failures.append(
                f"T1_ABSTAIN: abstention_rate={abstention_rate:.4f} > {max_abstention}"
            )
        if brier_type not in ("Eagle", "Bull"):
            failures.append(
                f"T1_BRIER: brier_type={brier_type} (need Eagle or Bull)"
            )

        details["failures"] = failures
        return details

    # ── Tier 2: Type-Specific Excellence ───────────────────────────────────

    def _evaluate_tier2(
        self,
        shadow_id: str,
        shadow_type: str,
        snapshots: list[DailySnapshot],
        trades: list,
    ) -> dict:
        """Evaluate Tier 2: Sortino, MAR, GPR, K-Ratio, benchmark comparison."""
        failures: list[str] = []
        thresholds = _TIER2_THRESHOLDS.get(shadow_type, _TIER2_THRESHOLDS["expert"])

        # DailySnapshot stores returns as percentage (e.g., 0.5 = 0.5%).
        # Convert to decimal for metric computation (e.g., 0.5% → 0.005).
        daily_returns = [
            (s.daily_return_pct or 0.0) / 100.0
            for s in snapshots if s.daily_return_pct is not None
        ]

        sortino = compute_sortino(daily_returns)
        mar = compute_mar(daily_returns)
        gpr = compute_gpr(daily_returns)
        k_ratio = compute_k_ratio(daily_returns)

        # Beat benchmark check (simplified: uses type-specific floor as proxy)
        benchmark_annual_return = get_benchmark_return(shadow_type)
        shadow_annual_return = annualized_return(daily_returns)
        beat_benchmark = shadow_annual_return > benchmark_annual_return

        # Anti-gaming: min-bet (>$100) trades must be <= 60%
        # If >60% are min-bets, apply 0.7 discount to Sortino/MAR
        min_bet_ratio = compute_min_bet_ratio(trades)
        if min_bet_ratio > 0.60:
            sortino *= 0.7
            mar *= 0.7

        # Single-trade dependency check
        single_trade_dominant = check_single_trade_dependency(trades)

        details = {
            "sortino": round(sortino, 4),
            "sortino_threshold": thresholds["sortino"],
            "mar": round(mar, 4),
            "mar_threshold": thresholds["mar"],
            "gpr": round(gpr, 4),
            "gpr_threshold": thresholds["gpr"],
            "k_ratio": round(k_ratio, 4),
            "k_ratio_threshold": thresholds["k_ratio"],
            "shadow_annual_return": round(shadow_annual_return, 4),
            "benchmark_annual_return": round(benchmark_annual_return, 4),
            "beat_benchmark": beat_benchmark,
            "min_bet_ratio": round(min_bet_ratio, 4),
            "single_trade_dominant": single_trade_dominant,
        }

        if sortino < thresholds["sortino"]:
            failures.append(
                f"T2_SORTINO: {sortino:.4f} < {thresholds['sortino']}"
            )
        if mar < thresholds["mar"]:
            failures.append(
                f"T2_MAR: {mar:.4f} < {thresholds['mar']}"
            )
        if gpr < thresholds["gpr"]:
            failures.append(
                f"T2_GPR: {gpr:.4f} < {thresholds['gpr']}"
            )
        if k_ratio < thresholds["k_ratio"]:
            failures.append(
                f"T2_KRATIO: {k_ratio:.4f} < {thresholds['k_ratio']}"
            )
        if not beat_benchmark:
            failures.append(
                f"T2_BENCHMARK: shadow={shadow_annual_return:.4f} <= benchmark={benchmark_annual_return:.4f}"
            )
        if single_trade_dominant:
            failures.append("T2_SINGLE_TRADE: single trade dominates >50% of total P&L")

        details["failures"] = failures
        return details
