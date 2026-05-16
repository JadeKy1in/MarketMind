"""Ranking Engine -- orchestrator for composite scoring and statistical testing.

Delegates calculation to ranking_composite (metrics, scoring, percentiles, haircut)
and ranking_stats (walk-forward validation, Sharpe, reset eligibility).

Zero LLM calls. All computation is deterministic mathematical formulas.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.ranking_engine")

from marketmind.config.settings import ShadowSettings
from marketmind.shadows.ranking_composite import (
    ShadowPerformance,
    RankingResult,
    compute_mppm,
    compute_calmar,
    compute_omega,
    compute_cagr,
    compute_composite_score as _compute_composite_score,
    compute_haircut as _compute_haircut,
    apply_bayesian_haircut as _apply_bayesian_haircut,
    compute_percentile_ranks as _compute_percentile_ranks,
)
from marketmind.shadows.ranking_stats import (
    WFValidationResult,
    WalkForwardValidator,
    estimate_sharpe as _estimate_sharpe_raw,
    check_reset_eligibility as _check_reset_eligibility,
)


class RankingEngine:
    """Pure Python ranking computation. No LLM calls."""

    def __init__(self, config: ShadowSettings):
        self.config = config

    # ── Core metrics ──────────────────────────────────────────────────────

    def compute_mppm(self, returns: list[float], gamma: float = 3.0) -> float:
        return compute_mppm(returns, gamma)

    def compute_calmar(self, cumulative_return: float, max_drawdown: float,
                       days: int = 252) -> float:
        return compute_calmar(cumulative_return, max_drawdown, days)

    def compute_omega(self, returns: list[float], threshold: float = 0.0) -> float:
        return compute_omega(returns, threshold)

    def compute_cagr(self, cumulative_return: float, days: int) -> float:
        return compute_cagr(cumulative_return, days)

    # ── Composite scoring ─────────────────────────────────────────────────

    def compute_composite_score(
        self, perf: ShadowPerformance, career_days: int | None = None
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        return _compute_composite_score(
            perf,
            self.config.composite_weights,
            career_days=career_days,
            abstention_penalty_weight=self.config.abstention_penalty_weight,
        )

    # ── Bayesian overfitting haircut ───────────────────────────────────────

    def compute_haircut(self, n_shadows: int, evaluation_days: int,
                        daily_returns: dict[str, list[float]] | None = None) -> float:
        return _compute_haircut(n_shadows, evaluation_days, daily_returns)

    def apply_bayesian_haircut(self, composite_score: float, n_shadows: int,
                               evaluation_days: int) -> float:
        return _apply_bayesian_haircut(composite_score, n_shadows, evaluation_days)

    # ── Percentile computation ────────────────────────────────────────────

    def compute_percentile_ranks(self, scores: dict[str, float]) -> dict[str, float]:
        return _compute_percentile_ranks(scores, self.config.parametric_threshold_n)

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

        P2-4 accuracy_gate: if market_accuracy < 0.50, ELITE is demoted to NORMAL.
        This breaks virtual PnL circularity by requiring shadows to outperform
        random chance against actual market returns.
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
            tier = "elite"
            # P2-4 accuracy gate: demote ELITE if market accuracy < 0.50
            if market_accuracy is not None and market_accuracy < 0.50:
                logger.info(
                    "ELITE demoted to NORMAL: market_accuracy=%.3f < 0.50",
                    market_accuracy
                )
                return "normal"
            return tier

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

    # ── Plateau detection ─────────────────────────────────────────────────

    def detect_plateau(
        self,
        shadow_id: str,
        tier_history: list[tuple[str, str]],
        win_rate_history: list[tuple[str, float]],
        insight_dates: list[str],
    ) -> tuple[bool, float]:
        """Returns (is_plateaued, plateau_score) where higher score = more stale.

        Plateau weights: 0.5 stagnation + 0.3 wr_stability + 0.2 insight_drought
        """
        cfg = self.config

        # Minimum-age guard: new shadows (< plateau_no_elite_days snapshots) skip detection
        if len(tier_history) < cfg.plateau_no_elite_days:
            return False, 0.0
        scores = []

        # Stagnation: no elite in plateau_no_elite_days
        sorted_tiers = sorted(tier_history, key=lambda x: x[0], reverse=True)
        recent_tiers = [t for d, t in sorted_tiers[:cfg.plateau_no_elite_days]]
        no_elite = "elite" not in recent_tiers if recent_tiers else True
        scores.append(0.5 if no_elite else 0.0)

        # WR stability: range of win rates in recent history
        sorted_wr = sorted(win_rate_history, key=lambda x: x[0], reverse=True)
        recent_wr = [wr for _, wr in sorted_wr[:cfg.plateau_no_elite_days]]
        if len(recent_wr) >= 2:
            wr_range = max(recent_wr) - min(recent_wr)
            scores.append(0.3 * min(wr_range / cfg.plateau_wr_range_pp, 1.0))
        else:
            scores.append(0.0)

        # Insight drought
        if insight_dates:
            latest_insight = max(insight_dates)
            days_since = (datetime.now(timezone.utc).date() -
                          datetime.strptime(latest_insight, "%Y-%m-%d").date()).days
            drought = min(days_since / cfg.plateau_no_insight_days, 1.0)
        else:
            drought = 1.0
        scores.append(0.2 * drought)

        plateau_score = sum(scores)
        return plateau_score >= 0.5, plateau_score

    # ── Full ranking pipeline ─────────────────────────────────────────────

    def rank_shadows(
        self,
        performances: dict[str, ShadowPerformance],
        score_histories: dict[str, list[dict]],
        date: str,
        market_accuracy: dict[str, float] | None = None,
        wfe_results: dict[str, float] | None = None,
    ) -> list[RankingResult]:
        """Full ranking: metrics -> composite -> haircut -> percentile -> ladder."""
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

        # ── WFE overfit penalty (P2-2 audit fix) ──
        # Shadows with WFE ratio < 0.5 have inflated IS -> penalty on deflated score
        if wfe_results:
            for sid, wfe_ratio in wfe_results.items():
                if sid in deflated and wfe_ratio < 0.5:
                    penalty = (0.5 - wfe_ratio) * 2.0  # 0->0 penalty, 0->1 max penalty
                    penalty = min(penalty, 0.5)  # Cap at 50% reduction
                    deflated[sid] = max(deflated[sid] * (1.0 - penalty), 0.001)
                    logger.info(
                        "WFE penalty applied to %s: wfe=%.3f penalty=%.2f%% deflated=%.4f",
                        sid, wfe_ratio, penalty * 100, deflated[sid]
                    )

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

        # ── Quota efficiency scoring (Phase 2) ──
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
            shadow_accuracy = market_accuracy.get(sid) if market_accuracy else None
            tier = self.determine_achievement_tier(
                [(h["date"], h.get("deflated_score", 0)) for h in score_hist],
                [(h["date"], h.get("percentile_rank", 0)) for h in score_hist],
                perf.max_drawdown,
                deflated_sharpe,
                market_accuracy=shadow_accuracy,
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

        # P2-5: Holm-Bonferroni correction -- downgrade tiers that fail FDR control
        self._apply_holm_bonferroni(results)

        return results

    @staticmethod
    def _apply_holm_bonferroni(results: list[RankingResult]) -> None:
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
        tier_order = {"elite": 4, "excellent": 3, "normal": 2, "watch": 1, "endangered": 0}
        reverse_tier = {4: "elite", 3: "excellent", 2: "normal", 1: "watch", 0: "endangered"}

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

    @staticmethod
    def _estimate_sharpe(returns: list[float]) -> float:
        return _estimate_sharpe_raw(returns)

    # ── Reset eligibility (Phase 2) ───────────────────────────────────────

    def check_reset_eligibility(
        self,
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
        return _check_reset_eligibility(
            self.config, tier_history, wr_history, insight_dates
        )
