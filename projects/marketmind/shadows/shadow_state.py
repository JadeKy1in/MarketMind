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

logger = logging.getLogger("marketmind.shadows.shadow_state")


# ── SQLite database ──────────────────────────────────────────────────────────

CODE_VERSION = 8  # Increment on any schema change; add migration to _MIGRATIONS

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadows (
    id TEXT PRIMARY KEY,
    shadow_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    methodology_prompt TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL,
    eliminated_at TEXT
);

CREATE TABLE IF NOT EXISTS methodology_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_prompt TEXT,
    new_prompt TEXT,
    reason TEXT,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS virtual_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    position_size_pct REAL NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    exit_reason TEXT,
    pnl_pct REAL,
    virtual_slippage_applied REAL DEFAULT 0.0,
    confidence_discount_applied REAL DEFAULT 0.0,
    paper_live_gap_ratio REAL DEFAULT 0.0,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    virtual_capital REAL NOT NULL,
    daily_return_pct REAL,
    cumulative_return_pct REAL,
    max_drawdown_pct REAL,
    win_rate_pct REAL,
    sharpe_ratio REAL,
    calmar_ratio REAL,
    omega_ratio REAL,
    mppm_score REAL,
    composite_score REAL,
    deflated_score REAL,
    percentile_rank REAL,
    achievement_tier TEXT,
    flash_quota_used INTEGER DEFAULT 0,
    pro_quota_used INTEGER DEFAULT 0,
    emergency_quotas_used INTEGER DEFAULT 0,
    insights_generated INTEGER DEFAULT 0,
    votes_produced INTEGER DEFAULT 0,
    discount_rate REAL DEFAULT 0.20,
    UNIQUE(shadow_id, date),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS shadow_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_output TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    model TEXT DEFAULT 'pro',
    UNIQUE(shadow_id, date),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS ranking_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    shadow_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    composite_score REAL NOT NULL,
    deflated_score REAL NOT NULL,
    component_scores TEXT NOT NULL,
    UNIQUE(date, shadow_id),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS integrity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    claim_detail TEXT NOT NULL,
    score_change INTEGER NOT NULL,
    new_score INTEGER NOT NULL,
    UNIQUE(shadow_id, date, event_type, claim_detail),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS emergency_quotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    confidence_self_report INTEGER NOT NULL,
    opportunity_description TEXT NOT NULL,
    result TEXT DEFAULT 'pending',
    pnl_impact_pct REAL,
    quota_penalty_applied TEXT,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS collusion_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    agreement_pct REAL NOT NULL,
    consecutive_days INTEGER NOT NULL,
    market_signal_strength REAL,
    verdict TEXT NOT NULL,
    user_action TEXT
);

CREATE TABLE IF NOT EXISTS emergency_quota_state (
    shadow_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS paper_live_gap_state (
    shadow_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS shadow_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long','short','abstain')),
    confidence REAL NOT NULL,
    thesis TEXT,
    risk_note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_votes_date ON shadow_votes(date);
CREATE INDEX IF NOT EXISTS idx_shadow_votes_shadow_date ON shadow_votes(shadow_id, date);

CREATE TABLE IF NOT EXISTS belief_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    proposition TEXT NOT NULL,
    alpha REAL NOT NULL DEFAULT 1.0,
    beta REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    tier TEXT NOT NULL DEFAULT 'working',
    source TEXT NOT NULL DEFAULT 'shadow',
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decayed_at TEXT DEFAULT NULL,
    retired_at TEXT DEFAULT NULL,
    retire_reason TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS belief_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    node_id TEXT NOT NULL,
    shadow_id TEXT NOT NULL,
    value REAL NOT NULL,
    confidence REAL NOT NULL,
    source_type TEXT NOT NULL,
    source_path TEXT DEFAULT '',
    extracted_text TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES belief_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS belief_retirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    retired_confidence REAL NOT NULL,
    threshold REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES belief_nodes(node_id)
);

CREATE INDEX IF NOT EXISTS idx_belief_nodes_status ON belief_nodes(status);
CREATE INDEX IF NOT EXISTS idx_belief_nodes_tier ON belief_nodes(tier);
CREATE INDEX IF NOT EXISTS idx_belief_observations_node ON belief_observations(node_id);
CREATE INDEX IF NOT EXISTS idx_belief_observations_shadow ON belief_observations(shadow_id);
"""


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


# ── Migration registry (module-level, after class definition) ───────────────

def _migration_1_add_discount_rate(conn: sqlite3.Connection) -> None:
    """Phase D: add discount_rate column to daily_snapshots."""
    ShadowStateDB._migrate_add_column(
        conn, "daily_snapshots", "discount_rate", "REAL DEFAULT 0.20"
    )


def _migration_2_add_belief_tables(conn: sqlite3.Connection) -> None:
    """Phase F-3: add 3-tier layered memory tables for ShadowMemoryStore."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS belief_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL UNIQUE,
            proposition TEXT NOT NULL,
            alpha REAL NOT NULL DEFAULT 1.0,
            beta REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'active',
            tier TEXT NOT NULL DEFAULT 'working',
            source TEXT NOT NULL DEFAULT 'shadow',
            tags TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            decayed_at TEXT DEFAULT NULL,
            retired_at TEXT DEFAULT NULL,
            retire_reason TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS belief_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id TEXT NOT NULL UNIQUE,
            node_id TEXT NOT NULL,
            shadow_id TEXT NOT NULL,
            value REAL NOT NULL,
            confidence REAL NOT NULL,
            source_type TEXT NOT NULL,
            source_path TEXT DEFAULT '',
            extracted_text TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES belief_nodes(node_id)
        );
        CREATE TABLE IF NOT EXISTS belief_retirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL,
            retired_confidence REAL NOT NULL,
            threshold REAL NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES belief_nodes(node_id)
        );
        CREATE INDEX IF NOT EXISTS idx_belief_nodes_status ON belief_nodes(status);
        CREATE INDEX IF NOT EXISTS idx_belief_nodes_tier ON belief_nodes(tier);
        CREATE INDEX IF NOT EXISTS idx_belief_observations_node ON belief_observations(node_id);
        CREATE INDEX IF NOT EXISTS idx_belief_observations_shadow ON belief_observations(shadow_id);
    """)


def _migration_3_add_market_prices(conn: sqlite3.Connection) -> None:
    """P2-4: add market_prices table for external market anchor validation."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL DEFAULT 0,
            next_day_return REAL,
            UNIQUE(ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_market_prices_ticker_date ON market_prices(ticker, date);
    """)


def _migration_4_add_cycle_checkpoints(conn: sqlite3.Connection) -> None:
    """P3-4: add cycle_checkpoints table for partial-state recovery."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cycle_checkpoints (
            date TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            step_completed INTEGER NOT NULL DEFAULT 0,
            shadow_states TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)


def _migration_5_add_signal_quality(conn: sqlite3.Connection) -> None:
    """Phase B audit: add outcome_label + outcome_return_pct to shadow_votes."""
    for col, col_type in [("outcome_label", "TEXT DEFAULT NULL"),
                           ("outcome_return_pct", "REAL DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE shadow_votes ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass


def _migration_6_add_access_audit_log(conn: sqlite3.Connection) -> None:
    """N2 + N-S4: add access_audit_log table for ELITE DB access control."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS access_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_id TEXT NOT NULL,
            target_shadow_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            detail TEXT DEFAULT '',
            accessed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_access_audit_log_caller ON access_audit_log(caller_id);
        CREATE INDEX IF NOT EXISTS idx_access_audit_log_accessed_at ON access_audit_log(accessed_at);
    """)


def _migration_7_add_phase_c_tables(conn: sqlite3.Connection) -> None:
    """H10+C6+H8: add forecast_scenarios, pipeline_run_log, red_team_observations."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS forecast_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_group_id TEXT NOT NULL,
            trigger_event_summary TEXT NOT NULL,
            prediction_label TEXT NOT NULL,
            predicted_probability REAL NOT NULL DEFAULT 0.5,
            trigger_conditions TEXT DEFAULT '{}',
            evidence_chain TEXT DEFAULT '',
            forecast_window_end TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            belief_alpha REAL NOT NULL DEFAULT 1.0,
            belief_beta REAL NOT NULL DEFAULT 1.0,
            matched_actual TEXT DEFAULT NULL,
            matched_at TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT 'main_ai'
        );
        CREATE INDEX IF NOT EXISTS idx_forecast_scenarios_group ON forecast_scenarios(scenario_group_id);
        CREATE INDEX IF NOT EXISTS idx_forecast_scenarios_status ON forecast_scenarios(status);

        CREATE TABLE IF NOT EXISTS pipeline_run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            stage TEXT NOT NULL,
            model_name TEXT NOT NULL,
            input_summary TEXT DEFAULT '',
            output_summary TEXT DEFAULT '',
            latency_ms INTEGER DEFAULT 0,
            error TEXT DEFAULT NULL,
            ai_labeled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_run_log_date ON pipeline_run_log(run_date);
        CREATE INDEX IF NOT EXISTS idx_pipeline_run_log_stage ON pipeline_run_log(stage, run_date);

        CREATE TABLE IF NOT EXISTS red_team_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT NOT NULL,
            observation_type TEXT NOT NULL,
            target_context TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'minor',
            evidence TEXT DEFAULT '',
            resolved_by_user INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_red_team_obs_date ON red_team_observations(session_date);
        CREATE INDEX IF NOT EXISTS idx_red_team_obs_type ON red_team_observations(observation_type);
        CREATE INDEX IF NOT EXISTS idx_red_team_obs_severity ON red_team_observations(severity);
    """)


def _migration_8_add_quarantine_column(conn: sqlite3.Connection) -> None:
    """P3: add post_collaboration_quarantine column to daily_snapshots (Resolution 4-C)."""
    try:
        conn.execute(
            "ALTER TABLE daily_snapshots ADD COLUMN post_collaboration_quarantine "
            "INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass


_MIGRATIONS: list[tuple[int, callable]] = [
    (1, _migration_1_add_discount_rate),
    (2, _migration_2_add_belief_tables),
    (3, _migration_3_add_market_prices),
    (4, _migration_4_add_cycle_checkpoints),
    (5, _migration_5_add_signal_quality),
    (6, _migration_6_add_access_audit_log),
    (7, _migration_7_add_phase_c_tables),
    (8, _migration_8_add_quarantine_column),
]
