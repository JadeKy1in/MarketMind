"""
belief_types.py — Phase 8.3.1 Belief State Manager Data Types

Defines the domain models that underpin the Belief State Manager.
Every belief node, observation, and conflict resolution is recorded
as an immutable Event Sourcing entry.

Five pillars (Phase 8.3 blueprint §8.3.1):
  1. BeliefNode         — A single Beta-distributed belief about a proposition
  2. BeliefObservation  — An atomic piece of evidence contributing to a belief
  3. ConflictRecord     — A conflict detected between two beliefs and its resolution
  4. BeliefRetirement   — A record of a belief being retired (confidence < θ)
  5. BeliefSnapshot     — A point-in-time snapshot of a belief node's full state

SPARC:
  Specification: all invariants enforced in __post_init__.
  Pseudocode: pure frozen dataclasses, no logic.
  Architecture: clean separation from shadow_types and event_store types.
  Refinement: no new dependencies beyond datetime and uuid.
  Completion: ready for belief_state_manager.py consumption.
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

class BeliefStatus(Enum):
    """Lifecycle status of a BeliefNode.

    ACTIVE         — Currently tracked, confidence >= θ threshold
    RETIRED        — Confidence dropped below θ, retired from active tracking
    CONFLICTED     — Temporarily locked while a ConflictRecord resolution is pending
    """
    ACTIVE = "active"
    RETIRED = "retired"
    CONFLICTED = "conflicted"


class ResolutionStrategy(Enum):
    """Strategies for resolving belief conflicts.

    OVERRIDE_HIGHER_CONFIDENCE  — The belief with higher confidence_score wins
    MERGE                       — Merge both evidence sets into a new combined node
    AMBIGUOUS_REJECT            — Both beliefs are deemed unreliable; reject both
    """
    OVERRIDE_HIGHER_CONFIDENCE = "override_higher_confidence"
    MERGE = "merge"
    AMBIGUOUS_REJECT = "ambiguous_reject"


class BeliefSource(Enum):
    """Source category for a belief observation.

    SHADOW_PREDICTION   — Originates from a ShadowPrediction verdict
    MARKET_DATA         — From raw market data hooks (alternative_data_hooks)
    MACRO_CALENDAR      — From macro_calendar economic events
    HUMAN_INPUT         — Manual PM override or annotation
    INFERRED            — Derived from other beliefs via conflict resolution
    """
    SHADOW_PREDICTION = "shadow_prediction"
    MARKET_DATA = "market_data"
    MACRO_CALENDAR = "macro_calendar"
    HUMAN_INPUT = "human_input"
    INFERRED = "inferred"


# ============================================================
# Helper Functions
# ============================================================

def _auto_iso() -> str:
    """Generate current UTC timestamp string in ISO-8601 with 'Z' suffix.

    Python 3.14 isoformat() already appends '+00:00', so we always
    produce a string without trailing timezone offset and append Z.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    ) + "Z"


def _auto_uuid() -> str:
    """Generate a random UUID4 string."""
    return str(uuid.uuid4())


def _default_zero_params() -> List[float]:
    """Default Beta parameters for a uniform prior Beta(1,1)."""
    return [1.0, 1.0]


# ============================================================
# Data Classes
# ============================================================

@dataclass(frozen=True)
class BeliefObservation:
    """A single atomic piece of evidence contributing to a belief.

    This is the fundamental unit of the append-only observation log.
    Each observation is immutable once recorded.

    Invariants (Phase 8.3.1):
      I1 — value must be in [0.0, 1.0] (clamped at ingestion)
      I2 — timestamp is fixed at creation
      I3 — source must be a valid BeliefSource enum value

    Args:
        value: The observation value [0.0, 1.0]. 1.0 = strong positive evidence,
               0.0 = strong negative evidence, 0.5 = neutral.
        source: Category of the evidence origin.
        confidence: How reliable this observation is [0.0, 1.0]. Default 1.0.
        timestamp: ISO-8601 string of creation time. Auto-generated if omitted.
        metadata: Optional dict for extensible context (e.g. ticker, prediction_id).
    """
    value: float
    source: BeliefSource
    confidence: float = 1.0
    timestamp: str = field(default_factory=_auto_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=_auto_uuid)

    def __post_init__(self) -> None:
        """Enforce invariants I1–I3."""
        # I1: value in [0.0, 1.0]
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(
                f"BeliefObservation value must be in [0.0, 1.0]; got {self.value}"
            )
        # I2: source must be a BeliefSource (validated by type system)
        if not isinstance(self.source, BeliefSource):
            raise TypeError(
                f"source must be a BeliefSource enum; got {type(self.source).__name__}"
            )
        # I3: confidence in [0.0, 1.0]
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeliefObservation":
        """Deserialize from a dict (as produced by to_dict)."""
        data = dict(data)  # shallow copy
        data["source"] = BeliefSource(data["source"])
        return cls(**data)


@dataclass(frozen=True)
class BeliefNode:
    """A single Beta-distributed belief about a proposition.

    A BeliefNode represents the system's current state of belief about
    a specific proposition (e.g. "TSLA will trend up"). The belief is
    parameterized as a Beta(alpha, beta) distribution.

    Invariants (Phase 8.3.1):
      I1 — alpha >= 1.0, beta >= 1.0 (corrected decay ensures this)
      I2 — status must be a valid BeliefStatus
      I3 — proposition_id is unique across all nodes

    Args:
        proposition: Human-readable description of the belief proposition.
        proposition_id: Unique identifier. Auto-generated if omitted.
        alpha: Beta distribution α parameter. Default 1.0 (uniform prior).
        beta: Beta distribution β parameter. Default 1.0 (uniform prior).
        status: Lifecycle status. Default ACTIVE.
        source: Primary source category for the node.
        created_at: ISO-8601 creation timestamp. Auto-generated if omitted.
        last_updated: ISO-8601 last-update timestamp. Auto-generated if omitted.
        metadata: Optional extensible context dict.
    """
    proposition: str
    proposition_id: str = field(default_factory=_auto_uuid)
    alpha: float = 1.0
    beta: float = 1.0
    status: BeliefStatus = BeliefStatus.ACTIVE
    source: BeliefSource = BeliefSource.INFERRED
    created_at: str = field(default_factory=_auto_iso)
    last_updated: str = field(default_factory=_auto_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce invariants I1–I3."""
        # I1: alpha >= 1.0, beta >= 1.0
        if self.alpha < 1.0:
            raise ValueError(
                f"alpha must be >= 1.0; got {self.alpha}. "
                "Gamma-corrected decay ensures this invariant."
            )
        if self.beta < 1.0:
            raise ValueError(
                f"beta must be >= 1.0; got {self.beta}. "
                "Gamma-corrected decay ensures this invariant."
            )
        # I2: status must be a BeliefStatus
        if not isinstance(self.status, BeliefStatus):
            raise TypeError(
                f"status must be a BeliefStatus enum; got {type(self.status).__name__}"
            )
        # I3: source must be a BeliefSource
        if not isinstance(self.source, BeliefSource):
            raise TypeError(
                f"source must be a BeliefSource enum; got {type(self.source).__name__}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d["status"] = self.status.value
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeliefNode":
        """Deserialize from a dict (as produced by to_dict)."""
        data = dict(data)  # shallow copy
        data["status"] = BeliefStatus(data["status"])
        data["source"] = BeliefSource(data["source"])
        return cls(**data)


@dataclass(frozen=True)
class ConflictRecord:
    """A conflict detected between two belief nodes and its resolution.

    Invariants (Phase 8.3.1):
      I1 — left_id and right_id must be different
      I2 — resolution must be a valid ResolutionStrategy
      I3 — conflict_id is unique across all conflicts

    Args:
        left_id: proposition_id of the first conflicting belief.
        right_id: proposition_id of the second conflicting belief.
        left_confidence: confidence_score of the left belief at conflict time.
        right_confidence: confidence_score of the right belief at conflict time.
        resolution: The strategy used to resolve the conflict.
        resolved_at: ISO-8601 resolution timestamp. Auto-generated if omitted.
        conflict_id: Unique identifier. Auto-generated if omitted.
        metadata: Optional extensible context dict.
    """
    left_id: str
    right_id: str
    left_confidence: float
    right_confidence: float
    resolution: ResolutionStrategy
    resolved_at: str = field(default_factory=_auto_iso)
    conflict_id: str = field(default_factory=_auto_uuid)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce invariants I1–I3."""
        # I1: must be different beliefs
        if self.left_id == self.right_id:
            raise ValueError(
                f"left_id and right_id must be different; got same '{self.left_id}'"
            )
        # I2: resolution must be a ResolutionStrategy
        if not isinstance(self.resolution, ResolutionStrategy):
            raise TypeError(
                f"resolution must be a ResolutionStrategy enum; "
                f"got {type(self.resolution).__name__}"
            )
        # Confidence scores must be in [0.0, 1.0]
        if not (0.0 <= self.left_confidence <= 1.0):
            raise ValueError(
                f"left_confidence must be in [0.0, 1.0]; got {self.left_confidence}"
            )
        if not (0.0 <= self.right_confidence <= 1.0):
            raise ValueError(
                f"right_confidence must be in [0.0, 1.0]; got {self.right_confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d["resolution"] = self.resolution.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictRecord":
        """Deserialize from a dict (as produced by to_dict)."""
        data = dict(data)
        data["resolution"] = ResolutionStrategy(data["resolution"])
        return cls(**data)


@dataclass(frozen=True)
class BeliefRetirement:
    """A record of a belief being retired due to confidence < θ.

    Invariants (Phase 8.3.1):
      I1 — retired_confidence < θ (enforced by manager, not type)

    Args:
        proposition_id: The retired belief's proposition_id.
        proposition: Human-readable description at time of retirement.
        reason: Why the belief was retired.
        retired_confidence: The confidence_score at retirement.
        threshold: The θ threshold that triggered retirement.
        retired_at: ISO-8601 timestamp. Auto-generated if omitted.
        retirement_id: Unique identifier. Auto-generated if omitted.
    """
    proposition_id: str
    proposition: str
    reason: str
    retired_confidence: float
    threshold: float = 0.1
    retired_at: str = field(default_factory=_auto_iso)
    retirement_id: str = field(default_factory=_auto_uuid)

    def __post_init__(self) -> None:
        """Validate numeric ranges."""
        if not (0.0 <= self.retired_confidence <= 1.0):
            raise ValueError(
                f"retired_confidence must be in [0.0, 1.0]; "
                f"got {self.retired_confidence}"
            )
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError(
                f"threshold must be in [0.0, 1.0]; got {self.threshold}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeliefRetirement":
        """Deserialize from a dict."""
        return cls(**data)


@dataclass(frozen=True)
class BeliefSnapshot:
    """A point-in-time snapshot of a belief node's full state.

    Used for memory-bank serialization, logging, and external querying.
    Not stored as a core event — computed on demand.

    Args:
        node: The snapshot of the BeliefNode at the given time.
        observation_count: Number of observations in the log.
        expectation: E[θ] = alpha / (alpha + beta).
        uncertainty: Var[θ] = (α·β) / ((α+β)² · (α+β+1)).
        score: confidence_score = expectation / (1 + uncertainty).
        status_label: Human-readable status string.
        timestamp: ISO-8601 snapshot time. Auto-generated.
    """
    node: BeliefNode
    observation_count: int
    expectation: float
    uncertainty: float
    score: float
    status_label: str
    timestamp: str = field(default_factory=_auto_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "proposition": self.node.proposition,
            "proposition_id": self.node.proposition_id,
            "alpha": self.node.alpha,
            "beta": self.node.beta,
            "status": self.node.status.value,
            "source": self.node.source.value,
            "observation_count": self.observation_count,
            "expectation": self.expectation,
            "uncertainty": self.uncertainty,
            "score": self.score,
            "status_label": self.status_label,
            "timestamp": self.timestamp,
        }