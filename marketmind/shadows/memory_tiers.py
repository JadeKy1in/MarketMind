"""Memory Tier Management — Decay, lifecycle, and statistics for belief tiers.

Implements Beta-Bernoulli decay, TTL-based eviction per tier (working/episodic/
semantic), belief promotion/retirement, and tier statistics. Extracted from
shadow_memory.py to comply with 500-line hard ceiling.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from marketmind.shadows.belief_math import (
    beta_expectation, beta_uncertainty, confidence_score, gamma_decay,
)

_WORKING_TTL_HOURS = 24
_EPISODIC_TTL_DAYS = 90
_RETIREMENT_THRESHOLD = 0.1


def _auto_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def apply_decay(state_db, gamma: float = 0.95) -> int:
    """Apply Beta-Bernoulli decay to all active belief nodes."""
    conn = state_db._connect()
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


def apply_tier_ttl(state_db, tier: str) -> int:
    """Apply TTL-based eviction to a specific tier."""
    if tier not in ("working", "episodic", "semantic"):
        raise ValueError(
            f"tier must be working/episodic/semantic; got '{tier}'"
        )
    if tier == "semantic":
        return 0
    conn = state_db._connect()
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


def promote_to_semantic(state_db, node_id: str) -> bool:
    """Promote a belief node to semantic memory (no TTL)."""
    conn = state_db._connect()
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


def retire_belief(state_db, node_id: str, reason: str) -> bool:
    """Retire a belief node."""
    conn = state_db._connect()
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


def get_memory_stats(state_db) -> dict[str, Any]:
    """Return counts per tier, total beliefs, active beliefs."""
    conn = state_db._connect()
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


def get_belief_node(state_db, node_id: str) -> Optional[dict]:
    """Get a single belief node with computed statistics."""
    conn = state_db._connect()
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
