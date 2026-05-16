"""Composite score calculation -- MPPM, Calmar, Omega, composite scoring, Bayesian haircut, percentile ranks.

Zero LLM calls. All computation is deterministic mathematical formulas.
Extracted from ranking_engine.py to comply with 500-line hard ceiling.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("marketmind.shadows.ranking_composite")

# Dynamic win-rate line parameters
_WR_LINE_FLOOR = 0.45
_WR_WEIGHT_FLOOR = 0.12
_WR_EARLY_DAYS = 60
_WR_MATURE_DAYS = 180
_WR_EARLY_WEIGHT_BOOST = 0.10
_PROFIT_LOSS_PENALTY = 0.40
_PROFIT_LOSS_FLOOR = 0.02


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


# ── Core metrics ──────────────────────────────────────────────────────

def compute_mppm(returns: list[float], gamma: float = 3.0) -> float:
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


def compute_calmar(cumulative_return: float, max_drawdown: float,
                   days: int = 252) -> float:
    """Calmar = CAGR / max(|MDD|, floor). Capped at 100."""
    mdd_floor = max(max_drawdown, 0.001)
    cagr = compute_cagr(cumulative_return, days) if days > 0 else cumulative_return
    calmar = cagr / mdd_floor
    return min(calmar, 100.0)


def compute_omega(returns: list[float], threshold: float = 0.0) -> float:
    """Omega(L=0) = sum(gains) / sum(|losses|). Capped at 10."""
    if not returns:
        return 1.0
    gains = sum(max(r - threshold, 0) for r in returns)
    losses = sum(abs(min(r - threshold, 0)) for r in returns)
    if losses == 0:
        return 10.0
    omega = gains / losses
    return min(omega, 10.0)


def compute_cagr(cumulative_return: float, days: int) -> float:
    """Annualize cumulative return over N trading days."""
    if days <= 0:
        return 0.0
    return cumulative_return * 252 / days


# ── Composite scoring ─────────────────────────────────────────────────

def _compute_wr_line(career_days: int | None, domain: str | None = None,
                     shadow_type: str | None = None) -> float:
    """Dynamic win-rate floor. Returns the minimum acceptable WR for ranking bonus."""
    if career_days is None:
        return _WR_LINE_FLOOR

    domain_adjust = 0.0
    if shadow_type == "daredevil":
        domain_adjust = -0.05
    elif domain and domain in ("contrarian", "short"):
        domain_adjust = -0.05

    if career_days < _WR_EARLY_DAYS:
        return max(_WR_LINE_FLOOR, 0.55 + domain_adjust)
    elif career_days < _WR_MATURE_DAYS:
        progress = (career_days - _WR_EARLY_DAYS) / (_WR_MATURE_DAYS - _WR_EARLY_DAYS)
        return max(_WR_LINE_FLOOR, 0.55 - 0.10 * progress + domain_adjust)
    else:
        return max(_WR_LINE_FLOOR, 0.45 + domain_adjust)


def _normalize_mppm(mppm: float) -> float:
    """Normalize MPPM to [0, 1]. Log-sigmoid transform."""
    if mppm == float("-inf"):
        return 0.0
    if math.isnan(mppm):
        return 0.0
    return 1.0 / (1.0 + math.exp(-mppm))


def _normalize_calmar(calmar: float) -> float:
    """Normalize Calmar to [0, 1]. Calmar > 3 is exceptional."""
    return min(calmar / 3.0, 1.0)


def compute_composite_score(
    perf: ShadowPerformance,
    composite_weights: dict[str, float],
    career_days: int | None = None,
    abstention_penalty_weight: float = 0.05,
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Returns (C_raw, component_scores_dict, modifiers_dict)."""
    w = dict(composite_weights)  # mutable copy
    modifiers = {
        "wr_weight_raw": w["win_rate"],
        "wr_weight_adjusted": w["win_rate"],
        "wr_line_value": 0.0,
        "profitability_penalty": 0.0,
        "career_days": career_days or 0,
    }

    omega = compute_omega(perf.daily_returns)
    calmar = compute_calmar(perf.cumulative_return, perf.max_drawdown,
                            days=perf.career_days)
    mppm = compute_mppm(perf.daily_returns)

    components = {
        "mppm": mppm,
        "calmar": calmar,
        "omega": omega,
        "win_rate": perf.win_rate,
    }

    wr_line = _compute_wr_line(
        career_days,
        domain=getattr(perf, 'domain', None),
        shadow_type=getattr(perf, 'shadow_type', None),
    )
    modifiers["wr_line_value"] = wr_line

    if career_days is not None and career_days < _WR_EARLY_DAYS:
        w["win_rate"] = min(w["win_rate"] + _WR_EARLY_WEIGHT_BOOST, 0.50)
        ratio = (1.0 - w["win_rate"]) / (1.0 - (w["win_rate"] - _WR_EARLY_WEIGHT_BOOST))
        for key in ("mppm", "calmar", "omega"):
            w[key] *= ratio

    elif career_days is not None and career_days >= _WR_MATURE_DAYS:
        if perf.cumulative_return > 0.10:
            wr_discount = min(0.08, (perf.cumulative_return - 0.10) * 0.15)
            w["win_rate"] = max(_WR_WEIGHT_FLOOR, w["win_rate"] - wr_discount)
            redist = wr_discount / 3.0
            for key in ("mppm", "calmar", "omega"):
                w[key] += redist

    modifiers["wr_weight_adjusted"] = w["win_rate"]

    mppm_norm = _normalize_mppm(mppm)
    calmar_norm = _normalize_calmar(calmar)
    omega_norm = omega / 10.0
    wr_norm = perf.win_rate

    composite = (
        w["mppm"] * mppm_norm +
        w["calmar"] * calmar_norm +
        w["omega"] * omega_norm +
        w["win_rate"] * wr_norm
    )

    if perf.cumulative_return < 0:
        penalty = min(
            _PROFIT_LOSS_PENALTY,
            abs(perf.cumulative_return) * 0.5
        )
        composite = max(composite * (1.0 - penalty), _PROFIT_LOSS_FLOOR)
        modifiers["profitability_penalty"] = penalty

    abstention_penalty = 0.0
    if career_days and career_days > 0:
        abstention_rate = perf.abstention_days / career_days
        if abstention_rate > 0.3:
            abstention_penalty = abstention_penalty_weight * abstention_rate
            composite -= abstention_penalty
    modifiers["abstention_penalty"] = abstention_penalty

    return max(composite, 0.0), components, modifiers


# ── Bayesian overfitting haircut ───────────────────────────────────────

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


def compute_haircut(n_shadows: int, evaluation_days: int,
                    daily_returns: dict[str, list[float]] | None = None) -> float:
    """Witzany (2021) with Effective-N correction (P2-1)."""
    if n_shadows < 1:
        n_shadows = 1

    n_eff = float(n_shadows)
    if daily_returns and len(daily_returns) >= 3:
        mean_corr = _mean_abs_correlation(daily_returns)
        if mean_corr is not None:
            n_eff = n_shadows / (1.0 + (n_shadows - 1) * mean_corr)
            n_eff = max(1.5, min(n_eff, float(n_shadows)))

    return evaluation_days / (evaluation_days + 8.0 + 24.0 * math.log(max(n_eff, 1.5)))


def apply_bayesian_haircut(composite_score: float, n_shadows: int,
                           evaluation_days: int) -> float:
    """C_deflated = C_raw * h(N,T)."""
    return composite_score * compute_haircut(n_shadows, evaluation_days)


# ── Percentile computation ────────────────────────────────────────────

def compute_percentile_ranks(scores: dict[str, float],
                              parametric_threshold_n: int = 30) -> dict[str, float]:
    """Map each shadow_id to its percentile rank (0-1) within the cohort."""
    if not scores:
        return {}
    n = len(scores)
    score_list = list(scores.values())

    if n >= parametric_threshold_n:
        return _empirical_percentiles(scores, score_list)
    elif n <= 15:
        return _parametric_percentiles(scores, score_list)
    else:
        alpha = n / parametric_threshold_n
        emp = _empirical_percentiles(scores, score_list)
        par = _parametric_percentiles(scores, score_list)
        return {
            sid: alpha * emp.get(sid, 0.5) + (1 - alpha) * par.get(sid, 0.5)
            for sid in scores
        }


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


def _parametric_percentiles(scores: dict[str, float],
                             score_list: list[float]) -> dict[str, float]:
    """Logistic-normal parametric percentile estimation for small N."""
    n = len(score_list)
    sorted_scores = sorted(score_list)
    result = {}
    for sid, score in scores.items():
        rank = sum(1 for s in sorted_scores if s <= score)
        p = (rank - 0.5) / n
        result[sid] = 1.0 / (1.0 + math.exp(-2.0 * (p - 0.5) * math.sqrt(n)))
    return result
