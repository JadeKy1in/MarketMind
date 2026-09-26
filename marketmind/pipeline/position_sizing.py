"""Single-input Kelly position sizing. Pure math, no LLM calls.

User conviction can only DISCOUNT the win probability, never increase it.
All inputs are range-validated before the Kelly formula executes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSizeResult:
    raw_kelly_pct: float
    half_kelly_pct: float
    quarter_kelly_pct: float
    volatility_adjustment: float
    correlation_discount: float
    recommended_pct: float
    capped: bool
    risk_bps: float


def compute_position_size(
    win_probability: float,
    win_loss_ratio: float,
    user_conviction_discount: float,
    volatility_percentile: float,
    correlation_to_portfolio: float,
    portfolio_pct_limit: float = 0.25,
) -> PositionSizeResult:
    """Single-input Kelly: user conviction can only discount, not increase.

    Args:
        win_probability: Platt-calibrated model probability (0-1).
        win_loss_ratio: avg_gain / avg_loss (> 0).
        user_conviction_discount: 0-1, user can only REDUCE probability.
        volatility_percentile: current vol vs historical (0-1).
        correlation_to_portfolio: avg correlation with existing positions (-1 to 1).
        portfolio_pct_limit: hard cap for single position (default 0.25).

    Returns:
        PositionSizeResult with raw/half/quarter Kelly and adjustments.

    Raises:
        ValueError: if any input is outside its valid range.
    """
    # ── Input validation (SH-1) ────────────────────────────────────────────
    if not (0.0 <= win_probability <= 1.0):
        raise ValueError(
            f"win_probability must be 0.0-1.0, got {win_probability}"
        )
    if win_loss_ratio <= 0.0:
        raise ValueError(
            f"win_loss_ratio must be > 0.0, got {win_loss_ratio}"
        )
    if not (0.0 <= user_conviction_discount <= 1.0):
        raise ValueError(
            f"user_conviction_discount must be 0.0-1.0, got {user_conviction_discount}"
        )
    if not (0.0 <= volatility_percentile <= 1.0):
        raise ValueError(
            f"volatility_percentile must be 0.0-1.0, got {volatility_percentile}"
        )
    if not (-1.0 <= correlation_to_portfolio <= 1.0):
        raise ValueError(
            f"correlation_to_portfolio must be -1.0 to 1.0, got {correlation_to_portfolio}"
        )
    if not (0.0 < portfolio_pct_limit <= 1.0):
        raise ValueError(
            f"portfolio_pct_limit must be > 0.0 and <= 1.0, got {portfolio_pct_limit}"
        )

    # ── 1. Apply user conviction discount to win probability ───────────────
    adjusted_prob = win_probability * user_conviction_discount

    # ── 2. Full Kelly: K% = W - (1 - W) / R ───────────────────────────────
    raw_kelly = adjusted_prob - (1.0 - adjusted_prob) / win_loss_ratio
    raw_kelly = max(0.0, min(raw_kelly, 1.0))

    # ── 3. Half Kelly (baseline) ───────────────────────────────────────────
    half_kelly = raw_kelly * 0.5

    # ── 4. Quarter Kelly (conservative) ────────────────────────────────────
    quarter_kelly = raw_kelly * 0.25

    # ── 5. Volatility adjustment: higher vol → smaller position ────────────
    vol_adj = 1.0 - (volatility_percentile - 0.5) * 0.5
    vol_adj = max(0.3, min(vol_adj, 1.2))

    # ── 6. Correlation discount: highly correlated → smaller allocation ────
    corr_discount = 1.0 - correlation_to_portfolio * 0.6
    corr_discount = max(0.2, min(corr_discount, 1.0))

    # ── 7. Apply adjustments ───────────────────────────────────────────────
    recommended = half_kelly * vol_adj * corr_discount

    # ── 8. Hard cap ────────────────────────────────────────────────────────
    capped = recommended > portfolio_pct_limit
    if capped:
        recommended = portfolio_pct_limit

    # ── 9. Risk in basis points ────────────────────────────────────────────
    risk_bps = recommended * 10000.0

    return PositionSizeResult(
        raw_kelly_pct=round(raw_kelly, 4),
        half_kelly_pct=round(half_kelly, 4),
        quarter_kelly_pct=round(quarter_kelly, 4),
        volatility_adjustment=round(vol_adj, 4),
        correlation_discount=round(corr_discount, 4),
        recommended_pct=round(recommended, 4),
        capped=capped,
        risk_bps=round(risk_bps, 0),
    )
