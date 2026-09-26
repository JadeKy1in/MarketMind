"""Integrity, emergency quota, and collusion persistence.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from marketmind.shadows.shadow_data_types import (
    IntegrityEvent, EmergencyQuotaRequest, CollusionFlag,
)

logger = logging.getLogger("marketmind.shadows.shadow_integrity_repo")


# ── Integrity events ───────────────────────────────────────────────────────

def record_integrity_event(
    conn: sqlite3.Connection, shadow_id: str, event: IntegrityEvent
) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO integrity_events
           (shadow_id, date, event_type, claim_detail, score_change, new_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (shadow_id, event.date, event.event_type, event.claim_detail,
         event.score_change, event.new_score)
    )
    recorded = cur.rowcount > 0
    if not recorded:
        logger.debug("Duplicate integrity event ignored: shadow=%s date=%s type=%s",
                     shadow_id, event.date, event.event_type)
    conn.commit()
    return recorded


def get_integrity_score(conn: sqlite3.Connection, shadow_id: str) -> int:
    row = conn.execute(
        """SELECT new_score FROM integrity_events
           WHERE shadow_id = ?
           ORDER BY date DESC LIMIT 1""",
        (shadow_id,)
    ).fetchone()
    return row["new_score"] if row else 100


def get_integrity_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 90
) -> list[IntegrityEvent]:
    rows = conn.execute(
        """SELECT * FROM integrity_events
           WHERE shadow_id = ?
           ORDER BY date DESC
           LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [IntegrityEvent(
        shadow_id=r["shadow_id"], date=r["date"],
        event_type=r["event_type"], claim_detail=r["claim_detail"],
        score_change=r["score_change"], new_score=r["new_score"],
    ) for r in rows]


# ── Emergency quotas ────────────────────────────────────────────────────────

def record_emergency_quota(
    conn: sqlite3.Connection, shadow_id: str, quota: EmergencyQuotaRequest
) -> int:
    cur = conn.execute(
        """INSERT INTO emergency_quotas
           (shadow_id, requested_at, confidence_self_report, opportunity_description)
           VALUES (?, ?, ?, ?)""",
        (shadow_id, quota.requested_at, quota.confidence_self_report,
         quota.opportunity_description)
    )
    conn.commit()
    return cur.lastrowid


def update_emergency_result(
    conn: sqlite3.Connection, quota_id: int, result: str,
    pnl_impact: float, penalty: str
) -> None:
    conn.execute(
        """UPDATE emergency_quotas
           SET result = ?, pnl_impact_pct = ?, quota_penalty_applied = ?
           WHERE id = ?""",
        (result, pnl_impact, penalty, quota_id)
    )
    conn.commit()


def get_pending_emergency_audits(
    conn: sqlite3.Connection
) -> list[EmergencyQuotaRequest]:
    rows = conn.execute(
        "SELECT * FROM emergency_quotas WHERE result = 'pending'"
    ).fetchall()
    return [EmergencyQuotaRequest(
        id=r["id"],
        shadow_id=r["shadow_id"],
        requested_at=r["requested_at"],
        confidence_self_report=r["confidence_self_report"],
        opportunity_description=r["opportunity_description"],
        result=r["result"],
        pnl_impact_pct=r["pnl_impact_pct"],
        quota_penalty_applied=r["quota_penalty_applied"],
    ) for r in rows]


# ── Emergency quota runtime state ──────────────────────────────────────────

def save_emergency_quota_state(
    conn: sqlite3.Connection, shadow_id: str, state_json: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO emergency_quota_state
           (shadow_id, state_json, updated_at)
           VALUES (?, ?, ?)""",
        (shadow_id, state_json, now)
    )
    conn.commit()


def load_emergency_quota_state(
    conn: sqlite3.Connection, shadow_id: str
) -> str | None:
    row = conn.execute(
        "SELECT state_json FROM emergency_quota_state WHERE shadow_id = ?",
        (shadow_id,)
    ).fetchone()
    return row["state_json"] if row else None


# ── Collusion ───────────────────────────────────────────────────────────────

def record_collusion_flag(conn: sqlite3.Connection, flag: CollusionFlag) -> None:
    conn.execute(
        """INSERT INTO collusion_flags
           (date, agreement_pct, consecutive_days, market_signal_strength,
            verdict, user_action)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (flag.date, flag.agreement_pct, flag.consecutive_days,
         flag.market_signal_strength, flag.verdict, flag.user_action)
    )
    conn.commit()


def get_recent_collusion_flags(
    conn: sqlite3.Connection, days: int = 30
) -> list[CollusionFlag]:
    rows = conn.execute(
        """SELECT * FROM collusion_flags
           ORDER BY date DESC
           LIMIT ?""",
        (days,)
    ).fetchall()
    return [CollusionFlag(
        date=r["date"],
        agreement_pct=r["agreement_pct"],
        consecutive_days=r["consecutive_days"],
        market_signal_strength=r["market_signal_strength"],
        verdict=r["verdict"],
        user_action=r["user_action"],
    ) for r in rows]


# ── Paper/live gap runtime state ────────────────────────────────────────────

def save_paper_live_gap_state(
    conn: sqlite3.Connection, shadow_id: str, state_json: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO paper_live_gap_state
           (shadow_id, state_json, updated_at)
           VALUES (?, ?, ?)""",
        (shadow_id, state_json, now)
    )
    conn.commit()


def load_paper_live_gap_state(
    conn: sqlite3.Connection, shadow_id: str
) -> str | None:
    row = conn.execute(
        "SELECT state_json FROM paper_live_gap_state WHERE shadow_id = ?",
        (shadow_id,)
    ).fetchone()
    return row["state_json"] if row else None
