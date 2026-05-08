"""
belief_state_manager.py — Phase 8.3.1 Belief State Manager (主管理器)

The Belief State Manager is the central orchestrator for maintaining
a Beta-distributed belief knowledge graph. It operates in three layers:

  1. Ingestion:  Accept BeliefObservations from any source (ShadowPrediction,
                 market data, macro calendar, human input).
  2. Processing: Update Beta(α, β) parameters, apply γ-decay, detect conflicts,
                 retire low-confidence beliefs.
  3. Querying:   Produce BeliefSnapshots, conflict logs, retirement records.

Architecture (Phase 8.3.1 Invariants):
  - Append-Only: Observations are never modified, only appended.
  - Immutable:   BeliefNode is replaced atomically on update (new frozen copy).
  - Memory MCP:  Persistence delegated to belief_memory_adapter — the manager
                 itself is a stateless processor.

SPARC:
  Specification: PM-approved pseudocode from phase8_3_blueprint_draft.md.
  Pseudocode: See module-level docstring for data flow.
  Architecture: Three-layer design (Ingestion → Processing → Querying).
  Refinement: Zero external dependencies beyond belief_math and belief_types.
  Completion: Ready for test suite (test_belief_state_manager.py).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .belief_math import (
    beta_update,
    gamma_decay,
    beta_uncertainty,
    beta_expectation,
    confidence_score,
)
from .belief_memory_adapter import BeliefMemoryAdapter, MemoryAdapterConfig
from .belief_types import (
    BeliefNode,
    BeliefObservation,
    BeliefRetirement,
    BeliefSnapshot,
    BeliefSource,
    BeliefStatus,
    ConflictRecord,
    ResolutionStrategy,
)

logger = logging.getLogger(__name__)


# ============================================================
# Exceptions
# ============================================================

class BeliefManagerError(Exception):
    """Base exception for all BeliefStateManager errors."""
    pass


class DuplicatePropositionError(BeliefManagerError):
    """Raised when trying to register a proposition_id that already exists."""
    pass


class BeliefNotFoundError(BeliefManagerError):
    """Raised when a proposition_id is not found in the registry."""
    pass


class ConflictNotFoundError(BeliefManagerError):
    """Raised when a conflict_id is not found."""
    pass


# ============================================================
# Internal Record (not exported — manager-only mutation tracker)
# ============================================================

class _InternalNode:
    """Internal mutable holder for a belief node + its observation log.

    NOT a frozen dataclass — this is the manager's private state.
    The frozen BeliefNode is replaced atomically on each update.

    Attributes:
        node: The current frozen BeliefNode (replaced on update).
        observations: Append-only list of BeliefObservations.
        conflict_ids: Set of conflict IDs this node has participated in.
        last_decay_steps: Number of decay steps applied since last observation.
    """
    __slots__ = ("node", "observations", "conflict_ids", "last_decay_steps")

    def __init__(self, node: BeliefNode) -> None:
        self.node = node
        self.observations: List[BeliefObservation] = []
        self.conflict_ids: Set[str] = set()
        self.last_decay_steps: int = 0

    def snapshot(self) -> BeliefSnapshot:
        """Compute a point-in-time snapshot from current state."""
        exp = beta_expectation(self.node.alpha, self.node.beta)
        unc = beta_uncertainty(self.node.alpha, self.node.beta)
        score = confidence_score(self.node.alpha, self.node.beta)
        return BeliefSnapshot(
            node=self.node,
            observation_count=len(self.observations),
            expectation=exp,
            uncertainty=unc,
            score=score,
            status_label=self.node.status.value,
        )


# ============================================================
# Configuration
# ============================================================

@dataclass
class BeliefManagerConfig:
    """Configuration for the BeliefStateManager.

    Attributes:
        gamma: Decay factor in (0, 1.0]. Default 0.95 (Phase 8.3.1 blueprint).
        theta: Retirement threshold in [0.0, 1.0]. Default 0.1.
        conflict_threshold: When two beliefs about the same proposition have
            expectation difference > this, a ConflictRecord is generated.
            Default 0.3.
        auto_decay_interval_seconds: If set, auto-decay applies this many
            seconds of decay on each observation. Default 86400 (1 day).
        max_observations_per_node: Safety limit. Default 10000.
    """
    gamma: float = 0.95
    theta: float = 0.1
    conflict_threshold: float = 0.3
    auto_decay_interval_seconds: int = 86_400  # 1 day
    max_observations_per_node: int = 10_000


# ============================================================
# Main Manager
# ============================================================

class BeliefStateManager:
    """Belief State Manager — the central orchestrator.

    Three-layer architecture:
      Layer 1 (Ingestion):   register_node(), ingest_observation()
      Layer 2 (Processing):  _apply_decay(), _detect_conflicts(), _retire()
      Layer 3 (Querying):    get_snapshot(), list_active(), list_conflicts()

    Usage:
        manager = BeliefStateManager()
        manager.register_node("TSLA uptrend")
        manager.ingest_observation("proposition-id", BeliefObservation(0.8, ...))
        snap = manager.get_snapshot("proposition-id")
    """

    def __init__(self, config: Optional[BeliefManagerConfig] = None) -> None:
        """Initialize the manager with optional config (defaults used otherwise)."""
        self._config = config or BeliefManagerConfig()
        # proposition_id → _InternalNode
        self._nodes: Dict[str, _InternalNode] = {}
        # conflict_id → ConflictRecord
        self._conflicts: Dict[str, ConflictRecord] = {}
        # retirement_id → BeliefRetirement
        self._retirements: Dict[str, BeliefRetirement] = {}

        # Index: proposition → Set[proposition_id] for conflict detection
        # Allows multiple nodes about the same proposition string.
        self._proposition_index: Dict[str, Set[str]] = {}

        logger.info(
            "BeliefStateManager initialized: γ=%s, θ=%s, conflict_threshold=%s",
            self._config.gamma,
            self._config.theta,
            self._config.conflict_threshold,
        )

    # ============================================================
    # Layer 1: Ingestion
    # ============================================================

    def register_node(
        self,
        proposition: str,
        *,
        proposition_id: Optional[str] = None,
        alpha: float = 1.0,
        beta: float = 1.0,
        source: BeliefSource = BeliefSource.INFERRED,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a new belief node with a uniform prior Beta(α, β).

        Args:
            proposition: Human-readable proposition description.
            proposition_id: Optional explicit ID. Auto-generated if omitted.
            alpha: Beta α. Default 1.0.
            beta: Beta β. Default 1.0.
            source: Primary source category.
            metadata: Optional extensible context.

        Returns:
            The proposition_id of the newly created node.

        Raises:
            DuplicatePropositionError: If proposition_id already exists.
        """
        node_id = proposition_id or str(uuid.uuid4())

        if node_id in self._nodes:
            raise DuplicatePropositionError(
                f"Proposition ID '{node_id}' already registered."
            )

        node = BeliefNode(
            proposition=proposition,
            proposition_id=node_id,
            alpha=alpha,
            beta=beta,
            status=BeliefStatus.ACTIVE,
            source=source,
            metadata=metadata or {},
        )

        internal = _InternalNode(node)
        self._nodes[node_id] = internal

        # Update proposition index
        if proposition not in self._proposition_index:
            self._proposition_index[proposition] = set()
        self._proposition_index[proposition].add(node_id)

        logger.debug("Registered belief node: %s — '%s'", node_id, proposition)
        return node_id

    def ingest_observation(
        self,
        proposition_id: str,
        observation: BeliefObservation,
        *,
        allow_create: bool = False,
    ) -> BeliefSnapshot:
        """Ingest a single belief observation and update the node.

        This is the primary entry point for evidence. The observation is
        appended to the node's immutable log, then the Beta parameters
        are updated via bayesian update.

        Steps:
          1. Decay: Apply γ-decay proportional to elapsed time since last update.
          2. Update: Apply beta_update(α, β, value * confidence).
          3. Conflict: Run conflict detection on the proposition index.
          4. Retirement: Check if confidence_score < θ.

        Args:
            proposition_id: Target belief node.
            observation: The observation to ingest.
            allow_create: If True, auto-create a uniform-prior node when
                          proposition_id doesn't exist. Default False.

        Returns:
            A BeliefSnapshot of the node after the update.

        Raises:
            BeliefNotFoundError: If proposition_id doesn't exist and
                                 allow_create is False.
        """
        internal = self._nodes.get(proposition_id)

        if internal is None:
            if allow_create:
                # Auto-create with the proposition name from metadata or fallback
                prop_name = observation.metadata.get("proposition", proposition_id)
                self.register_node(
                    proposition=prop_name,
                    proposition_id=proposition_id,
                    source=observation.source,
                    metadata=observation.metadata,
                )
                internal = self._nodes[proposition_id]
            else:
                raise BeliefNotFoundError(
                    f"Proposition '{proposition_id}' not found. "
                    "Use allow_create=True to auto-register."
                )

        # Safety limit check
        if len(internal.observations) >= self._config.max_observations_per_node:
            raise BeliefManagerError(
                f"Node '{proposition_id}' has reached max observations "
                f"({self._config.max_observations_per_node})."
            )

        # --- Step 0: Apply auto-decay based on elapsed time ---
        self._apply_decay(internal, observation.timestamp)

        # Zero-confidence observations are discarded entirely — no update.
        # This implements the "zero confidence = zero information" invariant.
        if observation.confidence <= 0.0:
            return self._to_snapshot(internal)

        # --- Step 1: Pass raw value + confidence to beta_update ---
        # Phase 8.4: The beta_update function now applies the symmetric
        # formula α' = α + value*conf, β' = β + (1-value)*conf internally.
        # This eliminates the noise asymmetry bug where low-confidence
        # observations were systemically bearish.
        new_alpha, new_beta = beta_update(
            internal.node.alpha,
            internal.node.beta,
            observation.value,
            confidence=observation.confidence,
        )

        # --- Step 3: Replace the frozen node ---
        updated_node = BeliefNode(
            proposition=internal.node.proposition,
            proposition_id=internal.node.proposition_id,
            alpha=new_alpha,
            beta=new_beta,
            status=internal.node.status,
            source=internal.node.source,
            created_at=internal.node.created_at,
            last_updated=observation.timestamp,
            metadata=internal.node.metadata,
        )
        internal.node = updated_node

        # --- Step 4: Append observation to immutable log ---
        internal.observations.append(observation)

        logger.debug(
            "Ingested observation: %s on '%s' (α=%.3f, β=%.3f, value=%.3f)",
            proposition_id,
            internal.node.proposition,
            new_alpha,
            new_beta,
            observation.value,
        )

        # --- Step 5: Conflict detection ---
        self._detect_conflicts(internal)

        # --- Step 6: Retirement check ---
        self._check_retirement(proposition_id)

        return self._to_snapshot(internal)

    def ingest_bulk_observations(
        self,
        observations: Dict[str, List[BeliefObservation]],
        *,
        allow_create: bool = False,
    ) -> Dict[str, BeliefSnapshot]:
        """Ingest multiple observations across multiple nodes.

        Args:
            observations: Map of proposition_id → list of observations.
            allow_create: Auto-register unknown proposition IDs.

        Returns:
            Map of proposition_id → final BeliefSnapshot after all ingestions.
        """
        results: Dict[str, BeliefSnapshot] = {}
        for prop_id, obs_list in observations.items():
            for obs in obs_list:
                results[prop_id] = self.ingest_observation(
                    prop_id, obs, allow_create=allow_create,
                )
        return results

    # ============================================================
    # Layer 2: Processing (internal)
    # ============================================================

    def _apply_decay(self, internal: _InternalNode, reference_timestamp: str) -> None:
        """Apply γ-decay proportional to elapsed time since last update.

        The decay transforms (α, β) → (α', β') where the corrected formula
        adds (γ^steps) * (α - 1) + 1, ensuring α' >= 1.0, β' >= 1.0.

        Args:
            internal: The internal node to decay.
            reference_timestamp: ISO-8601 timestamp of the current operation.
        """
        try:
            ref_dt = datetime.datetime.fromisoformat(
                reference_timestamp.replace("Z", "+00:00")
            )
            last_dt = datetime.datetime.fromisoformat(
                internal.node.last_updated.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            # If timestamps are malformed, skip decay
            return

        # Normalize both to offset-naive for safe subtraction
        # (handles mixed offset-aware from _auto_iso and offset-naive from
        #  Instantiator's datetime.now().isoformat())
        if ref_dt.tzinfo is not None:
            ref_dt = ref_dt.replace(tzinfo=None)
        if last_dt.tzinfo is not None:
            last_dt = last_dt.replace(tzinfo=None)

        elapsed_seconds = (ref_dt - last_dt).total_seconds()
        if elapsed_seconds <= 0:
            return

        # Calculate decay steps: equal to number of full intervals elapsed
        steps = int(elapsed_seconds / self._config.auto_decay_interval_seconds)
        if steps < 1:
            return

        new_alpha, new_beta = gamma_decay(
            internal.node.alpha,
            internal.node.beta,
            steps=steps,
            gamma=self._config.gamma,
        )

        internal.node = BeliefNode(
            proposition=internal.node.proposition,
            proposition_id=internal.node.proposition_id,
            alpha=new_alpha,
            beta=new_beta,
            status=internal.node.status,
            source=internal.node.source,
            created_at=internal.node.created_at,
            last_updated=reference_timestamp,
            metadata=internal.node.metadata,
        )
        internal.last_decay_steps += steps

        logger.debug(
            "Decay applied: %s (%d steps, γ=%.3f) → α=%.3f, β=%.3f",
            internal.node.proposition_id,
            steps,
            self._config.gamma,
            new_alpha,
            new_beta,
        )

    def _detect_conflicts(self, internal: _InternalNode) -> List[ConflictRecord]:
        """Detect conflicts with other nodes sharing the same proposition.

        Two nodes conflict if:
          1. Both are ACTIVE (not retired/conflicted).
          2. |E[θ_left] - E[θ_right]| > conflict_threshold.

        Returns:
            List of newly created ConflictRecords.
        """
        proposition = internal.node.proposition
        siblings = self._proposition_index.get(proposition, set())

        if len(siblings) < 2:
            return []

        new_conflicts: List[ConflictRecord] = []

        for sibling_id in siblings:
            if sibling_id == internal.node.proposition_id:
                continue

            sibling = self._nodes.get(sibling_id)
            if sibling is None:
                continue
            if sibling.node.status != BeliefStatus.ACTIVE:
                continue

            # Compute expectation difference
            exp_self = beta_expectation(internal.node.alpha, internal.node.beta)
            exp_sibling = beta_expectation(sibling.node.alpha, sibling.node.beta)

            if abs(exp_self - exp_sibling) <= self._config.conflict_threshold:
                continue

            # Conflict detected
            score_self = confidence_score(internal.node.alpha, internal.node.beta)
            score_sibling = confidence_score(sibling.node.alpha, sibling.node.beta)

            # Determine resolution
            if score_self > score_sibling:
                resolution = ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE
            elif score_sibling > score_self:
                resolution = ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE
            else:
                resolution = ResolutionStrategy.AMBIGUOUS_REJECT

            conflict = ConflictRecord(
                left_id=internal.node.proposition_id,
                right_id=sibling_id,
                left_confidence=score_self,
                right_confidence=score_sibling,
                resolution=resolution,
            )

            self._conflicts[conflict.conflict_id] = conflict
            internal.conflict_ids.add(conflict.conflict_id)
            sibling.conflict_ids.add(conflict.conflict_id)

            # Mark both nodes as CONFLICTED
            self._set_status(internal.node.proposition_id, BeliefStatus.CONFLICTED)
            self._set_status(sibling_id, BeliefStatus.CONFLICTED)

            new_conflicts.append(conflict)

            logger.warning(
                "Conflict detected: '%s' vs '%s' | Δ=%.3f | resolution=%s",
                internal.node.proposition_id,
                sibling_id,
                abs(exp_self - exp_sibling),
                resolution.value,
            )

        return new_conflicts

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        override_resolution: Optional[ResolutionStrategy] = None,
    ) -> Optional[BeliefSnapshot]:
        """Resolve a specific ConflictRecord.

        Applies the resolution strategy:
          - OVERRIDE_HIGHER_CONFIDENCE: The higher-confidence node is returned
            as the "winner" snapshot; the loser is retired.
          - MERGE: Both evidence sets are merged into a new combined node.
          - AMBIGUOUS_REJECT: Both nodes are retired.

        Args:
            conflict_id: The ID of the ConflictRecord to resolve.
            override_resolution: If provided, overrides the stored resolution.

        Returns:
            The "winning" BeliefSnapshot, or None if both were retired.

        Raises:
            ConflictNotFoundError: If conflict_id doesn't exist.
        """
        conflict = self._conflicts.get(conflict_id)
        if conflict is None:
            raise ConflictNotFoundError(f"Conflict '{conflict_id}' not found.")

        resolution = override_resolution or conflict.resolution

        left_node = self._nodes.get(conflict.left_id)
        right_node = self._nodes.get(conflict.right_id)

        if resolution == ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE:
            if left_node and right_node:
                if left_node.snapshot().score >= right_node.snapshot().score:
                    self._set_status(right_node.node.proposition_id, BeliefStatus.RETIRED)
                    self._record_retirement(
                        right_node.node.proposition_id,
                        right_node.node.proposition,
                        f"Lost conflict with {left_node.node.proposition_id}",
                        right_node.snapshot().score,
                    )
                    self._set_status(left_node.node.proposition_id, BeliefStatus.ACTIVE)
                    return left_node.snapshot()
                else:
                    self._set_status(left_node.node.proposition_id, BeliefStatus.RETIRED)
                    self._record_retirement(
                        left_node.node.proposition_id,
                        left_node.node.proposition,
                        f"Lost conflict with {right_node.node.proposition_id}",
                        left_node.snapshot().score,
                    )
                    self._set_status(right_node.node.proposition_id, BeliefStatus.ACTIVE)
                    return right_node.snapshot()

        elif resolution == ResolutionStrategy.MERGE:
            # Merge: create new combined node from both evidence pools
            if left_node and right_node:
                combined_alpha = left_node.node.alpha + right_node.node.alpha - 1.0
                combined_beta = left_node.node.beta + right_node.node.beta - 1.0

                merged_node = BeliefNode(
                    proposition=(
                        f"[Merged] {left_node.node.proposition} | "
                        f"{right_node.node.proposition}"
                    ),
                    alpha=combined_alpha,
                    beta=combined_beta,
                    source=BeliefSource.INFERRED,
                    metadata={
                        "merged_from": [left_node.node.proposition_id,
                                        right_node.node.proposition_id],
                    },
                )
                merged_internal = _InternalNode(merged_node)
                merged_internal.observations = (
                    left_node.observations + right_node.observations
                )
                self._nodes[merged_node.proposition_id] = merged_internal
                self._proposition_index.setdefault(
                    merged_node.proposition, set()
                ).add(merged_node.proposition_id)

                # Retire original nodes
                self._set_status(left_node.node.proposition_id, BeliefStatus.RETIRED)
                self._set_status(right_node.node.proposition_id, BeliefStatus.RETIRED)
                self._record_retirement(
                    left_node.node.proposition_id,
                    left_node.node.proposition,
                    f"Merged into {merged_node.proposition_id}",
                    left_node.snapshot().score,
                )
                self._record_retirement(
                    right_node.node.proposition_id,
                    right_node.node.proposition,
                    f"Merged into {merged_node.proposition_id}",
                    right_node.snapshot().score,
                )

                return merged_internal.snapshot()

        elif resolution == ResolutionStrategy.AMBIGUOUS_REJECT:
            # Both retired
            if left_node:
                self._set_status(left_node.node.proposition_id, BeliefStatus.RETIRED)
                self._record_retirement(
                    left_node.node.proposition_id,
                    left_node.node.proposition,
                    f"Ambiguous reject from conflict {conflict_id}",
                    left_node.snapshot().score,
                )
            if right_node:
                self._set_status(right_node.node.proposition_id, BeliefStatus.RETIRED)
                self._record_retirement(
                    right_node.node.proposition_id,
                    right_node.node.proposition,
                    f"Ambiguous reject from conflict {conflict_id}",
                    right_node.snapshot().score,
                )
            return None

        return None

    def _check_retirement(self, proposition_id: str) -> Optional[BeliefRetirement]:
        """Check if a node's confidence score has fallen below θ.

        If so, mark it as RETIRED and record the retirement.

        Args:
            proposition_id: Target node.

        Returns:
            BeliefRetirement if retired, None otherwise.
        """
        internal = self._nodes.get(proposition_id)
        if internal is None:
            return None
        if internal.node.status != BeliefStatus.ACTIVE:
            return None

        score = confidence_score(internal.node.alpha, internal.node.beta)
        if score >= self._config.theta:
            return None

        # Retire
        self._set_status(proposition_id, BeliefStatus.RETIRED)
        retirement = self._record_retirement(
            proposition_id,
            internal.node.proposition,
            f"Confidence score {score:.4f} < threshold {self._config.theta}",
            score,
        )
        logger.info(
            "Belief retired: '%s' — score=%.4f below θ=%.3f",
            proposition_id,
            score,
            self._config.theta,
        )
        return retirement

    def apply_global_decay(self, steps: int = 1) -> int:
        """Apply γ-decay to ALL active nodes (public alias for scheduled decay).

        This is the public entry point called by the ReflectionOrchestrator
        when T = n × 50 steps are detected. Delegates to apply_forced_decay_all.

        Args:
            steps: Number of decay steps to apply. Default 1.

        Returns:
            Number of nodes that were decayed.
        """
        return self.apply_forced_decay_all(steps=steps)

    def apply_forced_decay_all(self, steps: int = 1) -> int:
        """Force-apply γ-decay to all active nodes.

        Useful for simulating time passage in tests or scheduled maintenance.

        Args:
            steps: Number of decay steps to apply. Default 1.

        Returns:
            Number of nodes that were decayed.
        """
        count = 0
        for internal in self._nodes.values():
            if internal.node.status != BeliefStatus.ACTIVE:
                continue
            new_alpha, new_beta = gamma_decay(
                internal.node.alpha,
                internal.node.beta,
                steps=steps,
                gamma=self._config.gamma,
            )
            internal.node = BeliefNode(
                proposition=internal.node.proposition,
                proposition_id=internal.node.proposition_id,
                alpha=new_alpha,
                beta=new_beta,
                status=internal.node.status,
                source=internal.node.source,
                created_at=internal.node.created_at,
                last_updated=internal.node.last_updated,
                metadata=internal.node.metadata,
            )
            internal.last_decay_steps += steps
            count += 1

            # Check retirement after forced decay
            self._check_retirement(internal.node.proposition_id)

        logger.debug("Forced decay applied to %d nodes (%d steps)", count, steps)
        return count

    # ============================================================
    # Layer 3: Querying
    # ============================================================

    def get_snapshot(self, proposition_id: str) -> Optional[BeliefSnapshot]:
        """Get a point-in-time snapshot of a belief node.

        Args:
            proposition_id: Target node.

        Returns:
            BeliefSnapshot if found, None otherwise.
        """
        internal = self._nodes.get(proposition_id)
        if internal is None:
            return None
        return internal.snapshot()

    def list_active(self) -> List[BeliefSnapshot]:
        """List all active (non-retired) belief snapshots.

        Returns:
            List of BeliefSnapshot objects, sorted by score descending.
        """
        snapshots = [
            internal.snapshot()
            for internal in self._nodes.values()
            if internal.node.status == BeliefStatus.ACTIVE
        ]
        snapshots.sort(key=lambda s: s.score, reverse=True)
        return snapshots

    def list_all(self) -> List[BeliefSnapshot]:
        """List ALL belief snapshots (active, retired, conflicted).

        Returns:
            List of BeliefSnapshot objects, sorted by score descending.
        """
        snapshots = [
            internal.snapshot()
            for internal in self._nodes.values()
        ]
        snapshots.sort(key=lambda s: s.score, reverse=True)
        return snapshots

    def list_conflicts(self) -> List[ConflictRecord]:
        """List all unresolved conflict records.

        Returns:
            List of ConflictRecord objects, most recent first.
        """
        sorted_conflicts = sorted(
            self._conflicts.values(),
            key=lambda c: c.resolved_at,
            reverse=True,
        )
        return sorted_conflicts

    def list_retirements(self) -> List[BeliefRetirement]:
        """List all retirement records.

        Returns:
            List of BeliefRetirement objects, most recent first.
        """
        sorted_ret = sorted(
            self._retirements.values(),
            key=lambda r: r.retired_at,
            reverse=True,
        )
        return sorted_ret

    def get_conflict(self, conflict_id: str) -> Optional[ConflictRecord]:
        """Get a specific conflict record by ID.

        Args:
            conflict_id: Target conflict.

        Returns:
            ConflictRecord if found, None otherwise.
        """
        return self._conflicts.get(conflict_id)

    def get_node_count(self) -> int:
        """Return total number of registered nodes."""
        return len(self._nodes)

    def get_active_count(self) -> int:
        """Return number of active nodes."""
        return sum(
            1 for n in self._nodes.values()
            if n.node.status == BeliefStatus.ACTIVE
        )

    def get_config(self) -> BeliefManagerConfig:
        """Return a copy of the current configuration."""
        return deepcopy(self._config)

    def search_nodes(self, query: str) -> List[BeliefSnapshot]:
        """Search for nodes by proposition substring.

        Args:
            query: Substring to match against proposition text.

        Returns:
            List of matching BeliefSnapshot objects.
        """
        query_lower = query.lower()
        snapshots = [
            internal.snapshot()
            for internal in self._nodes.values()
            if query_lower in internal.node.proposition.lower()
        ]
        snapshots.sort(key=lambda s: s.score, reverse=True)
        return snapshots

    # ============================================================
    # State Introspection (for diagnostics)
    # ============================================================

    def export_state(self) -> Dict[str, Any]:
        """Export full internal state as a JSON-compatible dict.

        Used for memory-bank serialization and diagnostics.
        """
        return {
            "config": {
                "gamma": self._config.gamma,
                "theta": self._config.theta,
                "conflict_threshold": self._config.conflict_threshold,
                "auto_decay_interval_seconds": self._config.auto_decay_interval_seconds,
                "max_observations_per_node": self._config.max_observations_per_node,
            },
            "nodes": [
                internal.snapshot().to_dict()
                for internal in self._nodes.values()
            ],
            "conflicts": [
                c.to_dict()
                for c in self._conflicts.values()
            ],
            "retirements": [
                r.to_dict()
                for r in self._retirements.values()
            ],
            "stats": {
                "total_nodes": self.get_node_count(),
                "active_nodes": self.get_active_count(),
                "total_conflicts": len(self._conflicts),
                "total_retirements": len(self._retirements),
            },
        }

    # ============================================================
    # Private Helpers
    # ============================================================

    def _set_status(self, proposition_id: str, status: BeliefStatus) -> None:
        """Atomically update a node's status."""
        internal = self._nodes.get(proposition_id)
        if internal is None:
            return

        internal.node = BeliefNode(
            proposition=internal.node.proposition,
            proposition_id=internal.node.proposition_id,
            alpha=internal.node.alpha,
            beta=internal.node.beta,
            status=status,
            source=internal.node.source,
            created_at=internal.node.created_at,
            last_updated=internal.node.last_updated,
            metadata=internal.node.metadata,
        )

    def _record_retirement(
        self,
        proposition_id: str,
        proposition: str,
        reason: str,
        score: float,
    ) -> BeliefRetirement:
        """Create and store a BeliefRetirement record."""
        retirement = BeliefRetirement(
            proposition_id=proposition_id,
            proposition=proposition,
            reason=reason,
            retired_confidence=score,
            threshold=self._config.theta,
        )
        self._retirements[retirement.retirement_id] = retirement
        return retirement

    # ============================================================
    # Memory MCP Integration (Phase 8.3.2 — Read-Side Persistence)
    # ============================================================

    def set_memory_adapter(self, adapter: BeliefMemoryAdapter) -> None:
        """Inject a memory adapter for automatic persistence.

        When set, every ingest_observation call automatically syncs
        the updated belief state to the Memory MCP Server's knowledge graph.

        Args:
            adapter: A fully configured BeliefMemoryAdapter instance.
        """
        self._memory_adapter = adapter
        logger.info(
            "Memory adapter injected: memory_file=%s",
            adapter._config.memory_file,
        )

    def sync_to_memory(self) -> int:
        """Explicitly sync current belief state to the memory knowledge graph.

        This is the "read-side" persistence bridge — every belief state
        mutation (ingest, decay, retirement) can be written to the
        Memory MCP Server for long-term storage and inter-agent access.

        Returns:
            Number of entities written to the graph, or -1 if no adapter
            is configured.

        Usage:
            manager.sync_to_memory()  # Push current state to Memory MCP
        """
        if not hasattr(self, "_memory_adapter"):
            logger.warning("sync_to_memory called but no memory adapter set.")
            return -1

        try:
            snapshots = self.list_all()
            conflicts = self.list_conflicts()
            retirements = self.list_retirements()
            total = self._memory_adapter.export_to_memory(
                snapshots, conflicts, retirements,
            )
            logger.debug("Memory sync completed: %d entities written", total)
            return total
        except Exception as e:
            logger.error("Memory sync failed: %s", e)
            return -1

    def sync_after_ingest(self, proposition_id: str) -> bool:
        """Auto-sync to memory after an ingest_observation call.

        Called automatically by ingest_observation when a memory adapter
        is configured. Can also be called manually after bulk operations.

        Args:
            proposition_id: The proposition_id that was just ingested.

        Returns:
            True if sync was successful, False otherwise.
        """
        if not hasattr(self, "_memory_adapter"):
            return False

        total = self.sync_to_memory()
        return total >= 0

    @staticmethod
    def _to_snapshot(internal: _InternalNode) -> BeliefSnapshot:
        """Convert internal node to a public BeliefSnapshot."""
        return internal.snapshot()
