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
                    "SELECT * FROM shadows WHERE status != 'eliminated' AND shadow_type = ?",
                    (shadow_type,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadows WHERE status != 'eliminated'"
                ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def get_visible_shadows(self) -> list[ShadowConfig]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM shadows WHERE status != 'eliminated' AND shadow_type != 'challenger'"
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

    # ── Rankings (delegated to shadow_vote_repo) ──────────────────────────

    def save_rankings(self, date: str, rankings: list[tuple[str, float, float, dict]]) -> None:
        from marketmind.shadows.shadow_vote_repo import save_rankings
        conn = self._connect()
        try:
            save_rankings(conn, date, rankings)
        finally:
            conn.close()

    def get_ranking_history(self, shadow_id: str, days: int = 90) -> list[dict]:
        from marketmind.shadows.shadow_vote_repo import get_ranking_history
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

    # ── Vote / PnL (delegated to shadow_vote_repo) ────────────────────────

    def get_all_active_votes(self, date: str, ticker: str) -> list[dict]:
        from marketmind.shadows.shadow_vote_repo import get_all_active_votes
        conn = self._connect()
        try:
            return get_all_active_votes(conn, date, ticker)
        finally:
            conn.close()

    def get_next_day_return_sign(self, ticker_or_shadow: str, date: str) -> int | None:
        from marketmind.shadows.shadow_vote_repo import get_next_day_return_sign
        conn = self._connect()
        try:
            return get_next_day_return_sign(conn, ticker_or_shadow, date)
        finally:
            conn.close()

    def save_votes(self, shadow_id: str, date: str, votes: list) -> None:
        from marketmind.shadows.shadow_vote_repo import save_votes
        if not votes:
            return
        conn = self._connect()
        try:
            save_votes(conn, shadow_id, date, votes)
        finally:
            conn.close()

    def get_votes_by_date_range(self, start_date: str, end_date: str) -> list[dict]:
        from marketmind.shadows.shadow_vote_repo import get_votes_by_date_range
        conn = self._connect()
        try:
            return get_votes_by_date_range(conn, start_date, end_date)
        finally:
            conn.close()

    def get_pnl_by_domain(self, domain: str) -> list[float]:
        from marketmind.shadows.shadow_vote_repo import get_pnl_by_domain
        conn = self._connect()
        try:
            return get_pnl_by_domain(conn, domain)
        finally:
            conn.close()


