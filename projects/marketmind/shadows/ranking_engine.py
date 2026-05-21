"""Ranking Engine -- pure Python composite score, Bayesian haircut, achievement ladder.

Zero LLM calls. All computation is deterministic mathematical formulas.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.shadows.ranking_engine")

from marketmind.config.settings import ShadowSettings
from marketmind.shadows.composite_scoring import CompositeScoring
from marketmind.shadows.plateau_detector import PlateauDetector


@dataclass
class ShadowPerformance:
    """Single shadow's performance metrics for one evaluation period."""
    shadow_id: str
    daily_returns: list[float]
    cumulative_return: float
    max_drawdown: float
    max_drawdown_duration_days: int
    win_rate: float
    total_trades: int
    profitable_trades: int
    losing_trades: int
    abstention_days: int
    cagr: float
    domain: str | None = None
    shadow_type: str = "beta"
    career_days: int = 0
    brier_score: float = 1.0
    calibration_score: float = 0.0
    token_efficiency: float = 0.0
    domain_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class RankingResult:
    shadow_id: str
    rank: int
    composite_score: float
    deflated_score: float
    percentile_rank: float
    achievement_tier: str
    component_scores: dict[str, float]
    component_percentiles: dict[str, float]


class RankingEngine:
    """Pure Python ranking computation. No LLM calls."""

    # Backward-compatible aliases for constants extracted to CompositeScoring
    _V2_WEIGHTS = CompositeScoring.V2_WEIGHTS
    _V2_CALIBRATION_WEIGHT = CompositeScoring.V2_CALIBRATION_WEIGHT

    def __init__(self, config: ShadowSettings):
        self.config = config
        self._composite = CompositeScoring(config)
        self._plateau = PlateauDetector(config)

    # ── Core metrics ─────────────────────────────────────────────────────

    def compute_mppm(self, returns: list[float], gamma: float = 3.0) -> float:
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

    def compute_calmar(self, cumulative_return: float, max_drawdown: float) -> float:
        """Calmar = CAGR / max(|MDD|, floor). Capped at 100."""
        mdd_floor = max(max_drawdown, 0.001)
        cagr = cumulative_return
        calmar = cagr / mdd_floor
        return min(calmar, 100.0)

    def compute_omega(self, returns: list[float], threshold: float = 0.0) -> float:
        """Omega(L=0) = sum(gains) / sum(|losses|). Capped at 10."""
        if not returns:
            return 1.0
        gains = sum(max(r - threshold, 0) for r in returns)
        losses = sum(abs(min(r - threshold, 0)) for r in returns)
        if losses == 0:
            return 10.0
        omega = gains / losses
        return min(omega, 10.0)

    def compute_cagr(self, cumulative_return: float, days: int) -> float:
        """Annualize cumulative return over N trading days."""
        if days <= 0:
            return 0.0
        return cumulative_return * 252 / days

    # ── Composite scoring (delegated to CompositeScoring) ────────────────

    def compute_composite_score(
        self, perf: ShadowPerformance, career_days: int | None = None
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        """Returns (C_raw, component_scores_dict, modifiers_dict).

        Delegated to CompositeScoring. Modifiers track dynamic WR line
        adjustments and profitability penalties for ranking display.
        """
        return self._composite.compute_composite_score(
            perf, career_days,
            self.compute_omega, self.compute_calmar, self.compute_mppm,
        )

    # ── Bayesian overfitting haircut ──────────────────────────────────────

    def compute_haircut(self, n_shadows: int, evaluation_days: int,
                         daily_returns: dict[str, list[float]] | None = None) -> float:
        """Witzany (2021) with Effective-N correction (P2-1).

        If daily_returns is provided, computes the correlation matrix of
        shadow returns and estimates effective N via:
            Neff = N / (1 + (N-1) * mean_abs_corr)

        This prevents the haircut from over-penalizing uncorrelated shadows
        or under-penalizing tightly correlated ones.
        """
        if n_shadows < 1:
            n_shadows = 1

        n_eff = float(n_shadows)
        if daily_returns and len(daily_returns) >= 3:
            mean_corr = self._mean_abs_correlation(daily_returns)
            if mean_corr is not None:
                n_eff = n_shadows / (1.0 + (n_shadows - 1) * mean_corr)
                n_eff = max(1.5, min(n_eff, float(n_shadows)))  # clamp

        return evaluation_days / (evaluation_days + 8.0 + 24.0 * math.log(max(n_eff, 1.5)))

    @staticmethod
    def _mean_abs_correlation(daily_returns: dict[str, list[float]]) -> float | None:
        """Compute mean absolute pairwise correlation of shadow returns."""
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

    def apply_bayesian_haircut(self, composite_score: float, n_shadows: int,
                                evaluation_days: int) -> float:
        """C_deflated = C_raw * h(N,T)."""
        return composite_score * self.compute_haircut(n_shadows, evaluation_days)

    # ── Percentile computation ───────────────────────────────────────────

    def compute_percentile_ranks(self, scores: dict[str, float]) -> dict[str, float]:
        """Map each shadow_id to its percentile rank (0-1) within the cohort.
        Hybrid parametric/empirical approach.
        """
        if not scores:
            return {}
        n = len(scores)
        score_list = list(scores.values())

        if n >= self.config.parametric_threshold_n:
            return self._empirical_percentiles(scores, score_list)
        elif n <= 15:
            return self._parametric_percentiles(scores, score_list)
        else:
            alpha = n / self.config.parametric_threshold_n
            emp = self._empirical_percentiles(scores, score_list)
            par = self._parametric_percentiles(scores, score_list)
            return {
                sid: alpha * emp.get(sid, 0.5) + (1 - alpha) * par.get(sid, 0.5)
                for sid in scores
            }

    @staticmethod
    def _empirical_percentiles(scores: dict[str, float],
                                score_list: list[float]) -> dict[str, float]:
        """Fraction of scores <= x (with continuity correction)."""
        n = len(score_list)
        sorted_scores = sorted(score_list)
        result = {}
        for sid, score in scores.items():
            count_le = sum(1 for s in sorted_scores if s <= score)
            result[sid] = (count_le - 0.5) / n
        return result

    @staticmethod
    def _parametric_percentiles(scores: dict[str, float],
                                 score_list: list[float]) -> dict[str, float]:
        """Logistic-normal parametric percentile estimation for small N."""
        n = len(score_list)
        # Fit logistic-normal: first map scores to (0,1) via logit, fit normal
        # Simplified: use rank-based logistic approximation
        sorted_scores = sorted(score_list)
        result = {}
        for sid, score in scores.items():
            rank = sum(1 for s in sorted_scores if s <= score)
            # Logistic percentile: smooth interpolation
            p = (rank - 0.5) / n
            # Apply logistic smoothing for small N
            result[sid] = 1.0 / (1.0 + math.exp(-2.0 * (p - 0.5) * math.sqrt(n)))
        return result

    # ── Achievement ladder ────────────────────────────────────────────────

    def determine_achievement_tier(
        self,
        score_history: list[tuple[str, float]],
        percentile_history: list[tuple[str, float]],
        mdd: float,
        deflated_sharpe: float,
        market_accuracy: float | None = None,
    ) -> str:
        """Returns tier based on consecutive day rules.

        States: ELITE, EXCELLENT, NORMAL, WATCH, ENDANGERED

        P2-4: market_accuracy < 0.50 demotes ELITE to NORMAL.
        This prevents shadows from achieving top tier when directional
        predictions don't align with external market data.
        """
        if not percentile_history:
            return "normal"

        cfg = self.config
        days_at_elite = self._count_consecutive_above(
            percentile_history, cfg.achievement_percentiles["elite"]
        )
        days_at_excellent = self._count_consecutive_above(
            percentile_history, cfg.achievement_percentiles["excellent"]
        )
        days_below_watch = self._count_consecutive_below(
            percentile_history, cfg.achievement_percentiles["watch"]
        )
        days_below_endangered = self._count_consecutive_below(
            percentile_history, cfg.achievement_percentiles["endangered"]
        )

        # Elite check
        if days_at_elite >= cfg.elite_consecutive_days and deflated_sharpe > cfg.elite_deflated_sharpe_min:
            if market_accuracy is not None and market_accuracy < 0.50:
                logger.info(
                    "ELITE demoted to NORMAL: market_accuracy=%.2f < 0.50",
                    market_accuracy,
                )
                return "normal"
            return "elite"

        # Excellent check
        if days_at_excellent >= cfg.excellent_consecutive_days and deflated_sharpe > cfg.excellent_deflated_sharpe_min:
            return "excellent"

        # Endangered check
        if days_below_endangered >= cfg.endangered_consecutive_days:
            return "endangered"

        # Watch check
        if days_below_watch >= cfg.watch_consecutive_days or mdd > cfg.watch_mdd_threshold:
            return "watch"

        return "normal"

    @staticmethod
    def _count_consecutive_above(history: list[tuple[str, float]],
                                  threshold: float) -> int:
        """Count consecutive days (from most recent) above threshold."""
        if not history:
            return 0
        sorted_hist = sorted(history, key=lambda x: x[0], reverse=True)
        count = 0
        for _, val in sorted_hist:
            if val >= threshold:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _count_consecutive_below(history: list[tuple[str, float]],
                                  threshold: float) -> int:
        """Count consecutive days (from most recent) below threshold."""
        if not history:
            return 0
        sorted_hist = sorted(history, key=lambda x: x[0], reverse=True)
        count = 0
        for _, val in sorted_hist:
            if val < threshold:
                count += 1
            else:
                break
        return count

    # ── Plateau detection (delegated to PlateauDetector) ──────────────────

    def detect_plateau(
        self,
        shadow_id: str,
        tier_history: list[tuple[str, str]],
        win_rate_history: list[tuple[str, float]],
        insight_dates: list[str],
    ) -> tuple[bool, float]:
        """Returns (is_plateaued, plateau_score) where higher score = more stale."""
        return self._plateau.detect_plateau(
            shadow_id, tier_history, win_rate_history, insight_dates,
        )

    # ── Full ranking pipeline ─────────────────────────────────────────────

    def rank_shadows(
        self,
        performances: dict[str, ShadowPerformance],
        score_histories: dict[str, list[dict]],
        date: str,
        market_accuracies: dict[str, float] | None = None,
    ) -> list[RankingResult]:
        """Full ranking: metrics -> composite -> haircut -> percentile -> ladder.

        P2-4: market_accuracies map shadow_id -> external directional accuracy.
        Used to gate ELITE tier (accuracy < 0.50 -> demote to NORMAL).
        """
        n = len(performances)
        results = []

        # Compute raw composites
        raw_scores = {}
        component_data = {}
        modifiers_data = {}
        for sid, perf in performances.items():
            composite, components, modifiers = self.compute_composite_score(
                perf, career_days=perf.career_days
            )
            raw_scores[sid] = composite
            component_data[sid] = components
            modifiers_data[sid] = modifiers

        # Apply Bayesian haircut with Effective-N correction (P2-1)
        returns_for_corr = {
            sid: performances[sid].daily_returns for sid in performances
            if performances[sid].daily_returns
        }
        haircut = self.compute_haircut(n, self.config.evaluation_window_days, returns_for_corr)
        deflated = {sid: s * haircut for sid, s in raw_scores.items()}

        # Compute percentiles on deflated scores
        percentiles = self.compute_percentile_ranks(deflated)

        # Compute component percentiles
        component_pct = {}
        for comp_name in ["mppm", "calmar", "omega", "win_rate"]:
            comp_scores = {
                sid: component_data[sid].get(comp_name, 0)
                for sid in performances
            }
            component_pct[comp_name] = self.compute_percentile_ranks(comp_scores)

        # —— Quota efficiency scoring (Phase 2) ——
        # Group shadows by domain for within-domain normalization
        domain_groups: dict[str, list[str]] = {}
        for sid, perf in performances.items():
            dom = perf.domain or "macro"
            domain_groups.setdefault(dom, []).append(sid)

        quota_eff_by_domain: dict[str, float] = {}
        for domain, sids in domain_groups.items():
            eff_entries = []
            for sid in sids:
                perf = performances[sid]
                # Efficiency = profitable decisions / total trades within domain
                # Higher profitable_trades ratio relative to peers = more efficient
                eff = perf.profitable_trades / max(perf.total_trades, 1)
                eff_entries.append((sid, eff))
            max_eff = max(e[1] for e in eff_entries) if eff_entries else 1.0
            for sid, eff in eff_entries:
                quota_eff_by_domain[sid] = eff / max_eff if max_eff > 0 else 0.5

        # Apply quota efficiency as a composite bonus/penalty
        qe_weight = getattr(self.config, 'quota_efficiency_weight', 0.05)
        for sid in raw_scores:
            qe = quota_eff_by_domain.get(sid, 0.5)
            bonus = qe_weight * (qe - 0.5) * 2.0  # center at 0.5: below avg = penalty
            raw_scores[sid] = raw_scores[sid] + bonus
            modifiers_data[sid]["quota_efficiency"] = qe
            modifiers_data[sid]["quota_efficiency_bonus"] = bonus

        # Re-apply deflated after quota efficiency adjustment
        deflated = {sid: s * haircut for sid, s in raw_scores.items()}
        percentiles = self.compute_percentile_ranks(deflated)

        # Determine tiers and build results
        for sid in performances:
            perf = performances[sid]
            score_hist = score_histories.get(sid, [])

            deflated_sharpe = self._estimate_sharpe(perf.daily_returns)
            shadow_ma = market_accuracies.get(sid) if market_accuracies else None
            tier = self.determine_achievement_tier(
                [(h["date"], h.get("deflated_score", 0)) for h in score_hist],
                [(h["date"], h.get("percentile_rank", 0)) for h in score_hist],
                perf.max_drawdown,
                deflated_sharpe,
                market_accuracy=shadow_ma,
            )

            comp_pct_for_shadow = {
                name: component_pct[name].get(sid, 0.5)
                for name in component_pct
            }

            results.append(RankingResult(
                shadow_id=sid,
                rank=0,
                composite_score=raw_scores[sid],
                deflated_score=deflated[sid],
                percentile_rank=percentiles.get(sid, 0.5),
                achievement_tier=tier,
                component_scores=component_data[sid],
                component_percentiles=comp_pct_for_shadow,
            ))

        # Sort by deflated score descending, assign ranks
        results.sort(key=lambda r: r.deflated_score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        # P2-5: Holm-Bonferroni correction — downgrade tiers that fail FDR control
        self._apply_holm_bonferroni(results)

        return results

    @staticmethod
    def _apply_holm_bonferroni(results: list[RankingResult]) -> None:
        """Apply Holm-Bonferroni correction. Delegated to CompositeScoring."""
        CompositeScoring.apply_holm_bonferroni(results)

    @staticmethod
    def _estimate_sharpe(returns: list[float]) -> float:
        """Estimate annualized Sharpe from daily returns."""
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        if variance <= 0:
            return 0.0
        daily_sharpe = mean / math.sqrt(variance)
        return daily_sharpe * math.sqrt(252)

    # ── Reset eligibility (delegated to PlateauDetector) ──────────────────

    def check_reset_eligibility(
        self,
        tier_history: list[tuple[str, str]],     # (date, tier)
        wr_history: list[tuple[str, float]],      # (date, win_rate)
        insight_dates: list[str],                  # dates with insights
    ) -> tuple[bool, str]:
        """Check if a shadow should be reset to baseline methodology.

        Delegated to PlateauDetector.
        """
        return self._plateau.check_reset_eligibility(
            tier_history, wr_history, insight_dates,
        )


# ── Token efficiency (standalone) ────────────────────────────────────────

def compute_token_efficiency(shadow_id: str, cumulative_return: float,
                             total_tokens: int) -> float:
    """Pod-shop pattern: return per token consumed.

    Shadows that burn tokens without returns face tier downgrade.
    Returns 0.0 if no tokens consumed.
    """
    if total_tokens == 0:
        return 0.0
    return cumulative_return / total_tokens
