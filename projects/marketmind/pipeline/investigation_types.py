"""Shared data types for the HVR investigation loop.

Data-only module — HypothesisResult and InvestigationConfig dataclasses
are shared between investigation_loop.py (glue) and hvr_cycle.py (behavioral).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.causal_decomposition import CausalDecomposition
    from marketmind.pipeline.flow_decomposition import FlowAttribution
    from marketmind.pipeline.scenario_forecaster import ScenarioTree

from marketmind.config.investigation_config import (
    ADVERSARIAL_BEAR_CASE_REQUIRED,
    BEAR_CASE_CONFIDENCE_DISCOUNT,
    CONFIDENCE_ACTION_THRESHOLD,
    CONFIDENCE_WATCH_THRESHOLD,
    DIMINISHING_RETURNS_THRESHOLD,
    EXPECTATION_GAP_THRESHOLD,
    MAX_API_CALLS_PER_THREAD,
    MAX_DEEPENING_STEPS_PER_THREAD,
    MAX_HYPOTHESES_PER_SESSION,
)
from marketmind.pipeline.verification_chain import VerificationResult


@dataclass
class InvestigationConfig:
    """Runtime investigation parameters. Defaults loaded from investigation_config."""

    max_hypotheses: int = MAX_HYPOTHESES_PER_SESSION
    max_deepening_steps: int = MAX_DEEPENING_STEPS_PER_THREAD
    max_api_calls: int = MAX_API_CALLS_PER_THREAD
    diminishing_threshold: float = DIMINISHING_RETURNS_THRESHOLD
    expectation_gap_threshold: float = EXPECTATION_GAP_THRESHOLD
    confidence_action: float = CONFIDENCE_ACTION_THRESHOLD
    confidence_watch: float = CONFIDENCE_WATCH_THRESHOLD
    adversarial_required: bool = ADVERSARIAL_BEAR_CASE_REQUIRED
    bear_discount: float = BEAR_CASE_CONFIDENCE_DISCOUNT


@dataclass
class HypothesisResult:
    """Output of one complete HVR investigation thread.

    Attributes:
        hypothesis: The final (possibly refined) hypothesis text.
        expectation_gap: |actual - priced_in| ratio. >0.15 = worth investigating.
        verification: Full 4-layer VerificationResult from verification_chain.
        refined_hypothesis: The hypothesis after all refinement rounds.
        confidence: Composite confidence (0-1) after refinement.
        bear_case: Adversarial counter-argument — mandatory.
        bear_case_confidence: How strong the bear case is (0-1).
        verdict: ACTIONABLE | MONITOR | DISCARD | PRICED_IN | HIGH_CONTENTION.
        logic_chain: Step-by-step reasoning trace from all HVR rounds.
        direction: Structured direction label (e.g., "EUR/USD 看涨").
        risk_level: "低" | "中等" | "高".
        time_window: e.g., "1-4周", "1-3个月", "N/A", "已过期".
        layer_1_narrative: Human-readable Layer 1 market pricing narrative.
        layer_2_narrative: Human-readable Layer 2 fundamental narrative.
        layer_3_narrative: Human-readable Layer 3 multisource narrative.
        layer_4_narrative: Human-readable Layer 4 historical narrative.
        core_logic: Concise one-line thesis summary.
    """

    hypothesis: str
    expectation_gap: float
    verification: VerificationResult
    refined_hypothesis: str
    confidence: float
    bear_case: str
    bear_case_confidence: float
    verdict: str  # ACTIONABLE | MONITOR | DISCARD | PRICED_IN | HIGH_CONTENTION
    logic_chain: list[str] = field(default_factory=list)
    # ── Hypothesis card fields (generated post-verification) ────────
    direction: str = ""          # structured direction label e.g. "EUR/USD 看涨"
    risk_level: str = ""         # "低" | "中等" | "高"
    time_window: str = ""        # e.g. "2-4周", "1-3个月"
    layer_1_narrative: str = ""  # human-readable Layer 1 market pricing narrative
    layer_2_narrative: str = ""  # human-readable Layer 2 fundamental narrative
    layer_3_narrative: str = ""  # human-readable Layer 3 multisource narrative
    layer_4_narrative: str = ""  # human-readable Layer 4 historical narrative
    core_logic: str = ""         # concise one-line thesis summary
    # Phase H: deep analysis enrichments (populated by pipeline post-processing)
    causal: "CausalDecomposition | None" = None
    flow: "FlowAttribution | None" = None
    scenario_tree: "ScenarioTree | None" = None
