"""
sell_protocol.py — Phase 6 Track B: Sell/Liquidate Protocol.

When the Qualifier routes to ACTION_AND_ADJUST with action_subtrack=SELL,
this module takes over to produce a rigorously cross-verified sell analysis:

  - Concrete trigger identification: which macro data point, technical
    breakdown, or narrative shift caused the sell signal.
  - Cross-verification: confirm the signal is not a false positive by
    checking complementary indicators.
  - Clearout ratio: how much of the position to liquidate (25%–100%).
  - Protective stop-loss: suggested limit price for the remaining position.

Core principle: A sell requires ironclad evidence, not gut feeling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    QualifierInput,
    QualifierOutput,
)


# =========================================================================
# SellTrigger — what specifically caused the sell signal
# =========================================================================


class SellTriggerCategory(str, Enum):
    """Categorization of what triggered the sell signal."""
    MACRO_SURPRISE = "macro_surprise"             # e.g. NFP beat, CPI miss
    TECHNICAL_BREAK = "technical_break"            # e.g. SMA breakdown, support loss
    NARRATIVE_SHIFT = "narrative_shift"            # e.g. hawkish Fed pivot
    RISK_MANAGEMENT = "risk_management"            # e.g. stop-loss hit, drawdown limit
    REBALANCE = "rebalance"                        # e.g. target weight exceeded


@dataclass
class SellTrigger:
    """Specific trigger that initiated the sell signal."""

    category: SellTriggerCategory
    indicator: str                                 # e.g. "NFP_MoM", "SPX_50SMA", "FOMC_HAWKISH"
    raw_value: Optional[float] = None
    threshold_value: Optional[float] = None
    direction: str = "above"                       # "above" | "below" | "crossover"
    description: str = ""


# =========================================================================
# CrossVerification — confirm the trigger is genuine
# =========================================================================


@dataclass
class CrossVerification:
    """A cross-check against a complementary indicator to confirm the sell signal."""

    indicator: str                                 # complementary indicator checked
    verdict: str                                   # "confirms" | "contradicts" | "neutral"
    narrative: str                                 # explanation of the cross-check
    weight: float = 1.0                            # confidence weight for this check (0-1)


# =========================================================================
# SellAnalysis — the structured output of the sell protocol
# =========================================================================


@dataclass
class SellAnalysis:
    """Structured output of the Sell/Liquidate analysis.

    This is the core deliverable: a cross-verified sell recommendation
    with precise clearout ratio and protective stop-loss limits.
    """

    analysis_id: str
    judgment_id: str                               # links back to the Qualifier
    timestamp: str
    primary_trigger: SellTrigger                   # the single most important trigger
    secondary_triggers: List[SellTrigger] = field(default_factory=list)
    cross_verifications: List[CrossVerification] = field(default_factory=list)
    clearout_ratio: float = 1.0                    # 0.0–1.0, how much to sell
    stop_loss_price: Optional[float] = None        # protective stop for remainder
    stop_loss_distance_pct: Optional[float] = None # distance from current price (%)
    limit_price: Optional[float] = None            # preferred limit order price
    rationale: str = ""                            # full narrative rationale
    cross_check_verdict: str = "confirmed"         # "confirmed" | "mixed" | "warning"


# =========================================================================
# Trigger identification logic
# =========================================================================


def _identify_primary_trigger(input_: QualifierInput, output_: QualifierOutput) -> SellTrigger:
    """Identify the primary sell trigger from Qualifier context.

    Uses a priority chain to determine the most important trigger:
      1. NFP surprise (largest macro surprise)
      2. VIX spike (technical panic signal)
      3. CPI inflation overshoot
      4. DXY strength (risk-off regime shift)
      5. Inverted yield curve deepening
    """
    # Priority 1: NFP massive miss or beat inverted
    if input_.nfp_deviation is not None and abs(input_.nfp_deviation) > 2.0:
        direction = "above" if input_.nfp_deviation > 0 else "below"
        desc = (
            f"NFP deviation of {input_.nfp_deviation:+.1f}σ suggests "
            f"{'overheating' if input_.nfp_deviation > 0 else 'sudden weakness'} "
            f"in the labor market."
        )
        return SellTrigger(
            category=SellTriggerCategory.MACRO_SURPRISE,
            indicator="NFP_DEVIATION",
            raw_value=input_.nfp_deviation,
            threshold_value=2.0,
            direction=direction,
            description=desc,
        )

    # Priority 2: VIX spike > threshold
    if input_.vix_level is not None and input_.vix_level > 30:
        return SellTrigger(
            category=SellTriggerCategory.TECHNICAL_BREAK,
            indicator="VIX_SPIKE",
            raw_value=input_.vix_level,
            threshold_value=30.0,
            direction="above",
            description=(
                f"VIX at {input_.vix_level:.1f} exceeds the 30 panic threshold. "
                f"Widespread hedging and risk-off positioning detected."
            ),
        )

    # Priority 3: CPI overshoot
    if input_.cpi_mom is not None and input_.cpi_mom > 0.5:
        return SellTrigger(
            category=SellTriggerCategory.MACRO_SURPRISE,
            indicator="CPI_MOM",
            raw_value=input_.cpi_mom,
            threshold_value=0.5,
            direction="above",
            description=(
                f"CPI MoM at {input_.cpi_mom:.2f}% exceeds 0.5% threshold, "
                f"suggesting persistent inflation that may delay rate cuts."
            ),
        )

    # Priority 4: DXY breaking higher under weakening trend context
    if input_.dxy_trend == "strengthening":
        return SellTrigger(
            category=SellTriggerCategory.MACRO_SURPRISE,
            indicator="DXY_STRENGTH",
            direction="above",
            description=(
                "DXY strengthening signals capital flow into USD safe havens. "
                "Risk assets face headwinds in this regime."
            ),
        )

    # Priority 5: Yield curve deepening inversion
    if input_.yield_curve == "inverted":
        return SellTrigger(
            category=SellTriggerCategory.MACRO_SURPRISE,
            indicator="YIELD_CURVE_INVERSION",
            direction="below",
            description=(
                "Inverted yield curve deepens recession expectations. "
                "Cyclical and risk-sensitive assets should be reduced."
            ),
        )

    # Fallback
    return SellTrigger(
        category=SellTriggerCategory.RISK_MANAGEMENT,
        indicator="SIGNAL_DETERIORATION",
        description=(
            "General signal deterioration detected. Multiple indicators "
            "point to a deteriorating risk/reward profile."
        ),
    )


def _cross_verify_trigger(input_: QualifierInput, trigger: SellTrigger) -> List[CrossVerification]:
    """Cross-verify the sell trigger against complementary indicators.

    Returns a list of CrossVerification objects showing whether each
    complementary indicator confirms, contradicts, or is neutral to the trigger.
    """
    verifications: List[CrossVerification] = []

    # Always check VIX (if available) as a fear gauge cross-check
    if input_.vix_level is not None:
        if input_.vix_level > 25:
            verifications.append(CrossVerification(
                indicator="VIX_LEVEL",
                verdict="confirms",
                narrative=f"VIX at {input_.vix_level:.1f} confirms elevated fear.",
                weight=0.8,
            ))
        else:
            verifications.append(CrossVerification(
                indicator="VIX_LEVEL",
                verdict="neutral",
                narrative=f"VIX at {input_.vix_level:.1f} does not indicate panic.",
                weight=0.6,
            ))

    # Check yield curve
    if input_.yield_curve == "inverted":
        verifications.append(CrossVerification(
            indicator="YIELD_CURVE",
            verdict="confirms",
            narrative="Inverted yield curve reinforces recession/risk-off narrative.",
            weight=0.7,
        ))
    elif input_.yield_curve == "steepening":
        verifications.append(CrossVerification(
            indicator="YIELD_CURVE",
            verdict="contradicts",
            narrative="Steepening yield curve contradicts risk-off signal.",
            weight=0.5,
        ))

    # Check DXY
    if input_.dxy_trend == "strengthening":
        verifications.append(CrossVerification(
            indicator="DXY_TREND",
            verdict="confirms",
            narrative="Dollar strength aligns with risk-off regime shift.",
            weight=0.7,
        ))
    elif input_.dxy_trend == "weakening":
        verifications.append(CrossVerification(
            indicator="DXY_TREND",
            verdict="contradicts",
            narrative="Dollar weakness contradicts risk-off narrative.",
            weight=0.5,
        ))

    # Check market regime
    if input_.market_regime == "choppy":
        verifications.append(CrossVerification(
            indicator="MARKET_REGIME",
            verdict="neutral",
            narrative="Choppy regime adds noise but does not confirm directional bias.",
            weight=0.3,
        ))

    return verifications


def _compute_clearout(input_: QualifierInput, output_: QualifierOutput, verifications: List[CrossVerification]) -> float:
    """Compute the recommended clearout ratio (0.0–1.0).

    Base clearout depends on signal coherence:
      - coherence < 20 → 100% clearout (overwhelming signal)
      - coherence 20–40 → 75% clearout (strong signal)
      - coherence 40–60 → 50% clearout (moderate signal)
      - coherence > 60 → 25% clearout (weak signal, partial trim)

    Adjustments:
      - If most verifications confirm → +10%
      - If any verification contradicts → -15%
      - If NFP deviation > 3σ → +15% (extreme signal)
      - If VIX > 35 → +10% (panic accel)
    """
    coherence = output_.signal_coherence_score

    # Base clearout from signal strength
    if coherence < 20:
        base = 1.0    # 100% — overwhelming
    elif coherence < 40:
        base = 0.75   # 75% — strong
    elif coherence < 60:
        base = 0.50   # 50% — moderate
    else:
        base = 0.25   # 25% — partial trim

    # Adjustments
    confirms = sum(1 for v in verifications if v.verdict == "confirms")
    contradicts = sum(1 for v in verifications if v.verdict == "contradicts")
    total_checks = len(verifications) if verifications else 1

    if total_checks > 0 and confirms / total_checks > 0.5:
        base += 0.10

    if contradicts > 0:
        base -= 0.15

    if input_.nfp_deviation is not None and abs(input_.nfp_deviation) > 3.0:
        base += 0.15

    if input_.vix_level is not None and input_.vix_level > 35:
        base += 0.10

    return max(0.0, min(1.0, base))


def _compute_stop_loss(input_: QualifierInput, trigger: SellTrigger) -> Optional[float]:
    """Compute a protective stop-loss price suggestion.

    Physical isolation: returns a theoretical price suggestion, NOT actual
    position-adjusted values. In production, this would be combined with
    account state and position data.
    """
    # Placeholder: in real execution, this would read position cost basis
    # and macro volatility to compute a dynamic stop-loss.
    # For now, return None as a placeholder for future integration.
    return None


def _compute_limit_price(input_: QualifierInput, trigger: SellTrigger) -> Optional[float]:
    """Compute a suggested limit order price.

    Physical isolation: theoretical value only.
    """
    return None


# =========================================================================
# SellProtocol — the Track B sell entry point
# =========================================================================


class SellProtocol:
    """Track B: Sell/Liquidate Protocol.

    Generates a cross-verified SellAnalysis from a Qualifier judgment
    with action_subtrack=SELL. The analysis includes:
      - Primary trigger identification (with evidence)
      - Cross-verification against complementary indicators
      - Recommended clearout ratio
      - Protective stop-loss and limit price suggestions
    """

    def __init__(self) -> None:
        self._last_analysis: Optional[SellAnalysis] = None

    @property
    def last_analysis(self) -> Optional[SellAnalysis]:
        """Most recent SellAnalysis, if any."""
        return self._last_analysis

    def analyze(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
    ) -> SellAnalysis:
        """Produce a full SellAnalysis from Qualifier context.

        Args:
            qualifier_input: The original input fed to the Qualifier.
            qualifier_output: The Qualifier's judgment (must be ACTION + SELL).

        Returns:
            A fully populated SellAnalysis.

        Raises:
            ValueError: If not an ACTION+SELL judgment.
        """
        if qualifier_output.decision_track != DecisionTrack.ACTION_AND_ADJUST:
            raise ValueError(
                f"SellProtocol requires ACTION_AND_ADJUST, "
                f"got {qualifier_output.decision_track.value}"
            )
        if qualifier_output.action_subtrack != ActionSubtrack.SELL:
            raise ValueError(
                f"SellProtocol requires action_subtrack=SELL, "
                f"got {qualifier_output.action_subtrack}"
            )

        primary = _identify_primary_trigger(qualifier_input, qualifier_output)
        cross_checks = _cross_verify_trigger(qualifier_input, primary)
        clearout = _compute_clearout(qualifier_input, qualifier_output, cross_checks)
        stop_loss = _compute_stop_loss(qualifier_input, primary)
        limit_price = _compute_limit_price(qualifier_input, primary)

        # Determine overall verdict
        confirms = sum(1 for v in cross_checks if v.verdict == "confirms")
        contradicts = sum(1 for v in cross_checks if v.verdict == "contradicts")
        total = len(cross_checks)
        if total > 0 and contradicts >= confirms:
            verdict = "mixed"
        elif total > 0 and confirms == 0 and contradicts == 0:
            verdict = "neutral"
        elif contradicts > 0:
            verdict = "warning"
        else:
            verdict = "confirmed"

        # Build rationale
        parts = [
            f"Sell trigger: {primary.description}",
        ]
        if cross_checks:
            verdict_counts = {
                "confirms": confirms, "contradicts": contradicts,
                "neutral": total - confirms - contradicts,
            }
            parts.append(
                f"Cross-verification: {verdict_counts['confirms']} confirm, "
                f"{verdict_counts['contradicts']} contradict, "
                f"{verdict_counts['neutral']} neutral."
            )
        parts.append(f"Recommended clearout: {clearout * 100:.0f}%.")
        parts.append(f"Overall verdict: {verdict}.")

        analysis_id = f"sl_{qualifier_output.judgment_id[3:]}"

        self._last_analysis = SellAnalysis(
            analysis_id=analysis_id,
            judgment_id=qualifier_output.judgment_id,
            timestamp=qualifier_output.timestamp,
            primary_trigger=primary,
            cross_verifications=cross_checks,
            clearout_ratio=clearout,
            stop_loss_price=stop_loss,
            limit_price=limit_price,
            rationale=" ".join(parts),
            cross_check_verdict=verdict,
        )

        return self._last_analysis