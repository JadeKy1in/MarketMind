"""Phase 7.1 — Alternative Data Hooks Engine (Proxy Routing + Graceful Degradation)

5-layer alternative data discovery layer with PM-mandated resilience:

  1) Proxy Variable Routing: If primary data (A) fails → fall through proxy chain (B→C→D)
  2) Graceful Degradation: Insufficient data → 2D qualitative w/ explicit [DATA INSUFFICIENT]
  3) Absence as a Signal: Missing data is NOT an exception but an AlternativeSignal

Zero external dependency — uses Python stdlib only (urllib, html.parser).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union


# ─── Enums ───────────────────────────────────────────────────────────────────


class SignalLayer(Enum):
    """6-layer alternative data taxonomy (+ ABSENCE for missing-data-as-signal)."""
    L1_PUBLIC_NEGLECTED = "layer_1_public_neglected"
    L2_SEMI_PUBLIC = "layer_2_semi_public"
    L3_MICROSTRUCTURE = "layer_3_microstructure"
    L4_GEO_PHYSICAL = "layer_4_geo_physical"
    L5_REFLEXIVE_META = "layer_5_reflexive_meta"
    ABSENCE = "layer_absence_signal"          # ✨ Missing data → signal


class SignalDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    DIVERGENT = "divergent"
    CONTRARIAN = "contrarian"


class DegradationLevel(Enum):
    """How severely the data pipeline degraded before producing this signal.

    Values are ordered from least to most severe degradation:
      NONE → PASS_THROUGH → FULL_3D → SIGNAL_DEGRADED → QUANTITATIVE_2D → QUALITATIVE_ONLY → ABSENCE_SIGNAL
    """
    NONE = "none"                                              # No degradation, direct source
    PASS_THROUGH = "pass_through"                              # Passed through proxy chain successfully
    FULL_3D = "full_3d"                                        # Value + z-score + confidence
    SIGNAL_DEGRADED = "signal_degraded"                        # Signal quality degraded (used in mosaic reasoning)
    QUANTITATIVE_2D = "quantitative_2d"                        # Value + z-score only
    QUALITATIVE_ONLY = "qualitative_only"                      # Direction + reasoning only
    ABSENCE_SIGNAL = "absence_signal"                          # Data itself is the signal


# ─── Proxy Routing — Graceful Fallback Chain ─────────────────────────────────


@dataclass
class ProxyRoute:
    """Defines a fallback chain from primary source → proxy → proxy.

    Example:
        ProxyRoute(
            primary_source="institutional_flows",
            proxies=["etf_volume_surge", "options_put_call_ratio", "dark_pool_print"],
            proxy_descriptions={
                "etf_volume_surge": "ETF (IAU/GDX) pre-market volume spike",
                "options_put_call_ratio": "Aggregate put/call OI ratio shift",
                "dark_pool_print": "Dark pool large-print frequency anomaly",
            },
            layer_hint=SignalLayer.L3_MICROSTRUCTURE,
        )
    """
    primary_source: str
    proxies: List[str]
    proxy_descriptions: Dict[str, str] = field(default_factory=dict)
    layer_hint: SignalLayer = SignalLayer.L3_MICROSTRUCTURE


@dataclass
class ProxyResolution:
    """Result of resolving a proxy chain.

    Attributes:
        source_used: The source that was actually used (primary or fallback).
        proxy_chain_tried: All sources tried in order.
        proxy_chain_index: Index in chain that succeeded (-1 if all failed).
        degradation: Degradation level after resolution.
        fallback_description: Human-readable description of the proxy used.
        failure_reason: If all failed, the reason.
    """
    source_used: str
    proxy_chain_tried: List[str]
    proxy_chain_index: int
    degradation: DegradationLevel
    fallback_description: str = ""
    failure_reason: str = ""


class ProxyRouter:
    """Routes data requests through a fallback chain.

    Design:
        - Each primary source is registered with a ProxyRoute.
        - resolve() tries primary first, then each proxy in order.
        - Each attempt calls an optional "checker" function that validates
          whether the source is available. If no checker is provided, the
          source is assumed available (pass-through for stub mode).
        - Returns ProxyResolution with degradation metadata.

    Usage (stub mode — no checkers):
        router = ProxyRouter()
        router.register_route("institutional_flows", ProxyRoute(primary_source="institutional_flows", proxies=[]))
        result = router.resolve("institutional_flows")
        # result.source_used == "institutional_flows" (pass-through)
    """

    def __init__(self) -> None:
        self._routes: Dict[str, ProxyRoute] = {}
        self._checkers: Dict[str, Callable[[], bool]] = {}

    def register_route(self, primary_source: str, route: ProxyRoute) -> None:
        """Register a proxy fallback chain for a primary source."""
        self._routes[primary_source] = route

    def register_checker(self, source_name: str, checker: Callable[[], bool]) -> None:
        """Register an availability checker function for a data source.

        The checker should return True if the source is available, False otherwise.
        """
        self._checkers[source_name] = checker

    def resolve(self, primary_source: str) -> ProxyResolution:
        """Resolve a data source through its proxy fallback chain.

        Tries primary → proxy[0] → proxy[1] → ...
        Returns the first available source with full metadata.

        If ALL sources fail, returns ProxyResolution with
        source_used=primary_source, proxy_chain_index=-1, and a failure_reason.
        """
        route = self._routes.get(primary_source)
        if route is None:
            return ProxyResolution(
                source_used=primary_source,
                proxy_chain_tried=[primary_source],
                proxy_chain_index=0,
                degradation=DegradationLevel.FULL_3D,
                fallback_description="Primary source (no route registered)",
            )

        chain: List[str] = [primary_source] + route.proxies
        fallback_desc_map = route.proxy_descriptions

        for idx, source in enumerate(chain):
            checker = self._checkers.get(source)
            if checker is None or checker():
                # Source is available
                deg_level = self._compute_degradation(idx, source, primary_source)
                desc = (
                    f"Proxy[{idx}]: {fallback_desc_map.get(source, source)}"
                    if idx > 0 else "Primary source"
                )
                return ProxyResolution(
                    source_used=source,
                    proxy_chain_tried=chain,
                    proxy_chain_index=idx,
                    degradation=deg_level,
                    fallback_description=desc,
                )

        # All sources failed → ABSENCE as a signal (per PM mandate)
        return ProxyResolution(
            source_used=primary_source,
            proxy_chain_tried=chain,
            proxy_chain_index=-1,
            degradation=DegradationLevel.ABSENCE_SIGNAL,
            failure_reason=(
                f"All {len(chain)} sources in proxy chain unavailable: {chain}"
            ),
        )

    @staticmethod
    def _compute_degradation(
        chain_index: int, source_used: str, primary: str,
    ) -> DegradationLevel:
        """Map chain position to degradation level.

        - Index 0 (primary): FULL_3D
        - Index 1 (first proxy): QUANTITATIVE_2D (confidence loss from indirection)
        - Index >= 2 (deeper proxy): QUALITATIVE_ONLY (proxy drift too high)
        """
        if chain_index == 0:
            return DegradationLevel.FULL_3D
        if chain_index == 1:
            return DegradationLevel.QUANTITATIVE_2D
        return DegradationLevel.QUALITATIVE_ONLY


# ─── Core Data Structures ────────────────────────────────────────────────────


@dataclass
class AlternativeSignal:
    """Single alternative data signal with degradation-aware metadata.

    Attributes:
        signal_id: Unique identifier (e.g. "monero_btc_ratio_20260505")
        layer: Which of the 6 layers this signal belongs to
        source_name: Machine-readable source key
        source_description: Human-readable description
        current_value: Latest observed value (None if QUALITATIVE_ONLY)
        baseline_mean: Historical mean (None if QUALITATIVE_ONLY)
        baseline_std: Historical std (None if QUALITATIVE_ONLY)
        z_score: (current_value - baseline_mean) / baseline_std (None if QUALITATIVE_ONLY)
        direction: Signal directional classification
        confidence: Signal reliability (0.0–1.0, None if QUALITATIVE_ONLY)
        lookback_window_days: Number of days used for baseline computation (0 if unknown)
        last_updated: ISO-8601 timestamp of most recent observation
        reasoning_hook: LLM hint linking this signal to macro narratives
        manipulation_risk: Description of potential manipulation vectors
        degradation: Degradation level from proxy routing
        proxy_chain_used: Which data sources were tried before succeeding
        is_absence_signal: True if missing data itself generated this signal
        absence_narrative: If is_absence_signal, describes what disappeared
    """
    signal_id: str
    layer: SignalLayer
    source_name: str
    source_description: str
    current_value: Optional[float] = None
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    z_score: Optional[float] = None
    direction: SignalDirection = SignalDirection.DIVERGENT
    confidence: Optional[float] = None
    lookback_window_days: int = 0
    last_updated: str = ""
    reasoning_hook: str = ""
    manipulation_risk: str = ""
    degradation: DegradationLevel = DegradationLevel.FULL_3D
    proxy_chain_used: List[str] = field(default_factory=list)
    is_absence_signal: bool = False
    absence_narrative: str = ""

    def __post_init__(self) -> None:
        """Validate invariants based on degradation level."""
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if not self.signal_id:
            raise ValueError("signal_id must not be empty")
        if not self.source_name:
            raise ValueError("source_name must not be empty")

        # Degradation consistency checks
        if self.degradation == DegradationLevel.FULL_3D:
            if self.current_value is None or self.z_score is None or self.confidence is None:
                raise ValueError(
                    f"FULL_3D requires current_value, z_score, and confidence "
                    f"all non-None"
                )
        if self.degradation == DegradationLevel.QUALITATIVE_ONLY:
            if self.current_value is not None or self.z_score is not None or self.confidence is not None:
                raise ValueError(
                    f"QUALITATIVE_ONLY must have current_value=None, "
                    f"z_score=None, confidence=None (got value={self.current_value})"
                )
        if self.degradation == DegradationLevel.ABSENCE_SIGNAL:
            if not self.is_absence_signal:
                raise ValueError(
                    f"ABSENCE_SIGNAL degradation requires is_absence_signal=True"
                )
            if not self.absence_narrative:
                raise ValueError(
                    f"ABSENCE_SIGNAL degradation requires non-empty absence_narrative"
                )

    def is_anomalous(self, threshold: float = 1.5) -> bool:
        """Returns True if z_score exists and exceeds threshold.

        Absence signals are always considered anomalous (the disappearance
        itself is the anomaly).
        """
        if self.is_absence_signal:
            return True
        if self.z_score is None:
            return False
        return abs(self.z_score) > threshold

    def confidence_tag(self) -> str:
        """Returns a degradation/confidence tag for the final report.

        Per PM mandate: degraded signals get a visible [DATA INSUFFICIENT] tag.
        """
        if self.degradation == DegradationLevel.ABSENCE_SIGNAL:
            return "[ABSENCE AS SIGNAL]"
        if self.degradation == DegradationLevel.QUALITATIVE_ONLY:
            return "[DATA INSUFFICIENT - QUALITATIVE ONLY]"
        if self.degradation == DegradationLevel.QUANTITATIVE_2D:
            return "[DATA INSUFFICIENT - PROXY ROUTED]"
        return "[FULL 3D CONFIRMED]"


@dataclass
class AlternativeSignalMatrix:
    """Aggregated 6-layer signal matrix with cross-convergence & degradation stats.

    Attributes:
        matrix_id: Unique identifier
        generated_at: ISO-8601 generation timestamp
        l1_signals: Layer 1 signals (public but neglected)
        l2_signals: Layer 2 signals (semi-public structured)
        l3_signals: Layer 3 signals (microstructure anomalies)
        l4_signals: Layer 4 signals (geo-physical signals)
        l5_signals: Layer 5 signals (reflexive meta-signals)
        absence_signals: Layer ABSENCE signals (missing data as signal)
        layer_convergence_count: Number of layers with aligned signals
        total_signals_generated: Count of all signals in matrix
        convergence_narrative: LLM-generated mosaic narrative
        divergence_warnings: Layer-level contradictions
        linked_macro_tag_refs: References to Phase 5 MacroTag IDs
        degradation_count: Count of degraded signals
        degraded_signal_warnings: Warnings per degraded signal
        overall_data_quality: Best description of overall data quality
    """
    matrix_id: str
    generated_at: str
    l1_signals: List[AlternativeSignal] = field(default_factory=list)
    l2_signals: List[AlternativeSignal] = field(default_factory=list)
    l3_signals: List[AlternativeSignal] = field(default_factory=list)
    l4_signals: List[AlternativeSignal] = field(default_factory=list)
    l5_signals: List[AlternativeSignal] = field(default_factory=list)
    absence_signals: List[AlternativeSignal] = field(default_factory=list)  # ✨ New

    # Computed fields
    layer_convergence_count: int = 0
    total_signals_generated: int = 0
    convergence_narrative: str = ""
    divergence_warnings: List[str] = field(default_factory=list)
    linked_macro_tag_refs: List[str] = field(default_factory=list)
    degradation_count: int = 0                     # ✨ New
    degraded_signal_warnings: List[str] = field(default_factory=list)  # ✨ New
    overall_data_quality: str = "full_3d"          # ✨ New

    def __post_init__(self) -> None:
        """Validate invariants and auto-compute totals."""
        if not self.matrix_id:
            raise ValueError("matrix_id must not be empty")
        if not self.generated_at:
            raise ValueError("generated_at must not be empty")
        self._recompute()

    def _recompute(self) -> None:
        """Recompute all derived fields."""
        all_sigs = self.all_signals()
        self.total_signals_generated = len(all_sigs)

        # Degradation tracking
        self.degradation_count = sum(
            1 for s in all_sigs if s.degradation != DegradationLevel.FULL_3D
        )
        self.degraded_signal_warnings = [
            f"Signal '{s.signal_id}' degraded to {s.degradation.value}: "
            f"{s.confidence_tag()} (proxy chain: {s.proxy_chain_used})"
            for s in all_sigs if s.degradation != DegradationLevel.FULL_3D
        ]

        # Overall data quality
        deg_levels = {s.degradation for s in all_sigs} if all_sigs else set()
        if DegradationLevel.ABSENCE_SIGNAL in deg_levels:
            self.overall_data_quality = "degraded_with_absence_signals"
        elif DegradationLevel.QUALITATIVE_ONLY in deg_levels:
            self.overall_data_quality = "degraded_qualitative"
        elif DegradationLevel.QUANTITATIVE_2D in deg_levels:
            self.overall_data_quality = "degraded_quantitative_2d"
        else:
            self.overall_data_quality = "full_3d"

    def all_signals(self) -> List[AlternativeSignal]:
        """Returns a flat list of all signals across all layers (incl. absence)."""
        return (
            self.l1_signals
            + self.l2_signals
            + self.l3_signals
            + self.l4_signals
            + self.l5_signals
            + self.absence_signals
        )

    def anomalous_signals(self, threshold: float = 1.5) -> List[AlternativeSignal]:
        """Returns only signals whose z_score exceeds threshold or are absence signals."""
        return [s for s in self.all_signals() if s.is_anomalous(threshold)]

    def compute_convergence(self, threshold: float = 1.5) -> None:
        """Computes layer convergence count and divergence warnings.

        Convergence rule (from Phase 7 blueprint Rule 1):
          At least 3 different layers must have a signal with z_score > threshold
          or an absence signal, in the same direction.

        Divergence rule (Rule 2):
          If one layer has signals in the opposite direction of the majority,
          emit a divergence warning.
        """
        layer_directions: Dict[SignalLayer, set[SignalDirection]] = {}

        for signal in self.anomalous_signals(threshold):
            if signal.layer not in layer_directions:
                layer_directions[signal.layer] = set()
            layer_directions[signal.layer].add(signal.direction)

        # Count layers that have at least one anomalous signal
        self.layer_convergence_count = len(layer_directions)

        # Detect divergence
        self.divergence_warnings = []
        for layer, directions in layer_directions.items():
            bullish = SignalDirection.BULLISH in directions
            bearish = SignalDirection.BEARISH in directions
            divergent = SignalDirection.DIVERGENT in directions
            contrarian = SignalDirection.CONTRARIAN in directions

            if bullish and bearish:
                self.divergence_warnings.append(
                    f"Layer {layer.value} contains both BULLISH and "
                    f"BEARISH signals — possible data conflict"
                )
            if divergent:
                self.divergence_warnings.append(
                    f"Layer {layer.value} has DIVERGENT signal "
                    f"— requires Red Team audit"
                )
            if contrarian:
                self.divergence_warnings.append(
                    f"Layer {layer.value} has CONTRARIAN signal "
                    f"— requires Red Team audit"
                )

        # Append degradation warnings to divergence warnings
        if self.degraded_signal_warnings:
            self.divergence_warnings.append(
                f"Degradation: {self.degradation_count} signal(s) degraded "
                f"({self.overall_data_quality}). "
                f"See degraded_signal_warnings for details."
            )

        self.convergence_narrative = (
            f"Convergence: {self.layer_convergence_count} layers with "
            f"anomalous signals out of 6 possible layers. "
            f"Data quality: {self.overall_data_quality}. "
            f"Degraded signals: {self.degradation_count}."
        )


# ─── Absence as a Signal — Constructor ────────────────────────────────────────


def build_absence_signal(
    source_name: str,
    source_description: str,
    direction: SignalDirection,
    layer: SignalLayer = SignalLayer.ABSENCE,
    reasoning_hook: str = "",
    manipulation_risk: str = "",
    absence_narrative: str = "",
) -> AlternativeSignal:
    """Build a signal from missing data.

    Per PM mandate: if expected public data disappears, it's NOT an exception —
    it's an AlternativeSignal fed to the Red Team auditor.

    Args:
        source_name: What data disappeared
        source_description: Human-readable description of the missing data
        direction: What the absence implies directionally
        layer: Which layer this absence belongs to (default ABSENCE)
        reasoning_hook: LLM hint linking absence to macro narratives
        manipulation_risk: Could the absence be manufactured?
        absence_narrative: Detailed description of what disappeared and why it matters

    Returns:
        AlternativeSignal with degradation=ABSENCE_SIGNAL,
        is_absence_signal=True, and non-empty absence_narrative.
    """
    if not absence_narrative:
        absence_narrative = (
            f"Expected data from '{source_name}' is unavailable. "
            f"The disappearance itself may be a signal."
        )

    now_utc = datetime.now(timezone.utc)
    return AlternativeSignal(
        signal_id=f"absence_{source_name}_{now_utc.strftime('%Y%m%d_%H%M%S')}",
        layer=layer,
        source_name=source_name,
        source_description=source_description,
        current_value=None,
        baseline_mean=None,
        baseline_std=None,
        z_score=None,
        direction=direction,
        confidence=None,
        lookback_window_days=0,
        last_updated=now_utc.isoformat(),
        reasoning_hook=reasoning_hook,
        manipulation_risk=manipulation_risk,
        degradation=DegradationLevel.ABSENCE_SIGNAL,
        is_absence_signal=True,
        absence_narrative=absence_narrative,
    )


# ─── Proxy-Aware Signal Builder ──────────────────────────────────────────────


def build_signal_with_proxy(
    signal_id: str,
    layer: SignalLayer,
    source_name: str,
    source_description: str,
    proxy_chain_tried: List[str],
    proxy_chain_index: int,
    degradation: DegradationLevel,
    fallback_description: str = "",
    current_value: Optional[float] = None,
    baseline_mean: Optional[float] = None,
    baseline_std: Optional[float] = None,
    direction: SignalDirection = SignalDirection.DIVERGENT,
    confidence: Optional[float] = None,
    lookback_window_days: int = 0,
    reasoning_hook: str = "",
    manipulation_risk: str = "",
) -> AlternativeSignal:
    """Build an AlternativeSignal with full proxy routing metadata.

    Delegates to the AlternativeSignal constructor, injecting proxy_chain_used
    and degradation info.

    For QUALITATIVE_ONLY degradation, current_value/z_score/confidence are
    forced to None to maintain invariants.
    """
    now_utc = datetime.now(timezone.utc)

    if degradation == DegradationLevel.QUALITATIVE_ONLY:
        current_value = None
        baseline_mean = None
        baseline_std = None
        confidence = None
        z_score_val: Optional[float] = None
    elif current_value is not None and baseline_mean is not None and baseline_std is not None:
        z_score_val = round(
            compute_z_score_from_stats(current_value, baseline_mean, baseline_std), 4
        )
    else:
        z_score_val = None

    # Auto-downgrade: if caller requests FULL_3D but can't provide stats to
    # compute z-score, degrade to QUANTITATIVE_2D (has value + confidence,
    # but no z-score). This cascades to fix all fetcher stubs that pass
    # confidence without baseline stats.
    if degradation == DegradationLevel.FULL_3D and z_score_val is None:
        degradation = DegradationLevel.QUANTITATIVE_2D

    return AlternativeSignal(
        signal_id=signal_id,
        layer=layer,
        source_name=source_name,
        source_description=source_description,
        current_value=current_value,
        baseline_mean=baseline_mean,
        baseline_std=baseline_std,
        z_score=z_score_val,
        direction=direction,
        confidence=confidence,
        lookback_window_days=lookback_window_days,
        last_updated=now_utc.isoformat(),
        reasoning_hook=reasoning_hook,
        manipulation_risk=manipulation_risk,
        degradation=degradation,
        proxy_chain_used=proxy_chain_tried,
        is_absence_signal=False,
        absence_narrative="",
    )


# ─── Statistical Utilities ──────────────────────────────────────────────────


def compute_z_score(
    values: List[float],
    current_value: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """Computes z-score of current_value relative to a sample.

    Args:
        values: Historical sample of values (at least 2 points required).
        current_value: The latest observation. If None, uses values[-1].

    Returns:
        Tuple of (z_score, mean, std, current_value).

    Raises:
        ValueError: If fewer than 2 values are provided.
        ValueError: If standard deviation is zero (all values identical).
    """
    if len(values) < 2:
        raise ValueError(f"Need at least 2 values for z-score, got {len(values)}")

    mean = statistics.mean(values)
    std = statistics.stdev(values)

    if std == 0.0:
        raise ValueError(
            f"Cannot compute z-score: standard deviation is zero "
            f"(all {len(values)} values are identical = {mean})"
        )

    if current_value is None:
        current_value = values[-1]

    z_score = (current_value - mean) / std
    return (z_score, mean, std, current_value)


def compute_z_score_from_stats(
    current_value: float,
    baseline_mean: float,
    baseline_std: float,
) -> float:
    """Computes z-score given pre-computed statistics.

    Args:
        current_value: The latest observation.
        baseline_mean: Pre-computed historical mean.
        baseline_std: Pre-computed historical standard deviation.

    Returns:
        z_score (standard deviations from mean).

    Raises:
        ValueError: If baseline_std is zero or negative.
    """
    if baseline_std <= 0:
        raise ValueError(
            f"baseline_std must be positive, got {baseline_std}"
        )
    return (current_value - baseline_mean) / baseline_std


# ─── Default Proxy Routes ────────────────────────────────────────────────────


def create_default_proxy_router() -> ProxyRouter:
    """Creates a ProxyRouter with pre-configured fallback chains.

    These routes map the PM's real-world examples to proxy chains:

    PM Example: Institutional flow data unavailable
      → Proxy to ETF (IAU/GDX) pre-market volume surge
      → Options put/call ratio shift
      → Dark pool large-print frequency

    PM Example: Middle East spot transaction data walled
      → Proxy to energy stock implied volatility (IV)
      → Sovereign CDS spread widening
      → Dry bulk shipping rate anomaly
    """
    router = ProxyRouter()

    # Institutional flows → ETF volume → Options → Dark pool
    router.register_route(
        "institutional_flows",
        ProxyRoute(
            primary_source="institutional_flows",
            proxies=["etf_volume_surge", "options_put_call_ratio", "dark_pool_print"],
            proxy_descriptions={
                "etf_volume_surge": "ETF (IAU/GDX) pre-market volume spike as capital flow proxy",
                "options_put_call_ratio": "Aggregate put/call OI ratio shift",
                "dark_pool_print": "Dark pool large-print frequency anomaly",
            },
            layer_hint=SignalLayer.L3_MICROSTRUCTURE,
        ),
    )

    # Middle East oil transactions → Energy IV → Sovereign CDS → Shipping
    router.register_route(
        "middle_east_oil_spot",
        ProxyRoute(
            primary_source="middle_east_oil_spot",
            proxies=[
                "energy_stock_iv",
                "sovereign_cds_spread",
                "dry_bulk_shipping_rate",
            ],
            proxy_descriptions={
                "energy_stock_iv": "Energy sector implied volatility spike",
                "sovereign_cds_spread": "Sovereign CDS spread widening for Gulf states",
                "dry_bulk_shipping_rate": "Dry bulk shipping rate anomaly (BDI)",
            },
            layer_hint=SignalLayer.L4_GEO_PHYSICAL,
        ),
    )

    # Insider trading (SEC EDGAR 13F) → Congress trading → CEO social activity
    router.register_route(
        "sec_edgar_insider",
        ProxyRoute(
            primary_source="sec_edgar_insider",
            proxies=[
                "congress_trading_disclosures",
                "ceo_social_media_silence",
            ],
            proxy_descriptions={
                "congress_trading_disclosures": "STOCK Act congressional trade reports",
                "ceo_social_media_silence": "CEO social media posting frequency drop",
            },
            layer_hint=SignalLayer.L2_SEMI_PUBLIC,
        ),
    )

    # Crypto privacy flows → DEX volume spike → Stablecoin premium → Mining hash
    router.register_route(
        "crypto_privacy_flows",
        ProxyRoute(
            primary_source="crypto_privacy_flows",
            proxies=[
                "dex_volume_spike",
                "stablecoin_premium_deviation",
                "mining_hash_rate_shift",
            ],
            proxy_descriptions={
                "dex_volume_spike": "DEX aggregate volume anomaly (Uniswap etc.)",
                "stablecoin_premium_deviation": "Stablecoin (USDT/USDC) premium/discount deviation",
                "mining_hash_rate_shift": "Bitcoin mining hash rate sudden shift",
            },
            layer_hint=SignalLayer.L3_MICROSTRUCTURE,
        ),
    )

    return router


# ─── Core Fetcher Function with Proxy Routing ────────────────────────────────


def fetch_with_proxy_routing(
    router: ProxyRouter,
    primary_source: str,
    build_signal_fn: Callable[[str, str, DegradationLevel, List[str], int], List[AlternativeSignal]],
    default_layer: SignalLayer = SignalLayer.L3_MICROSTRUCTURE,
    default_description: str = "",
) -> List[AlternativeSignal]:
    """Generic fetcher that routes through proxy chain.

    This is the main entry point for all alternative data fetch operations.

    Args:
        router: ProxyRouter instance with registered routes.
        primary_source: The primary data source key.
        build_signal_fn: Callable that takes:
            - source_used (str): The source that was resolved
            - fallback_description (str): Human-readable proxy description
            - degradation (DegradationLevel): How degraded the data is
            - proxy_chain_tried (List[str]): All sources tried
            - proxy_chain_index (int): Which index succeeded
            Returns: List[AlternativeSignal]
        default_layer: Fallback layer if not defined in route.
        default_description: Fallback description.

    Returns:
        List of AlternativeSignal.
        If ALL sources fail, returns a single absence signal.
    """
    resolution = router.resolve(primary_source)

    if resolution.proxy_chain_index == -1:
        # All sources failed → Absence as a Signal
        route = None
        try:
            route = router._routes.get(primary_source)
        except Exception:  # nosec
            pass
        layer = route.layer_hint if route else default_layer
        desc = route.proxy_descriptions.get(primary_source, default_description) if route else default_description

        return [
            build_absence_signal(
                source_name=primary_source,
                source_description=desc or f"Data unavailable for {primary_source}",
                direction=SignalDirection.DIVERGENT,
                layer=layer,
                absence_narrative=resolution.failure_reason,
                reasoning_hook=f"All {len(resolution.proxy_chain_tried)} sources "
                               f"failed for {primary_source}. Absence itself is the signal.",
            )
        ]

    # Source resolved → build signals
    return build_signal_fn(
        resolution.source_used,
        resolution.fallback_description,
        resolution.degradation,
        resolution.proxy_chain_tried,
        resolution.proxy_chain_index,
    )


# ─── Fetcher Stubs (Proxy-Aware) ──────────────────────────────────────────────


def fetch_sec_edgar_signals(
    tickers: Optional[List[str]] = None,
    router: Optional[ProxyRouter] = None,
) -> List[AlternativeSignal]:
    """Fetches SEC EDGAR signals with proxy routing.

    In production, parses SEC.gov RSS or EDGAR full-text search.
    Uses only Python stdlib urllib + html.parser.

    Args:
        tickers: Optional stock tickers to filter.
        router: Optional ProxyRouter for fallback. If None, uses default.

    Returns:
        List of AlternativeSignal objects (empty list in stub mode).
    """
    _ = tickers

    if router is not None:
        def _build_sigs(
            source_used: str,
            fallback_desc: str,
            degradation: DegradationLevel,
            chain: List[str],
            chain_idx: int,
        ) -> List[AlternativeSignal]:
            sig = build_signal_with_proxy(
                signal_id=f"sec_{source_used}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                layer=SignalLayer.L2_SEMI_PUBLIC,
                source_name=source_used,
                source_description=fallback_desc,
                proxy_chain_tried=chain,
                proxy_chain_index=chain_idx,
                degradation=degradation,
                direction=SignalDirection.DIVERGENT,
                confidence=0.5,
            )
            return [sig]

        return fetch_with_proxy_routing(
            router=router,
            primary_source="sec_edgar_insider",
            build_signal_fn=_build_sigs,
            default_layer=SignalLayer.L2_SEMI_PUBLIC,
            default_description="SEC EDGAR insider filing signals",
        )

    # No router: stub mode, returns empty
    return []


def fetch_cot_report_signals(
    commodity: str = "EUR",
    router: Optional[ProxyRouter] = None,
) -> List[AlternativeSignal]:
    """Fetches CFTC COT Report with proxy routing.

    Args:
        commodity: Commodity code (default 'EUR' for Euro).
        router: Optional ProxyRouter.

    Returns:
        List of AlternativeSignal objects.
    """
    _ = commodity

    if router is not None:
        def _build_sigs(
            source_used: str,
            fallback_desc: str,
            degradation: DegradationLevel,
            chain: List[str],
            chain_idx: int,
        ) -> List[AlternativeSignal]:
            sig = build_signal_with_proxy(
                signal_id=f"cot_{source_used}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                layer=SignalLayer.L2_SEMI_PUBLIC,
                source_name=source_used,
                source_description=fallback_desc,
                proxy_chain_tried=chain,
                proxy_chain_index=chain_idx,
                degradation=degradation,
                direction=SignalDirection.DIVERGENT,
                confidence=0.5,
            )
            return [sig]

        return fetch_with_proxy_routing(
            router=router,
            primary_source="institutional_flows",
            build_signal_fn=_build_sigs,
            default_layer=SignalLayer.L2_SEMI_PUBLIC,
            default_description="CFTC COT report signals",
        )

    return []


def fetch_crypto_privacy_signals(
    router: Optional[ProxyRouter] = None,
) -> List[AlternativeSignal]:
    """Fetches crypto privacy flow signals with proxy routing.

    Maps PM's cross-border capital exfiltration detection pattern:
    Monero/BTC ratio anomaly → Privacy coin premium → Exchange withdrawal spike.

    Args:
        router: Optional ProxyRouter.

    Returns:
        List of AlternativeSignal objects.
    """
    if router is not None:
        def _build_sigs(
            source_used: str,
            fallback_desc: str,
            degradation: DegradationLevel,
            chain: List[str],
            chain_idx: int,
        ) -> List[AlternativeSignal]:
            sig = build_signal_with_proxy(
                signal_id=f"crypto_{source_used}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                layer=SignalLayer.L3_MICROSTRUCTURE,
                source_name=source_used,
                source_description=fallback_desc,
                proxy_chain_tried=chain,
                proxy_chain_index=chain_idx,
                degradation=degradation,
                direction=SignalDirection.DIVERGENT,
                confidence=0.4,
                reasoning_hook=(
                    "Crypto privacy flow anomaly. Cross-reference with stablecoin premium "
                    "deviation and DEX volume for capital exfiltration confirmation."
                ),
                manipulation_risk="Wash trading on low-liquidity DEX pairs can fake volume spikes",
            )
            return [sig]

        return fetch_with_proxy_routing(
            router=router,
            primary_source="crypto_privacy_flows",
            build_signal_fn=_build_sigs,
            default_layer=SignalLayer.L3_MICROSTRUCTURE,
            default_description="Crypto privacy flow signals",
        )

    return []


def fetch_ceo_departure_signals(
    router: Optional[ProxyRouter] = None,
) -> List[AlternativeSignal]:
    """Fetches CEO departure / executive anomaly signals with proxy routing.

    Maps PM's insider capital exfiltration detection pattern:
    CEO departure frequency → Social media silence → Conference cancellation.

    Args:
        router: Optional ProxyRouter.

    Returns:
        List of AlternativeSignal objects.
    """
    if router is not None:
        def _build_sigs(
            source_used: str,
            fallback_desc: str,
            degradation: DegradationLevel,
            chain: List[str],
            chain_idx: int,
        ) -> List[AlternativeSignal]:
            sig = build_signal_with_proxy(
                signal_id=f"ceo_{source_used}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                layer=SignalLayer.L1_PUBLIC_NEGLECTED,
                source_name=source_used,
                source_description=fallback_desc,
                proxy_chain_tried=chain,
                proxy_chain_index=chain_idx,
                degradation=degradation,
                direction=SignalDirection.BEARISH,
                confidence=0.3,
                reasoning_hook=(
                    "CEO departure / executive anomaly. If multiple C-suite departures "
                    "cluster within 90 days AND social media goes silent, flag insider capital flight."
                ),
                manipulation_risk="Companies may plant fake resignation news to distract from earnings misses",
            )
            return [sig]

        return fetch_with_proxy_routing(
            router=router,
            primary_source="sec_edgar_insider",
            build_signal_fn=_build_sigs,
            default_layer=SignalLayer.L1_PUBLIC_NEGLECTED,
            default_description="CEO departure / executive anomaly signals",
        )

    return []


# ─── Module Exports ──────────────────────────────────────────────────────────

__all__ = [
    # Enums
    "SignalLayer",
    "SignalDirection",
    "DegradationLevel",
    # Proxy routing
    "ProxyRoute",
    "ProxyResolution",
    "ProxyRouter",
    "create_default_proxy_router",
    "fetch_with_proxy_routing",
    # Core data structures
    "AlternativeSignal",
    "AlternativeSignalMatrix",
    # Builders
    "build_absence_signal",
    "build_signal_with_proxy",
    # Stats
    "compute_z_score",
    "compute_z_score_from_stats",
    # Fetcher stubs
    "fetch_sec_edgar_signals",
    "fetch_cot_report_signals",
    "fetch_crypto_privacy_signals",
    "fetch_ceo_departure_signals",
]
