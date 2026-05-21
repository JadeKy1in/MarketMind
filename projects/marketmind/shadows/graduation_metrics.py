"""Metric computation functions for the graduation engine.

Extracted from graduation_engine.py per modular architecture rules (§3.1).
Pure mathematical functions with no DB or engine dependencies.

All functions are standalone — no class wrapper needed. Each function
computes exactly one financial metric from raw data.
"""
from __future__ import annotations

import logging
import math

import numpy as np

from marketmind.shadows.graduation_stress_tests import compute_max_dd_from_returns
from marketmind.shadows.brier_decomposition import decompose_brier

logger = logging.getLogger("marketmind.shadows.graduation_metrics")

# ── Contrarian subtype thresholds ─────────────────────────────────────────────

_CONTRARIAN_TRADE_DD = {
    # shadow_id suffix → (min_trades, max_dd)
    "fade_master": (50, 0.35),
    "sideways_scout": (40, 0.30),
    "vol_surfer": (30, 0.40),
    "hunter": (25, 0.40),
}

# ── Lookback windows ──────────────────────────────────────────────────────────

_TYPE_LOOKBACK_WINDOWS = {
    "expert": 90,
    "momentum": 75,
    "contrarian": 252,
}

# ── Benchmark returns ─────────────────────────────────────────────────────────

_TYPE_BENCHMARK_RETURNS = {
    "expert": 0.07,      # ~SPY long-term avg
    "momentum": 0.08,    # SG Trend Index proxy
    "contrarian": 0.06,  # Fama-French LT Rev proxy
}


# ── Trade metrics ─────────────────────────────────────────────────────────────

def compute_win_rate(trades: list) -> float:
    """Compute win rate from trade history."""
    closed_trades = [t for t in trades if t.pnl_pct is not None]
    if not closed_trades:
        return 0.0
    wins = sum(1 for t in closed_trades if (t.pnl_pct or 0) > 0)
    return wins / len(closed_trades)


def compute_min_bet_ratio(trades: list) -> float:
    """Compute ratio of min-bet trades to total trades (anti-gaming)."""
    if not trades:
        return 0.0
    # Min-bet = position_size_pct <= 0.2% (approx $100 on $50K)
    min_bets = sum(1 for t in trades if (t.position_size_pct or 0) <= 0.002)
    return min_bets / len(trades)


def check_single_trade_dependency(trades: list) -> bool:
    """Check if a single trade dominates total P&L (>50%)."""
    closed = [t for t in trades if t.pnl_pct is not None]
    if len(closed) < 3:
        return False
    total_pnl = sum(abs(t.pnl_pct or 0) for t in closed)
    if total_pnl < 1e-10:
        return False
    max_pnl = max(abs(t.pnl_pct or 0) for t in closed)
    return (max_pnl / total_pnl) > 0.50


# ── Return metrics (operate on decimal daily return lists) ────────────────────

def compute_total_return(snapshots: list) -> float:
    """Compute cumulative total return from snapshot chain.

    Args:
        snapshots: List of objects with ``cumulative_return_pct`` and
                   ``daily_return_pct`` attributes (percentage values).
    """
    if not snapshots:
        return 0.0
    # Use the latest snapshot's cumulative return
    latest = snapshots[-1]
    if latest.cumulative_return_pct is not None:
        return latest.cumulative_return_pct / 100.0
    # Fallback: compound daily returns (convert % to decimal)
    returns = [(s.daily_return_pct or 0.0) / 100.0 for s in snapshots if s.daily_return_pct is not None]
    if not returns:
        return 0.0
    cumulative = 1.0
    for r in returns:
        cumulative *= (1.0 + r)
    return cumulative - 1.0


def compute_max_dd(snapshots: list) -> float:
    """Compute maximum drawdown from snapshots.

    Args:
        snapshots: List of objects with ``max_drawdown_pct`` and
                   ``daily_return_pct`` attributes.
    """
    if not snapshots:
        return 0.0
    # Use the max_drawdown_pct from snapshots if available
    max_dd = 0.0
    for s in snapshots:
        if s.max_drawdown_pct is not None:
            max_dd = max(max_dd, abs(s.max_drawdown_pct))
    if max_dd > 0:
        return max_dd / 100.0
    # Fallback: compute from cumulative returns (convert % to decimal)
    returns = [(s.daily_return_pct or 0.0) / 100.0 for s in snapshots if s.daily_return_pct is not None]
    return compute_max_dd_from_returns(returns)


def annualized_return(daily_returns: list[float]) -> float:
    """Compute annualized return from daily returns."""
    n = len(daily_returns)
    if n == 0:
        return 0.0
    cumulative = 1.0
    for r in daily_returns:
        cumulative *= (1.0 + r)
    if cumulative <= 0:
        return -1.0
    return cumulative ** (252.0 / n) - 1.0


def compute_sortino(daily_returns: list[float], risk_free_annual: float = 0.04) -> float:
    """Compute Sortino ratio: (Rp - Rf) / DownsideDev.

    DownsideDev = std of negative returns only. Returns annualized value.
    """
    n = len(daily_returns)
    if n == 0:
        return 0.0

    rf_daily = risk_free_annual / 252
    mean_return = sum(daily_returns) / n
    excess = mean_return - rf_daily

    # Downside deviation
    downside = [min(r - rf_daily, 0) for r in daily_returns]
    downside_sq = sum(d * d for d in downside) / n
    if downside_sq <= 1e-10:
        return float("inf") if excess > 0 else 0.0

    downside_dev = math.sqrt(downside_sq)
    daily_sortino = excess / downside_dev
    return daily_sortino * math.sqrt(252)  # annualized


def compute_mar(daily_returns: list[float]) -> float:
    """Compute MAR ratio: CAGR / |MaxDD|."""
    n = len(daily_returns)
    if n == 0:
        return 0.0

    # CAGR
    cumulative = 1.0
    for r in daily_returns:
        cumulative *= (1.0 + r)
    if cumulative <= 0:
        return 0.0
    cagr = cumulative ** (252.0 / n) - 1.0 if n > 0 else 0.0

    # Max DD
    max_dd = compute_max_dd_from_returns(daily_returns)
    if max_dd < 1e-6:
        return cagr / 0.001  # floor

    return cagr / max_dd


def compute_gpr(daily_returns: list[float]) -> float:
    """Compute Gain-to-Pain Ratio: sum(gains) / sum(|losses|)."""
    gains = sum(r for r in daily_returns if r > 0)
    losses = sum(abs(r) for r in daily_returns if r < 0)
    if losses < 1e-10:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def compute_k_ratio(daily_returns: list[float]) -> float:
    """Compute K-Ratio: Slope(VAMI) / SE(Slope).

    VAMI = Value Added Monthly Index: cumulative value of $1 invested.
    We fit a linear regression of VAMI vs time and use slope/SE(slope).
    Returns annualized value.
    """
    n = len(daily_returns)
    if n < 5:
        return 0.0

    # VAMI: cumulative value
    vami = [1.0]
    for r in daily_returns:
        vami.append(vami[-1] * (1.0 + r))
    vami = vami[1:]  # n elements

    # Linear regression: VAMI = a + b * t
    t = np.arange(1, n + 1, dtype=float)
    v = np.array(vami, dtype=float)

    # OLS slope and SE
    t_mean = float(np.mean(t))
    v_mean = float(np.mean(v))
    numerator = float(np.sum((t - t_mean) * (v - v_mean)))
    denominator = float(np.sum((t - t_mean) ** 2))

    if denominator < 1e-10:
        return 0.0

    slope = numerator / denominator
    residuals = v - (v_mean + slope * (t - t_mean))
    rss = float(np.sum(residuals ** 2))
    se_slope = math.sqrt(rss / (n - 2) / denominator) if n > 2 else float("inf")

    if se_slope < 1e-10:
        return float("inf") if slope > 0 else 0.0

    # Annualize
    return (slope * 252) / (se_slope * math.sqrt(252))


# ── Type-specific utilities ───────────────────────────────────────────────────

def get_benchmark_return(shadow_type: str) -> float:
    """Get type-specific benchmark annual return (simplified proxy)."""
    return _TYPE_BENCHMARK_RETURNS.get(shadow_type, 0.07)


def contrarian_trade_dd(shadow_id: str) -> tuple[int, float]:
    """Get contrarian subtype-specific (min_trades, max_dd) thresholds."""
    for key, (min_t, dd) in _CONTRARIAN_TRADE_DD.items():
        if key in shadow_id:
            return min_t, dd
    return (25, 0.35)  # default for unknown contrarian


def default_lookback(shadow_type: str) -> int:
    """Get type-specific default evaluation window in days."""
    return _TYPE_LOOKBACK_WINDOWS.get(shadow_type, 90)


# ── Brier type estimation ────────────────────────────────────────────────────

def estimate_brier_type(shadow_id: str, trades: list) -> str:
    """Estimate Brier/Manokhin type from available data.

    Since we lack per-trade confidence scores in the trade history, we
    construct a coarse estimate: long trades are assigned prob=0.55 and
    short trades prob=0.45. With only 2 unique probability values, the
    Brier decomposition will always return "Sloth" (weak discrimination).

    To avoid penalizing shadows for this data limitation, we default to
    "Bull" (poor calibration, strong discrimination — the safe assumption
    when per-trade confidence data is unavailable). When actual confidence
    scores become available in the trade history, this function should be
    updated to use them.
    """
    # Collect direction predictions vs outcomes from closed trades
    probabilities: list[float] = []
    outcomes: list[int] = []

    for t in trades:
        if t.pnl_pct is None:
            continue
        # Direction encoded as probability: long → prob of positive return
        prob = 0.55 if t.direction == "long" else 0.45  # default confidence
        outcome = 1 if (t.pnl_pct or 0) > 0 else 0
        probabilities.append(prob)
        outcomes.append(outcome)

    if len(outcomes) < 10:
        return "Bull"

    # Check for probability diversity: if all probabilities are identical
    # or come from only 2 values, skip decomposition (will always be Sloth)
    unique_probs = set(round(p, 4) for p in probabilities)
    if len(unique_probs) < 3:
        return "Bull"

    try:
        decomposition = decompose_brier(probabilities, outcomes, n_bins=min(10, len(outcomes)))
        return decomposition.manokhin_type
    except Exception:
        logger.debug("Brier decomposition failed for %s, defaulting to Bull", shadow_id)
        return "Bull"
