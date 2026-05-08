"""Phase 7.2 — Mosaic Reasoning Protocol.

Transforms fragmented alternative data signals into enhanced macro narratives
with cross-domain linkage, reverse timeline reasoning, consensus fragility
assessment, and physical verification locks.

SPARC:
  Specification: pipeline-based engine that ingests AlternativeSignalMatrix,
                 produces MosaicNarrative with >=3 PhysicalVerificationIndicators.
  Pseudocode: each engine is a pure function → orchestrator composes them.
  Architecture: five engine modules + one orchestrator.
  Refinement: all invariants enforced via __post_init__ on dataclasses.
  Completion: full test coverage on all paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.alternative_data_hooks import (
    AlternativeSignal,
    AlternativeSignalMatrix,
    DegradationLevel,
    SignalDirection,
    SignalLayer,
)


# ============================================================
# Data Structures
# ============================================================


@dataclass
class PhysicalVerificationIndicator:
    """A physical (real-world, hard-to-manipulate) indicator that
    must be observed at a specific threshold to validate a narrative.

    The blueprint mandates at least 3 PVIs per MosaicNarrative.
    """

    pvi_id: str
    indicator_name: str
    description: str
    current_value: float
    target_threshold: float
    target_direction: str  # "above", "below", or "between"
    verification_deadline: str
    linked_logic_chain: str
    consequence_if_failed: str
    data_source: str
    manipulation_risk: str

    def __post_init__(self) -> None:
        if not self.pvi_id:
            raise ValueError("pvi_id must not be empty")
        if not self.indicator_name:
            raise ValueError("indicator_name must not be empty")
        valid_dirs = ("above", "below", "between")
        if self.target_direction not in valid_dirs:
            raise ValueError(
                f"target_direction must be one of {valid_dirs}; got {self.target_direction!r}"
            )
        # Sanity check: both values negative with "above" direction where
        # threshold is already met is unrealistic (nonsensical threshold range).
        if self.target_direction == "above" and self.current_value >= self.target_threshold:
            if self.target_threshold < 0:
                raise ValueError(
                    f"threshold {self.target_threshold} vs current {self.current_value} "
                    "seems unrealistic"
                )
        if self.target_direction == "below" and self.current_value <= self.target_threshold:
            if self.target_threshold < 0:
                raise ValueError(
                    f"threshold {self.target_threshold} vs current {self.current_value} "
                    "seems unrealistic"
                )

    def is_verified(self, observed_value: float) -> bool:
        """Check if an observed value satisfies the verification condition."""
        if self.target_direction == "above":
            return observed_value >= self.target_threshold
        elif self.target_direction == "below":
            return observed_value <= self.target_threshold
        elif self.target_direction == "between":
            # "between" treated as exact match (must hit target precisely)
            return observed_value == self.target_threshold
        else:
            raise ValueError(f"Unknown target_direction: {self.target_direction}")

    def verification_status(self, observed_value: Optional[float]) -> str:
        """Return 'PENDING', 'VERIFIED', or 'FAILED' based on optional observed value."""
        if observed_value is None:
            return "PENDING"
        if self.is_verified(observed_value):
            return "VERIFIED"
        return "FAILED"


@dataclass
class CrossDomainLink:
    """A forced cross-domain causal link between two anomalous signals."""

    link_id: str
    source_a: str
    source_b: str
    intermediate_variable: str
    causal_description: str
    weakest_assumption: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.link_id:
            raise ValueError("link_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {self.confidence}"
            )


@dataclass
class ReverseTimelineStep:
    """One step in a reverse timeline that reconstructs the path
    from an observed outcome back to its causal origins."""

    step_label: str
    days_offset: int
    actor_description: str
    action_description: str
    motivation: str
    observable_trace: str


@dataclass
class MosaicNarrative:
    """The final enhanced macro narrative output by the Mosaic Reasoner.

    Must contain at least 3 PhysicalVerificationIndicators (blueprint mandate).
    """

    narrative_id: str
    generated_at: str
    macro_theme: str
    confidence: float
    consensus_fragility: float = 50.0
    anomaly_signals_used: List[str] = field(default_factory=list)
    trigger_layers: List[str] = field(default_factory=list)
    cross_domain_links: List[CrossDomainLink] = field(default_factory=list)
    reverse_timeline: List[ReverseTimelineStep] = field(default_factory=list)
    physical_verifications: List[PhysicalVerificationIndicator] = field(
        default_factory=list
    )
    counter_narrative: str = ""
    why_counter_is_weaker: str = ""
    source_matrix_id: str = ""

    def __post_init__(self) -> None:
        if not self.narrative_id:
            raise ValueError("narrative_id must not be empty")
        if not self.generated_at:
            raise ValueError("generated_at must not be empty")
        if not self.macro_theme:
            raise ValueError("macro_theme must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {self.confidence}"
            )
        if not 0.0 <= self.consensus_fragility <= 100.0:
            raise ValueError(
                f"consensus_fragility must be in [0.0, 100.0]; "
                f"got {self.consensus_fragility}"
            )
        if len(self.physical_verifications) < 3:
            raise ValueError(
                f"MosaicNarrative requires at least 3 PhysicalVerificationIndicators; "
                f"got {len(self.physical_verifications)}"
            )

    # --- Auto-derived count properties ---

    @property
    def anomaly_signal_count(self) -> int:
        return len(self.anomaly_signals_used)

    @property
    def cross_domain_link_count(self) -> int:
        return len(self.cross_domain_links)

    @property
    def reverse_timeline_count(self) -> int:
        return len(self.reverse_timeline)

    @property
    def pvi_count(self) -> int:
        return len(self.physical_verifications)

    def has_physical_verification_passed(self) -> bool:
        """Check ALL PVIs — if any FAILED, the narrative is invalidated."""
        for pvi in self.physical_verifications:
            # We check via is_verified with current_value as a naive observed check
            # For true runtime, use observed real-world values.
            # In test mode, PVIs without observed values default to PENDING → safe.
            if not pvi.is_verified(pvi.current_value):
                return False
        return True


# ============================================================
# Engine 1 — Anomaly-First Discovery
# ============================================================


def discover_anomalies(
    matrix: AlternativeSignalMatrix,
    z_threshold: float = 1.5,
) -> List[AlternativeSignal]:
    """Extract signals where |z_score| >= z_threshold OR is_absence_signal."""
    anomalies = []
    for sig in matrix.all_signals():
        if sig.is_absence_signal or abs(sig.z_score) >= z_threshold:
            anomalies.append(sig)

    # Sort by absolute z_score descending (strongest anomaly first).
    # Absence signals may have z_score=None so we use a sentinel (-1) to push them last.
    anomalies.sort(key=lambda s: abs(s.z_score) if s.z_score is not None else -1, reverse=True)
    return anomalies


def classify_trigger_layers(
    anomalies: List[AlternativeSignal],
) -> List[str]:
    """Return unique layer names from anomalous signals, preserving discovery order."""
    seen: List[str] = []
    for sig in anomalies:
        layer_name = sig.layer.value if hasattr(sig.layer, "value") else str(sig.layer)
        if layer_name not in seen:
            seen.append(layer_name)
    return seen


def estimate_anomaly_confidence(
    anomalies: List[AlternativeSignal],
) -> float:
    """Estimate overall confidence from anomaly diversity and signal confidence.

    Formula: (unique_layers / 6) * 0.8 + avg(signal_confidence) * 0.2
    Capped at 1.0.
    """
    if not anomalies:
        return 0.0

    unique_layers = len(set(
        sig.layer.value if hasattr(sig.layer, "value") else str(sig.layer)
        for sig in anomalies
    ))
    layer_ratio = min(unique_layers / 6.0, 1.0)
    confidences = [
        c for sig in anomalies
        if (c := sig.confidence) is not None
    ]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.5
    raw = layer_ratio * 0.8 + avg_conf * 0.2
    return min(raw, 1.0)


# ============================================================
# Engine 2 — Forced Cross-Domain Mapping
# ============================================================


# Lookup table: for layer pairs that don't share an intermediate variable,
# fallback to a generic divergent connector.
# Intermediate variables represent real-world propagation channels.
_LAYER_PAIR_INTERMEDIATE: Dict[Tuple[str, str], str] = {
    ("L1_PUBLIC_NEGLECTED", "L2_SEMI_PUBLIC"): "CapitalFlowThrough",
    ("L2_SEMI_PUBLIC", "L1_PUBLIC_NEGLECTED"): "CapitalFlowThrough",
    ("L1_PUBLIC_NEGLECTED", "L3_MICROSTRUCTURE"): "MarketDepthLiquidityShift",
    ("L3_MICROSTRUCTURE", "L1_PUBLIC_NEGLECTED"): "MarketDepthLiquidityShift",
    ("L1_PUBLIC_NEGLECTED", "L4_GEO_PHYSICAL"): "SupplyChainDisruption",
    ("L4_GEO_PHYSICAL", "L1_PUBLIC_NEGLECTED"): "SupplyChainDisruption",
    ("L1_PUBLIC_NEGLECTED", "L5_REFLEXIVE_META"): "SentimentPriceFeedback",
    ("L5_REFLEXIVE_META", "L1_PUBLIC_NEGLECTED"): "SentimentPriceFeedback",
    ("L2_SEMI_PUBLIC", "L3_MICROSTRUCTURE"): "InstitutionalOrderFlow",
    ("L3_MICROSTRUCTURE", "L2_SEMI_PUBLIC"): "InstitutionalOrderFlow",
    ("L2_SEMI_PUBLIC", "L4_GEO_PHYSICAL"): "CommodityInputCost",
    ("L4_GEO_PHYSICAL", "L2_SEMI_PUBLIC"): "CommodityInputCost",
    ("L2_SEMI_PUBLIC", "L5_REFLEXIVE_META"): "EarningsExpectationCycle",
    ("L5_REFLEXIVE_META", "L2_SEMI_PUBLIC"): "EarningsExpectationCycle",
    ("L3_MICROSTRUCTURE", "L4_GEO_PHYSICAL"): "HedgingPressureTransmission",
    ("L4_GEO_PHYSICAL", "L3_MICROSTRUCTURE"): "HedgingPressureTransmission",
    ("L3_MICROSTRUCTURE", "L5_REFLEXIVE_META"): "VolatilityRiskPremium",
    ("L5_REFLEXIVE_META", "L3_MICROSTRUCTURE"): "VolatilityRiskPremium",
    ("L4_GEO_PHYSICAL", "L5_REFLEXIVE_META"): "ClimatePolicyUncertainty",
    ("L5_REFLEXIVE_META", "L4_GEO_PHYSICAL"): "ClimatePolicyUncertainty",
}

_DIVERGENT_INTERMEDIATE = "InterLayerDisconnect"


def _layer_name(sig: AlternativeSignal) -> str:
    return sig.layer.name if hasattr(sig.layer, "name") else str(sig.layer)


def map_cross_domain_links(
    anomalies: List[AlternativeSignal],
) -> List[CrossDomainLink]:
    """Force cross-domain links between anomalous signals from different layers.

    Requires at least 2 anomalies from distinct layers.
    Same-layer signals are NOT linked (boring).
    """
    if len(anomalies) < 2:
        return []

    # Group by layer
    by_layer: Dict[str, List[AlternativeSignal]] = {}
    for sig in anomalies:
        layer = _layer_name(sig)
        by_layer.setdefault(layer, []).append(sig)

    layers = list(by_layer.keys())
    if len(layers) < 2:
        return []

    links: List[CrossDomainLink] = []
    link_idx = 0

    # All cross-layer pairs
    for i in range(len(layers)):
        for j in range(i + 1, len(layers)):
            layer_a = layers[i]
            layer_b = layers[j]
            sig_a = by_layer[layer_a][0]
            sig_b = by_layer[layer_b][0]

            # Determine intermediate variable
            pair_key = (layer_a, layer_b)
            if pair_key in _LAYER_PAIR_INTERMEDIATE:
                intermediate = _LAYER_PAIR_INTERMEDIATE[pair_key]
            else:
                intermediate = _DIVERGENT_INTERMEDIATE

            # If directions diverge, use divergent fallback
            if sig_a.direction != sig_b.direction:
                intermediate = _DIVERGENT_INTERMEDIATE

            # Confidence: distance-weighted cross-layer conviction
            z_a = abs(sig_a.z_score) if sig_a.z_score is not None else 0.0
            z_b = abs(sig_b.z_score) if sig_b.z_score is not None else 0.0
            z_combined = (z_a + z_b) / 4.0
            conf = min(z_combined / 3.0, 1.0)

            link_idx += 1
            links.append(CrossDomainLink(
                link_id=f"cdl_{link_idx:03d}",
                source_a=sig_a.signal_id,
                source_b=sig_b.signal_id,
                intermediate_variable=intermediate,
                causal_description=(
                    f"Anomalous signal {sig_a.signal_id} ({_layer_name(sig_a)}) "
                    f"transmits through {intermediate} to "
                    f"{sig_b.signal_id} ({_layer_name(sig_b)})"
                ),
                weakest_assumption=f"{intermediate} accurately mediates this relationship",
                confidence=round(conf, 4),
            ))

    return links


# ============================================================
# Engine 3 — Reverse Timeline Reasoning
# ============================================================


def build_reverse_timeline(
    anomalies: List[AlternativeSignal],
    dominant_direction: SignalDirection,
    macro_theme_hint: str = "",
) -> List[ReverseTimelineStep]:
    """Reconstruct a 4-step reverse timeline from T-0 back to T-90.

    Each step describes actors, actions, motivations, and observable traces.
    """
    if not anomalies:
        # Default fallback timeline
        return _default_timeline(dominant_direction, macro_theme_hint)

    # Determine direction verb
    is_bullish = dominant_direction == SignalDirection.BULLISH
    direction_label = "Accumulation / price-up" if is_bullish else "Distribution / price-down"

    # Summarize key layers for narrative
    layers = classify_trigger_layers(anomalies)
    layers_str = ", ".join(layers[:3]) if layers else "unknown"
    theme = macro_theme_hint or "regime shift"

    return [
        ReverseTimelineStep(
            step_label="T-0",
            days_offset=0,
            actor_description="Market participants (retail + HFT)",
            action_description=(
                f"React to converging anomalous signals in {layers_str}: "
                f"{direction_label} pattern triggers positioning shift"
            ),
            motivation="Late-stage realization of macro regime change",
            observable_trace="Volume spikes, bid-ask widening, cross-asset correlation breakdown",
        ),
        ReverseTimelineStep(
            step_label="T-30",
            days_offset=30,
            actor_description=f"Institutional investors aligned with {theme}",
            action_description=(
                f"Begin portfolio tilting toward {theme} exposure; "
                "hedge fund rotational flows intensify"
            ),
            motivation="Early alpha capture and risk rebalancing",
            observable_trace="13F filing lag reveals positioning; options OI builds",
        ),
        ReverseTimelineStep(
            step_label="T-60",
            days_offset=60,
            actor_description="Sell-side analysts and macro commentators",
            action_description=(
                f"Publish upgraded forecasts aligning with {theme} narrative; "
                "consensus gradually shifts"
            ),
            motivation="Client demand for narrative justification; franchise positioning",
            observable_trace="Research note volume increase; earnings call transcript mentions",
        ),
        ReverseTimelineStep(
            step_label="T-90",
            days_offset=90,
            actor_description="Early-pivot players (smart money, insiders)",
            action_description=(
                f"Deploy initial capital into {theme} before mainstream "
                "recognition; accumulate at advantageous prices"
            ),
            motivation="Proprietary macro model triggers entry signal",
            observable_trace="Dark pool block trades; insider filing cluster; OTC flow",
        ),
    ]


def _default_timeline(
    dominant_direction: SignalDirection,
    macro_theme_hint: str = "",
) -> List[ReverseTimelineStep]:
    """Fallback timeline when no anomalies are available."""
    is_bullish = dominant_direction == SignalDirection.BULLISH
    direction_verb = "expand" if is_bullish else "contract"
    theme = macro_theme_hint or "transition"

    return [
        ReverseTimelineStep(
            step_label="T-0", days_offset=0,
            actor_description="Marginal price setter",
            action_description="Execute final positioning adjustment",
            motivation="Price discovery completion",
            observable_trace="Closing auction imbalance",
        ),
        ReverseTimelineStep(
            step_label="T-30", days_offset=30,
            actor_description="Portfolio managers",
            action_description=f"Rotate factor exposure to {direction_verb} in {theme}",
            motivation="Performance chasing / risk reduction",
            observable_trace="Factor ETF flow",
        ),
        ReverseTimelineStep(
            step_label="T-60", days_offset=60,
            actor_description="Research desks",
            action_description=f"Publish thematic pieces on {theme}",
            motivation="Client demand for actionable narrative",
            observable_trace="Institutional research access",
        ),
        ReverseTimelineStep(
            step_label="T-90", days_offset=90,
            actor_description="Early adopters",
            action_description=f"Build initial {theme} positions",
            motivation="Proprietary signal triggers entry",
            observable_trace="Whale wallet / insider cluster",
        ),
    ]


# ============================================================
# Engine 4 — Consensus Fragility
# ============================================================


def compute_consensus_fragility(
    matrix: AlternativeSignalMatrix,
    anomalies: List[AlternativeSignal],
    num_trigger_layers: int,
) -> Tuple[float, List[str]]:
    """Compute consensus fragility score (0 = very stable, 100 = fragile).

    Drivers:
      - Baseline 50
      - +12 per divergence warning
      - +10 per missing convergence layer (below ideal 3)
      - + (degraded_ratio * 20)
      - + crowding penalty: max(0, (crowding_ratio - 0.7) * 50)
    """
    drivers: List[str] = []

    if not anomalies:
        return 100.0, ["No anomalous signals — consensus is maximally fragile (vacuum)"]

    # Baseline
    score = 50.0
    drivers.append("Baseline 50")

    # Divergence penalty
    divergence_count = len(matrix.divergence_warnings)
    if divergence_count > 0:
        penalty = divergence_count * 12.0
        score += penalty
        drivers.append(
            f"{divergence_count} divergence warning(s): +{penalty:.0f}"
        )

    # Convergence deficit (ideal = 3+ layers)
    deficit = max(0, 3 - num_trigger_layers)
    if deficit > 0:
        penalty = deficit * 10.0
        score += penalty
        drivers.append(f"Convergence deficit ({num_trigger_layers} < 3): +{penalty:.0f}")

    # Degradation penalty
    total_signals = len(matrix.all_signals()) or 1
    degraded_signals = matrix.degradation_count
    degraded_ratio = degraded_signals / total_signals
    if degraded_ratio > 0:
        penalty = degraded_ratio * 20.0
        score += penalty
        drivers.append(
            f"Signal degradation ({degraded_signals}/{total_signals}): +{penalty:.1f}"
        )

    # Crowding penalty — if too many anomalies are all in same direction
    if len(anomalies) >= 3:
        bullish_count = sum(
            1 for s in anomalies if s.direction == SignalDirection.BULLISH
        )
        bearish_count = sum(
            1 for s in anomalies if s.direction == SignalDirection.BEARISH
        )
        max_same = max(bullish_count, bearish_count)
        crowding_ratio = max_same / len(anomalies)
        if crowding_ratio > 0.7:
            penalty = (crowding_ratio - 0.7) * 50.0
            score += penalty
            drivers.append(
                f"Signal crowding ({max_same}/{len(anomalies)} same direction): +{penalty:.1f}"
            )

    return min(score, 100.0), drivers


# ============================================================
# Engine 5 — Physical Verification Lock Generator
# ============================================================


def generate_physical_verifications(
    anomalies: List[AlternativeSignal],
    dominant_direction: SignalDirection,
    macro_theme: str = "",
) -> List[PhysicalVerificationIndicator]:
    """Generate at least 3 PhysicalVerificationIndicators for the narrative.

    Blueprint mandate: each narrative MUST have >=3 PVIs.
    """
    is_bullish = dominant_direction == SignalDirection.BULLISH
    has_microstructure = any(
        _layer_name(s) == "L3_MICROSTRUCTURE" for s in anomalies
    )
    has_geo = any(
        _layer_name(s) == "L4_GEO_PHYSICAL" for s in anomalies
    )

    now = datetime.now(timezone.utc)

    pvis: List[PhysicalVerificationIndicator] = []

    # --- PVI 1: Yield / Rates ---
    # Bullish = above threshold (yields rise → growth narrative)
    # Bearish = below threshold (yields falter → recession)
    yield_direction = "above" if is_bullish else "below"
    yield_threshold = 5.0 if is_bullish else 3.5
    pvis.append(PhysicalVerificationIndicator(
        pvi_id="pvi_yield_01",
        indicator_name="us10y_yield",
        description=(
            f"10Y UST yield must go {yield_direction} {yield_threshold}% "
            f"to validate {macro_theme or 'macro'} narrative"
        ),
        current_value=4.35,
        target_threshold=yield_threshold,
        target_direction=yield_direction,
        verification_deadline=(now + timedelta(days=30)).isoformat(),
        linked_logic_chain=(
            f"Anomalous signals → {macro_theme or 'regime shift'} → "
            f"risk premium repricing → yield move"
        ),
        consequence_if_failed="Narrative invalidated: bond market rejecting growth thesis",
        data_source="UST yield curve (Federal Reserve H.15)",
        manipulation_risk="low",
    ))

    # --- PVI 2: VIX / Volatility ---
    vix_direction = "above" if has_microstructure else "below"
    vix_threshold = 22.0 if has_microstructure else 15.0
    pvis.append(PhysicalVerificationIndicator(
        pvi_id="pvi_vix_01",
        indicator_name="vix",
        description=(
            f"VIX must go {vix_direction} {vix_threshold} to confirm "
            f"volatility regime embedded in microstructure signals"
        ),
        current_value=15.5,
        target_threshold=vix_threshold,
        target_direction=vix_direction,
        verification_deadline=(now + timedelta(days=14)).isoformat(),
        linked_logic_chain=(
            "Microstructure anomalies → options dealer hedging → VIX level adjustment"
        ),
        consequence_if_failed="Volatility narrative unsupported by market pricing of risk",
        data_source="CBOE VIX Index",
        manipulation_risk="medium",
    ))

    # --- PVI 3: Geo / Physical ---
    if has_geo:
        geo_direction = "above" if is_bullish else "below"
        pvis.append(PhysicalVerificationIndicator(
            pvi_id="pvi_geo_01",
            indicator_name="commodity_index",
            description=(
                f"Broad commodity index must go {geo_direction} to align "
                f"with geo-physical supply constraints"
            ),
            current_value=285.0,
            target_threshold=310.0,
            target_direction=geo_direction,
            verification_deadline=(now + timedelta(days=45)).isoformat(),
            linked_logic_chain=(
                "Geo-physical anomalies → supply chain → commodity price transmission"
            ),
            consequence_if_failed="Physical supply constraint thesis lacks price confirmation",
            data_source="BBG BCOM Index",
            manipulation_risk="medium",
        ))
    else:
        # Fallback: credit spread
        spread_dir = "below" if is_bullish else "above"
        pvis.append(PhysicalVerificationIndicator(
            pvi_id="pvi_credit_01",
            indicator_name="ig_credit_spread",
            description=(
                f"IG credit spread must go {spread_dir} to validate "
                f"risk appetite regime"
            ),
            current_value=115.0,
            target_threshold=100.0 if is_bullish else 140.0,
            target_direction=spread_dir,
            verification_deadline=(now + timedelta(days=21)).isoformat(),
            linked_logic_chain=(
                "Anomaly detection → risk sentiment → credit market pricing"
            ),
            consequence_if_failed="Credit market not confirming risk-on/off regime",
            data_source="CDX.IG Index",
            manipulation_risk="low",
        ))

    # --- PVI 4: Dollar / FX (4th indicator for robustness) ---
    fx_dir = "above" if is_bullish else "below"
    pvis.append(PhysicalVerificationIndicator(
        pvi_id="pvi_dxy_01",
        indicator_name="dxy",
        description=(
            f"DXY must go {fx_dir} to validate capital flow assumptions "
            f"in {macro_theme or 'macro'} narrative"
        ),
        current_value=104.0,
        target_threshold=102.0 if is_bullish else 106.0,
        target_direction=fx_dir,
        verification_deadline=(now + timedelta(days=21)).isoformat(),
        linked_logic_chain=(
            "Cross-domain anomaly mapping → capital flow intermediate → FX adjustment"
        ),
        consequence_if_failed="FX flow not supporting directional macro thesis",
        data_source="DXY Index (ICE)",
        manipulation_risk="low",
    ))

    return pvis


# ============================================================
# Orchestrator — build_macro_narrative
# ============================================================


def _determine_dominant_direction(
    anomalies: List[AlternativeSignal],
) -> SignalDirection:
    """Determine the dominant signal direction from anomalies.

    Returns BULLISH or BEARISH based on weighted z-score sum.
    """
    if not anomalies:
        return SignalDirection.BEARISH

    weighted_sum = sum(
        (abs(sig.z_score) if sig.z_score is not None else 0.0)
        * (1.0 if sig.direction == SignalDirection.BULLISH else -1.0)
        for sig in anomalies
        if sig.direction in (SignalDirection.BULLISH, SignalDirection.BEARISH)
    )

    if weighted_sum > 0.5:
        return SignalDirection.BULLISH
    return SignalDirection.BEARISH


def build_macro_narrative(
    matrix: AlternativeSignalMatrix,
    macro_theme: str = "",
) -> MosaicNarrative:
    """Orchestrator: run all five engines over an AlternativeSignalMatrix
    and produce a fully-populated MosaicNarrative.

    This is the main entry point for Phase 7.2.
    """
    # Reject empty matrix
    if not matrix.all_signals():
        raise ValueError("Cannot build narrative from empty signal matrix")

    # --- Engine 1: Anomaly-First Discovery ---
    anomalies = discover_anomalies(matrix)
    trigger_layers = classify_trigger_layers(anomalies)
    anomaly_confidence = estimate_anomaly_confidence(anomalies)
    dominant_dir = _determine_dominant_direction(anomalies) if anomalies else SignalDirection.BEARISH

    anomaly_signal_ids = [s.signal_id for s in anomalies]

    # --- Engine 2: Cross-Domain Mapping ---
    cross_links = map_cross_domain_links(anomalies)

    # --- Engine 3: Reverse Timeline ---
    timeline = build_reverse_timeline(anomalies, dominant_dir, macro_theme)

    # --- Engine 4: Consensus Fragility ---
    fragility_score, _ = compute_consensus_fragility(
        matrix, anomalies, len(trigger_layers),
    )

    # --- Engine 5: Physical Verification Locks ---
    pvis = generate_physical_verifications(anomalies, dominant_dir, macro_theme)

    # --- Build counter-narrative ---
    counter_narrative = (
        f"Counter to {macro_theme or 'primary'} thesis: "
        f"anomalies may be noise; fragility {fragility_score:.0f}/100 suggests "
        f"consensus may not fully break"
    )
    why_counter_is_weaker = (
        f"Primary narrative has {len(pvis)} physical verification locks; "
        f"counter-narrative lacks equivalent falsifiability constraints"
    )

    now_str = datetime.now(timezone.utc).isoformat()

    narrative = MosaicNarrative(
        narrative_id=f"mn_{len(anomaly_signal_ids)}_{now_str[:10]}",
        generated_at=now_str,
        macro_theme=macro_theme if macro_theme else "Macro regime shift (multi-layer anomaly)",
        confidence=round(anomaly_confidence, 4),
        consensus_fragility=round(fragility_score, 2),
        anomaly_signals_used=anomaly_signal_ids,
        trigger_layers=trigger_layers,
        cross_domain_links=cross_links,
        reverse_timeline=timeline,
        physical_verifications=pvis,
        counter_narrative=counter_narrative,
        why_counter_is_weaker=why_counter_is_weaker,
        source_matrix_id=matrix.matrix_id,
    )

    return narrative