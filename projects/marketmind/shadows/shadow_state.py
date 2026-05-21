"""Shadow state persistence -- SQLite schema, config models, CRUD operations."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from marketmind.shadows.shadow_data_types import (  # noqa: F401 — re-export for backward compat
    ShadowConfig,
    VirtualTradeOpen,
    VirtualTrade,
    DailySnapshot,
    IntegrityEvent,
    EmergencyQuotaRequest,
    CollusionFlag,
)
from marketmind.shadows.shadow_schema import (  # noqa: F401 — re-export
    CODE_VERSION,
    _SCHEMA_SQL,
    _MIGRATIONS,
)

logger = logging.getLogger("marketmind.shadows.shadow_state")

# Schema version + DDL + migrations imported from shadow_schema
_ = _SCHEMA_SQL  # reference to suppress unused-import warning

class ShadowStateDB:
    """SQLite-backed shadow state persistence."""

    def __init__(self, db_path: str = "data/shadows/shadows.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            db_version = int(row["value"]) if row else 0

            if db_version > CODE_VERSION:
                logger.warning(
                    "DB schema_version %d > code CODE_VERSION %d — "
                    "database was opened with newer code. Skipping migrations.",
                    db_version, CODE_VERSION
                )
            else:
                for ver, func in _MIGRATIONS:
                    if ver > db_version:
                        func(conn)
                        conn.execute(
                            "INSERT OR REPLACE INTO metadata (key, value) "
                            "VALUES ('schema_version', ?)",
                            (str(ver),)
                        )
                        logger.info("Migration %d applied successfully.", ver)

            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_add_column(conn: sqlite3.Connection, table: str,
                            column: str, col_type: str) -> None:
        """Safe ALTER TABLE ADD COLUMN — ignores if column already exists."""
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info("Migration: added %s.%s %s", table, column, col_type)
        except sqlite3.OperationalError:
            pass  # Column already exists — safe to ignore

    def close(self) -> None:
        pass  # SQLite connections are closed per-operation

    # ── Shadow CRUD ──────────────────────────────────────────────────────

    def create_shadow(self, config: ShadowConfig) -> str:
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM shadows WHERE id = ?", (config.shadow_id,)
            ).fetchone()
            if existing:
                raise ValueError(f"Shadow '{config.shadow_id}' already exists")

            config_json = json.dumps({
                "virtual_capital": config.virtual_capital,
                "max_positions": config.max_positions,
                "model": config.model,
                "temperature": config.temperature,
                "reasoning_effort": config.reasoning_effort,
                "domain": config.domain,
                "max_drawdown_limit": config.max_drawdown_limit,
                "min_trades_for_ranking": config.min_trades_for_ranking,
                "parent_shadow_id": config.parent_shadow_id,
                "generation": config.generation,
            })
            conn.execute(
                """INSERT INTO shadows (id, shadow_type, display_name, status,
                   methodology_prompt, config_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (config.shadow_id, config.shadow_type, config.display_name,
                 config.status, config.methodology_prompt, config_json,
                 config.created_at)
            )
            conn.commit()
            return config.shadow_id
        finally:
            conn.close()

    def get_shadow(self, shadow_id: str) -> ShadowConfig | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM shadows WHERE id = ?", (shadow_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_config(row)
        finally:
            conn.close()

    def get_active_shadows(self, shadow_type: str | None = None) -> list[ShadowConfig]:
        conn = self._connect()
        try:
            if shadow_type:
                rows = conn.execute(
                    "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired') AND shadow_type = ?",
                    (shadow_type,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired')"
                ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def get_visible_shadows(self) -> list[ShadowConfig]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired')"
                " AND shadow_type != 'challenger'"
            ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def get_ranking_eligible_shadows(self) -> list[ShadowConfig]:
        """Shadows eligible for ranking, collusion detection, and challenger engine.
        Excludes beta, retired, eliminated, and challenger shadows."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired','beta')"
                " AND shadow_type != 'challenger'"
            ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def update_shadow_status(self, shadow_id: str, status: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE shadows SET status = ? WHERE id = ?",
                (status, shadow_id)
            )
            conn.commit()
        finally:
            conn.close()

    def retire_shadow(self, shadow_id: str, reason: str) -> None:
        """Mark shadow as retired. Preserves methodology and history as frozen benchmark."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE shadows SET status = 'retired', retired_at = ?, "
                "retirement_reason = ? WHERE id = ?",
                (now, reason, shadow_id)
            )
            conn.execute(
                """UPDATE virtual_trades SET exit_reason = 'shadow_retired',
                   exit_date = ? WHERE shadow_id = ? AND exit_price IS NULL""",
                (now[:10], shadow_id)
            )
            conn.commit()
        finally:
            conn.close()

    def eliminate_shadow(self, shadow_id: str, reason: str) -> None:
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE shadows SET status = 'eliminated', eliminated_at = ? WHERE id = ?",
                (now, shadow_id)
            )
            conn.execute(
                """UPDATE virtual_trades SET exit_reason = 'shadow_eliminated',
                   exit_date = ? WHERE shadow_id = ? AND exit_price IS NULL""",
                (now[:10], shadow_id)
            )
            conn.commit()
        finally:
            conn.close()

    def update_shadow_type(self, shadow_id: str, new_type: str) -> bool:
        """Change a shadow's type (e.g., challenger → expert on promotion)."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE shadows SET shadow_type = ? WHERE id = ?",
                (new_type, shadow_id)
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def update_methodology_prompt(self, shadow_id: str, new_prompt: str,
                                    reason: str = "") -> bool:
        """Update a shadow's methodology prompt and log the change (P1-1).

        Returns True if the shadow was found and updated.
        """
        conn = self._connect()
        try:
            old = conn.execute(
                "SELECT methodology_prompt FROM shadows WHERE id = ?",
                (shadow_id,)
            ).fetchone()
            if old is None:
                return False
            old_prompt = old["methodology_prompt"] or ""

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE shadows SET methodology_prompt = ? WHERE id = ?",
                (new_prompt, shadow_id)
            )
            conn.execute(
                """INSERT INTO methodology_changes
                   (shadow_id, change_type, old_prompt, new_prompt, reason, changed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shadow_id, "update", old_prompt[:500], new_prompt[:500], reason, now)
            )
            conn.commit()
            logger.info("Methodology updated for %s: %s", shadow_id, reason)
            return True
        finally:
            conn.close()

    def get_methodology_history(self, shadow_id: str,
                                 limit: int = 20) -> list[dict]:
        """Get methodology change history for a shadow (P1-1)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT change_type, reason, changed_at FROM methodology_changes
                   WHERE shadow_id = ? ORDER BY changed_at DESC LIMIT ?""",
                (shadow_id, limit)
            ).fetchall()
            return [{"change_type": r["change_type"], "reason": r["reason"],
                     "changed_at": r["changed_at"]} for r in rows]
        finally:
            conn.close()

    def get_original_methodology(self, shadow_id: str) -> str | None:
        """Get the first recorded methodology prompt (baseline) for a shadow."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT old_prompt FROM methodology_changes
                   WHERE shadow_id = ? ORDER BY changed_at ASC LIMIT 1""",
                (shadow_id,)
            ).fetchone()
            return row["old_prompt"] if row else None
        finally:
            conn.close()

    def get_failure_patterns(self, shadow_id: str, days: int = 90) -> list[str]:
        """Get failure patterns from AEL debriefs (P3-1).

        Queries methodology_changes for debrief-type entries within the
        specified day window. Each row's reason field contains one failure
        pattern description.

        Args:
            shadow_id: The shadow whose debriefs to query.
            days: Lookback window in days (default 90).

        Returns:
            List of failure pattern strings, most recent first. Empty if none.
        """
        conn = self._connect()
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT reason, new_prompt FROM methodology_changes
                   WHERE shadow_id = ? AND change_type = 'debrief'
                   AND changed_at >= ?
                   ORDER BY changed_at DESC""",
                (shadow_id, cutoff)
            ).fetchall()

            patterns = []
            for row in rows:
                reason = (row["reason"] or "").strip()
                if reason:
                    patterns.append(reason)

            # Also extract from [FAILURE PATTERNS TO AVOID] block in new_prompt
            for row in rows:
                new_prompt = row["new_prompt"] or ""
                if "[FAILURE PATTERNS TO AVOID" in new_prompt:
                    section = new_prompt.split("[FAILURE PATTERNS TO AVOID")[1]
                    section = section.split("\n\n")[0] if "\n\n" in section else section
                    for line in section.split("\n"):
                        line = line.strip().lstrip("-").strip()
                        if line and not line.startswith("learned"):
                            patterns.append(line)

            return patterns
        finally:
            conn.close()

    def get_retired_insights(self, shadow_id: str, days: int = 90) -> list[str]:
        """Get retired insights from crystallization (P3-1).

        Queries methodology_changes for crystallization_retire entries.
        Retired insights are previously-validated insights that have been
        invalidated by new evidence.

        Args:
            shadow_id: The shadow whose retired insights to query.
            days: Lookback window in days (default 90).

        Returns:
            List of retired insight strings, most recent first. Empty if none.
        """
        conn = self._connect()
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT reason, new_prompt FROM methodology_changes
                   WHERE shadow_id = ? AND change_type = 'crystallization_retire'
                   AND changed_at >= ?
                   ORDER BY changed_at DESC""",
                (shadow_id, cutoff)
            ).fetchall()

            insights = []
            for row in rows:
                reason = (row["reason"] or "").strip()
                if reason:
                    insights.append(reason)

            # Also extract from [RETIRED] block in new_prompt
            for row in rows:
                new_prompt = row["new_prompt"] or ""
                if "[RETIRED:" in new_prompt:
                    section = new_prompt.split("[RETIRED:")[1]
                    section = section.split("]")[0] if "]" in section else section
                    section = section.strip()
                    if section:
                        insights.append(section)

            return insights
        finally:
            conn.close()

    @staticmethod
    def _row_to_config(row: sqlite3.Row) -> ShadowConfig:
        try:
            config_json = json.loads(row["config_json"] or "{}")
        except json.JSONDecodeError:
            logger.warning("Corrupted config_json for shadow %s, using defaults", row["id"])
            config_json = {}
        return ShadowConfig(
            shadow_id=row["id"],
            shadow_type=row["shadow_type"],
            display_name=row["display_name"],
            methodology_prompt=row["methodology_prompt"] or "",
            virtual_capital=config_json.get("virtual_capital", 0),
            max_positions=config_json.get("max_positions", 3),
            model=config_json.get("model", "pro"),
            temperature=config_json.get("temperature", 0.3),
            reasoning_effort=config_json.get("reasoning_effort", "max"),
            domain=config_json.get("domain"),
            max_drawdown_limit=config_json.get("max_drawdown_limit", 0.35),
            min_trades_for_ranking=config_json.get("min_trades_for_ranking", 5),
            parent_shadow_id=config_json.get("parent_shadow_id"),
            generation=config_json.get("generation", 0),
            status=row["status"],
            eliminated_at=row["eliminated_at"],
            retired_at=row["retired_at"],
            retirement_reason=row["retirement_reason"],
            created_at=row["created_at"],
        )

    # ── Virtual trades (delegated to shadow_trade_repo) ───────────────────

    def record_trade_open(self, shadow_id: str, trade: VirtualTradeOpen) -> int:
        from marketmind.shadows.shadow_trade_repo import record_trade_open
        conn = self._connect()
        try:
            return record_trade_open(conn, shadow_id, trade)
        finally:
            conn.close()

    def record_trade_close(self, trade_id: int, exit_price: float,
                           exit_reason: str, pnl_pct: float) -> None:
        from marketmind.shadows.shadow_trade_repo import record_trade_close
        conn = self._connect()
        try:
            record_trade_close(conn, trade_id, exit_price, exit_reason, pnl_pct)
        finally:
            conn.close()

    def get_open_trades(self, shadow_id: str) -> list[VirtualTrade]:
        from marketmind.shadows.shadow_trade_repo import get_open_trades
        conn = self._connect()
        try:
            return get_open_trades(conn, shadow_id)
        finally:
            conn.close()

    def get_trade_history(self, shadow_id: str, limit: int = 90) -> list[VirtualTrade]:
        from marketmind.shadows.shadow_trade_repo import get_trade_history
        conn = self._connect()
        try:
            return get_trade_history(conn, shadow_id, limit)
        finally:
            conn.close()

    # ── Daily snapshots (delegated to shadow_snapshot_repo) ───────────────

    def save_snapshot(self, shadow_id: str, snapshot: DailySnapshot) -> None:
        from marketmind.shadows.shadow_snapshot_repo import save_snapshot
        conn = self._connect()
        try:
            save_snapshot(conn, shadow_id, snapshot)
        finally:
            conn.close()

    def get_snapshot_history(self, shadow_id: str, days: int = 90) -> list[DailySnapshot]:
        from marketmind.shadows.shadow_snapshot_repo import get_snapshot_history
        conn = self._connect()
        try:
            return get_snapshot_history(conn, shadow_id, days)
        finally:
            conn.close()

    def get_latest_snapshot(self, shadow_id: str) -> DailySnapshot | None:
        from marketmind.shadows.shadow_snapshot_repo import get_latest_snapshot
        conn = self._connect()
        try:
            return get_latest_snapshot(conn, shadow_id)
        finally:
            conn.close()

    def get_tier_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, str]]:
        from marketmind.shadows.shadow_snapshot_repo import get_tier_history
        conn = self._connect()
        try:
            return get_tier_history(conn, shadow_id, days)
        finally:
            conn.close()

    def get_wr_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, float]]:
        from marketmind.shadows.shadow_snapshot_repo import get_wr_history
        conn = self._connect()
        try:
            return get_wr_history(conn, shadow_id, days)
        finally:
            conn.close()

    def get_insight_dates(self, shadow_id: str, days: int = 120) -> list[str]:
        from marketmind.shadows.shadow_snapshot_repo import get_insight_dates
        conn = self._connect()
        try:
            return get_insight_dates(conn, shadow_id, days)
        finally:
            conn.close()

    def get_abstention_days(self, shadow_id: str, days: int = 180) -> int:
        from marketmind.shadows.shadow_snapshot_repo import get_abstention_days
        conn = self._connect()
        try:
            return get_abstention_days(conn, shadow_id, days)
        finally:
            conn.close()

    def save_raw_output(self, shadow_id: str, date: str, raw_output: str,
                         token_count: int = 0, model: str = "pro") -> None:
        from marketmind.shadows.shadow_snapshot_repo import save_raw_output
        conn = self._connect()
        try:
            save_raw_output(conn, shadow_id, date, raw_output, token_count, model)
        finally:
            conn.close()

    def count_consecutive_zero_insights(self, shadow_id: str,
                                         max_days: int = 8) -> int:
        from marketmind.shadows.shadow_snapshot_repo import count_consecutive_zero_insights
        conn = self._connect()
        try:
            return count_consecutive_zero_insights(conn, shadow_id, max_days)
        finally:
            conn.close()

    def get_raw_output(self, shadow_id: str, date: str) -> str | None:
        from marketmind.shadows.shadow_snapshot_repo import get_raw_output
        conn = self._connect()
        try:
            return get_raw_output(conn, shadow_id, date)
        finally:
            conn.close()

    def get_token_history(self, shadow_id: str, days: int = 30) -> list[int]:
        from marketmind.shadows.shadow_snapshot_repo import get_token_history
        conn = self._connect()
        try:
            return get_token_history(conn, shadow_id, days)
        finally:
            conn.close()

    def update_snapshot_fields(self, shadow_id: str, date: str, **fields) -> None:
        from marketmind.shadows.shadow_snapshot_repo import update_snapshot_fields
        conn = self._connect()
        try:
            update_snapshot_fields(conn, shadow_id, date, **fields)
        finally:
            conn.close()

    # ── Rankings (delegated to shadow_analysis_repo) ───────────────────────

    def save_rankings(self, date: str, rankings: list[tuple[str, float, float, dict]]) -> None:
        from marketmind.shadows.shadow_analysis_repo import save_rankings
        conn = self._connect()
        try:
            save_rankings(conn, date, rankings)
        finally:
            conn.close()

    def get_ranking_history(self, shadow_id: str, days: int = 90) -> list[dict]:
        from marketmind.shadows.shadow_analysis_repo import get_ranking_history
        conn = self._connect()
        try:
            return get_ranking_history(conn, shadow_id, days)
        finally:
            conn.close()

    # ── Integrity / Emergency / Collusion (delegated to shadow_integrity_repo) ─

    def record_integrity_event(self, shadow_id: str, event: IntegrityEvent) -> bool:
        from marketmind.shadows.shadow_integrity_repo import record_integrity_event
        conn = self._connect()
        try:
            return record_integrity_event(conn, shadow_id, event)
        finally:
            conn.close()

    def get_integrity_score(self, shadow_id: str) -> int:
        from marketmind.shadows.shadow_integrity_repo import get_integrity_score
        conn = self._connect()
        try:
            return get_integrity_score(conn, shadow_id)
        finally:
            conn.close()

    def get_integrity_history(self, shadow_id: str, days: int = 90) -> list[IntegrityEvent]:
        from marketmind.shadows.shadow_integrity_repo import get_integrity_history
        conn = self._connect()
        try:
            return get_integrity_history(conn, shadow_id, days)
        finally:
            conn.close()

    def record_emergency_quota(self, shadow_id: str, quota: EmergencyQuotaRequest) -> int:
        from marketmind.shadows.shadow_integrity_repo import record_emergency_quota
        conn = self._connect()
        try:
            return record_emergency_quota(conn, shadow_id, quota)
        finally:
            conn.close()

    def update_emergency_result(self, quota_id: int, result: str,
                                pnl_impact: float, penalty: str) -> None:
        from marketmind.shadows.shadow_integrity_repo import update_emergency_result
        conn = self._connect()
        try:
            update_emergency_result(conn, quota_id, result, pnl_impact, penalty)
        finally:
            conn.close()

    def get_pending_emergency_audits(self) -> list[EmergencyQuotaRequest]:
        from marketmind.shadows.shadow_integrity_repo import get_pending_emergency_audits
        conn = self._connect()
        try:
            return get_pending_emergency_audits(conn)
        finally:
            conn.close()

    def record_collusion_flag(self, flag: CollusionFlag) -> None:
        from marketmind.shadows.shadow_integrity_repo import record_collusion_flag
        conn = self._connect()
        try:
            record_collusion_flag(conn, flag)
        finally:
            conn.close()

    def get_recent_collusion_flags(self, days: int = 30) -> list[CollusionFlag]:
        from marketmind.shadows.shadow_integrity_repo import get_recent_collusion_flags
        conn = self._connect()
        try:
            return get_recent_collusion_flags(conn, days)
        finally:
            conn.close()

    def save_emergency_quota_state(self, shadow_id: str, state_json: str) -> None:
        from marketmind.shadows.shadow_integrity_repo import save_emergency_quota_state
        conn = self._connect()
        try:
            save_emergency_quota_state(conn, shadow_id, state_json)
        finally:
            conn.close()

    def load_emergency_quota_state(self, shadow_id: str) -> str | None:
        from marketmind.shadows.shadow_integrity_repo import load_emergency_quota_state
        conn = self._connect()
        try:
            return load_emergency_quota_state(conn, shadow_id)
        finally:
            conn.close()

    def save_paper_live_gap_state(self, shadow_id: str, state_json: str) -> None:
        from marketmind.shadows.shadow_integrity_repo import save_paper_live_gap_state
        conn = self._connect()
        try:
            save_paper_live_gap_state(conn, shadow_id, state_json)
        finally:
            conn.close()

    def load_paper_live_gap_state(self, shadow_id: str) -> str | None:
        from marketmind.shadows.shadow_integrity_repo import load_paper_live_gap_state
        conn = self._connect()
        try:
            return load_paper_live_gap_state(conn, shadow_id)
        finally:
            conn.close()

    # ── Cycle checkpoints (P3-4 partial-state recovery) ────────────────────

    def save_checkpoint(self, date: str, shadow_id: str, status: str,
                        step: int, analysis_json: str | None = None,
                        error_message: str | None = None) -> None:
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
        conn = self._connect()
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
        finally:
            conn.close()

    def get_checkpoint(self, date: str, shadow_id: str) -> dict | None:
        """Get checkpoint for a specific shadow on a specific date (P3-4).

        Returns None if no checkpoint exists for this (date, shadow_id) pair.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM cycle_checkpoints WHERE date = ? AND shadow_id = ?",
                (date, shadow_id)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_incomplete_shadows(self, date: str) -> list[str]:
        """Return shadow_ids with status='pending' or 'failed' for a date (P3-4).

        Used at cycle start to determine which shadows need to be re-run
        after a mid-cycle crash.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT shadow_id FROM cycle_checkpoints "
                "WHERE date = ? AND status IN ('pending', 'failed')",
                (date,)
            ).fetchall()
            return [r["shadow_id"] for r in rows]
        finally:
            conn.close()

    def clear_date_checkpoints(self, date: str) -> None:
        """Delete all checkpoints for a date (cleanup after cycle completes, P3-4)."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM cycle_checkpoints WHERE date = ?", (date,))
            conn.commit()
        finally:
            conn.close()

    # ── Bulk operations ───────────────────────────────────────────────────

    def get_all_daily_snapshots(self, date: str) -> list[DailySnapshot]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM daily_snapshots WHERE date = ?",
                (date,)
            ).fetchall()
            return [self._row_to_snapshot(r) for r in rows]
        finally:
            conn.close()

    # ── Analysis / PnL (delegated to shadow_analysis_repo) ─────────────────
    # NOTE: These methods are for BACKTEST and internal ecosystem use ONLY.
    # Shadows are an internal competition ecosystem for ranking/evolution/
    # crystallization. They do NOT vote on investment decisions.
    # app.py:110 sets shadow_analyses = None by design — this is intentional.
    # Analysis persistence exists solely for backtest_runner.py signal-quality
    # analysis and crystallization validation.

    def get_all_active_analyses(self, date: str, ticker: str) -> list[dict]:
        """[INTERNAL-ONLY] Get active shadow metadata. For ecosystem health, NOT decision input."""
        from marketmind.shadows.shadow_analysis_repo import get_all_active_analyses
        conn = self._connect()
        try:
            return get_all_active_analyses(conn, date, ticker)
        finally:
            conn.close()

    def get_next_day_return_sign(self, ticker_or_shadow: str, date: str) -> int | None:
        from marketmind.shadows.shadow_analysis_repo import get_next_day_return_sign
        conn = self._connect()
        try:
            return get_next_day_return_sign(conn, ticker_or_shadow, date)
        finally:
            conn.close()

    def save_analyses(self, shadow_id: str, date: str, analyses: list) -> None:
        """[INTERNAL-ONLY] Persist shadow analyses for backtest/audit. NOT a decision input."""
        from marketmind.shadows.shadow_analysis_repo import save_analyses
        if not analyses:
            return
        conn = self._connect()
        try:
            save_analyses(conn, shadow_id, date, analyses)
        finally:
            conn.close()

    def save_beta_analyses(self, shadow_id: str, date: str, analyses: list,
                           methodology_variant: str | None = None) -> None:
        """Persist beta shadow analyses to isolated beta_analyses table."""
        if not analyses:
            return
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        try:
            for a in analyses:
                conn.execute(
                    """INSERT INTO beta_analyses (shadow_id, date, ticker, direction,
                       confidence, thesis, risk_note, methodology_variant, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shadow_id, date,
                     a.get("ticker", ""), a.get("direction", "abstain"),
                     a.get("confidence", 0.0), a.get("thesis", ""),
                     a.get("risk_note", ""), methodology_variant, now)
                )
            conn.commit()
        finally:
            conn.close()

    def get_analyses_by_date_range(self, start_date: str, end_date: str) -> list[dict]:
        """[INTERNAL-ONLY] Query analyses for BACKTEST signal-quality analysis. NOT a decision input."""
        from marketmind.shadows.shadow_analysis_repo import get_analyses_by_date_range
        conn = self._connect()
        try:
            return get_analyses_by_date_range(conn, start_date, end_date)
        finally:
            conn.close()

    # ── Market prices CRUD (P2-4) ─────────────────────────────────────

    def insert_market_price(self, ticker: str, date: str, open_price: float,
                            high: float, low: float, close: float, volume: int,
                            next_day_return: float | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO market_prices
                   (ticker, date, open, high, low, close, volume, next_day_return)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker, date, open_price, high, low, close, volume, next_day_return))
            conn.commit()
        finally:
            conn.close()

    def get_market_prices(self, ticker: str, start_date: str | None = None,
                          end_date: str | None = None) -> list[dict]:
        conn = self._connect()
        try:
            if start_date and end_date:
                rows = conn.execute(
                    """SELECT * FROM market_prices WHERE ticker = ? AND date >= ? AND date <= ?
                       ORDER BY date ASC""",
                    (ticker, start_date, end_date)).fetchall()
            elif start_date:
                rows = conn.execute(
                    """SELECT * FROM market_prices WHERE ticker = ? AND date >= ?
                       ORDER BY date ASC""",
                    (ticker, start_date)).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM market_prices WHERE ticker = ? ORDER BY date ASC""",
                    (ticker,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_next_day_return(self, ticker: str, date: str) -> float | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT next_day_return FROM market_prices WHERE ticker = ? AND date = ?",
                (ticker, date)).fetchone()
            return row["next_day_return"] if row else None
        finally:
            conn.close()

    def get_analyses_with_direction(self, shadow_id: str,
                                     days: int = 90) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT ticker, direction, date FROM shadow_analyses
                   WHERE shadow_id = ? AND direction != 'abstain'
                   ORDER BY date DESC LIMIT ?""",
                (shadow_id, days)).fetchall()
            return [{"ticker": r["ticker"], "direction": r["direction"],
                     "date": r["date"]} for r in rows]
        finally:
            conn.close()

    def get_pnl_by_domain(self, domain: str) -> list[float]:
        from marketmind.shadows.shadow_analysis_repo import get_pnl_by_domain
        conn = self._connect()
        try:
            return get_pnl_by_domain(conn, domain)
        finally:
            conn.close()


