"""PendingSignalRegistry — manage awaiting signals for shadow ecosystem.

Manages the pending_signals table: register future signals, check trigger
conditions, expire stale signals, and transfer orphaned signals when a
shadow is eliminated.

All operations are pure Python — zero LLM calls. The DB schema is defined
in shadow_schema.py (migration 12).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.shadows.pending_signal_registry")

# Default DB path relative to project root
DEFAULT_DB_PATH = "data/shadows/shadows.db"

# Status constants
STATUS_AWAITING = "awaiting"
STATUS_TRIGGERED = "triggered"
STATUS_EXPIRED = "expired"


class PendingSignalRegistry:
    """Manage the pending_signals table for future-event-triggered signals.

    Shadows register signals they expect to trigger based on upcoming
    events (earnings, FOMC, macro data releases). The registry auto-checks
    and expires stale entries.

    Usage:
        registry = PendingSignalRegistry("data/shadows/shadows.db")
        sig_id = registry.register_signal(
            shadow_id="expert:gold:agent_01",
            signal_type="earnings",
            description="AAPL Q2 earnings beat expected",
            trigger_condition="AAPL earnings release date",
            ticker="AAPL",
            expected_date="2026-05-25",
        )
        triggered = registry.check_triggers("2026-05-25")
        expired_count = registry.expire_signals("2026-06-05")
    """

    _EXPIRY_GRACE_DAYS = 7
    _DEFAULT_MAX_COUNT = 10

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """Initialize the registry with a path to the shadows SQLite DB.

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

    # ── Register ──────────────────────────────────────────────────────────

    def register_signal(
        self,
        shadow_id: str,
        signal_type: str,
        description: str,
        trigger_condition: str,
        ticker: str,
        expected_date: str,
    ) -> int:
        """Register a pending signal awaiting a future event trigger.

        Args:
            shadow_id: The shadow that created this signal.
            signal_type: Category (e.g. "earnings", "fomc", "macro", "volatility").
            description: Human-readable description of the expected signal.
            trigger_condition: What event triggers this signal.
            ticker: Primary ticker this signal relates to.
            expected_date: ISO date string (YYYY-MM-DD) when trigger is expected.

        Returns:
            The new signal's integer ID.

        Raises:
            ValueError: If shadow_id or ticker is empty, or expected_date is invalid.
            sqlite3.Error: On database errors.
        """
        if not shadow_id or not shadow_id.strip():
            raise ValueError("shadow_id must not be empty")
        if not ticker or not ticker.strip():
            raise ValueError("ticker must not be empty")
        # Validate date format
        try:
            datetime.strptime(expected_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValueError(
                f"expected_date must be YYYY-MM-DD format, got '{expected_date}'"
            )

        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """INSERT INTO pending_signals
                   (shadow_id, signal_type, description, trigger_condition,
                    ticker, expected_date, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id.strip(), signal_type, description, trigger_condition,
                 ticker.strip().upper(), expected_date, STATUS_AWAITING, now)
            )
            conn.commit()
            signal_id = cursor.lastrowid
            logger.debug(
                "Registered pending signal #%d for %s: %s on %s",
                signal_id, shadow_id, signal_type, expected_date,
            )
            return signal_id
        finally:
            conn.close()

    # ── Check triggers ────────────────────────────────────────────────────

    def check_triggers(self, date: str) -> list[dict]:
        """Return all awaiting signals whose expected_date <= given date.

        These are signals that should be considered "triggered" because
        the expected event date has arrived or passed.

        Args:
            date: ISO date string (YYYY-MM-DD) to check against.

        Returns:
            List of signal dicts sorted by priority (oldest expected_date first).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM pending_signals
                   WHERE status = ? AND expected_date <= ?
                   ORDER BY expected_date ASC""",
                (STATUS_AWAITING, date)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── Expire signals ────────────────────────────────────────────────────

    def expire_signals(self, date: str) -> int:
        """Mark as expired all signals past their expected_date + grace period.

        Signals are expired when: expected_date + 7 days < date AND they are
        still in 'awaiting' status (never triggered).

        Args:
            date: ISO date string (YYYY-MM-DD) representing "today".

        Returns:
            Number of signals expired.
        """
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValueError(f"date must be YYYY-MM-DD format, got '{date}'")

        cutoff = current_date - timedelta(days=self._EXPIRY_GRACE_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        conn = self._connect()
        try:
            cursor = conn.execute(
                """UPDATE pending_signals SET status = ?
                   WHERE status = ? AND expected_date <= ?""",
                (STATUS_EXPIRED, STATUS_AWAITING, cutoff_str)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info("Expired %d pending signals (cutoff: %s)", count, cutoff_str)
            return count
        finally:
            conn.close()

    # ── Get pending for shadow ─────────────────────────────────────────────

    def get_pending_for_shadow(
        self, shadow_id: str, max_count: int = _DEFAULT_MAX_COUNT
    ) -> list[dict]:
        """Get pending (awaiting) signals for a specific shadow.

        Results are priority-sorted: closest expected_date first, then
        most recently created.

        Args:
            shadow_id: The shadow whose pending signals to fetch.
            max_count: Maximum number of signals to return (default 10).

        Returns:
            List of signal dicts sorted by priority.
        """
        if not shadow_id or not shadow_id.strip():
            return []

        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM pending_signals
                   WHERE shadow_id = ? AND status = ?
                   ORDER BY expected_date ASC, created_at DESC
                   LIMIT ?""",
                (shadow_id.strip(), STATUS_AWAITING, max_count)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── Transfer orphaned signals ─────────────────────────────────────────

    def transfer_orphaned_signals(self, eliminated_shadow_id: str) -> int:
        """Transfer pending signals from an eliminated shadow to system owner.

        When a shadow is eliminated, its pending signals should not be lost.
        They are reassigned to the system owner for evaluation.

        Args:
            eliminated_shadow_id: The shadow_id that was eliminated.

        Returns:
            Number of signals transferred.
        """
        if not eliminated_shadow_id or not eliminated_shadow_id.strip():
            return 0

        system_owner = "system:owner"
        conn = self._connect()
        try:
            cursor = conn.execute(
                """UPDATE pending_signals SET shadow_id = ?
                   WHERE shadow_id = ? AND status = ?""",
                (system_owner, eliminated_shadow_id.strip(), STATUS_AWAITING)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(
                    "Transferred %d orphaned signals from %s to %s",
                    count, eliminated_shadow_id, system_owner,
                )
            return count
        finally:
            conn.close()

    # ── Utility ───────────────────────────────────────────────────────────

    def mark_triggered(self, signal_id: int) -> None:
        """Explicitly mark a signal as triggered.

        Args:
            signal_id: The signal's integer ID.
        """
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE pending_signals SET status = ?, triggered_at = ?
                   WHERE id = ? AND status = ?""",
                (STATUS_TRIGGERED, now, signal_id, STATUS_AWAITING)
            )
            conn.commit()
        finally:
            conn.close()

    def count_awaiting(self, shadow_id: str | None = None) -> int:
        """Count awaiting signals, optionally filtered by shadow.

        Args:
            shadow_id: If provided, count only for this shadow.

        Returns:
            Number of signals with status='awaiting'.
        """
        conn = self._connect()
        try:
            if shadow_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM pending_signals WHERE status = ? AND shadow_id = ?",
                    (STATUS_AWAITING, shadow_id.strip())
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM pending_signals WHERE status = ?",
                    (STATUS_AWAITING,)
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
