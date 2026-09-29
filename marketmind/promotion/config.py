"""Every promotion threshold in one place (docs/S7_DESIGN.md §一). The dashboard lists these."""
from __future__ import annotations

# ── Data ────────────────────────────────────────────────────────────────
NOTIONAL_USD = 10_000.0          # daily return = sum(pnl_usd on exit date) / notional
TRADING_DAYS_PER_YEAR = 252
MIN_POSITION_USD = 100.0         # "minimum position" trades (SPEC §6.1)
# Only matured decision cohorts are evaluated (fix 2026-09-29): a decision day counts
# once all its records have settled, or this many trading days after entry window +
# longest hold of that day (records still open then are left out and reported).
MATURITY_GRACE_DAYS = 5

# ── Probation -> formal ────────────────────────────────────────────────
PROBATION_DAYS = 60              # trading days with records
MINTRL_CONFIDENCE = 0.95         # Bailey & Lopez de Prado MinTRL, benchmark Sharpe 0
MINTRL_BENCHMARK_SHARPE = 0.0
# "Beats random" gate (owner decision 2026-09-28): Monte Carlo random portfolios instead
# of the ledger's one-trade-a-day random shadow (promotion/random_mc.py); since
# 2026-09-29 the shadow's own trades moved in time (same ticker, hold, direction).
MC_DRAWS = 1000                  # random portfolios per shadow and review day
MC_QUANTILE = 0.95               # shadow mean net return >= this quantile of the draws ...
MC_ALPHA = 0.05                  # ... and one-sided p = (1 + #draws >= mean) / (1 + valid) <= this
MC_MIN_VALID = 200               # fewer valid draws -> "not evaluable" (gate fails closed)
MC_MAX_UNPRICED_SHARE = 0.2      # more than this share of trades without usable bars -> not evaluable
MC_MIN_WINDOW_DAYS = 40          # shorter evaluation window -> not evaluable (the time-shift
                                 # test has at most window - 1 distinct draws)
MC_MAX_GAP_DAYS = 4              # a trade's first/last bar may be at most this many calendar
                                 # days inside its entry/exit dates (holidays, weekends)
MC_FETCH_BUDGET_S = 120.0        # wall-clock budget for loading uncached bars in one review

# ── Composite score (formal shadows only) ──────────────────────────────
SCORE_WEIGHTS = {"mppm": 0.35, "calmar": 0.25, "omega": 0.20, "win_rate": 0.20}
MPPM_RHO = 3.0
OMEGA_THRESHOLD = 0.0
SHRINKAGE_K = 30                 # weight n / (n + k), n = settled trades
MIN_POSITION_SHARE_LIMIT = 0.6   # share of <= $100 trades above this ...
MIN_POSITION_HAIRCUT = 0.8       # ... multiplies the composite score by this

# ── Formal -> advisor ──────────────────────────────────────────────────
ADVISOR_MIN_FORMAL_DAYS = 20
TIER1_TOP_SHARE = 0.20
TIER2_TOP_SHARE = 0.50
STRESS_WORST_SHARE = 0.10        # worst 10% market-benchmark days: shadow mean >= market mean
STRESS_MIN_DAYS = 10             # market days needed before the stress test can pass
STRESS_ALPHA = 0.05              # ... and mean(shadow - market) on those days > 0, one-sided HAC
STRESS_MIN_WORST_DAYS = 10       # fewer worst-decile days -> significance insufficient (not passed)
FORWARD_OOS_DAYS = 20            # net return over the first 20 trading days as formal > 0
PBO_MAX = 0.30                   # C20 stricter bar
PBO_BLOCKS = 16                  # CSCV blocks
DSR_MIN = 0.95                   # C20 stricter bar (Sidak-form DSR, metrics.dsr)
DSR_CLUSTER_CORR = 0.5           # candidates with return correlation >= this are one trial
DSR_MIN_OVERLAP_DAYS = 20        # fewer common days -> treated as uncorrelated (separate trials)
BRIER_MAX = 0.25

# ── Monitoring ─────────────────────────────────────────────────────────
# Robust CUSUM (fix 2026-09-29): reference = the formal period only (formal_since ..
# advisor_since], median / MAD standardisation winsorised at CUSUM_WINSOR, alarm
# threshold h calibrated per advisor by block bootstrap of the reference so that the
# in-control run length is geometric-equivalent to an ARL >= CUSUM_ARL0 trading days
# with ~90% probability despite the estimated parameters (metrics.calibrate_cusum_h).
CUSUM_K = 0.5                    # allowance, in robust standard deviations
CUSUM_WINSOR = 4.0               # standardised daily values clipped to +/- this
CUSUM_ARL0 = 500                 # in-control average run length target (trading days)
CUSUM_BOOT_PATHS = 200           # bootstrap paths per reference resample
CUSUM_BOOT_HORIZON = 250         # days simulated per path
CUSUM_CHECK_DAYS = (60, 120, 250)  # P(false alarm within t days) <= 1 - exp(-t / CUSUM_ARL0)
CUSUM_GK_RESAMPLES = 30          # reference resamples (Gandy & Kvaloy 2013 guaranteed performance)
CUSUM_GK_QUANTILE = 0.9          # h = this quantile of the per-resample thresholds
CUSUM_MIN_REFERENCE_DAYS = 20    # formal-period days needed before monitoring starts

# ── Elimination -> challenger (C30) ────────────────────────────────────
EVALUATION_PERIOD_DAYS = 20
BOTTOM_SHARE = 0.20
BOTTOM_PERIODS_FOR_CHALLENGE = 3

STAGES = ("probation", "formal", "advisor", "paused", "blocked")


def thresholds() -> dict:
    """All thresholds as a plain dict, for the dashboard."""
    return {k: v for k, v in globals().items() if k.isupper() and not k.startswith("_")}
