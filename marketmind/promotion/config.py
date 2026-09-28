"""Every promotion threshold in one place (docs/S7_DESIGN.md §一). The dashboard lists these."""
from __future__ import annotations

# ── Data ────────────────────────────────────────────────────────────────
NOTIONAL_USD = 10_000.0          # daily return = sum(pnl_usd on exit date) / notional
TRADING_DAYS_PER_YEAR = 252
MIN_POSITION_USD = 100.0         # "minimum position" trades (SPEC §6.1)

# ── Probation -> formal ────────────────────────────────────────────────
PROBATION_DAYS = 60              # trading days with records
MINTRL_CONFIDENCE = 0.95         # Bailey & Lopez de Prado MinTRL, benchmark Sharpe 0
MINTRL_BENCHMARK_SHARPE = 0.0
# "Beats random" gate (owner decision 2026-09-28): Monte Carlo random portfolios instead
# of the ledger's one-trade-a-day random shadow (promotion/random_mc.py).
MC_DRAWS = 1000                  # random portfolios per shadow and review day
MC_QUANTILE = 0.95               # shadow mean net return >= this quantile of the draws ...
MC_ALPHA = 0.05                  # ... and one-sided p = (1 + #draws >= mean) / (1 + valid) <= this
MC_MIN_VALID = 200               # fewer valid draws -> "not evaluable" (gate fails closed)
MC_MAX_POOL_MISSING = 0.5        # more than this share of the ticker pool without bars -> not evaluable
MC_MAX_GAP_DAYS = 4              # a pool ticker's first/last bar in a trade window may be at most
                                 # this many calendar days inside the window (holidays, weekends)
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
STRESS_WORST_SHARE = 0.10        # worst 10% market-benchmark days
STRESS_MULTIPLE = 2.0            # shadow mean on those days >= -2 x |market mean|
STRESS_MIN_DAYS = 10             # market days needed before the stress test can pass
FORWARD_OOS_DAYS = 20            # net return over the first 20 trading days as formal > 0
PBO_MAX = 0.30                   # C20 stricter bar
PBO_BLOCKS = 16                  # CSCV blocks
DSR_MIN = 0.95                   # C20 stricter bar
BRIER_MAX = 0.25

# ── Monitoring ─────────────────────────────────────────────────────────
CUSUM_K = 0.5                    # allowance, in standard deviations
CUSUM_H = 5.0                    # alarm threshold, in standard deviations
CUSUM_MIN_REFERENCE_DAYS = 20    # pre-advisor days needed to estimate mean / sd

# ── Elimination -> challenger (C30) ────────────────────────────────────
EVALUATION_PERIOD_DAYS = 20
BOTTOM_SHARE = 0.20
BOTTOM_PERIODS_FOR_CHALLENGE = 3

STAGES = ("probation", "formal", "advisor", "paused", "blocked")


def thresholds() -> dict:
    """All thresholds as a plain dict, for the dashboard."""
    return {k: v for k, v in globals().items() if k.isupper() and not k.startswith("_")}
