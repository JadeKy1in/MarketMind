"""Promotion statistics (docs/S7_DESIGN.md §一). Pure functions, numpy/scipy only.

Conventions: `r` is a 1-D array of per-period simple returns. Sharpe ratios are
per period (not annualized) unless stated. Kurtosis is the non-excess (Pearson)
kurtosis, 3 for a normal distribution, as in Bailey & Lopez de Prado.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from itertools import combinations

import numpy as np
from scipy import stats

from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C

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


def _cohort_day(e: LedgerEntry, calendar: list[str]) -> str | None:
    """The calendar day a record's decision is booked on: first calendar day >= its
    decision (creation) date; None after the calendar ends."""
    d = _day(e.created_at)
    i = bisect_left(calendar, d) if d else len(calendar)
    return calendar[i] if i < len(calendar) else None


def cohort_pnl(entries: list[LedgerEntry], calendar: list[str],
               notional: float = C.NOTIONAL_USD) -> dict[str, float]:
    """Settled rows booked on their DECISION day: {day: sum(pnl_usd) / notional}.

    Used by the promotion ladder on matured decision cohorts only (fix 2026-09-29):
    every record decided on a day is included once all of them have settled, so the
    series cannot favour records that exited early (targets) over those still open."""
    out: dict[str, float] = {}
    for e in entries:
        if e.status != "settled" or e.pnl_usd is None:
            continue
        d = _cohort_day(e, calendar)
        if d is not None:
            out[d] = out.get(d, 0.0) + e.pnl_usd / notional
    return out


def cohort_market(entries: list[LedgerEntry], calendar: list[str],
                  notional: float = C.NOTIONAL_USD) -> dict[str, float]:
    """Market benchmark on the same capital, booked like `cohort_pnl`:
    {decision day: sum(position_usd * market_return) / notional}."""
    out: dict[str, float] = {}
    for e in entries:
        if e.status != "settled" or e.market_return is None:
            continue
        d = _cohort_day(e, calendar)
        if d is not None:
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


def dsr(r, n_trials: int) -> float:
    """Deflated Sharpe Ratio, Sidak form (fix 2026-09-29):

        DSR = PSR(SR* = 0) ^ K,   variance term floored at its normal-returns value 1

    i.e. the probability that the best of K independent zero-skill trials would not
    reach this Sharpe; DSR >= 0.95 caps the family-wise false-pass rate at 5% across
    K trials (Sidak 1967; Lopez de Prado 2020, Machine Learning for Asset Managers
    §8, which derives the DSR's multiple-testing correction from this FWER). K is the
    effective number of trials (`effective_trials`).

    Why not the Bailey & Lopez de Prado (2014) benchmark SR0 = sqrt(V[SR]) * E[max]:
    with V the raw cross-sectional variance it adds the expected maximum AND the
    candidate's own sampling noise, so a shadow with an annual Sharpe of 2.5 among 30
    passed 0.2-1% of the time after 80-250 days; with V net of sampling noise SR0 is ~0
    when nobody has skill and 50% of 30 zero-skill shadows' best passed. The floor on
    1 - g3*SR + (g4-1)/4*SR^2 stops sample skewness, which rises with the same outliers
    that lift SR, from inflating PSR in small fat-tailed samples (FWER 7-15% -> 4-5%).
    Simulated 2026-09-29 (docs/S7_DESIGN.md implementation notes)."""
    r = np.asarray(r, dtype=float)
    if r.size < 2:
        return 0.0
    g3, g4 = skew_kurt(r)
    sr = sharpe(r)
    z = sr * math.sqrt(r.size - 1) / math.sqrt(max(_sr_var_term(sr, g3, g4), 1.0))
    return float(stats.norm.cdf(z)) ** max(1, int(n_trials))


def effective_trials(series: dict[str, tuple[list[str], np.ndarray]],
                     corr_threshold: float = C.DSR_CLUSTER_CORR,
                     min_overlap: int = C.DSR_MIN_OVERLAP_DAYS) -> tuple[int, list[list[str]]]:
    """Effective number of independent trials (Lopez de Prado & Lewis 2019, "Detection
    of false investment strategies using unsupervised learning methods", Quant. Finance
    19(9)): candidates whose daily returns are correlated are one trial.

    Pairwise Pearson correlation over the days both series cover (pairs with fewer than
    `min_overlap` common days, or a constant series, count as uncorrelated), average-
    linkage hierarchical clustering on the distance 1 - rho, cut at 1 - corr_threshold.
    Returns (number of clusters, clusters as sorted id lists). 1 for no candidates."""
    ids = sorted(series)
    if len(ids) <= 1:
        return 1, [ids] if ids else []
    maps = [dict(zip(series[i][0], np.asarray(series[i][1], dtype=float))) for i in ids]
    n = len(ids)
    dist = np.ones((n, n))
    np.fill_diagonal(dist, 0.0)
    for a in range(n):
        for b in range(a + 1, n):
            common = sorted(maps[a].keys() & maps[b].keys())
            if len(common) < min_overlap:
                continue
            x = np.array([maps[a][d] for d in common])
            y = np.array([maps[b][d] for d in common])
            if x.std() == 0 or y.std() == 0:
                continue
            dist[a, b] = dist[b, a] = 1.0 - float(np.corrcoef(x, y)[0, 1])
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    labels = fcluster(linkage(squareform(np.clip(dist, 0.0, 2.0), checks=False), "average"),
                      t=1.0 - corr_threshold, criterion="distance")
    clusters: dict[int, list[str]] = {}
    for sid, lab in zip(ids, labels):
        clusters.setdefault(int(lab), []).append(sid)
    return len(clusters), sorted(clusters.values())


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


def cusum_down(r, mean: float, sd: float, k: float = C.CUSUM_K, h: float = 5.0,
               clip: float | None = None) -> int | None:
    """One-sided lower tabular CUSUM for a downward mean shift (Page 1954):

        z_t = (x_t - mean) / sd,   S_t = max(0, S_{t-1} - z_t - k),   alarm when S_t > h

    k and h in standard deviations; `clip` winsorises z_t at +/- clip. The ladder
    passes a robust (median, MAD) center / scale and a bootstrap-calibrated h
    (`calibrate_cusum_h`). Returns the index of the first alarm, else None."""
    if sd <= 0:
        return None
    z = (np.asarray(r, dtype=float) - mean) / sd
    if clip is not None:
        z = np.clip(z, -clip, clip)
    s = 0.0
    for i, x in enumerate(z):
        s = max(0.0, s - x - k)
        if s > h:
            return i
    return None


def robust_center_scale(x) -> tuple[float, float]:
    """(median, 1.4826 * MAD): a normal-consistent location / scale that a few fat-tail
    days cannot move. Falls back to the sample sd when more than half the values tie
    (MAD 0); (median, 0) when the series is constant."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0, 0.0
    med = float(np.median(x))
    scale = 1.4826 * float(np.median(np.abs(x - med)))
    if scale <= 0 and x.size >= 2:
        scale = float(x.std(ddof=1))
    return med, scale


def robust_z(x, center: float, scale: float, clip: float = C.CUSUM_WINSOR) -> np.ndarray:
    """Standardise with (center, scale) and winsorise at +/- clip."""
    return np.clip((np.asarray(x, dtype=float) - center) / scale, -clip, clip)


def _circular_blocks(x: np.ndarray, rows: int, length: int, block: int,
                     rng: np.random.Generator) -> np.ndarray:
    """`rows` circular moving-block resamples of x, each `length` long."""
    n = x.size
    n_blocks = -(-length // block)
    starts = rng.integers(0, n, size=(rows, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(rows, -1) % n
    return x[idx[:, :length]]


def _cusum_h_bootstrap(x0: np.ndarray, k: float, arl0: float, block: int,
                       rng: np.random.Generator, paths: int, horizon: int, clip: float) -> float:
    """Smallest h whose bootstrap in-control false-alarm probabilities stay within the
    geometric-equivalent bounds P(alarm within t days) <= 1 - exp(-t / arl0), t in
    CUSUM_CHECK_DAYS. Every path re-estimates the median / MAD center and scale from
    its own resample of x0 before standardising in-control data drawn from x0."""
    n = x0.size
    center0, scale0 = robust_center_scale(x0)
    est = _circular_blocks(x0, paths, n, block, rng)
    center = np.median(est, axis=1)
    scale = 1.4826 * np.median(np.abs(est - center[:, None]), axis=1)
    sd = est.std(axis=1, ddof=1) if n >= 2 else np.zeros(paths)
    scale = np.where(scale > 0, scale, np.where(sd > 0, sd, scale0 if scale0 > 0 else 1.0))
    z = np.clip((_circular_blocks(x0, paths, horizon, block, rng) - center[:, None])
                / scale[:, None], -clip, clip)
    s = np.zeros(paths)
    run_max = np.empty((paths, horizon))
    peak = np.zeros(paths)
    for t in range(horizon):                 # S_t does not depend on h: one pass for all h
        s = np.maximum(0.0, s - z[:, t] - k)
        peak = np.maximum(peak, s)
        run_max[:, t] = peak
    checks = [t for t in C.CUSUM_CHECK_DAYS if t <= horizon] or [horizon]

    def in_control(h: float) -> bool:
        return all(float(np.mean(run_max[:, t - 1] > h)) <= 1.0 - math.exp(-t / arl0)
                   for t in checks)

    lo, hi = 0.0, float(run_max[:, -1].max()) + 1e-9
    if in_control(lo):
        return lo
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if in_control(mid) else (mid, hi)
    return hi


def calibrate_cusum_h(ref, k: float = C.CUSUM_K, arl0: float = C.CUSUM_ARL0,
                      block: int = 1, seed: int = 0, paths: int = C.CUSUM_BOOT_PATHS,
                      horizon: int = C.CUSUM_BOOT_HORIZON, clip: float = C.CUSUM_WINSOR,
                      resamples: int = C.CUSUM_GK_RESAMPLES,
                      quantile: float = C.CUSUM_GK_QUANTILE) -> float:
    """Alarm threshold h of the robust lower CUSUM for an in-control ARL >= arl0, from
    the raw reference returns `ref`, with guaranteed conditional performance under
    estimated parameters (Gandy & Kvaloy 2013, "Guaranteed conditional performance of
    control charts via bootstrap methods", Scand. J. Statist. 40(4)):

    - `resamples` circular block resamples of the reference stand in for "other
      reference periods the shadow could have had"; for each, `_cusum_h_bootstrap`
      finds the h that keeps the false-alarm probability within the geometric-
      equivalent ARL bound when the chart is built from such a reference;
    - h = the `quantile` (90%) of those thresholds, so the target holds with ~90%
      probability despite the short, noisy reference.

    Blocks of `block` days keep the autocorrelation of overlapping holds (the ladder
    uses min(mean hold, round(n ** (1/3))), the Hall, Horowitz & Jing 1995 rate: long
    blocks from a short reference understate the estimation error). Simulated
    2026-09-29 (docs/S7_DESIGN.md implementation notes). Deterministic for a given
    seed; inf when the reference is empty."""
    x0 = np.asarray(ref, dtype=float)
    if x0.size == 0:
        return math.inf
    block = max(1, min(int(block), x0.size))
    rng = np.random.default_rng(seed)
    outer = _circular_blocks(x0, max(1, resamples), x0.size, block, rng)
    hs = [_cusum_h_bootstrap(row, k, arl0, block, rng, paths, horizon, clip) for row in outer]
    return float(np.quantile(hs, quantile))


def stress_hac_lag(n: int) -> int:
    """Newey-West (1994) rule-of-thumb bandwidth floor(4 (n/100)^(2/9)), at least 1.
    The worst-decile days are sparse in time, so little overlap is expected between
    them; fixed-b p-values (`hac_t_test`) keep the size right for whatever lag is used."""
    return max(1, int(math.floor(4.0 * (max(n, 1) / 100.0) ** (2.0 / 9.0))))


def stress_test(shadow_r, market_r, worst_share: float = C.STRESS_WORST_SHARE,
                min_days: int = C.STRESS_MIN_DAYS, alpha: float = C.STRESS_ALPHA,
                min_worst_days: int = C.STRESS_MIN_WORST_DAYS) -> tuple[bool | None, dict]:
    """On the worst `worst_share` market-benchmark days (days with market exposure only),
    two conditions must both hold:

    1. the shadow's mean daily return >= the market benchmark's mean on those days
       (it beats holding the market with the same capital when the market is worst;
       fix 2026-09-29, the old bar >= 2 x the market mean let 99% of zero-skill beta-1
       longs through);
    2. the paired daily differences d = shadow - market on those days (in date order)
       are significantly > 0: one-sided HAC (Newey-West, fixed-b) t-test
       (`hac_t_test`, lag `stress_hac_lag`), p <= `alpha` (owner decision 2026-09-29;
       without it a zero-skill beta-1 long passed about half the time).

    Returns (passed, details). passed is None when there are fewer than `min_days`
    market days or fewer than `min_worst_days` worst-decile days ("insufficient":
    not passed); False when the differences have no variation (not testable)."""
    s, mk = np.asarray(shadow_r, dtype=float), np.asarray(market_r, dtype=float)
    idx = np.flatnonzero(mk != 0)
    if idx.size < min_days:
        return None, {"market_days": int(idx.size), "significance": "insufficient"}
    n_worst = max(1, math.ceil(worst_share * idx.size))
    worst = np.sort(idx[np.argsort(mk[idx], kind="stable")[:n_worst]])
    s_mean, m_mean = float(s[worst].mean()), float(mk[worst].mean())
    detail = {"market_days": int(idx.size), "worst_days": int(n_worst),
              "shadow_mean": s_mean, "market_mean": m_mean, "mean_rule": bool(s_mean >= m_mean)}
    if n_worst < min_worst_days:
        detail["significance"] = "insufficient"
        return None, detail
    test = hac_t_test(s[worst] - mk[worst], stress_hac_lag(n_worst))
    p = test["p_value"]
    detail.update(significance="tested" if p is not None else "untestable",
                  diff_mean=test["mean"], diff_t=test["t"], p_value=p, hac_lag=test["lag"],
                  alpha=alpha)
    return bool(detail["mean_rule"] and p is not None and p <= alpha), detail


# ── Paired comparison (variant trials, docs/S7_DESIGN.md §二) ─────────────

def newey_west_variance(d, lag: int) -> float:
    """Newey-West (1987) long-run variance of a series with Bartlett weights:

        LRV = g_0 + 2 * sum_{j=1..L} (1 - j / (L + 1)) * g_j,
        g_j = (1/n) * sum_{t=j+1..n} (d_t - mean)(d_{t-j} - mean)

    `lag` is clipped to [0, n - 1]. Non-negative by construction."""
    d = np.asarray(d, dtype=float)
    n = d.size
    if n == 0:
        return 0.0
    x = d - d.mean()
    lag = max(0, min(int(lag), n - 1))
    lrv = float(x @ x) / n
    for j in range(1, lag + 1):
        lrv += 2.0 * (1.0 - j / (lag + 1)) * float(x[j:] @ x[:-j]) / n
    return max(lrv, 0.0)


FIXED_B_DRAWS = 20_000
_fixed_b_cache: dict[tuple[int, int], np.ndarray] = {}


def fixed_b_null(n: int, lag: int, draws: int = FIXED_B_DRAWS) -> np.ndarray:
    """Sorted null draws of the Newey-West t statistic for sample size n and this lag.

    Fixed-b inference (Kiefer & Vogelsang 2005): with the bandwidth a fixed share
    b = (lag + 1) / n of the sample, the HAC t is not Student-t even under H0; its
    limit depends on b only (pivotal, also under serial correlation). The draws use
    iid N(0,1) series of the same n and lag, so the finite-sample distribution is
    matched exactly for Gaussian data. Seeded, cached per (n, lag): reproducible.
    Owner decision 2026-09-28, after a simulation showed the Student-t p-values
    rejecting a true null 12-25% of the time at a nominal 5% (hold 5-20 days, n=40)."""
    key = (int(n), int(lag))
    if key not in _fixed_b_cache:
        rng = np.random.default_rng(1_000_003 * key[0] + key[1])
        x = rng.standard_normal((draws, n))
        xc = x - x.mean(axis=1, keepdims=True)
        lrv = (xc * xc).sum(axis=1) / n
        for j in range(1, key[1] + 1):
            lrv += 2.0 * (1.0 - j / (key[1] + 1)) * (xc[:, j:] * xc[:, :-j]).sum(axis=1) / n
        t = x.mean(axis=1) / np.sqrt(np.maximum(lrv, 1e-300) / n)
        _fixed_b_cache[key] = np.sort(t)
    return _fixed_b_cache[key]


def hac_t_test(d, lag: int) -> dict:
    """One-sided test of H0: E[d] <= 0 against E[d] > 0 with a HAC (Newey-West) standard
    error, i.e. the Diebold-Mariano (1995) statistic on a loss/P&L differential:

        t = mean(d) / sqrt(LRV / n),  p = share of fixed-b null draws >= t

    (`fixed_b_null`; `p_value_student` keeps the old Student-t n-1 value for reference).
    p is None when the series has fewer than 2 points or no variation (not testable)."""
    d = np.asarray(d, dtype=float)
    n = d.size
    out = {"n": int(n), "lag": max(0, min(int(lag), n - 1)) if n else 0,
           "mean": float(d.mean()) if n else None, "se": None, "t": None, "p_value": None}
    if n < 2:
        return out
    lrv = newey_west_variance(d, lag)
    if lrv <= 1e-18:
        return out
    se = math.sqrt(lrv / n)
    t = float(d.mean()) / se
    null = fixed_b_null(n, out["lag"])
    p = float((null.size - np.searchsorted(null, t, side="left")) / null.size)
    out.update(se=se, t=t, p_value=max(p, 1.0 / null.size),
               p_value_student=float(stats.t.sf(t, df=n - 1)), inference="fixed-b")
    return out


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm (1979) step-down adjusted p-values, same order as the input:
    sorted ascending, p_adj(i) = max_{j<=i} min(1, (m - j + 1) * p(j)).
    Rejecting where p_adj <= alpha controls the family-wise error rate at alpha."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adj[i] = running
    return adj
