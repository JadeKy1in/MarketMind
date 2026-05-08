"""
observe_wait.py — Phase 6 Track A: Strategic Observe & Wait Protocol.

When the Qualifier routes to OBSERVE_AND_WAIT, this module takes over to
produce a structured analysis:

  - Market Evolution Projection (市场演变推演): identify underlying currents
    that are not yet actionable but may become so.
  - Trigger Thresholds: concrete conditions (macro data, price levels) that
    would flip the decision to ACTION_AND_ADJUST.
  - Watchlist: specific assets/indicators to monitor.

This implements the "strategic patience" pattern — the system does not
simply idle; it actively monitors and pre-positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.qualitative_judgment import (
    DecisionTrack,
    ObserveScenario,
    QualifierInput,
    QualifierOutput,
)


# =========================================================================
# TriggerThreshold — a condition that would flip to ACTION
# =========================================================================


@dataclass
class TriggerThreshold:
    """A specific, measurable condition that would trigger an ACTION decision.

    Example thresholds:
      - "CPI MoM drops below 0.2% → activate long T-bonds"
      - "SPX breaks below 200d SMA → activate hedge"
      - "DXY strengthens past 105 → activate short EM FX"
    """

    indicator: str                           # e.g. "CPI_MoM", "SPX_vs_200SMA"
    direction: str                           # "above" | "below" | "crosses"
    value: float                             # the threshold value
    target_track: str                        # "BUY" | "SELL" | "REBALANCE"
    rationale: str                           # why this threshold matters
    priority: int = 1                        # 1 = highest, 3 = lowest


# =========================================================================
# UnderCurrent — an observable macro/narrative current beneath the surface
# =========================================================================


@dataclass
class UnderCurrent:
    """An underlying market current that is not yet the dominant narrative."""

    name: str                                # e.g. "Sticky Services Inflation"
    signal_type: str                         # "macro" | "narrative" | "technical"
    direction: str                           # "bullish" | "bearish" | "divergent"
    intensity: float                         # 0.0–1.0 how strong the current is
    description: str                         # plain-text summary
    related_indicators: List[str] = field(default_factory=list)


# =========================================================================
# ObserveReport — the structured output of Track A
# =========================================================================


@dataclass
class ObserveReport:
    """Structured output of the Observe & Wait analysis."""

    report_id: str
    judgment_id: str                         # links back to the Qualifier judgment
    timestamp: str
    scenario: ObserveScenario               # why we are observing
    scenario_detail: str                     # human-readable explanation
    underlying_currents: List[UnderCurrent] = field(default_factory=list)
    trigger_thresholds: List[TriggerThreshold] = field(default_factory=list)
    watchlist_tickers: List[str] = field(default_factory=list)
    narrative_extension: str = ""            # extended market evolution narrative
    confidence: float = 0.5                  # confidence in this analysis (0-1)
    protocol: str = "OBSERVE_WAIT"           # protocol identifier for ExecutionOutput


# =========================================================================
# Scenario templates — map ObserveScenario to human-readable detail
# =========================================================================

_SCENARIO_TEMPLATES: Dict[ObserveScenario, str] = {
    ObserveScenario.CONTRADICTION: (
        "Macro signals are sending mixed messages. Cross-source agreement is "
        "low, suggesting the market has not yet found a dominant narrative. "
        "Wait for alignment before committing capital."
    ),
    ObserveScenario.POOR_RSK_REWARD: (
        "Signal coherence is adequate, but the reward/risk profile is "
        "unfavorable. The potential upside does not justify the downside risk "
        "at current prices. Wait for a better entry or catalyst."
    ),
    ObserveScenario.CHOPPY_REGIME: (
        "Price action is range-bound with no clear directional bias. "
        "Trend-following strategies are ineffective in this regime. "
        "Wait for a breakout or a volatility expansion."
    ),
    ObserveScenario.DATA_DROUGHT: (
        "Insufficient catalyst data to form a high-conviction view. "
        "Key economic releases are pending. Monitor the calendar for "
        "upcoming data points that could tip the scales."
    ),
    ObserveScenario.VALUATION_EXTREME: (
        "Valuations are at extreme levels, suggesting elevated risk of "
        "mean reversion. Even if the macro direction is clear, the entry "
        "price carries significant mean-reversion risk."
    ),
}


def _get_scenario_detail(scenario: ObserveScenario) -> str:
    """Return human-readable template for a given ObserveScenario."""
    return _SCENARIO_TEMPLATES.get(scenario, "Observing until signals clarify.")


# =========================================================================
# Track A — generation of trigger thresholds and undercurrents
# =========================================================================


def _generate_trigger_thresholds(
    input_: QualifierInput, scenario: ObserveScenario
) -> List[TriggerThreshold]:
    """Generate actionable trigger thresholds from macro context.

    Maps specific macro conditions to future action triggers.
    Each trigger has a concrete indicator, direction, and value.
    """
    thresholds: List[TriggerThreshold] = []

    # NFP-related thresholds
    if input_.nfp_deviation is not None and abs(input_.nfp_deviation) > 1.5:
        thresholds.append(TriggerThreshold(
            indicator="NFP_DEVIATION",
            direction="below",
            value=1.0,
            target_track="BUY",
            rationale="NFP surprise fading → narrative re-anchoring risk subsides",
            priority=1,
        ))

    # DXY-related thresholds
    if input_.dxy_trend == "strengthening":
        thresholds.append(TriggerThreshold(
            indicator="DXY_LEVEL",
            direction="below",
            value=103.0,
            target_track="BUY",
            rationale="DXY weakness resumes → risk-on alignment returns",
            priority=2,
        ))
    elif input_.dxy_trend == "weakening":
        thresholds.append(TriggerThreshold(
            indicator="DXY_LEVEL",
            direction="above",
            value=105.5,
            target_track="SELL",
            rationale="DXY strength breaks trend → risk-off regime shift",
            priority=2,
        ))

    # VIX-related thresholds
    if input_.vix_level is not None:
        if input_.vix_level > 28:
            thresholds.append(TriggerThreshold(
                indicator="VIX_LEVEL",
                direction="below",
                value=20.0,
                target_track="BUY",
                rationale="Panic subsiding → safe to re-enter risk assets",
                priority=1,
            ))
        elif input_.vix_level < 15:
            thresholds.append(TriggerThreshold(
                indicator="VIX_LEVEL",
                direction="above",
                value=22.0,
                target_track="SELL",
                rationale="Complacency breaking → hedge/protect downside",
                priority=2,
            ))

    # Yield curve thresholds
    if input_.yield_curve == "inverted":
        thresholds.append(TriggerThreshold(
            indicator="YIELD_CURVE_2Y10Y",
            direction="above",
            value=0.0,
            target_track="BUY",
            rationale="Curve normalization → recession priced out, reflation trade",
            priority=1,
        ))
    elif input_.yield_curve == "steepening":
        thresholds.append(TriggerThreshold(
            indicator="YIELD_CURVE_2Y10Y",
            direction="below",
            value=-0.25,
            target_track="SELL",
            rationale="Curve re-inverting → recession fears resurface",
            priority=2,
        ))

    # Market regime-specific thresholds
    if input_.market_regime == "choppy":
        thresholds.append(TriggerThreshold(
            indicator="SPX_BOLLINGER_WIDTH",
            direction="above",
            value=1.5,
            target_track="BUY",
            rationale="Volatility expansion → trend emerging from chop",
            priority=1,
        ))

    return thresholds


def _generate_undercurrents(input_: QualifierInput) -> List[UnderCurrent]:
    """Identify underlying currents beneath the dominant narrative."""
    currents: List[UnderCurrent] = []

    # DXY trend as a current
    if input_.dxy_trend == "weakening":
        currents.append(UnderCurrent(
            name="Dollar Weakening Cycle",
            signal_type="macro",
            direction="bullish",
            intensity=0.7,
            description=(
                "USD weakness is a multi-session trend that supports "
                "commodities, EM equities, and USD-denominated assets."
            ),
            related_indicators=["DXY", "UUP", "FXE"],
        ))
    elif input_.dxy_trend == "strengthening":
        currents.append(UnderCurrent(
            name="Dollar Strengthening Cycle",
            signal_type="macro",
            direction="bearish",
            intensity=0.7,
            description=(
                "USD strength pressures EM currencies and commodity "
                "prices. Risk-off bias likely to persist."
            ),
            related_indicators=["DXY", "UUP"],
        ))

    # VIX regime as a current
    if input_.vix_level is not None:
        if input_.vix_level > 25:
            currents.append(UnderCurrent(
                name="Elevated Volatility Regime",
                signal_type="technical",
                direction="bearish",
                intensity=min(1.0, input_.vix_level / 40.0),
                description="VIX above 25 signals elevated uncertainty.",
                related_indicators=["VIX", "VVIX"],
            ))

    # Yield curve current
    if input_.yield_curve == "inverted":
        currents.append(UnderCurrent(
            name="Inverted Yield Curve (Recession Signal)",
            signal_type="macro",
            direction="bearish",
            intensity=0.8,
            description=(
                "An inverted 2Y-10Y yield curve has historically preceded "
                "recessions. Credit conditions are tightening."
            ),
            related_indicators=["TNX", "UST10Y", "UST2Y"],
        ))
    elif input_.yield_curve == "steepening":
        currents.append(UnderCurrent(
            name="Yield Curve Steepening (Recovery Signal)",
            signal_type="macro",
            direction="bullish",
            intensity=0.6,
            description=(
                "A steepening yield curve suggests the market is pricing "
                "in future growth. Reflation trades may benefit."
            ),
            related_indicators=["TNX", "UST10Y", "UST2Y"],
        ))

    # CPI/MoM as a current
    if input_.cpi_mom is not None:
        if input_.cpi_mom > 0.4:
            currents.append(UnderCurrent(
                name="Sticky Inflation Pressure",
                signal_type="macro",
                direction="bearish",
                intensity=min(1.0, (input_.cpi_mom - 0.2) / 0.5),
                description="Elevated MoM CPI suggests inflation is not yet tamed.",
                related_indicators=["CPI", "PCE", "T5YIE"],
            ))

    return currents


def _generate_watchlist(input_: QualifierInput) -> List[str]:
    """Suggest tickers to watch based on macro context."""
    tickers: List[str] = []

    if input_.dxy_trend == "weakening":
        tickers.extend(["GLD", "SLV", "DBC", "FXE"])
    elif input_.dxy_trend == "strengthening":
        tickers.extend(["UUP", "SHY", "TLT"])

    if input_.yield_curve == "inverted":
        tickers.extend(["TLT", "IEF", "HYG"])
    elif input_.yield_curve == "steepening":
        tickers.extend(["KRE", "XLB", "EEM"])

    if input_.vix_level is not None and input_.vix_level > 25:
        tickers.extend(["SHY", "BIL", "GLD"])

    if input_.market_regime == "choppy":
        tickers.extend(["TLT", "GLD", "DBA"])

    return list(set(tickers))  # deduplicate


# =========================================================================
# ObserveWait — the Track A entry point
# =========================================================================


class ObserveWait:
    """Track A: Strategic Observe & Wait Protocol.

    Generates a structured ObserveReport from a Qualifier judgment that
    was routed to OBSERVE_AND_WAIT. The report includes:
      - Why we are observing (scenario detail)
      - Underlying currents beneath the surface
      - Trigger thresholds that would flip to ACTION
      - A watchlist of tickers to monitor
    """

    protocol: str = "OBSERVE_WAIT"

    def __init__(self) -> None:
        self._last_report: Optional[ObserveReport] = None

    @property
    def last_report(self) -> Optional[ObserveReport]:
        """Most recent ObserveReport, if any."""
        return self._last_report

    def analyze(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
    ) -> ObserveReport:
        """Produce a full ObserveReport from Qualifier context.

        Args:
            qualifier_input: The original input fed to the Qualifier.
            qualifier_output: The Qualifier's judgment (must be OBSERVE).

        Returns:
            A fully populated ObserveReport.

        Raises:
            ValueError: If qualifier_output is not OBSERVE_AND_WAIT.
        """
        if qualifier_output.decision_track != DecisionTrack.OBSERVE_AND_WAIT:
            raise ValueError(
                f"ObserveWait can only process OBSERVE judgments, "
                f"got {qualifier_output.decision_track.value}"
            )

        scenario = qualifier_output.observe_scenario or ObserveScenario.CONTRADICTION
        scenario_detail = _get_scenario_detail(scenario)

        undercurrents = _generate_undercurrents(qualifier_input)
        trigger_thresholds = _generate_trigger_thresholds(qualifier_input, scenario)
        watchlist = _generate_watchlist(qualifier_input)

        # Build narrative extension
        extension_parts = [scenario_detail]
        if undercurrents:
            uc_names = ", ".join(uc.name for uc in undercurrents[:3])
            extension_parts.append(
                f"Underlying currents to monitor: {uc_names}."
            )
        if trigger_thresholds:
            tx_names = ", ".join(
                f"{t.indicator} {t.direction} {t.value}"
                for t in trigger_thresholds[:3]
            )
            extension_parts.append(
                f"Key triggers: {tx_names}."
            )
        if watchlist:
            extension_parts.append(
                f"Watchlist: {', '.join(watchlist[:5])}."
            )

        report_id = f"ow_{qualifier_output.judgment_id[3:]}"

        self._last_report = ObserveReport(
            report_id=report_id,
            judgment_id=qualifier_output.judgment_id,
            timestamp=qualifier_output.timestamp,
            scenario=scenario,
            scenario_detail=scenario_detail,
            underlying_currents=undercurrents,
            trigger_thresholds=trigger_thresholds,
            watchlist_tickers=watchlist,
            narrative_extension=" ".join(extension_parts),
            confidence=qualifier_output.track_confidence,
        )

        return self._last_report


# =========================================================================
# Backward-compatible aliases for Phase 5 / Phase 6 integration
# =========================================================================
# order_builder.py and tests use ObserveAnalysis, ObserveWaitProtocol,
# and MarketDriftAnalysis from this module. These aliases maintain
# compatibility without breaking the internal naming convention.

ObserveAnalysis = ObserveReport
ObserveWaitProtocol = ObserveWait
MarketDriftAnalysis = UnderCurrent
