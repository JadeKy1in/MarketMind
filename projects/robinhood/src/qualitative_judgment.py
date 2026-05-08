"""
qualitative_judgment.py — Phase 6 (Dual-Track Decision Engine) top-level router.

The Dual-Track Decision Tree evaluates incoming macro signals and
determines whether the system should enter:

  - Track A: OBSERVE_AND_WAIT  — contradictory/poor risk-reward signals
  - Track B: ACTION_AND_ADJUST — clear, causally validated signals

This module hosts the Qualifier (定性判定器) which implements the
coherence scoring and track routing logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from src.scout_types import MacroTag, NarrativeTag, SourceRecord


# =========================================================================
# DecisionTrack — the two top-level tracks
# =========================================================================


class DecisionTrack(str, Enum):
    """The two tracks of the Dual-Track Decision Engine."""

    OBSERVE_AND_WAIT = "OBSERVE_AND_WAIT"
    ACTION_AND_ADJUST = "ACTION_AND_ADJUST"


class ObserveScenario(str, Enum):
    """Why we chose OBSERVE — specific sub-reasons."""

    CONTRADICTION = "CONTRADICTION"           # conflicting macro signals
    POOR_RSK_REWARD = "POOR_RSK_REWARD"       # reward/risk ratio < 1.5
    CHOPPY_REGIME = "CHOPPY_REGIME"           # market in range-bound chop
    DATA_DROUGHT = "DATA_DROUGHT"             # insufficient catalyst data
    VALUATION_EXTREME = "VALUATION_EXTREME"   # risk of mean reversion


class ActionSubtrack(str, Enum):
    """Sub-tracks within ACTION_AND_ADJUST."""

    BUY = "BUY"
    SELL = "SELL"
    REBALANCE = "REBALANCE"


# =========================================================================
# QualifierState — aggregation of all signals fed into the qualifier
# =========================================================================


@dataclass
class QualifierInput:
    """Aggregated input for the Qualitative Judgment engine.

    This is populated from Phase 5 outputs + fresh macro data.
    """

    session_id: str
    macro_tags: List[MacroTag] = field(default_factory=list)
    narrative_tags: List[NarrativeTag] = field(default_factory=list)
    sources: List[SourceRecord] = field(default_factory=list)
    nfp_deviation: Optional[float] = None   # z-score vs consensus
    cpi_mom: Optional[float] = None         # CPI month-over-month %
    dxy_trend: Optional[str] = None         # "strengthening" | "weakening" | "flat"
    vix_level: Optional[float] = None       # CBOE VIX spot
    yield_curve: Optional[str] = None       # "normal" | "inverted" | "steepening"
    market_regime: Optional[str] = None     # "trending" | "choppy" | "risk_on" | "risk_off"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# =========================================================================
# QualifierOutput — the result of the qualitative judgment
# =========================================================================


@dataclass
class QualifierOutput:
    """Output of the qualitative judgment process.

    This is a refined version of the blueprint's QualitativeJudgment,
    tailored for programmatic consumption by downstream modules.
    """

    judgment_id: str
    timestamp: str
    decision_track: DecisionTrack
    track_confidence: float            # 0.0–1.0
    signal_coherence_score: float      # 0.0–100.0
    reward_risk_ratio: float           # derived from expected upside/downside
    decision_rationale: str
    action_subtrack: Optional[ActionSubtrack] = None  # only for ACTION
    observe_scenario: Optional[ObserveScenario] = None  # only for OBSERVE
    key_indicators: Dict[str, Any] = field(default_factory=dict)
    causal_audit_refs: List[str] = field(default_factory=list)


# =========================================================================
# Qualifier — the top-level routing engine
# =========================================================================

# Weights for signal coherence computation
_COHERENCE_WEIGHTS = {
    "cross_source_agreement": 0.30,
    "macro_technical_alignment": 0.25,
    "causal_audit_clearance": 0.20,
    "narrative_consistency": 0.15,
    "sentiment_divergence": 0.10,
}


def _compute_coherence(input_: QualifierInput) -> float:
    """Compute signal coherence score (0–100).

    Higher values mean signals agree and reinforce each other.
    This is a lightweight heuristic; in production this would use
    a learned model or ensemble voting.
    """
    score = 50.0  # neutral baseline

    # 1) Cross-source agreement: if we have multiple sources saying the same thing
    if input_.macro_tags:
        categories = {}
        for tag in input_.macro_tags:
            categories.setdefault(tag.category, []).append(tag.confidence)
        agreement_bonus = 0.0
        for cat, confs in categories.items():
            if len(confs) >= 2:
                # Confidence cluster: tags in same category agree
                mean_conf = sum(confs) / len(confs)
                agreement_bonus += (mean_conf - 0.5) * 10  # -5 to +5 per category
        score += max(-15, min(15, agreement_bonus))

    # 2) Macro-technical alignment
    if input_.dxy_trend == "weakening" and any(
        t.category == "monetary_policy" and "dovish" in t.narrative.lower()
        for t in input_.macro_tags
    ):
        score += 10  # dovish policy + weak dollar = risk-on alignment
    if input_.dxy_trend == "strengthening" and any(
        t.category == "monetary_policy" and "hawkish" in t.narrative.lower()
        for t in input_.macro_tags
    ):
        score += 10  # hawkish + strong dollar = risk-off alignment

    # 3) NFP surprise damping
    if input_.nfp_deviation is not None:
        # Large NFP surprise undermines existing narratives
        if abs(input_.nfp_deviation) > 2.0:
            score -= 15
        elif abs(input_.nfp_deviation) > 1.5:
            score -= 8

    # 4) VIX-based regime check
    if input_.vix_level is not None:
        if input_.vix_level > 30:
            score -= 10  # panic regime = low coherence
        elif input_.vix_level < 15:
            score += 5   # complacency = moderate coherence

    return max(0.0, min(100.0, score))


def _compute_reward_risk_ratio(input_: QualifierInput) -> float:
    """Compute approximate reward/risk ratio from macro context.

    Returns a float where >2.0 is favorable, <1.5 suggests caution.
    """
    ratio = 1.5  # default neutral

    # Tailwind detection
    tailwinds = 0
    headwinds = 0

    if input_.dxy_trend == "weakening":
        tailwinds += 1
    elif input_.dxy_trend == "strengthening":
        headwinds += 1

    if input_.yield_curve == "steepening":
        tailwinds += 1
    elif input_.yield_curve == "inverted":
        headwinds += 1

    if input_.vix_level is not None:
        if input_.vix_level < 18:
            tailwinds += 1
        elif input_.vix_level > 28:
            headwinds += 1

    net = tailwinds - headwinds
    ratio += net * 0.3

    # NFP surprise penalty
    if input_.nfp_deviation is not None and abs(input_.nfp_deviation) > 1.5:
        ratio -= 0.5

    return max(0.5, min(5.0, ratio))


_DEFAULT_SCENARIOS = {
    ("low_coherence", "low_ratio"): ObserveScenario.CONTRADICTION,
    ("high_coherence", "low_ratio"): ObserveScenario.POOR_RSK_REWARD,
    ("low_coherence", "high_ratio"): ObserveScenario.CONTRADICTION,
}


def _resolve_observe_scenario(
    coherence: float, ror: float, regime: Optional[str]
) -> ObserveScenario:
    """Determine the specific ObserveScenario from signal context."""
    coh_bin = "high_coherence" if coherence >= 60 else "low_coherence"
    ror_bin = "high_ratio" if ror >= 1.5 else "low_ratio"
    scenario = _DEFAULT_SCENARIOS.get((coh_bin, ror_bin))

    if scenario:
        return scenario

    # Check regime-based overrides
    if regime == "choppy":
        return ObserveScenario.CHOPPY_REGIME

    # Default fallback
    return ObserveScenario.CONTRADICTION


class Qualifier:
    """The Qualitative Judgment Engine (定性判定器).

    This is the entry point for Phase 6. It receives aggregated macro
    signals and decides whether to observe or act.
    """

    def __init__(self) -> None:
        self._input: Optional[QualifierInput] = None
        self._output: Optional[QualifierOutput] = None

    @property
    def last_output(self) -> Optional[QualifierOutput]:
        """Most recent judgment output, if any."""
        return self._output

    def judge(self, input_: QualifierInput) -> QualifierOutput:
        """Execute qualitative judgment and return the decision."""
        self._input = input_

        # 1) Compute core metrics
        coherence = _compute_coherence(input_)
        ror = _compute_reward_risk_ratio(input_)

        # 2) Determine decision track
        if coherence >= 50.0 and ror >= 1.5:
            track = DecisionTrack.ACTION_AND_ADJUST
            # Determine optimal subtrack
            if input_.market_regime in ("risk_on", "trending"):
                subtrack = ActionSubtrack.BUY
            else:
                # Default: let downstream decide between BUY/SELL
                subtrack = ActionSubtrack.BUY
            scenario = None
        else:
            track = DecisionTrack.OBSERVE_AND_WAIT
            subtrack = None
            scenario = _resolve_observe_scenario(
                coherence, ror, input_.market_regime
            )

        # 3) Build rationale
        rationale_parts = []
        if track == DecisionTrack.OBSERVE_AND_WAIT:
            if coherence < 50:
                rationale_parts.append(
                    f"Signal coherence low ({coherence:.1f}/100)"
                )
            if ror < 1.5:
                rationale_parts.append(
                    f"Reward/risk ratio unfavorable ({ror:.2f})"
                )
        else:
            rationale_parts.append(
                f"Signal coherence adequate ({coherence:.1f}/100)"
            )
            rationale_parts.append(
                f"Reward/risk ratio favorable ({ror:.2f})"
            )

        rationale = "; ".join(rationale_parts) if rationale_parts else "Manual override required"

        # 4) Collect key indicators
        indicators: Dict[str, Any] = {
            "macro_tag_count": len(input_.macro_tags),
            "narrative_tag_count": len(input_.narrative_tags),
            "source_count": len(input_.sources),
        }
        if input_.dxy_trend:
            indicators["dxy_trend"] = input_.dxy_trend
        if input_.vix_level is not None:
            indicators["vix"] = input_.vix_level
        if input_.yield_curve:
            indicators["yield_curve"] = input_.yield_curve

        # 5) Emit output
        now_str = datetime.now(timezone.utc).isoformat()
        self._output = QualifierOutput(
            judgment_id=f"qj_{now_str[:10].replace('-', '')}_{input_.session_id[-8:]}",
            timestamp=now_str,
            decision_track=track,
            track_confidence=min(1.0, max(0.0, coherence / 100.0)),
            signal_coherence_score=round(coherence, 1),
            reward_risk_ratio=round(ror, 2),
            decision_rationale=rationale,
            action_subtrack=subtrack,
            observe_scenario=scenario,
            key_indicators=indicators,
            causal_audit_refs=[s.source_id for s in input_.sources[:5]],
        )

        return self._output