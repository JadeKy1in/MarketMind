"""ShadowMemoryStore — 3-tier layered memory for shadow agents."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from marketmind.shadows.belief_math import (
    beta_update, gamma_decay, beta_expectation,
    beta_uncertainty, confidence_score,
)
from marketmind.shadows.memory_tiers import (
    apply_decay as _apply_decay_tiers,
    apply_tier_ttl as _apply_tier_ttl_tiers,
    promote_to_semantic as _promote_to_semantic_tiers,
    retire_belief as _retire_belief_tiers,
    get_memory_stats as _get_memory_stats_tiers,
    get_belief_node as _get_belief_node_tiers,
)
from marketmind.shadows.shadow_state import ShadowStateDB

_RETIREMENT_THRESHOLD = 0.1


def _auto_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _auto_uuid() -> str:
    return str(uuid.uuid4())


def _derive_proposition(shadow_id: str, observation: Any) -> str:
    ticker = observation.metadata.get("ticker", "") if observation.metadata else ""
    if ticker:
        return f"shadow:{shadow_id}:ticker:{ticker}"
    source_type = getattr(observation, "source_type", "unknown")
    return f"shadow:{shadow_id}:source:{source_type}"


class ShadowMemoryStore:
    """3-tier layered memory for shadow agents."""

    def __init__(self, state_db: ShadowStateDB) -> None:
        self._db = state_db
        self._gamma: float = 0.95

    # -- Ingestion --

    async def ingest_observation(
        self, shadow_id: str, observation: Any, tier: str = "working"
    ) -> str:
        """Store observation in specified tier with TTL."""
        return self.ingest_observation_sync(shadow_id, observation, tier)

    def ingest_observation_sync(
        self, shadow_id: str, observation: Any, tier: str = "working"
    ) -> str:
        """Synchronous variant of ingest_observation for testability."""
        if tier not in ("working", "episodic", "semantic"):
            raise ValueError(
                f"tier must be one of working/episodic/semantic; got '{tier}'"
            )

        proposition = _derive_proposition(shadow_id, observation)
        obs_id = getattr(observation, "observation_id", "") or _auto_uuid()
        source_type = getattr(observation, "source_type", "text")
        source_path = getattr(observation, "source_path", "")
        extracted_text = getattr(observation, "extracted_text", "")
        metadata = getattr(observation, "metadata", {}) or {}
        obs_confidence = getattr(observation, "confidence", 1.0)
        now = _auto_iso()

        conn = self._db._connect()
        try:
            row = conn.execute(
                "SELECT node_id, alpha, beta, status, updated_at "
                "FROM belief_nodes "
                "WHERE proposition = ? AND source = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (proposition, "shadow"),
            ).fetchone()

            if row is None:
                node_id = _auto_uuid()
                conn.execute(
                    "INSERT INTO belief_nodes "
                    "(node_id, proposition, alpha, beta, status, tier, "
                    " source, tags, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (node_id, proposition, 1.0, 1.0, "active", tier,
                     "shadow", json.dumps(metadata.get("tags", [])), now, now),
                )
                current_alpha, current_beta = 1.0, 1.0
            else:
                node_id = row["node_id"]
                current_alpha = row["alpha"]
                current_beta = row["beta"]
                try:
                    last_updated = row["updated_at"]
                    last_dt = datetime.fromisoformat(
                        last_updated.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    now_dt = datetime.fromisoformat(
                        now.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    elapsed_seconds = (now_dt - last_dt).total_seconds()
                    steps = int(elapsed_seconds / 86_400)
                    if steps > 0:
                        current_alpha, current_beta = gamma_decay(
                            current_alpha, current_beta,
                            gamma=self._gamma, steps=steps,
                        )
                except (ValueError, TypeError):
                    pass

            belief_value = min(max(obs_confidence, 0.0), 1.0)
            new_alpha, new_beta = beta_update(
                current_alpha, current_beta, belief_value,
                confidence=obs_confidence,
            )

            conn.execute(
                "UPDATE belief_nodes "
                "SET alpha = ?, beta = ?, updated_at = ?, tier = ? "
                "WHERE node_id = ?",
                (new_alpha, new_beta, now, tier, node_id),
            )

            conn.execute(
                "INSERT OR IGNORE INTO belief_observations "
                "(observation_id, node_id, shadow_id, value, confidence, "
                " source_type, source_path, extracted_text, metadata_json, "
                " created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (obs_id, node_id, shadow_id, belief_value, obs_confidence,
                 source_type, source_path, extracted_text,
                 json.dumps(metadata), now),
            )

            score = confidence_score(new_alpha, new_beta)
            if score < _RETIREMENT_THRESHOLD:
                conn.execute(
                    "UPDATE belief_nodes "
                    "SET status = 'retired', retired_at = ?, "
                    "retire_reason = ? "
                    "WHERE node_id = ?",
                    (now,
                     f"Auto-retired: score {score:.4f} below "
                     f"{_RETIREMENT_THRESHOLD}",
                     node_id),
                )
                conn.execute(
                    "INSERT INTO belief_retirements "
                    "(node_id, retired_confidence, threshold, reason, "
                    " created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (node_id, score, _RETIREMENT_THRESHOLD,
                     f"Auto-retired: score {score:.4f}", now),
                )

            conn.commit()
            return node_id
        finally:
            conn.close()

    async def ingest_bulk(
        self, shadow_id: str, observations: list, tier: str = "working"
    ) -> list[str]:
        """Batch ingest observations."""
        results = []
        for obs in observations:
            node_id = await self.ingest_observation(shadow_id, obs, tier)
            results.append(node_id)
        return results

    # -- Query --

    def query_beliefs(self, query: Any) -> list[dict]:
        """Query across memory tiers with age-weighted ranking."""
        q_tier = getattr(query, "tier", "all") or "all"
        ticker = getattr(query, "ticker", None)
        domain = getattr(query, "domain", None)
        min_strength = getattr(query, "min_belief_strength", 0.0) or 0.0
        q_limit = getattr(query, "limit", 20) or 20
        tags = getattr(query, "tags", None) or []
        date_from = getattr(query, "date_from", None)
        date_to = getattr(query, "date_to", None)

        conn = self._db._connect()
        try:
            sql = (
                "SELECT n.node_id, n.proposition, n.alpha, n.beta, "
                "n.status, n.tier, n.source, n.tags, "
                "n.created_at, n.updated_at, "
                "(SELECT COUNT(*) FROM belief_observations o "
                " WHERE o.node_id = n.node_id) AS observation_count "
                "FROM belief_nodes n "
                "WHERE 1=1"
            )
            params = []

            if q_tier != "all":
                sql += " AND n.tier = ?"
                params.append(q_tier)
            if ticker:
                sql += " AND n.proposition LIKE ?"
                params.append(f"%ticker:{ticker}%")
            if domain:
                sql += " AND n.proposition LIKE ?"
                params.append(f"%domain:{domain}%")
            if date_from:
                sql += " AND n.updated_at >= ?"
                params.append(date_from)
            if date_to:
                sql += " AND n.updated_at <= ?"
                params.append(date_to)
            sql += " AND n.status = 'active'"

            rows = conn.execute(sql, params).fetchall()
            results = []
            now_dt = datetime.now(timezone.utc)

            for row in rows:
                alpha = row["alpha"]
                beta = row["beta"]
                score = confidence_score(alpha, beta)
                if score < min_strength:
                    continue
                try:
                    node_tags = json.loads(row["tags"] or "[]")
                except json.JSONDecodeError:
                    node_tags = []
                if tags and not any(t in node_tags for t in tags):
                    continue
                try:
                    updated_dt = datetime.fromisoformat(
                        (row["updated_at"] or "").replace("Z", "+00:00")
                    )
                    age_seconds = (
                        now_dt - updated_dt.replace(tzinfo=now_dt.tzinfo)
                    ).total_seconds()
                    age_days = max(0.0, age_seconds / 86_400)
                    recency_bonus = max(0.0, 1.0 - (age_days / 7.0)) * 0.1
                except (ValueError, TypeError):
                    age_days = 999.0
                    recency_bonus = 0.0

                results.append({
                    "node_id": row["node_id"],
                    "proposition": row["proposition"],
                    "alpha": alpha,
                    "beta": beta,
                    "status": row["status"],
                    "tier": row["tier"],
                    "expectation": beta_expectation(alpha, beta),
                    "uncertainty": beta_uncertainty(alpha, beta),
                    "confidence_score": score,
                    "weighted_score": score + recency_bonus,
                    "observation_count": row["observation_count"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "age_days": age_days,
                })

            results.sort(key=lambda r: r["weighted_score"], reverse=True)
            return results[:q_limit]
        finally:
            conn.close()

    def get_observations(
        self, shadow_id: str, tier: str = "working", limit: int = 50
    ) -> list[dict]:
        """Get observations for a shadow from a memory tier."""
        conn = self._db._connect()
        try:
            sql = (
                "SELECT o.observation_id, o.node_id, o.shadow_id, "
                "o.value, o.confidence, o.source_type, "
                "o.source_path, o.extracted_text, o.metadata_json, "
                "o.created_at, n.tier "
                "FROM belief_observations o "
                "JOIN belief_nodes n ON o.node_id = n.node_id "
                "WHERE o.shadow_id = ?"
            )
            params = [shadow_id]
            if tier != "all":
                sql += " AND n.tier = ?"
                params.append(tier)
            sql += " ORDER BY o.created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    meta = {}
                results.append(dict(
                    observation_id=row["observation_id"],
                    node_id=row["node_id"],
                    shadow_id=row["shadow_id"],
                    value=row["value"],
                    confidence=row["confidence"],
                    source_type=row["source_type"],
                    source_path=row["source_path"],
                    extracted_text=row["extracted_text"],
                    metadata=meta,
                    created_at=row["created_at"],
                    tier=row["tier"],
                ))
            return results
        finally:
            conn.close()

    # -- Decay --

    def apply_decay(self, gamma: float = 0.95) -> int:
        """Apply Beta-Bernoulli decay to all active belief nodes."""
        return _apply_decay_tiers(self._db, gamma)

    def apply_tier_decay(self, tier: str) -> int:
        """Apply TTL-based eviction to a specific tier."""
        return _apply_tier_ttl_tiers(self._db, tier)

    # -- Lifecycle --

    def promote_to_semantic(self, node_id: str) -> bool:
        """Promote a belief node to semantic memory (no TTL)."""
        return _promote_to_semantic_tiers(self._db, node_id)

    def retire_belief(self, node_id: str, reason: str) -> bool:
        """Retire a belief node."""
        return _retire_belief_tiers(self._db, node_id, reason)

    def get_memory_stats(self) -> dict:
        """Return counts per tier, total beliefs, active beliefs."""
        return _get_memory_stats_tiers(self._db)

    def get_belief_node(self, node_id: str) -> Optional[dict]:
        """Get a single belief node with computed statistics."""
        return _get_belief_node_tiers(self._db, node_id)
