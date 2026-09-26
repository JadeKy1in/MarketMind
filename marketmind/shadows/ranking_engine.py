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
from marketmind.shadows.ranking_stats import (
    apply_bayesian_haircut,
    compute_cagr,
    compute_calmar,
    compute_haircut,
    compute_mppm,
    compute_omega,
    compute_percentile_ranks,
    estimate_sharpe,
)


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

    # ── Core metrics (delegated to ranking_stats) ──────────────────────

    def compute_mppm(self, returns: list[float], gamma: float = 3.0) -> float:
        return compute_mppm(returns, gamma)

    def compute_calmar(self, cumulative_return: float, max_drawdown: float) -> float:
        return compute_calmar(cumulative_return, max_drawdown)

    def compute_omega(self, returns: list[float], threshold: float = 0.0) -> float:
        return compute_omega(returns, threshold)

    def compute_cagr(self, cumulative_return: float, days: int) -> float:
        return compute_cagr(cumulative_return, days)

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

    # ── Bayesian overfitting haircut (delegated to ranking_stats) ───────

    def compute_haircut(self, n_shadows: int, evaluation_days: int,
                         daily_returns: dict[str, list[float]] | None = None) -> float:
        return compute_haircut(n_shadows, evaluation_days, daily_returns)

    def apply_bayesian_haircut(self, composite_score: float, n_shadows: int,
                                evaluation_days: int) -> float:
        return apply_bayesian_haircut(composite_score, n_shadows, evaluation_days)

    # ── Percentile computation (delegated to ranking_stats) ────────────

    def compute_percentile_ranks(self, scores: dict[str, float]) -> dict[str, float]:
        return compute_percentile_ranks(scores, self.config.parametric_threshold_n)

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

        Phase 1: 4-tier system (ELITE, EXCELLENT, NORMAL, ENDANGERED).
        WATCH merged into ENDANGERED at 0.20 threshold.
        Win-rate floor protection with 3-part gate.
        Absolute Sharpe gate prevents all-ELITE degradation.
        Hysteresis buffer (84-86%) prevents boundary toggling.
        """
        if not percentile_history:
            return "normal"

        cfg = self.config
        current_tier = self._get_current_tier_from_history()

        days_at_elite = self._count_consecutive_above(
            percentile_history, cfg.achievement_percentiles["elite"]
        )
        days_at_excellent = self._count_consecutive_above(
            percentile_history, cfg.achievement_percentiles["excellent"]
        )
        days_below_endangered = self._count_consecutive_below(
            percentile_history, cfg.achievement_percentiles["endangered"]
        )

        # Elite check with absolute Sharpe gate
        if days_at_elite >= cfg.elite_consecutive_days:
            if deflated_sharpe < cfg.elite_absolute_sharpe_min:
                pass  # Absolute quality gate blocks ELITE
            elif market_accuracy is not None and market_accuracy < 0.50:
                pass  # Market accuracy gate blocks ELITE
            else:
                # Hysteresis: 84-86% holds current tier
                latest_pct = percentile_history[-1][1] if percentile_history else 0
                if current_tier == "excellent" and 0.84 <= latest_pct <= 0.86:
                    return "excellent"
                return "elite"

        # Excellent check with win-rate floor protection
        if days_at_excellent >= cfg.excellent_consecutive_days and deflated_sharpe >= cfg.excellent_absolute_sharpe_min:
            return "excellent"

        # Win-rate floor: prevent demotion with 3-part gate
        if current_tier in ("elite", "excellent") and self._win_rate_floor_active(
            wr=getattr(self, '_cached_wr', 0.0),
            cumulative_return=getattr(self, '_cached_cum_return', 0.0),
            avg_position_pct=getattr(self, '_cached_avg_pos', 0.0),
        ):
            return current_tier  # Protected

        # Endangered check
        if days_below_endangered >= cfg.endangered_consecutive_days:
            return "endangered"

        return "normal"

    def _get_current_tier_from_history(self) -> str:
        """Extract current tier from latest snapshot via state_db if available."""
        if hasattr(self, '_state_db') and self._state_db:
            snap = self._state_db.get_latest_snapshot(self._last_shadow_id)
            if snap and snap.achievement_tier:
                return snap.achievement_tier
        return "normal"

    def _win_rate_floor_active(self, wr: float = 0.0, cumulative_return: float = 0.0,
                                avg_position_pct: float = 0.0) -> bool:
        """3-part gate: win-rate >50% + cumulative return > 0 + avg position >1%.

        CPI integration (Phase 2 follow-up): replace cumulative_return > 0 with
        cumulative_return > CPI over evaluation period. Requires bls_fetcher
        pipeline integration. Currently uses nominal-return check as proxy.
        """
        if wr < 0.50:
            return False
        if cumulative_return <= 0:
            return False  # Proxy for inflation (CPI integration pending)
        if avg_position_pct < 0.01:
            return False
        return True

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

            deflated_sharpe = estimate_sharpe(perf.daily_returns)
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
