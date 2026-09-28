"""Promotion statistics (docs/S7_DESIGN.md §一). Pure functions, numpy/scipy only.

Conventions: `r` is a 1-D array of per-period simple returns. Sharpe ratios are
per period (not annualized) unless stated. Kurtosis is the non-excess (Pearson)
kurtosis, 3 for a normal distribution, as in Bailey & Lopez de Prado.
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
from scipy import stats

from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C

EULER_GAMMA = 0.5772156649015329


# ── Ledger -> daily series ──────────────────────────────────────────────

def _day(ts: str | None) -> str | None:
    return ts[:10] if ts else None


def trading_calendar(entries: list[LedgerEntry], until: str | None = None) -> list[str]:
    """Trading days = sorted union of exit dates of settled rows across all sources."""
    days = {_day(e.exit_date) for e in entries if e.status == "settled" and e.exit_date}
    return sorted(d for d in days if d and (until is None or d <= until))


def daily_pnl(entries: list[LedgerEntry], notional: float = C.NOTIONAL_USD) -> dict[str, float]:
    """Settled rows booked on their exit date: {date: sum(pnl_usd) / notional} (S7 §一 数据)."""
    out: dict[str, float] = {}
    for e in entries:
        if e.status != "settled" or not e.exit_date or e.pnl_usd is None:
            continue
        d = _day(e.exit_date)
        out[d] = out.get(d, 0.0) + e.pnl_usd / notional
    return out


def daily_market(entries: list[LedgerEntry], notional: float = C.NOTIONAL_USD) -> dict[str, float]:
    """Market benchmark on the same capital: {exit date: sum(position_usd * market_return) / notional}.

    The ledger stores the market return over each trade's holding window, so this is
    what the shadow's capital would have earned in the market benchmark instead."""
    out: dict[str, float] = {}
    for e in entries:
        if e.status != "settled" or not e.exit_date or e.market_return is None:
            continue
        d = _day(e.exit_date)
        out[d] = out.get(d, 0.0) + e.position_usd * e.market_return / notional
    return out


def daily_series(by_date: dict[str, float], calendar: list[str]) -> np.ndarray:
    """Align a {date: return} map to a calendar; trading days without exits are 0."""
    return np.array([by_date.get(d, 0.0) for d in calendar], dtype=float)


def n_eff(n_settled: int, span_days: int, mean_hold_bars: float) -> float:
    """Effective independent samples: min(settled trades, span / mean holding period).

    Overlapping holds make trades dependent (S7 §一 数据)."""
    if n_settled <= 0 or mean_hold_bars <= 0:
        return 0.0
    return float(min(n_settled, span_days / mean_hold_bars))


# ── Moments and Sharpe ─────────────────────────────────────────────────

def sharpe(r) -> float:
    """Per-period Sharpe ratio mean / sd (ddof=1), zero risk-free rate. 0 when sd is 0."""
    r = np.asarray(r, dtype=float)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else 0.0


def skew_kurt(r) -> tuple[float, float]:
    """(skewness, non-excess kurtosis) with population moments; (0, 3) when degenerate."""
    r = np.asarray(r, dtype=float)
    if r.size < 3 or r.std() == 0:
        return 0.0, 3.0
    return float(stats.skew(r, bias=True)), float(stats.kurtosis(r, fisher=False, bias=True))


def _sr_var_term(sr: float, g3: float, g4: float) -> float:
    return 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr


def min_trl(sr: float, g3: float, g4: float, sr_benchmark: float = C.MINTRL_BENCHMARK_SHARPE,
            confidence: float = C.MINTRL_CONFIDENCE) -> float:
    """Minimum Track Record Length (Bailey & Lopez de Prado 2012, "The Sharpe Ratio
    Efficient Frontier", J. of Risk 15(2)):

        MinTRL = 1 + [1 - g3*SR + (g4-1)/4 * SR^2] * (z_alpha / (SR - SR*))^2

    in observations of the series SR was measured on. inf if SR <= SR*."""
    if sr <= sr_benchmark:
        return math.inf
    z = stats.norm.ppf(confidence)
    return 1.0 + _sr_var_term(sr, g3, g4) * (z / (sr - sr_benchmark)) ** 2


def psr(sr: float, n: float, g3: float, g4: float, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012):

        PSR = Phi( (SR - SR*) * sqrt(n-1) / sqrt(1 - g3*SR + (g4-1)/4 * SR^2) )"""
    if n < 2:
        return 0.0
    denom = math.sqrt(max(_sr_var_term(sr, g3, g4), 1e-12))
    return float(stats.norm.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum Sharpe among N unskilled trials (Bailey & Lopez de Prado 2014,
    "The Deflated Sharpe Ratio", J. of Portfolio Management 40(5)):

        SR0 = sqrt(V[SR]) * ((1-gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N e)))

    gamma = Euler-Mascheroni constant. 0 for a single trial."""
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * stats.norm.ppf(1 - 1 / n)
                                     + EULER_GAMMA * stats.norm.ppf(1 - 1 / (n * math.e)))


def sharpe_estimator_variance(r) -> float:
    """Asymptotic variance of the Sharpe estimator (Mertens 2002):
    [1 - g3*SR + (g4-1)/4 * SR^2] / (n - 1)."""
    r = np.asarray(r, dtype=float)
    if r.size < 2:
        return 0.0
    g3, g4 = skew_kurt(r)
    return _sr_var_term(sharpe(r), g3, g4) / (r.size - 1)


def dsr(r, n_trials: int, sr_variance: float | None = None) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): PSR with the benchmark set
    to the expected maximum Sharpe of `n_trials` trials. `sr_variance` is the variance
    of Sharpe across trials; when None, the series' own estimator variance is used."""
    r = np.asarray(r, dtype=float)
    if r.size < 2:
        return 0.0
    var = sharpe_estimator_variance(r) if sr_variance is None else sr_variance
    g3, g4 = skew_kurt(r)
    return psr(sharpe(r), r.size, g3, g4, expected_max_sharpe(n_trials, var))


# ── Composite-score components ─────────────────────────────────────────

def mppm(r, rho: float = C.MPPM_RHO, periods_per_year: int = C.TRADING_DAYS_PER_YEAR) -> float:
    """Manipulation-Proof Performance Measure (Goetzmann, Ingersoll, Spiegel & Welch 2007,
    RFS 20(5)), zero risk-free rate, dt = 1 / periods_per_year:

        Theta = 1 / ((1-rho) * dt) * ln( mean( (1 + r_t)^(1-rho) ) )"""
    r = np.asarray(r, dtype=float)
    if r.size == 0:
        return 0.0
    if np.any(1 + r <= 0):
        return -math.inf
    dt = 1.0 / periods_per_year
    return float(math.log(np.mean((1 + r) ** (1 - rho))) / ((1 - rho) * dt))


def max_drawdown(r) -> float:
    """Largest peak-to-trough fall of the additive equity curve 1 + cumsum(r), as a
    positive fraction of notional (pnl is booked against a fixed notional)."""
    r = np.asarray(r, dtype=float)
    if r.size == 0:
        return 0.0
    equity = np.concatenate([[1.0], 1.0 + np.cumsum(r)])
    return float(np.max(np.maximum.accumulate(equity) - equity))


def calmar(r, periods_per_year: int = C.TRADING_DAYS_PER_YEAR) -> float:
    """Calmar ratio (Young 1991): annualized mean return / max drawdown.
    inf with no drawdown and a positive mean; 0 with neither."""
    r = np.asarray(r, dtype=float)
    if r.size == 0:
        return 0.0
    ann = float(r.mean()) * periods_per_year
    mdd = max_drawdown(r)
    if mdd == 0:
        return math.inf if ann > 0 else 0.0
    return ann / mdd


def omega(r, threshold: float = C.OMEGA_THRESHOLD) -> float:
    """Omega ratio (Keating & Shadwick 2002): sum(max(r-L,0)) / sum(max(L-r,0)).
    inf with gains and no losses; 0 with nothing above L."""
    r = np.asarray(r, dtype=float)
    up = float(np.sum(np.maximum(r - threshold, 0)))
    down = float(np.sum(np.maximum(threshold - r, 0)))
    if down == 0:
        return math.inf if up > 0 else 0.0
    return up / down


def shrink(value: float, n: float, prior_mean: float, k: float = C.SHRINKAGE_K) -> float:
    """Bayesian (credibility) shrinkage toward the group mean with weight n / (n + k)."""
    w = n / (n + k) if n + k > 0 else 0.0
    return prior_mean + w * (value - prior_mean)


def percentile_ranks(values: list[float]) -> list[float]:
    """Average-tie ranks divided by N, in (0, 1]; the largest value gets 1.0.
    +/-inf sort naturally; None / NaN count as the worst."""
    if not values:
        return []
    arr = np.array([-math.inf if v is None or math.isnan(v) else v for v in values], dtype=float)
    return [float(x) for x in stats.rankdata(arr, method="average") / arr.size]


# ── Overfitting and monitoring ─────────────────────────────────────────

def pbo_cscv(matrix, n_blocks: int = C.PBO_BLOCKS) -> float | None:
    """Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation
    (Bailey, Borwein, Lopez de Prado & Zhu 2017, J. of Computational Finance 20(4)).

    `matrix` is T x N (rows = periods, columns = strategies). Rows are cut into
    `n_blocks` equal blocks (earliest remainder rows dropped). For every split of the
    blocks into two halves, the strategy with the best in-sample Sharpe is located in
    the out-of-sample ranking: w = rank / (N + 1), logit = ln(w / (1 - w)).
    PBO = share of splits with logit <= 0. None when N < 2 or T < 2 * n_blocks."""
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2 or m.shape[0] < 2 * n_blocks or n_blocks % 2:
        return None
    t, n = m.shape
    size = t // n_blocks
    m = m[t - size * n_blocks:]
    blocks = m.reshape(n_blocks, size, n)
    b_sum, b_sq = blocks.sum(axis=1), (blocks ** 2).sum(axis=1)          # S x N
    combos = np.zeros((math.comb(n_blocks, n_blocks // 2), n_blocks))
    for row, c in enumerate(combinations(range(n_blocks), n_blocks // 2)):
        combos[row, list(c)] = 1.0

    def _sr(mask: np.ndarray) -> np.ndarray:
        cnt = mask.sum(axis=1, keepdims=True) * size
        mean = (mask @ b_sum) / cnt
        sd = np.sqrt(np.maximum((mask @ b_sq) / cnt - mean ** 2, 0))
        return np.divide(mean, sd, out=np.zeros_like(mean), where=sd > 1e-15)

    is_sr, oos_sr = _sr(combos), _sr(1 - combos)
    best = np.argmax(is_sr, axis=1)
    chosen = oos_sr[np.arange(best.size), best][:, None]
    # average-tie rank of the chosen strategy within its out-of-sample row
    rank = (oos_sr < chosen).sum(axis=1) + ((oos_sr == chosen).sum(axis=1) + 1) / 2
    w = rank / (n + 1)
    return float(np.mean(np.log(w / (1 - w)) <= 0))


def cusum_down(r, mean: float, sd: float, k: float = C.CUSUM_K,
               h: float = C.CUSUM_H) -> int | None:
    """One-sided lower tabular CUSUM for a downward mean shift (Page 1954):

        z_t = (x_t - mean) / sd,   S_t = max(0, S_{t-1} - z_t - k),   alarm when S_t > h

    k and h in standard deviations. Returns the index of the first alarm, else None."""
    if sd <= 0:
        return None
    s = 0.0
    for i, x in enumerate(np.asarray(r, dtype=float)):
        s = max(0.0, s - (x - mean) / sd - k)
        if s > h:
            return i
    return None


def stress_test(shadow_r, market_r, worst_share: float = C.STRESS_WORST_SHARE,
                multiple: float = C.STRESS_MULTIPLE,
                min_days: int = C.STRESS_MIN_DAYS) -> tuple[bool | None, dict]:
    """On the worst `worst_share` market-benchmark days (days with market exposure only),
    the shadow's mean daily return must be >= multiple * min(market mean, 0).
    Returns (passed, or None with fewer than `min_days` market days; details)."""
    s, mk = np.asarray(shadow_r, dtype=float), np.asarray(market_r, dtype=float)
    idx = np.flatnonzero(mk != 0)
    if idx.size < min_days:
        return None, {"market_days": int(idx.size)}
    n_worst = max(1, math.ceil(worst_share * idx.size))
    worst = idx[np.argsort(mk[idx], kind="stable")[:n_worst]]
    s_mean, m_mean = float(s[worst].mean()), float(mk[worst].mean())
    return bool(s_mean >= multiple * min(m_mean, 0.0)), {
        "market_days": int(idx.size), "worst_days": int(n_worst),
        "shadow_mean": s_mean, "market_mean": m_mean}
