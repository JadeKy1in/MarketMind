"""Cycle checkpoint persistence — partial-state recovery for shadow analysis.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.shadow_checkpoint_repo")


def save_checkpoint(
    conn: sqlite3.Connection, date: str, shadow_id: str, status: str,
    step: int, analysis_json: str | None = None,
    error_message: str | None = None
) -> None:
    """Save a per-shadow checkpoint for partial-state recovery (P3-4).

    Called after each individual shadow analysis completes or fails.
    If the DB write itself fails, logs a warning but does NOT raise —
    checkpoint persistence failures must not crash the analysis loop.

    Args:
        date: ISO date string (YYYY-MM-DD).
        shadow_id: Shadow identifier.
        status: 'pending', 'completed', or 'failed'.
        step: Pipeline step number (4 = analysis step).
        analysis_json: Serialized analysis output (for completed checkpoints).
        error_message: Exception message (for failed checkpoints).
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if status == 'completed' else None
        started_at = now if status == 'pending' else None

        conn.execute(
            """INSERT OR REPLACE INTO cycle_checkpoints
               (date, shadow_id, status, step_completed, analysis_json,
                started_at, completed_at, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, shadow_id, status, step, analysis_json,
             started_at, completed_at, error_message)
        )
        conn.commit()
    except Exception as e:
        logger.warning(
            "Failed to save checkpoint for %s/%s: %s", date, shadow_id, e
        )


def get_checkpoint(
    conn: sqlite3.Connection, date: str, shadow_id: str
) -> dict | None:
    """Get checkpoint for a specific shadow on a specific date (P3-4).

    Returns None if no checkpoint exists for this (date, shadow_id) pair.
    """
    row = conn.execute(
        "SELECT * FROM cycle_checkpoints WHERE date = ? AND shadow_id = ?",
        (date, shadow_id)
    ).fetchone()
    return dict(row) if row else None


def get_incomplete_shadows(
    conn: sqlite3.Connection, date: str
) -> list[str]:
    """Return shadow_ids with status='pending' or 'failed' for a date (P3-4).

    Used at cycle start to determine which shadows need to be re-run
    after a mid-cycle crash.
    """
    rows = conn.execute(
        "SELECT shadow_id FROM cycle_checkpoints "
        "WHERE date = ? AND status IN ('pending', 'failed')",
        (date,)
    ).fetchall()
    return [r["shadow_id"] for r in rows]


def clear_date_checkpoints(
    conn: sqlite3.Connection, date: str
) -> None:
    """Delete all checkpoints for a date (cleanup after cycle completes, P3-4)."""
    conn.execute("DELETE FROM cycle_checkpoints WHERE date = ?", (date,))
    conn.commit()
