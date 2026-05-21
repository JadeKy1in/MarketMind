"""EventTracker — continuous monitoring track for shadow ecosystem events.

Manages the event_tracks table: start, update, query active tracks, and close
tracks with outcomes. Used by shadows and the Fade Master to monitor ongoing
market events, themes, and macro developments.

All operations are pure Python — zero LLM calls. The DB schema is defined
in shadow_schema.py (migration 12).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.shadows.event_tracker")

# Default DB path
DEFAULT_DB_PATH = "data/shadows/shadows.db"

# Status constants
STATUS_ACTIVE = "active"
STATUS_MONITORING = "monitoring"
STATUS_CLOSED = "closed"


class EventTracker:
    """Manage the event_tracks table for continuous event monitoring.

    Shadows create tracks to monitor ongoing market events. The tracker
    provides lifecycle management: start, update notes, query active,
    and close with final outcome.

    Usage:
        tracker = EventTracker("data/shadows/shadows.db")
        track_id = tracker.start_track(
            shadow_id="expert:gold:agent_01",
            topic="Gold breakout above $2100",
            category="technical_breakout",
            key_metric="gold_spot_price",
        )
        tracker.update_track(track_id, status="monitoring", notes="Retesting $2100 support")
        active = tracker.get_active_tracks("expert:gold:agent_01")
        tracker.close_track(track_id, outcome="Confirmed: gold closed above $2150 for 3 days")
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """Initialize the event tracker with a path to the shadows SQLite DB.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Get a SQLite connection with standard pragmas."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Start track ───────────────────────────────────────────────────────

    def start_track(
        self,
        shadow_id: str,
        topic: str,
        category: str,
        key_metric: str = "",
    ) -> int:
        """Start a new event monitoring track.

        Args:
            shadow_id: The shadow creating this track.
            topic: Short description of the event being tracked.
            category: Category label (e.g. "technical_breakout", "earnings",
                     "macro_event", "volatility_spike").
            key_metric: The primary metric to monitor (e.g. ticker, indicator name).

        Returns:
            The new track's integer ID.

        Raises:
            ValueError: If shadow_id or topic is empty.
            sqlite3.Error: On database errors.
        """
        if not shadow_id or not shadow_id.strip():
            raise ValueError("shadow_id must not be empty")
        if not topic or not topic.strip():
            raise ValueError("topic must not be empty")

        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """INSERT INTO event_tracks
                   (shadow_id, topic, category, key_metric, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id.strip(), topic.strip(), category, key_metric,
                 STATUS_ACTIVE, now, now)
            )
            conn.commit()
            track_id = cursor.lastrowid
            logger.debug(
                "Started event track #%d for %s: %s [%s]",
                track_id, shadow_id, topic, category,
            )
            return track_id
        finally:
            conn.close()

    # ── Update track ──────────────────────────────────────────────────────

    def update_track(
        self,
        track_id: int,
        status: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Update an event track's status and/or notes.

        Args:
            track_id: The track's integer ID.
            status: New status (e.g. "monitoring"). If None, unchanged.
            notes: New notes. If None, unchanged.

        Raises:
            ValueError: If status is invalid.
        """
        _VALID_STATUSES = {STATUS_ACTIVE, STATUS_MONITORING, STATUS_CLOSED}
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError(
                f"status must be one of {_VALID_STATUSES}, got '{status}'"
            )

        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            if status is not None and notes is not None:
                conn.execute(
                    """UPDATE event_tracks SET status = ?, notes = ?, updated_at = ?
                       WHERE id = ?""",
                    (status, notes, now, track_id)
                )
            elif status is not None:
                conn.execute(
                    """UPDATE event_tracks SET status = ?, updated_at = ?
                       WHERE id = ?""",
                    (status, now, track_id)
                )
            elif notes is not None:
                conn.execute(
                    """UPDATE event_tracks SET notes = ?, updated_at = ?
                       WHERE id = ?""",
                    (notes, now, track_id)
                )
            conn.commit()
        finally:
            conn.close()

    # ── Get active tracks ─────────────────────────────────────────────────

    def get_active_tracks(self, shadow_id: str) -> list[dict]:
        """Get all active (not closed) event tracks for a shadow.

        Args:
            shadow_id: The shadow whose active tracks to fetch.

        Returns:
            List of track dicts sorted by created_at (newest first).
        """
        if not shadow_id or not shadow_id.strip():
            return []

        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM event_tracks
                   WHERE shadow_id = ? AND status != ?
                   ORDER BY created_at DESC""",
                (shadow_id.strip(), STATUS_CLOSED)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── Close track ───────────────────────────────────────────────────────

    def close_track(self, track_id: int, outcome: str = "") -> None:
        """Close an event track with a final outcome description.

        Args:
            track_id: The track's integer ID.
            outcome: Final outcome summary (e.g. "Confirmed breakout",
                    "False signal — price reverted").
        """
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE event_tracks
                   SET status = ?, outcome = ?, closed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (STATUS_CLOSED, outcome, now, now, track_id)
            )
            conn.commit()
            logger.debug("Closed event track #%d: %s", track_id, outcome)
        finally:
            conn.close()

    # ── Utility ───────────────────────────────────────────────────────────

    def get_track(self, track_id: int) -> dict | None:
        """Get a single event track by ID.

        Args:
            track_id: The track's integer ID.

        Returns:
            Track dict or None if not found.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM event_tracks WHERE id = ?", (track_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def count_active(self, shadow_id: str | None = None) -> int:
        """Count active (non-closed) tracks, optionally filtered by shadow.

        Args:
            shadow_id: If provided, count only for this shadow.

        Returns:
            Number of tracks with status != 'closed'.
        """
        conn = self._connect()
        try:
            if shadow_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM event_tracks WHERE status != ? AND shadow_id = ?",
                    (STATUS_CLOSED, shadow_id.strip())
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM event_tracks WHERE status != ?",
                    (STATUS_CLOSED,)
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
