"""Composite scoring with dynamic win-rate line and V2 calibration weights.

Extracted from ranking_engine.py per modular architecture rules (§3.1).
Handles: composite score computation, dynamic WR line, MPPM/Calmar normalization,
calibration blending, profitability penalty, and abstention penalty.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.composite_scoring")

if TYPE_CHECKING:
    from marketmind.shadows.ranking_engine import RankingResult, ShadowPerformance


class CompositeScoring:
    """Dynamic win-rate line + V2 composite scoring engine.

    Delegates raw metric computation (omega, calmar, mppm) to callbacks
    provided by RankingEngine, keeping the metric primitives in one place
    while extracting the scoring logic.
    """

    # Dynamic win-rate line parameters
    WR_LINE_FLOOR = 0.45          # Hard floor — actual win rate can never go below this
    WR_WEIGHT_FLOOR = 0.12        # Minimum WR weight in composite (distinct from line)
    WR_EARLY_DAYS = 60            # New shadow: heavy WR emphasis
    WR_MATURE_DAYS = 180          # Mature shadow: can trade WR for profitability
    WR_EARLY_WEIGHT_BOOST = 0.10  # Extra WR weight during early career (+10pp)
    PROFIT_LOSS_PENALTY = 0.40    # Multiplicative penalty when cumulative return < 0
    PROFIT_LOSS_FLOOR = 0.02      # Minimum composite after penalty (prevent zero-division)

    # V2 composite weights (Phase 2b: learning-enhanced ranking)
    V2_WEIGHTS = {"mppm": 0.30, "calmar": 0.20, "omega": 0.15, "win_rate": 0.15}
    V2_CALIBRATION_WEIGHT = 0.20

    def __init__(self, config: ShadowSettings):
        self.config = config

    def compute_composite_score(
        self,
        perf: ShadowPerformance,
        career_days: int | None,
        compute_omega: Callable[[list[float]], float],
        compute_calmar: Callable[[float, float], float],
        compute_mppm: Callable[[list[float]], float],
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        """Returns (C_raw, component_scores_dict, modifiers_dict).

        Modifiers track the dynamic WR line adjustments and profitability
        penalties for transparency in ranking display.

        V2 formula (Phase 2b): when calibration data is available,
        C_v2 = 0.30*MPPM + 0.20*Calmar + 0.15*Omega + 0.15*WR + 0.20*Calibration_Score.
        If no Brier/calibration data, the 0.20 calibration weight redistributes
        across the 4 existing components (backward compatible with v1).
        """
        has_calibration = perf.brier_score < 1.0 or perf.calibration_score > 0.0

        if has_calibration:
            w = dict(self.V2_WEIGHTS)
            calibration_weight = self.V2_CALIBRATION_WEIGHT
        else:
            w = dict(self.config.composite_weights)
            calibration_weight = 0.0

        perf_pool = 1.0 - calibration_weight  # 0.80 in v2, 1.0 in v1

        modifiers = {
            "wr_weight_raw": w["win_rate"],
            "wr_weight_adjusted": w["win_rate"],
            "wr_line_value": 0.0,
            "profitability_penalty": 0.0,
            "career_days": career_days or 0,
            "calibration_weight": calibration_weight,
            "has_calibration": has_calibration,
        }

        omega = compute_omega(perf.daily_returns)
        calmar = compute_calmar(perf.cumulative_return, perf.max_drawdown)
        mppm = compute_mppm(perf.daily_returns)

        components = {
            "mppm": mppm,
            "calmar": calmar,
            "omega": omega,
            "win_rate": perf.win_rate,
        }

        # —— Dynamic win-rate line ——
        wr_line = self._compute_wr_line(
            career_days,
            domain=getattr(perf, 'domain', None),
            shadow_type=getattr(perf, 'shadow_type', None),
        )
        modifiers["wr_line_value"] = wr_line

        if career_days is not None and career_days < self.WR_EARLY_DAYS:
            # Early career: boost WR weight to incentivize direction accuracy
            boosted = min(w["win_rate"] + self.WR_EARLY_WEIGHT_BOOST, 0.50)
            if perf_pool > boosted:
                ratio = (perf_pool - boosted) / (perf_pool - w["win_rate"])
                for key in ("mppm", "calmar", "omega"):
                    w[key] *= ratio
            w["win_rate"] = boosted

        elif career_days is not None and career_days >= self.WR_MATURE_DAYS:
            # Mature: allow WR weight to decrease if profitability is strong
            if perf.cumulative_return > 0.10:
                wr_discount = min(0.08, (perf.cumulative_return - 0.10) * 0.15)
                w["win_rate"] = max(self.WR_WEIGHT_FLOOR, w["win_rate"] - wr_discount)
                redist = wr_discount / 3.0
                for key in ("mppm", "calmar", "omega"):
                    w[key] += redist

        modifiers["wr_weight_adjusted"] = w["win_rate"]

        # Normalize each component to [0, 1]
        mppm_norm = self._normalize_mppm(mppm)
        calmar_norm = self._normalize_calmar(calmar)
        omega_norm = omega / 10.0
        wr_norm = perf.win_rate

        composite = (
            w["mppm"] * mppm_norm +
            w["calmar"] * calmar_norm +
            w["omega"] * omega_norm +
            w["win_rate"] * wr_norm
        )

        # —— Calibration score (Phase 2b v2 formula) ——
        if has_calibration:
            if perf.calibration_score > 0.0:
                cal_score = perf.calibration_score
            else:
                brier_component = 1.0 - perf.brier_score
                if perf.domain_scores:
                    scores = list(perf.domain_scores.values())
                    mean_score = sum(scores) / len(scores)
                    resolution = sum((s - mean_score) ** 2 for s in scores) / len(scores)
                else:
                    resolution = 0.0
                cal_score = 0.5 * brier_component + 0.5 * resolution
                cal_score = max(0.0, min(1.0, cal_score))

            composite += calibration_weight * cal_score
            components["calibration"] = cal_score
            modifiers["calibration_score"] = cal_score

        # —— Profitability penalty ——
        if perf.cumulative_return < 0:
            penalty = min(
                self.PROFIT_LOSS_PENALTY,
                abs(perf.cumulative_return) * 0.5
            )
            composite = max(composite * (1.0 - penalty), self.PROFIT_LOSS_FLOOR)
            modifiers["profitability_penalty"] = penalty

        # —— Abstention penalty (anti-conservatism, Phase 2) ——
        abstention_penalty = 0.0
        if career_days and career_days > 0:
            abstention_rate = perf.abstention_days / career_days
            if abstention_rate > 0.3:  # Only penalize if >30% days abstained
                abstention_penalty = self.config.abstention_penalty_weight * abstention_rate
                composite -= abstention_penalty
        modifiers["abstention_penalty"] = abstention_penalty

        return max(composite, 0.0), components, modifiers

    @staticmethod
    def _compute_wr_line(career_days: int | None, domain: str | None = None,
                         shadow_type: str | None = None) -> float:
        """Dynamic win-rate floor. Returns the minimum acceptable WR for ranking bonus.

        Early career: higher line (encourage direction accuracy).
        Mature career: line can relax if shadow is profitable.
        Domain/shadow_type flexibility: daredevil and contrarian strategies
        naturally have lower win rates.
        """
        if career_days is None:
            return CompositeScoring.WR_LINE_FLOOR

        # Strategy-type adjustment: daredevils and contrarian strategies
        # structurally have lower win rates by design
        domain_adjust = 0.0
        if shadow_type == "daredevil":
            domain_adjust = -0.05
        elif domain and domain in ("contrarian", "short"):
            domain_adjust = -0.05

        if career_days < CompositeScoring.WR_EARLY_DAYS:
            return max(CompositeScoring.WR_LINE_FLOOR, 0.55 + domain_adjust)
        elif career_days < CompositeScoring.WR_MATURE_DAYS:
            progress = (career_days - CompositeScoring.WR_EARLY_DAYS) / (
                CompositeScoring.WR_MATURE_DAYS - CompositeScoring.WR_EARLY_DAYS
            )
            return max(CompositeScoring.WR_LINE_FLOOR, 0.55 - 0.10 * progress + domain_adjust)
        else:
            return max(CompositeScoring.WR_LINE_FLOOR, 0.45 + domain_adjust)

    @staticmethod
    def _normalize_mppm(mppm: float) -> float:
        """Normalize MPPM to [0, 1]. Log-sigmoid transform.
        MPPM typically ranges from -2 to +2 for daily returns.
        """
        if mppm == float("-inf"):
            return 0.0
        if math.isnan(mppm):
            return 0.0
        return 1.0 / (1.0 + math.exp(-mppm))

    @staticmethod
    def _normalize_calmar(calmar: float) -> float:
        """Normalize Calmar to [0, 1]. Calmar > 3 is exceptional."""
        return min(calmar / 3.0, 1.0)

    @staticmethod
    def apply_holm_bonferroni(results: list[RankingResult]) -> None:
        """Apply Holm-Bonferroni correction to achievement tier assignments.

        For N shadows, the probability of at least one false ELITE is
        ~1 - (1-alpha)^N. With 22 shadows, this is ~97% without correction.
        This method steps down through ranked shadows and requires surviving
        a corrected alpha threshold.

        Shadows at the boundary that fail the corrected threshold are
        downgraded to the next tier.
        """
        n = len(results)
        if n < 2:
            return

        # Tier severity ordering (for downgrade logic)
        tier_order = {"elite": 3, "excellent": 2, "normal": 1, "endangered": 0}
        reverse_tier = {3: "elite", 2: "excellent", 1: "normal", 0: "endangered"}

        # For ELITE/EXCELLENT shadows: require surviving step-down
        # Sort by percentile_rank descending (most significant first) for Holm
        alpha = 0.05  # family-wise error rate
        ranked = sorted(results, key=lambda r: r.percentile_rank, reverse=True)

        # Count how many ELITE + EXCELLENT exist
        elevated = [r for r in ranked if r.achievement_tier in ("elite", "excellent")]
        k = len(elevated)

        for i, r in enumerate(elevated):
            corrected_alpha = alpha / (k - i)  # Holm step-down
            # If shadow's percentile rank would not be significant at corrected alpha,
            # downgrade to NORMAL
            if r.percentile_rank < (1.0 - corrected_alpha):
                old_tier = r.achievement_tier
                r.achievement_tier = "normal"
                logger.info(
                    "Holm-Bonferroni: %s downgraded from %s to normal "
                    "(percentile=%.2f, corrected_alpha=%.4f)",
                    r.shadow_id, old_tier, r.percentile_rank, corrected_alpha
                )
