"""Ranking Engine -- pure Python composite score, Bayesian haircut, achievement ladder.

Zero LLM calls. All computation is deterministic mathematical formulas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from marketmind.config.settings import ShadowSettings


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

    def __init__(self, config: ShadowSettings):
        self.config = config

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

    # ── Composite scoring ────────────────────────────────────────────────

    # Dynamic win-rate line parameters
    _WR_LINE_FLOOR = 0.45         # Hard floor — actual win rate can never go below this
    _WR_WEIGHT_FLOOR = 0.12       # Minimum WR weight in composite (distinct from line)
    _WR_EARLY_DAYS = 60           # New shadow: heavy WR emphasis
    _WR_MATURE_DAYS = 180         # Mature shadow: can trade WR for profitability
    _WR_EARLY_WEIGHT_BOOST = 0.10  # Extra WR weight during early career (+10pp)
    _PROFIT_LOSS_PENALTY = 0.40   # Multiplicative penalty when cumulative return < 0
    _PROFIT_LOSS_FLOOR = 0.02     # Minimum composite after penalty (prevent zero-division)

    def compute_composite_score(
        self, perf: ShadowPerformance, career_days: int | None = None
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        """Returns (C_raw, component_scores_dict, modifiers_dict).

        Modifiers track the dynamic WR line adjustments and profitability
        penalties for transparency in ranking display.
        """
        w = dict(self.config.composite_weights)  # mutable copy
        modifiers = {
            "wr_weight_raw": w["win_rate"],
            "wr_weight_adjusted": w["win_rate"],
            "wr_line_value": 0.0,
            "profitability_penalty": 0.0,
            "career_days": career_days or 0,
        }

        omega = self.compute_omega(perf.daily_returns)
        calmar = self.compute_calmar(perf.cumulative_return, perf.max_drawdown)
        mppm = self.compute_mppm(perf.daily_returns)

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

        if career_days is not None and career_days < self._WR_EARLY_DAYS:
            # Early career: boost WR weight to incentivize direction accuracy
            w["win_rate"] = min(w["win_rate"] + self._WR_EARLY_WEIGHT_BOOST, 0.50)
            # Slightly reduce other weights to keep sum ~1.0
            ratio = (1.0 - w["win_rate"]) / (1.0 - (w["win_rate"] - self._WR_EARLY_WEIGHT_BOOST))
            for key in ("mppm", "calmar", "omega"):
                w[key] *= ratio

        elif career_days is not None and career_days >= self._WR_MATURE_DAYS:
            # Mature: allow WR weight to decrease if profitability is strong
            if perf.cumulative_return > 0.10:
                wr_discount = min(0.08, (perf.cumulative_return - 0.10) * 0.15)
                w["win_rate"] = max(self._WR_WEIGHT_FLOOR, w["win_rate"] - wr_discount)
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

        # —— Profitability penalty: negative cumulative return = largest penalty ——
        if perf.cumulative_return < 0:
            penalty = min(
                self._PROFIT_LOSS_PENALTY,
                abs(perf.cumulative_return) * 0.5
            )
            composite = max(composite * (1.0 - penalty), self._PROFIT_LOSS_FLOOR)
            modifiers["profitability_penalty"] = penalty

        return composite, components, modifiers

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
            return RankingEngine._WR_LINE_FLOOR

        # Strategy-type adjustment: daredevils and contrarian strategies
        # structurally have lower win rates by design
        domain_adjust = 0.0
        if shadow_type == "daredevil":
            domain_adjust = -0.05
        elif domain and domain in ("contrarian", "short"):
            domain_adjust = -0.05

        if career_days < RankingEngine._WR_EARLY_DAYS:
            return max(RankingEngine._WR_LINE_FLOOR, 0.55 + domain_adjust)
        elif career_days < RankingEngine._WR_MATURE_DAYS:
            progress = (career_days - RankingEngine._WR_EARLY_DAYS) / (
                RankingEngine._WR_MATURE_DAYS - RankingEngine._WR_EARLY_DAYS
            )
            return max(RankingEngine._WR_LINE_FLOOR, 0.55 - 0.10 * progress + domain_adjust)
        else:
            return max(RankingEngine._WR_LINE_FLOOR, 0.45 + domain_adjust)

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

    # ── Bayesian overfitting haircut ──────────────────────────────────────

    def compute_haircut(self, n_shadows: int, evaluation_days: int) -> float:
        """Witzany (2021): h(N,T) = T / (T + 8 + 24 * ln(N))."""
        if n_shadows < 1:
            n_shadows = 1
        return evaluation_days / (evaluation_days + 8.0 + 24.0 * math.log(n_shadows))

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
    ) -> str:
        """Returns tier based on consecutive day rules.

        States: ELITE, EXCELLENT, NORMAL, WATCH, ENDANGERED
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
            days_since = (datetime.now().date() -
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

        # Apply Bayesian haircut
        haircut = self.compute_haircut(n, self.config.evaluation_window_days)
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

        # Determine tiers and build results
        for sid in performances:
            perf = performances[sid]
            score_hist = score_histories.get(sid, [])

            deflated_sharpe = self._estimate_sharpe(perf.daily_returns)
            tier = self.determine_achievement_tier(
                [(h["date"], h.get("deflated_score", 0)) for h in score_hist],
                [(h["date"], h.get("percentile_rank", 0)) for h in score_hist],
                perf.max_drawdown,
                deflated_sharpe,
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

        return results

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
