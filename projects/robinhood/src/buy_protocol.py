"""
buy_protocol.py — Phase 6 Track B: Buy / Risk-Reward Profiling Protocol.

When the Qualifier routes to ACTION_AND_ADJUST with action_subtrack=BUY,
this module takes over to produce a two-layer buy analysis:

  Layer 1 — RiskProfile (机会整体方向画像)
    Classifies the opportunity as one of:
      - ASYMMETRIC:   低风险/高回报 (non‑event, high safety margin)
      - SPECULATIVE:  高风险/高回报 (event‑driven, short window)
      - TREND_FOLLOWING: 中等风险/中等回报 (established macro trend)

  Layer 2 — Asset Penetration (配置标的穿透分析)
    Generates a matrix of recommended tickers across three layers:
      - core:               direct‑exposure ETF (tight tracking)
      - upstream_leverage:  upstream equity (operational leverage)
      - downstream_related: downstream / related service provider

  Final output — OrderSuggestion
    Wraps both layers into a physically‑isolated order JSON structure
    with Limit Price / Stop Loss / Take Profit per ticker.

Core principle: A buy requires a defensible risk‑reward profile,
  not just a directional narrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    QualifierInput,
    QualifierOutput,
)
from src.scout_types import AssetBasket


# =========================================================================
# RiskProfile — Layer 1: opportunity profiling
# =========================================================================


class RiskProfileLabel(str, Enum):
    """Three archetypes of investment opportunity."""
    ASYMMETRIC = "asymmetric"               # 低风险/高回报
    SPECULATIVE = "speculative"             # 高风险/高回报
    TREND_FOLLOWING = "trend_following"     # 中等风险/中等回报


@dataclass
class RiskProfile:
    """Layer 1 output: opportunity‑level risk‑reward profiling.

    Describes the *type* of opportunity being considered, including
    expected upside/downside, safety margin, and confidence level.
    """

    profile_id: str
    narrative_ref: str                           # ref to the MacroTag.narrative
    label: RiskProfileLabel
    risk_reward_ratio: float                     # e.g. 3.5 means 3.5:1
    expected_upside_pct: float                   # % upside from current price
    expected_downside_pct: float                 # % downside from current price
    safety_margin_pct: float                     # margin of safety (%)
    confidence_rating: str                       # "HIGH" | "MEDIUM" | "LOW"
    rationale: str                               # human‑readable rationale (100–400 chars)
    triggering_conditions: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)
    time_horizon: str = "3–6 months"


# =========================================================================
# AssetPenetration — Layer 2: individual ticker penetration
# =========================================================================


class PenetrationLayer(str, Enum):
    """Three tiers of the asset penetration matrix."""
    CORE = "core"                        # direct‑exposure ETF
    UPSTREAM_LEVERAGE = "upstream_leverage"   # upstream equity / miners
    DOWNSTREAM_RELATED = "downstream_related" # downstream / related


@dataclass
class AssetPenetrationItem:
    """Single ticker in the asset penetration matrix.

    Each item includes a suggested position size (as % of buying power),
    limit / stop / take profit prices, and risk notes.
    """

    ticker: str
    direction: str = "BUY"
    layer: str = "core"
    layer_rationale: str = ""
    suggested_weight_pct: float = 0.0           # % of buying_power
    current_price: Optional[float] = None
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    expected_return_pct: Optional[float] = None
    beta: Optional[float] = None
    correlation_warning: Optional[str] = None
    risk_note: Optional[str] = None


# =========================================================================
# OrderSuggestion — final deliverable packaging
# =========================================================================


@dataclass
class OrderSuggestion:
    """Final output of Track B BUY: a physically isolated order suggestion.

    Contains:
      - Layer 1: RiskProfile
      - Layer 2: List[AssetPenetrationItem]
      - Capital summary (total notional commitment, cash reserve)
      - Causal audit references
      - Execution disclaimer (physical isolation)
    """

    order_id: str
    created_at: str
    decision_track: str = "ACTION_AND_ADJUST"
    action_type: str = "BUY"

    # Layer 1
    risk_profile: Optional[RiskProfile] = None

    # Layer 2
    penetration_items: List[AssetPenetrationItem] = field(default_factory=list)

    # Capital summary
    total_notional_commitment: float = 0.0
    cash_reserve_after: float = 0.0
    cash_reserve_pct: float = 0.0
    account_state_ref: str = ""

    # Causal audit references
    causal_audit_refs: List[str] = field(default_factory=list)

    # Physical isolation
    execution_disclaimer: str = (
        "THEORETICAL ONLY — NO BROKERAGE API CONNECTED. "
        "This order suggestion is a purely analytical output."
    )


# =========================================================================
# Layer 1: RiskProfile classification logic
# =========================================================================


def _classify_risk_profile(
    qualifier_input: QualifierInput,
    qualifier_output: QualifierOutput,
) -> RiskProfile:
    """Classify the opportunity into ASYMMETRIC / SPECULATIVE / TREND_FOLLOWING.

    The classification uses a decision tree based on:
      1. VIX level → ASYMMETRIC candidate if VIX > 35 (panic)
      2. NFP deviation → SPECULATIVE candidate if extreme surprise
      3. Macro signal coherence → TREND_FOLLOWING if >= 70
      4. Market regime → deep‑seek through available signals

    Returns a fully populated RiskProfile.
    """
    narrative_ref = ""
    if qualifier_input.macro_tags:
        narrative_ref = qualifier_input.macro_tags[0].narrative

    vix = qualifier_input.vix_level or 15.0
    coherence = qualifier_output.signal_coherence_score
    regime = qualifier_input.market_regime or "trending"
    nfp_dev = qualifier_input.nfp_deviation or 0.0
    rr_ratio = qualifier_output.reward_risk_ratio

    # ── ASYMMETRIC: panic / extreme safety margin ──
    if vix > 35 or coherence < 25:
        label = RiskProfileLabel.ASYMMETRIC
        upside = 30.0 if vix > 35 else 20.0
        downside = 10.0
        safety = 35.0 if vix > 35 else 25.0
        confidence = "HIGH" if coherence < 20 else "MEDIUM"
        trigger_conditions = [
            f"VIX at {vix:.1f} (> 35 panic threshold)" if vix > 35 else f"Signal coherence {coherence:.0f} (< 25, market distress)",
        ]
        risk_warnings = [
            "Panic may deepen before recovery — scale entry gradually",
            "Liquidity may be impaired during severe dislocations",
        ]
        time_horizon = "6–12 months"
        rationale = (
            f"ASYMMETRIC opportunity identified. VIX at {vix:.1f} indicates "
            f"extreme fear, historically a high‑probability entry zone "
            f"for mean‑reversion plays. Safety margin estimated at {safety:.0f}%, "
            f"providing a favourable risk/reward profile for patient capital."
        )

    # ── SPECULATIVE: high beta / event driven ──
    elif abs(nfp_dev) > 2.0 or regime in ("choppy", "risk_off"):
        label = RiskProfileLabel.SPECULATIVE
        upside = 25.0 if abs(nfp_dev) > 2.0 else 15.0
        downside = 15.0
        safety = 10.0
        confidence = "MEDIUM" if abs(nfp_dev) > 2.0 else "LOW"
        trigger_conditions = [
            f"NFP deviation {nfp_dev:+.1f}σ" if abs(nfp_dev) > 2.0 else f"Market regime: {regime}",
        ]
        risk_warnings = [
            "Speculative positions require tight stop‑loss discipline",
            "High beta may amplify both gains and losses",
            "Event‑driven opportunities carry binary risk",
        ]
        time_horizon = "1–3 months"
        rationale = (
            f"SPECULATIVE opportunity. "
            + (f"NFP surprise of {nfp_dev:+.1f}σ creates event‑driven volatility. "
               if abs(nfp_dev) > 2.0 else f"Market regime ({regime}) warrants cautious positioning. ")
            + f"Time horizon is short (1–3 months) with binary risk profile."
        )

    # ── TREND_FOLLOWING: established macro trend ──
    else:
        label = RiskProfileLabel.TREND_FOLLOWING
        upside = 15.0
        downside = 8.0
        safety = 20.0
        confidence = "HIGH" if coherence >= 70 else "MEDIUM"
        trigger_conditions = [
            f"Signal coherence {coherence:.0f} (>= 70: strong directional consensus)",
        ]
        risk_warnings = [
            "Trend may exhaust — monitor momentum divergence",
            "Position sizing should account for macro regime shifts",
        ]
        time_horizon = "3–6 months"
        rationale = (
            f"TREND_FOLLOWING opportunity. Signal coherence at {coherence:.0f} "
            f"indicates strong directional consensus across independent sources. "
            f"The macro trend is established and provides a favourable "
            f"risk/reward profile with moderate drawdown expectations."
        )

    effective_rr = rr_ratio if rr_ratio > 0 else (upside / downside)

    return RiskProfile(
        profile_id=f"rp_{qualifier_output.judgment_id[3:]}",
        narrative_ref=narrative_ref,
        label=label,
        risk_reward_ratio=round(effective_rr, 2),
        expected_upside_pct=upside,
        expected_downside_pct=downside,
        safety_margin_pct=safety,
        confidence_rating=confidence,
        rationale=rationale,
        triggering_conditions=trigger_conditions,
        risk_warnings=risk_warnings,
        time_horizon=time_horizon,
    )


# =========================================================================
# Layer 2: Asset penetration logic
# =========================================================================


def _build_penetration_matrix(
    qualifier_input: QualifierInput,
    risk_profile: RiskProfile,
    asset_basket: Optional[AssetBasket],
) -> List[AssetPenetrationItem]:
    """Build the asset penetration matrix for the given risk profile.

    Uses `AssetBasket` to determine concrete ticker suggestions across
    the three penetration layers (core / upstream / downstream).

    If `asset_basket` is None or empty, returns a minimal set based on
    macro direction inferred from the input signals.
    """
    items: List[AssetPenetrationItem] = []

    # Determine base weight limits from risk profile
    if risk_profile.label == RiskProfileLabel.ASYMMETRIC:
        profile_mult = 1.2
        core_base, upstream_base, downstream_base = 12.0, 6.0, 4.0
    elif risk_profile.label == RiskProfileLabel.SPECULATIVE:
        profile_mult = 0.5
        core_base, upstream_base, downstream_base = 8.0, 3.0, 2.0
    else:  # TREND_FOLLOWING
        profile_mult = 1.0
        core_base, upstream_base, downstream_base = 10.0, 5.0, 3.0

    # Confidence adjustment
    if risk_profile.confidence_rating == "HIGH":
        conf_mult = 1.0
    elif risk_profile.confidence_rating == "MEDIUM":
        conf_mult = 0.7
    else:  # LOW
        conf_mult = 0.4

    def _weight(base: float) -> float:
        return round(base * conf_mult * profile_mult, 1)

    # ── Layer 1: Core exposure (direct ETF) ──
    core_tickers = []
    if asset_basket and asset_basket.high_liquidity:
        core_tickers = asset_basket.high_liquidity[:3]

    # If we have macro direction but no basket, infer from signals
    if not core_tickers:
        dxy = qualifier_input.dxy_trend
        vix = qualifier_input.vix_level or 15.0
        if dxy == "weakening":
            core_tickers = ["GLD", "DBC", "TLT"]
        elif dxy == "strengthening":
            core_tickers = ["USFR", "SHY", "DBC"]
        elif vix > 25:
            core_tickers = ["GLD", "TLT", "USFR"]
        else:
            core_tickers = ["SPY", "QLD", "DBC"]

    for i, ticker in enumerate(core_tickers):
        items.append(AssetPenetrationItem(
            ticker=ticker,
            layer=PenetrationLayer.CORE.value,
            layer_rationale=(
                f"Core {['liquidity', 'exposure', 'beta'][i] if i < 3 else 'diversifier'} "
                f"ETF with tight tracking and low expense ratio"
            ),
            suggested_weight_pct=_weight(core_base) / max(len(core_tickers), 1),
            limit_price=None,
            stop_loss=None,
            take_profit=None,
        ))

    # ── Layer 2: Upstream leverage (equity / miners — higher beta) ──
    upstream_tickers = []
    if asset_basket and asset_basket.high_beta:
        upstream_tickers = asset_basket.high_beta[:2]

    if not upstream_tickers:
        # If DXY weakening → commodity/commodity‑producer bias
        if qualifier_input.dxy_trend == "weakening":
            upstream_tickers = ["GDX", "XLE"]
        elif qualifier_input.vix_level and qualifier_input.vix_level > 25:
            upstream_tickers = ["GDX", "ERX"]
        else:
            upstream_tickers = ["XLE", "XLF"]

    for ticker in upstream_tickers:
        items.append(AssetPenetrationItem(
            ticker=ticker,
            layer=PenetrationLayer.UPSTREAM_LEVERAGE.value,
            layer_rationale=(
                "Upstream equity with operational leverage — higher beta "
                "and greater sensitivity to the macro tailwind"
            ),
            suggested_weight_pct=_weight(upstream_base) / max(len(upstream_tickers), 1),
            beta=1.5 if "GDX" in ticker or "ERX" in ticker else 1.2,
            risk_note=(
                "High beta — position size conservatively" if "ERX" in ticker
                else "Sector‑concentrated — monitor correlation risk"
            ),
        ))

    # ── Layer 3: Downstream / related ──
    downstream_tickers = []
    if asset_basket and asset_basket.low_expense_ratio:
        downstream_tickers = asset_basket.low_expense_ratio[:1]

    if not downstream_tickers:
        downstream_tickers = ["VDE"]

    for ticker in downstream_tickers:
        items.append(AssetPenetrationItem(
            ticker=ticker,
            layer=PenetrationLayer.DOWNSTREAM_RELATED.value,
            layer_rationale=(
                "Downstream / related exposure providing diversified "
                "participation with lower volatility than upstream plays"
            ),
            suggested_weight_pct=_weight(downstream_base) / max(len(downstream_tickers), 1),
        ))

    return items


# =========================================================================
# Price computation helpers
# =========================================================================


def _compute_limit_price(
    current_price: Optional[float],
    direction: str,
) -> Optional[float]:
    """Compute a theoretical limit price for a given ticker.

    Physical isolation: returns a theoretical value, not an executed order.
    For BUY orders, uses a small discount from current price (limit buy).
    Returns None if current_price is unavailable.
    """
    if current_price is None:
        return None
    if direction == "BUY":
        return round(current_price * 0.995, 2)   # 0.5% below market
    return None


def _compute_stop_loss(
    current_price: Optional[float],
    risk_profile: RiskProfile,
) -> Optional[float]:
    """Compute a stop‑loss price based on risk profile.

    - ASYMMETRIC: loose stop (~10% below) — let conviction play out
    - SPECULATIVE: tight stop (~5% below) — protect against binary risk
    - TREND_FOLLOWING: moderate stop (~7% below) — trend following discipline
    Returns None if current_price is unavailable.
    """
    if current_price is None:
        return None
    distance_map = {
        RiskProfileLabel.ASYMMETRIC: 0.90,
        RiskProfileLabel.SPECULATIVE: 0.95,
        RiskProfileLabel.TREND_FOLLOWING: 0.93,
    }
    factor = distance_map.get(risk_profile.label, 0.93)
    return round(current_price * factor, 2)


def _compute_take_profit(
    current_price: Optional[float],
    risk_profile: RiskProfile,
) -> Optional[float]:
    """Compute a take‑profit price based on expected upside.

    - ASYMMETRIC: +20–30% target
    - SPECULATIVE: +15–25% target (shorter window)
    - TREND_FOLLOWING: +15% target (measured move)
    Returns None if current_price is unavailable.
    """
    if current_price is None:
        return None
    upside_map = {
        RiskProfileLabel.ASYMMETRIC: 1.25,
        RiskProfileLabel.SPECULATIVE: 1.20,
        RiskProfileLabel.TREND_FOLLOWING: 1.15,
    }
    factor = upside_map.get(risk_profile.label, 1.15)
    return round(current_price * factor, 2)


# =========================================================================
# BuyProtocol — the Track B BUY entry point
# =========================================================================


class BuyProtocol:
    """Track B: Buy / Risk‑Reward Profiling Protocol.

    Generates a two‑layer buy analysis from a Qualifier judgment
    with action_subtrack=BUY:

      Layer 1 — RiskProfile: classifies the opportunity archetype.
      Layer 2 — AssetPenetrationItems: ticker matrix with position sizing.
      Final  — OrderSuggestion: physically isolated order structure.

    Usage::

        protocol = BuyProtocol()
        order = protocol.analyze(qualifier_input, qualifier_output, asset_basket)
        print(order.execution_disclaimer)
        # "THEORETICAL ONLY — NO BROKERAGE API CONNECTED. ..."
    """

    def __init__(self) -> None:
        self._last_order: Optional[OrderSuggestion] = None
        self._last_risk_profile: Optional[RiskProfile] = None

    @property
    def last_order(self) -> Optional[OrderSuggestion]:
        """Most recent OrderSuggestion, if any."""
        return self._last_order

    @property
    def last_risk_profile(self) -> Optional[RiskProfile]:
        """Most recent RiskProfile, if any."""
        return self._last_risk_profile

    def analyze(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
        asset_basket: Optional[AssetBasket] = None,
        buying_power: float = 100_000.0,
    ) -> OrderSuggestion:
        """Produce a full OrderSuggestion from Qualifier context.

        Args:
            qualifier_input: The original input fed to the Qualifier.
            qualifier_output: The Qualifier's judgment (must be ACTION + BUY).
            asset_basket: Optional Phase‑5 AssetBasket for ticker suggestions.
            buying_power: Available capital (defaults to 100k for demo).

        Returns:
            A fully populated OrderSuggestion with two layers.

        Raises:
            ValueError: If not an ACTION+BUY judgment.
        """
        if qualifier_output.decision_track != DecisionTrack.ACTION_AND_ADJUST:
            raise ValueError(
                f"BuyProtocol requires ACTION_AND_ADJUST, "
                f"got {qualifier_output.decision_track.value}"
            )
        if qualifier_output.action_subtrack != ActionSubtrack.BUY:
            raise ValueError(
                f"BuyProtocol requires action_subtrack=BUY, "
                f"got {qualifier_output.action_subtrack}"
            )

        # ── Layer 1 — RiskProfile ──
        risk_profile = _classify_risk_profile(qualifier_input, qualifier_output)
        self._last_risk_profile = risk_profile

        # ── Layer 2 — Asset Penetration ──
        penetration_items = _build_penetration_matrix(
            qualifier_input, risk_profile, asset_basket,
        )

        # ── Compute prices for each item ──
        for item in penetration_items:
            item.limit_price = _compute_limit_price(item.current_price, item.direction)
            item.stop_loss = _compute_stop_loss(item.current_price, risk_profile)
            item.take_profit = _compute_take_profit(item.current_price, risk_profile)

        # ── Capital summary ──
        total_weight = sum(item.suggested_weight_pct for item in penetration_items)
        notional_commitment = buying_power * (total_weight / 100.0)
        cash_reserve = buying_power - notional_commitment
        cash_pct = (cash_reserve / buying_power * 100.0) if buying_power > 0 else 0.0

        # ── Build final OrderSuggestion ──
        order_id = f"ord_{qualifier_output.judgment_id[3:]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        self._last_order = OrderSuggestion(
            order_id=order_id,
            created_at=timestamp,
            action_type="BUY",
            risk_profile=risk_profile,
            penetration_items=penetration_items,
            total_notional_commitment=round(notional_commitment, 2),
            cash_reserve_after=round(cash_reserve, 2),
            cash_reserve_pct=round(cash_pct, 2),
            account_state_ref=f"snapshot_{timestamp[:10]}",
            causal_audit_refs=[],  # placeholder — wire from QualifierOutput
        )

        return self._last_order