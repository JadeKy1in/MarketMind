"""ShadowMemoryStore — 3-tier layered memory for shadow agents."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from marketmind.shadows.belief_math import (
    beta_update, gamma_decay, beta_expectation,
    beta_uncertainty, confidence_score,
)
from marketmind.shadows.belief_types import (
    BeliefSource, BeliefStatus,
)
from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger(__name__)

_WORKING_TTL_HOURS = 24
_EPISODIC_TTL_DAYS = 90
_RETIREMENT_THRESHOLD = 0.1

_SOURCE_TYPE_MAP: Dict[str, BeliefSource] = {
    "image": BeliefSource.MARKET_DATA,
    "pdf": BeliefSource.MARKET_DATA,
    "screenshot": BeliefSource.MARKET_DATA,
    "text": BeliefSource.SHADOW_PREDICTION,
    "audio": BeliefSource.MACRO_CALENDAR,
}


def _auto_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _auto_uuid() -> str:
    return str(uuid.uuid4())


def _source_type_to_belief_source(source_type: str) -> BeliefSource:
    return _SOURCE_TYPE_MAP.get(source_type, BeliefSource.INFERRED)


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
        conn = self._db._connect()
        try:
            rows = conn.execute(
                "SELECT node_id, alpha, beta "
                "FROM belief_nodes WHERE status = 'active'"
            ).fetchall()
            count = 0
            now = _auto_iso()
            for row in rows:
                new_alpha, new_beta = gamma_decay(
                    row["alpha"], row["beta"], gamma=gamma, steps=1
                )
                conn.execute(
                    "UPDATE belief_nodes "
                    "SET alpha=?, beta=?, updated_at=?, decayed_at=? "
                    "WHERE node_id=?",
                    (new_alpha, new_beta, now, now, row["node_id"]),
                )
                score = confidence_score(new_alpha, new_beta)
                if score < _RETIREMENT_THRESHOLD:
                    conn.execute(
                        "UPDATE belief_nodes "
                        "SET status='retired', retired_at=?, "
                        "retire_reason=? "
                        "WHERE node_id=?",
                        (now,
                         f"Decayed below threshold: {score:.4f}",
                         row["node_id"]),
                    )
                    conn.execute(
                        "INSERT INTO belief_retirements "
                        "(node_id, retired_confidence, threshold, reason, "
                        " created_at) "
                        "VALUES (?,?,?,?,?)",
                        (row["node_id"], score, _RETIREMENT_THRESHOLD,
                         f"Decayed: {score:.4f}", now),
                    )
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    def apply_tier_decay(self, tier: str) -> int:
        """Apply TTL-based eviction to a specific tier."""
        if tier not in ("working", "episodic", "semantic"):
            raise ValueError(
                f"tier must be working/episodic/semantic; got '{tier}'"
            )
        if tier == "semantic":
            return 0
        conn = self._db._connect()
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            if tier == "working":
                cutoff = now - timedelta(hours=_WORKING_TTL_HOURS)
            else:
                cutoff = now - timedelta(days=_EPISODIC_TTL_DAYS)
            cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            rows = conn.execute(
                "SELECT node_id, alpha, beta, created_at "
                "FROM belief_nodes "
                "WHERE tier = ? AND status = 'active' AND created_at < ?",
                (tier, cutoff_iso),
            ).fetchall()
            count = 0
            for row in rows:
                score = confidence_score(row["alpha"], row["beta"])
                reason = (
                    f"TTL eviction: {tier} memory expired "
                    f"(created {row['created_at']})"
                )
                conn.execute(
                    "UPDATE belief_nodes "
                    "SET status='retired', retired_at=?, retire_reason=? "
                    "WHERE node_id=?",
                    (now_iso, reason, row["node_id"]),
                )
                conn.execute(
                    "INSERT INTO belief_retirements "
                    "(node_id, retired_confidence, threshold, reason, "
                    " created_at) "
                    "VALUES (?,?,?,?,?)",
                    (row["node_id"], score, _RETIREMENT_THRESHOLD,
                     reason, now_iso),
                )
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    # -- Lifecycle --

    def promote_to_semantic(self, node_id: str) -> bool:
        """Promote a belief node to semantic memory (no TTL)."""
        conn = self._db._connect()
        try:
            row = conn.execute(
                "SELECT node_id FROM belief_nodes WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                return False
            now = _auto_iso()
            conn.execute(
                "UPDATE belief_nodes "
                "SET tier='semantic', updated_at=? "
                "WHERE node_id=?",
                (now, node_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def retire_belief(self, node_id: str, reason: str) -> bool:
        """Retire a belief node."""
        conn = self._db._connect()
        try:
            row = conn.execute(
                "SELECT node_id, alpha, beta, status "
                "FROM belief_nodes WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] == "retired":
                return False
            score = confidence_score(row["alpha"], row["beta"])
            now = _auto_iso()
            conn.execute(
                "UPDATE belief_nodes "
                "SET status='retired', retired_at=?, retire_reason=? "
                "WHERE node_id=?",
                (now, reason, node_id),
            )
            conn.execute(
                "INSERT INTO belief_retirements "
                "(node_id, retired_confidence, threshold, reason, "
                " created_at) "
                "VALUES (?,?,?,?,?)",
                (node_id, score, _RETIREMENT_THRESHOLD, reason, now),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_memory_stats(self) -> dict:
        """Return counts per tier, total beliefs, active beliefs."""
        conn = self._db._connect()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes"
            ).fetchone()["cnt"]
            active = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes "
                "WHERE status='active'"
            ).fetchone()["cnt"]
            retired = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes "
                "WHERE status='retired'"
            ).fetchone()["cnt"]
            working = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes "
                "WHERE tier='working' AND status='active'"
            ).fetchone()["cnt"]
            episodic = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes "
                "WHERE tier='episodic' AND status='active'"
            ).fetchone()["cnt"]
            semantic = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_nodes "
                "WHERE tier='semantic' AND status='active'"
            ).fetchone()["cnt"]
            total_obs = conn.execute(
                "SELECT COUNT(*) AS cnt FROM belief_observations"
            ).fetchone()["cnt"]
            # Compute avg_confidence in Python (SQLite doesn't know confidence_score)
            alpha_beta_rows = conn.execute(
                "SELECT alpha, beta FROM belief_nodes WHERE status='active'"
            ).fetchall()
            if alpha_beta_rows:
                scores = [confidence_score(r["alpha"], r["beta"]) for r in alpha_beta_rows]
                avg_conf = sum(scores) / len(scores)
            else:
                avg_conf = 0.0
            return dict(
                total_nodes=total,
                active_nodes=active,
                retired_nodes=retired,
                working_count=working,
                episodic_count=episodic,
                semantic_count=semantic,
                total_observations=total_obs,
                avg_confidence=avg_conf or 0.0,
            )
        finally:
            conn.close()

    def get_belief_node(self, node_id: str) -> Optional[dict]:
        """Get a single belief node with computed statistics."""
        conn = self._db._connect()
        try:
            row = conn.execute(
                "SELECT n.*, "
                "(SELECT COUNT(*) FROM belief_observations o "
                " WHERE o.node_id=n.node_id) AS observation_count "
                "FROM belief_nodes n WHERE n.node_id=?",
                (node_id,),
            ).fetchone()
            if row is None:
                return None
            alpha = row["alpha"]
            beta = row["beta"]
            try:
                tags_val = json.loads(row["tags"] or "[]")
            except json.JSONDecodeError:
                tags_val = []
            return dict(
                node_id=row["node_id"],
                proposition=row["proposition"],
                alpha=alpha, beta=beta,
                status=row["status"], tier=row["tier"],
                source=row["source"], tags=tags_val,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                decayed_at=row["decayed_at"],
                retired_at=row["retired_at"],
                retire_reason=row["retire_reason"],
                observation_count=row["observation_count"],
                expectation=beta_expectation(alpha, beta),
                uncertainty=beta_uncertainty(alpha, beta),
                confidence_score=confidence_score(alpha, beta),
            )
        finally:
            conn.close()
