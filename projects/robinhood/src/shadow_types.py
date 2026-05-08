"""
shadow_types.py — Phase 8.0 / 8.1 Core Data Types for Shadow Mode & The Tribunal

Defines the domain models that underpin the Shadow Mode prediction pipeline and
the Tribunal's verdict system.  These types are the "schema as law" — every
prediction, verdict, and scenario is recorded as an immutable Event Sourcing
entry in event_store.py.

Four pillars (Phase 8 blueprint §8.0):
  1. ShadowPrediction     — A single absolute assertion about a ticker's future
  2. ShadowScenario       — Aggressive (bypass safety) / Ambiguous (micro-predict)
  3. TribunalVerdict      — Pass/fail judgement against realised market data
  4. BatchShadowRun       — Metadata envelope for a batch of predictions

SPARC:
  Specification: all invariants enforced in __post_init__.
  Pseudocode: pure dataclasses, no logic.
  Architecture: clean separation from decision_aggregator types.
  Refinement: no new dependencies beyond datetime and uuid.
  Completion: ready for event_store.py consumption.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# Enums
# ============================================================

class ShadowScenarioType(Enum):
    """Two core scenarios mandated by Phase 8.1 blueprint.

    AGGRESSIVE  — Bypass safety valves, buying-power limits; output max-levy bets.
    AMBIGUOUS   — Forced micro-prediction when signals conflict; never "Observe".
    """
    AGGRESSIVE = "aggressive"
    AMBIGUOUS = "ambiguous"


class PredictionTarget(Enum):
    """What the prediction is asserting about."""

    DIRECTIONAL_MOVE = "directional_move"
    RELATIVE_OUTPERFORM = "relative_outperform"
    VOLATILITY_BREAKOUT = "volatility_breakout"
    FLOW_REVERSAL = "flow_reversal"
    SUPPORT_BREAK = "support_break"
    RESISTANCE_BREAK = "resistance_break"


class ComparisonOperator(Enum):
    """Comparison operators for predictions."""
    LESS_THAN = "lt"
    GREATER_THAN = "gt"
    EQUAL = "eq"
    CROSS_BELOW = "cross_below"
    CROSS_ABOVE = "cross_above"


class VerdictStatus(Enum):
    """Tribunal's binary pass/fail judgement per prediction."""

    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    INVALID = "INVALID"


class ScenarioLabel(Enum):
    """Qualitative labels for shadow scenarios.

    Reifies the two Phase 8.1 scenario types into concrete labels:
      AGGRESSIVE_BULL  — Max-bull, safety-bypassed bet
      AGGRESSIVE_BEAR  — Max-bear, safety-bypassed bet
      AMBIGUOUS_MIXED  — Micro-prediction under mixed/conflicting signals
      AMBIGUOUS_FLAT   — Micro-prediction expecting range-bound price action
    """
    AGGRESSIVE_BULL = "aggressive_bull"
    AGGRESSIVE_BEAR = "aggressive_bear"
    AMBIGUOUS_MIXED = "ambiguous_mixed"
    AMBIGUOUS_FLAT = "ambiguous_flat"


class ShadowMode(Enum):
    """Execution mode selector for main.py routing."""
    AGGRESSIVE = "aggressive"
    AMBIGUOUS = "ambiguous"
    STRICT = "strict"


# ============================================================
# Type Aliases
# ============================================================

EventStoreRef = str
"""A reference string identifying an event store path or base_dir."""


# ============================================================
# Data Classes
# ============================================================

def _auto_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"


def _auto_uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class ShadowPrediction:
    """A single absolute assertion — the zero-hedging unit.

    Invariants (Phase 8.1 Zero-Hedging Protocol):
      I1 — assertion must NOT contain fuzzy words (checked by zero_hedging_validator)
      I2 — target_date must be in the future at creation time
      I3 — predicted_value must be precise (numeric, not range)
      I4 — confidence must be delivered as a hard number, not a band

    Positional constructor: ShadowPrediction(target_ticker, target_type,
                                             predicted_value, comparison_operator)
    """

    target_ticker: str = ""
    target_type: PredictionTarget = PredictionTarget.DIRECTIONAL_MOVE
    predicted_value: float = 0.0
    comparison_operator: str = "gt"

    # Unique identity (auto-generated if not provided)
    prediction_id: str = field(default_factory=_auto_uuid)

    # Optional metadata
    scenario_id: str = ""
    scenario_type: ShadowScenarioType = ShadowScenarioType.AGGRESSIVE
    assertion: str = ""                       # e.g. "TLT will close below 88.50"
    confidence: float = 100.0                 # Hard number 0-100 (NOT a band)
    reasoning: str = ""                       # Human-readable rationale

    # Temporal
    prediction_date: str = field(default_factory=_auto_iso)
    target_date: str = ""
    prediction_horizon_hours: int = 0

    # Traceability
    source_decision_track: str = ""
    was_safety_valve_bypassed: bool = False
    original_safety_valves: List[str] = field(default_factory=list)

    # Metadata for tribunal
    resolved_at: str = ""
    verdict: Optional[VerdictStatus] = None

    # Phase 8.3.2 — Belief system integration
    # Maps ticker symbol → belief_weight [0.0, 1.0] from BeliefStateManager.
    # The predictor queries active beliefs for the target ticker and adjusts
    # the final confidence score proportionally.
    belief_weights: Optional[Dict[str, float]] = None
    """Belief-driven weights per ticker. Populated by BeliefAwarePredictor.
    Keys: ticker symbols (e.g. 'TSLA', 'SPY').
    Values: weights in [0.0, 1.0] reflecting belief strength.
    None means no belief adjustment was applied."""

    @property
    def belief_adjusted_confidence(self) -> float:
        """Return the confidence score after belief-weight adjustment.

        If belief_weights is None or empty, returns the raw confidence.
        Otherwise, computes: adjusted = confidence * mean_belief_weight
        where mean_belief_weight is the average of all belief_weights values.

        This ensures predictions backed by strong active beliefs retain
        higher confidence, while predictions against weak/absent beliefs
        are penalized.
        """
        if not self.belief_weights:
            return self.confidence
        weights = list(self.belief_weights.values())
        if not weights:
            return self.confidence
        mean_weight = sum(weights) / len(weights)
        # Clamp to [0, 100]
        return max(0.0, min(100.0, self.confidence * mean_weight))

    def __post_init__(self) -> None:
        if not self.target_ticker:
            raise ValueError("target_ticker must not be empty")
        if self.confidence < 0.0 or self.confidence > 100.0:
            raise ValueError(f"confidence must be in [0, 100]; got {self.confidence}")

    @property
    def is_resolved(self) -> bool:
        return self.verdict is not None and self.verdict != VerdictStatus.PENDING


@dataclass(frozen=True)
class ShadowScenario:
    """A full scenario run for one ticker under one scenario label.

    Aggregates multiple ShadowPredictions that collectively represent the
    scenario's bet on a given ticker.
    """

    label: ScenarioLabel = ScenarioLabel.AGGRESSIVE_BULL
    predictions: List[ShadowPrediction] = field(default_factory=list)
    description: str = ""
    target_ticker: str = ""

    # Unique identity
    scenario_id: str = field(default_factory=_auto_uuid)

    # Macro context
    macro_theme: str = ""
    paradigm_anchors_snapshot: Optional[Dict[str, str]] = None
    original_decision_score: float = 0.0
    prediction_count: int = 0

    # Timestamps
    generated_at: str = field(default_factory=_auto_iso)
    executed_at: str = ""

    def __post_init__(self) -> None:
        if self.predictions:
            object.__setattr__(self, "prediction_count", len(self.predictions))

    def add_prediction(self, prediction: ShadowPrediction) -> ShadowScenario:
        """Return a new scenario with the prediction appended (immutable pattern)."""
        new_predictions = list(self.predictions) + [prediction]
        return ShadowScenario(
            label=self.label,
            predictions=new_predictions,
            description=self.description,
            target_ticker=self.target_ticker,
            scenario_id=self.scenario_id,
            macro_theme=self.macro_theme,
            paradigm_anchors_snapshot=self.paradigm_anchors_snapshot,
            original_decision_score=self.original_decision_score,
            prediction_count=len(new_predictions),
            generated_at=self.generated_at,
            executed_at=self.executed_at,
        )

    @property
    def scenario_type(self) -> ShadowScenarioType:
        """Derive scenario type from label."""
        if self.label in (ScenarioLabel.AGGRESSIVE_BULL, ScenarioLabel.AGGRESSIVE_BEAR):
            return ShadowScenarioType.AGGRESSIVE
        return ShadowScenarioType.AMBIGUOUS


@dataclass(frozen=True)
class TribunalVerdict:
    """The Tribunal's non-black-and-white judgement per prediction.

    Each prediction is matched against realised market data and assigned
    PASS or FAIL.  The verdict is itself an immutable event — written to
    the event store alongside the original prediction.

    Positional constructor: TribunalVerdict(prediction_id, target_ticker, status,
                                            deviation_pct, actual_close,
                                            predicted_value, reason)
    """

    prediction_id: str = ""
    target_ticker: str = ""
    status: VerdictStatus = VerdictStatus.PENDING
    deviation_pct: float = 0.0
    actual_close: float = 0.0
    predicted_value: float = 0.0
    reason: str = ""

    # Unique identity (auto-generated if not provided)
    verdict_id: str = field(default_factory=_auto_uuid)
    scenario_id: str = ""
    tolerance_pct: float = 5.0

    # Context at judgement time
    market_data_snapshot: Dict[str, Any] = field(default_factory=dict)
    verdict_date: str = field(default_factory=_auto_iso)

    def __post_init__(self) -> None:
        if not self.prediction_id:
            raise ValueError("prediction_id must not be empty")
        if self.tolerance_pct < 0:
            raise ValueError(f"tolerance_pct must be >= 0; got {self.tolerance_pct}")

    @property
    def passed(self) -> bool:
        return self.status == VerdictStatus.PASS

    @property
    def actual_value(self) -> float:
        """Alias for actual_close — backward compat with Phase 8.0 event_store."""
        return self.actual_close

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "verdict_id": self.verdict_id,
            "prediction_id": self.prediction_id,
            "scenario_id": self.scenario_id,
            "target_ticker": self.target_ticker,
            "status": self.status.value,
            "deviation_pct": self.deviation_pct,
            "actual_close": self.actual_close,
            "predicted_value": self.predicted_value,
            "reason": self.reason,
            "tolerance_pct": self.tolerance_pct,
            "market_data_snapshot": self.market_data_snapshot,
            "verdict_date": self.verdict_date,
        }


@dataclass(frozen=True)
class BatchShadowRun:
    """Top-level envelope for a single shadow-mode batch execution.

    Contains all scenarios (one or more per ticker) generated in one batch pass.
    The entire batch is committed to the event store as a single atomic event.

    Positional constructor: BatchShadowRun(tickers, scenarios, mode)
    """

    tickers: List[str] = field(default_factory=list)
    scenarios: List[ShadowScenario] = field(default_factory=list)
    mode: ShadowMode = ShadowMode.AGGRESSIVE

    # Unique identity (auto-generated if not provided)
    batch_id: str = field(default_factory=_auto_uuid)
    generated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    total_predictions: int = 0

    # Source
    source_reports: List[str] = field(default_factory=list)
    account_snapshot_id: str = ""

    def __post_init__(self) -> None:
        # Calculate total predictions from scenarios
        total = sum(len(s.predictions) for s in self.scenarios)
        object.__setattr__(self, "total_predictions", total)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        mode_val = self.mode.value if isinstance(self.mode, ShadowMode) else str(self.mode)
        return {
            "batch_id": self.batch_id,
            "mode": mode_val,
            "generated_at": self.generated_at.isoformat() if isinstance(self.generated_at, datetime.datetime) else str(self.generated_at),
            "tickers": list(self.tickers),
            "scenarios": [
                {
                    "scenario_id": s.scenario_id,
                    "label": s.label.value,
                    "target_ticker": s.target_ticker,
                    "predictions": [
                        {
                            "prediction_id": p.prediction_id,
                            "target_ticker": p.target_ticker,
                            "target_type": p.target_type.value,
                            "predicted_value": p.predicted_value,
                            "comparison_operator": p.comparison_operator,
                            "assertion": p.assertion,
                            "confidence": p.confidence,
                            "reasoning": p.reasoning,
                            "prediction_date": p.prediction_date,
                        }
                        for p in s.predictions
                    ],
                    "prediction_count": s.prediction_count,
                }
                for s in self.scenarios
            ],
            "total_predictions": self.total_predictions,
            "source_reports": list(self.source_reports),
            "account_snapshot_id": self.account_snapshot_id,
        }