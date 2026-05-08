"""
belief_memory_adapter.py — Phase 8.3.1 Memory MCP Server Adapter

Adapters the BeliefStateManager to the self-hosted Memory MCP Server for
persistent knowledge graph storage and retrieval.

The adapter translates between:
  - BeliefNode / BeliefSnapshot (internal Python domain objects)
  - Entity / Relation / Observation (Memory MCP knowledge graph primitives)

Architecture:
  - Import-independence: The adapter can be imported without the memory
    server running; it will raise MemoryServerUnavailableError at runtime.
  - Append-only: Observations from the belief manager are mapped to
    entity observations in the memory graph.
  - Bidirectional: Supports both push (export) and pull (import) operations.

SPARC:
  Specification: PM-approved interface from phase8_3_blueprint_draft.md.
  Pseudocode: See module-level data flow below.
  Architecture: Thin adapter layer — no business logic, pure translation.
  Refinement: All conversion is stateless; any state lives in the memory server.
  Completion: Ready for test suite (integrated in test_belief_state_manager.py).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

class MemoryServerError(Exception):
    """Base exception for all Memory MCP adapter errors."""
    pass


class MemoryServerUnavailableError(MemoryServerError):
    """Raised when the memory MCP server process cannot be started or is not responding."""
    pass


class MemoryServerTimeoutError(MemoryServerError):
    """Raised when the memory MCP server does not respond within the timeout."""
    pass


# ============================================================
# Configuration
# ============================================================

@dataclass
class MemoryAdapterConfig:
    """Configuration for the memory adapter.

    Attributes:
        server_path: Path to the memory server executable.
        memory_file: Path to the persistent knowledge graph JSON file.
        timeout_seconds: Max wait for server response. Default 10.0.
        max_retries: Number of startup retries. Default 2.
    """
    server_path: str = (
        "node e:\\AI_Studio_Workspace\\mcp_sandbox\\skills\\memory_server\\dist\\index.js"
        " --memory-file e:\\AI_Studio_Workspace\\mcp_sandbox\\memory\\knowledge_graph.json"
    )
    memory_file: str = (
        "e:\\AI_Studio_Workspace\\mcp_sandbox\\memory\\knowledge_graph.json"
    )
    timeout_seconds: float = 10.0
    max_retries: int = 2


# ============================================================
# Entity Type Constants (used in Memory MCP knowledge graph)
# ============================================================

class EntityType:
    """Entity type string constants for the memory knowledge graph."""
    BELIEF_NODE = "BeliefNode"
    BELIEF_OBSERVATION = "BeliefObservation"
    CONFLICT_RECORD = "ConflictRecord"
    RETIREMENT_RECORD = "BeliefRetirement"


class RelationType:
    """Relation type string constants."""
    HAS_OBSERVATION = "has_observation"
    CONFLICTS_WITH = "conflicts_with"
    RETIRED_FROM = "retired_from"
    DERIVED_FROM = "derived_from"


# ============================================================
# Adapter: BeliefStateManager ↔ Memory MCP Server
# ============================================================

class BeliefMemoryAdapter:
    """Adapter for synchronizing belief state with the Memory MCP Server.

    This adapter reads/writes the memory server's JSON knowledge graph file
    directly, parsing it into the internal knowledge graph structure and
    providing methods to translate between BeliefStateManager domain objects
    and memory graph entities/relations.

    Data Flow:
      export_to_memory(beliefs, conflicts, retirements)
        → Reads current graph
        → Upserts entity for each belief node (with observations embedded)
        → Upserts entity for each conflict
        → Upserts entity for each retirement
        → Applies relations
        → Writes updated graph

      import_from_memory()
        → Reads current graph
        → Extracts belief nodes, conflicts, retirements
        → Returns deserialized domain objects
    """

    def __init__(self, config: Optional[MemoryAdapterConfig] = None) -> None:
        """Initialize the adapter.

        Args:
            config: Optional adapter configuration. Default parameters used if omitted.
        """
        self._config = config or MemoryAdapterConfig()
        self._graph_cache: Optional[Dict[str, Any]] = None
        logger.debug(
            "BeliefMemoryAdapter initialized: memory_file=%s",
            self._config.memory_file,
        )

    # ============================================================
    # Graph I/O (low-level)
    # ============================================================

    def _read_graph(self) -> Dict[str, Any]:
        """Read the knowledge graph from the memory server's JSON file.

        Returns:
            Parsed JSON dict with 'entities', 'relations' keys.
            Returns empty graph if file doesn't exist.

        Raises:
            MemoryServerUnavailableError: If the file cannot be accessed.
        """
        import os

        if not os.path.exists(self._config.memory_file):
            logger.info("Memory file not found; starting with empty graph.")
            return {"entities": [], "relations": []}

        try:
            with open(self._config.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Normalize structure
            if "entities" not in data:
                data["entities"] = []
            if "relations" not in data:
                data["relations"] = []
            return data
        except (json.JSONDecodeError, OSError) as e:
            raise MemoryServerUnavailableError(
                f"Failed to read memory graph: {e}"
            ) from e

    def _write_graph(self, graph: Dict[str, Any]) -> None:
        """Write the knowledge graph to the memory server's JSON file."""
        import os

        try:
            os.makedirs(os.path.dirname(self._config.memory_file), exist_ok=True)
            with open(self._config.memory_file, "w", encoding="utf-8") as f:
                json.dump(graph, f, indent=2, ensure_ascii=False)
        except OSError as e:
            raise MemoryServerUnavailableError(
                f"Failed to write memory graph: {e}"
            ) from e

    # ============================================================
    # Entity builders (domain → memory graph entity)
    # ============================================================

    def _belief_node_to_entity(
        self, snapshot: BeliefSnapshot,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Convert a BeliefSnapshot to a memory graph entity + observations.

        Returns:
            Tuple of (entity_dict, observation_strings).
        """
        node = snapshot.node
        observations = [
            f"Beta(α={node.alpha:.4f}, β={node.beta:.4f})",
            f"Expectation: {snapshot.expectation:.4f}",
            f"Uncertainty: {snapshot.uncertainty:.4f}",
            f"Confidence Score: {snapshot.score:.4f}",
            f"Observation Count: {snapshot.observation_count}",
            f"Source: {node.source.value}",
            f"Status: {snapshot.status_label}",
        ]

        entity = {
            "name": f"belief:{node.proposition_id}",
            "entityType": EntityType.BELIEF_NODE,
            "observations": observations,
            "metadata": {
                "proposition_id": node.proposition_id,
                "proposition": node.proposition,
                "alpha": node.alpha,
                "beta": node.beta,
                "source": node.source.value,
                "status": node.status.value,
                "created_at": node.created_at,
                "last_updated": node.last_updated,
                "extra_metadata": json.dumps(node.metadata),
            },
        }
        return entity, observations

    def _conflict_to_entity(self, conflict: ConflictRecord) -> Dict[str, Any]:
        """Convert a ConflictRecord to a memory graph entity."""
        observations = [
            f"Left: {conflict.left_id} (score={conflict.left_confidence:.4f})",
            f"Right: {conflict.right_id} (score={conflict.right_confidence:.4f})",
            f"Resolution: {conflict.resolution.value}",
        ]

        return {
            "name": f"conflict:{conflict.conflict_id}",
            "entityType": EntityType.CONFLICT_RECORD,
            "observations": observations,
            "metadata": {
                "conflict_id": conflict.conflict_id,
                "left_id": conflict.left_id,
                "right_id": conflict.right_id,
                "left_confidence": conflict.left_confidence,
                "right_confidence": conflict.right_confidence,
                "resolution": conflict.resolution.value,
                "resolved_at": conflict.resolved_at,
            },
        }

    def _retirement_to_entity(self, retirement: BeliefRetirement) -> Dict[str, Any]:
        """Convert a BeliefRetirement to a memory graph entity."""
        observations = [
            f"Proposition: {retirement.proposition}",
            f"Reason: {retirement.reason}",
            f"Retired Confidence: {retirement.retired_confidence:.4f}",
            f"Threshold: {retirement.threshold:.3f}",
        ]

        return {
            "name": f"retirement:{retirement.retirement_id}",
            "entityType": EntityType.RETIREMENT_RECORD,
            "observations": observations,
            "metadata": {
                "retirement_id": retirement.retirement_id,
                "proposition_id": retirement.proposition_id,
                "proposition": retirement.proposition,
                "reason": retirement.reason,
                "retired_confidence": retirement.retired_confidence,
                "threshold": retirement.threshold,
                "retired_at": retirement.retired_at,
            },
        }

    # ============================================================
    # Export: BeliefStateManager → Memory Graph
    # ============================================================

    def export_to_memory(
        self,
        snapshots: List[BeliefSnapshot],
        conflicts: List[ConflictRecord],
        retirements: List[BeliefRetirement],
    ) -> int:
        """Export the full belief state to the memory knowledge graph.

        Args:
            snapshots: All current belief snapshots.
            conflicts: All conflict records.
            retirements: All retirement records.

        Returns:
            Total number of entities written.
        """
        graph = self._read_graph()

        # Clear existing belief nodes, conflicts, and retirements
        graph["entities"] = [
            e for e in graph["entities"]
            if e.get("entityType") not in (
                EntityType.BELIEF_NODE,
                EntityType.CONFLICT_RECORD,
                EntityType.RETIREMENT_RECORD,
            )
        ]
        graph["relations"] = [
            r for r in graph["relations"]
            if not r.get("from", "").startswith("belief:")
            and not r.get("from", "").startswith("conflict:")
            and not r.get("from", "").startswith("retirement:")
        ]

        # Add belief node entities
        for snapshot in snapshots:
            entity, _ = self._belief_node_to_entity(snapshot)
            graph["entities"].append(entity)

        # Add conflict entities + relations
        for conflict in conflicts:
            entity = self._conflict_to_entity(conflict)
            graph["entities"].append(entity)
            graph["relations"].append({
                "from": f"belief:{conflict.left_id}",
                "to": f"conflict:{conflict.conflict_id}",
                "relationType": RelationType.CONFLICTS_WITH,
            })
            graph["relations"].append({
                "from": f"belief:{conflict.right_id}",
                "to": f"conflict:{conflict.conflict_id}",
                "relationType": RelationType.CONFLICTS_WITH,
            })

        # Add retirement entities + relations
        for retirement in retirements:
            entity = self._retirement_to_entity(retirement)
            graph["entities"].append(entity)
            graph["relations"].append({
                "from": f"belief:{retirement.proposition_id}",
                "to": f"retirement:{retirement.retirement_id}",
                "relationType": RelationType.RETIRED_FROM,
            })

        self._write_graph(graph)

        total = len(snapshots) + len(conflicts) + len(retirements)
        logger.info(
            "Exported %d entities to memory graph (%d beliefs, %d conflicts, %d retirements)",
            total,
            len(snapshots),
            len(conflicts),
            len(retirements),
        )
        return total

    # ============================================================
    # Import: Memory Graph → Domain Objects
    # ============================================================

    def import_from_memory(self) -> Dict[str, Any]:
        """Import belief state from the memory knowledge graph.

        Returns:
            Dict with keys:
              - 'snapshots': List of reconstructed BeliefSnapshot objects.
              - 'conflicts': List of reconstructed ConflictRecord objects.
              - 'retirements': List of reconstructed BeliefRetirement objects.
              - 'raw_entities': Raw entity list for debugging.
        """
        graph = self._read_graph()

        result: Dict[str, Any] = {
            "snapshots": [],
            "conflicts": [],
            "retirements": [],
            "raw_entities": graph["entities"],
        }

        for entity in graph["entities"]:
            etype = entity.get("entityType")
            meta = entity.get("metadata", {})

            if etype == EntityType.BELIEF_NODE:
                snap = self._entity_to_snapshot(entity)
                if snap is not None:
                    result["snapshots"].append(snap)

            elif etype == EntityType.CONFLICT_RECORD:
                conflict = self._entity_to_conflict(entity)
                if conflict is not None:
                    result["conflicts"].append(conflict)

            elif etype == EntityType.RETIREMENT_RECORD:
                retirement = self._entity_to_retirement(entity)
                if retirement is not None:
                    result["retirements"].append(retirement)

        return result

    # ============================================================
    # Entity parsers (memory graph entity → domain)
    # ============================================================

    def _entity_to_snapshot(self, entity: Dict[str, Any]) -> Optional[BeliefSnapshot]:
        """Deserialize a memory graph entity back to a BeliefSnapshot."""
        meta = entity.get("metadata", {})
        try:
            node = BeliefNode(
                proposition=meta.get("proposition", "unknown"),
                proposition_id=meta.get("proposition_id", "unknown"),
                alpha=float(meta.get("alpha", 1.0)),
                beta=float(meta.get("beta", 1.0)),
                status=BeliefStatus(meta.get("status", "active")),
                source=BeliefSource(meta.get("source", "inferred")),
                created_at=meta.get("created_at", ""),
                last_updated=meta.get("last_updated", ""),
                metadata=json.loads(meta.get("extra_metadata", "{}")),
            )
            return BeliefSnapshot(
                node=node,
                observation_count=0,
                expectation=float(meta.get("alpha", 1.0)) / (
                    float(meta.get("alpha", 1.0)) + float(meta.get("beta", 1.0))
                ),
                uncertainty=0.0,  # Cannot reconstruct without observations
                score=0.0,        # Requires observations to compute
                status_label=node.status.value,
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Failed to deserialize belief entity: %s", e)
            return None

    def _entity_to_conflict(self, entity: Dict[str, Any]) -> Optional[ConflictRecord]:
        """Deserialize a memory graph entity back to a ConflictRecord."""
        meta = entity.get("metadata", {})
        try:
            return ConflictRecord(
                left_id=meta.get("left_id", ""),
                right_id=meta.get("right_id", ""),
                left_confidence=float(meta.get("left_confidence", 0.0)),
                right_confidence=float(meta.get("right_confidence", 0.0)),
                resolution=ResolutionStrategy(
                    meta.get("resolution", "ambiguous_reject")
                ),
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Failed to deserialize conflict entity: %s", e)
            return None

    def _entity_to_retirement(
        self, entity: Dict[str, Any],
    ) -> Optional[BeliefRetirement]:
        """Deserialize a memory graph entity back to a BeliefRetirement."""
        meta = entity.get("metadata", {})
        try:
            return BeliefRetirement(
                proposition_id=meta.get("proposition_id", ""),
                proposition=meta.get("proposition", ""),
                reason=meta.get("reason", ""),
                retired_confidence=float(meta.get("retired_confidence", 0.0)),
                threshold=float(meta.get("threshold", 0.1)),
                retired_at=meta.get("retired_at", ""),
                retirement_id=meta.get("retirement_id", ""),
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Failed to deserialize retirement entity: %s", e)
            return None

    # ============================================================
    # Introspection
    # ============================================================

    def get_graph_stats(self) -> Dict[str, int]:
        """Get statistics about the current memory graph."""
        graph = self._read_graph()
        entities = graph.get("entities", [])
        relations = graph.get("relations", [])

        type_counts: Dict[str, int] = {}
        for e in entities:
            etype = e.get("entityType", "Unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1

        return {
            "total_entities": len(entities),
            "total_relations": len(relations),
            "by_type": type_counts,
        }

    def clear_belief_state(self) -> int:
        """Remove all belief-related entities/relations from the memory graph.

        Returns:
            Number of entities removed.
        """
        graph = self._read_graph()

        belief_entity_names = set()
        remaining_entities = []
        for e in graph["entities"]:
            if e.get("entityType") in (
                EntityType.BELIEF_NODE,
                EntityType.CONFLICT_RECORD,
                EntityType.RETIREMENT_RECORD,
            ):
                belief_entity_names.add(e.get("name", ""))
            else:
                remaining_entities.append(e)

        graph["entities"] = remaining_entities
        graph["relations"] = [
            r for r in graph.get("relations", [])
            if r.get("from", "") not in belief_entity_names
            and r.get("to", "") not in belief_entity_names
        ]

        self._write_graph(graph)
        removed = len(belief_entity_names)
        logger.info("Cleared %d belief entities from memory graph", removed)
        return removed