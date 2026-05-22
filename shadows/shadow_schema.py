"""SQLite schema DDL, migrations, and version tracking.

Extracted from shadow_state.py per modular architecture rules (§3.1).
Imported by ShadowStateDB.init_schema() at runtime.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from marketmind.shadows.shadow_migrations import (
    _migration_7_add_phase_c_tables,
    _migration_8_add_quarantine_column,
    _migration_9_add_beta_and_retired,
    _migration_10_rename_shadow_votes_to_shadow_analyses,
    _migration_11_upgrade_cycle_checkpoints,
    _migration_12_add_phase_c_independent_tools,
)

logger = logging.getLogger("marketmind.shadows.shadow_schema")

# ── SQLite database ──────────────────────────────────────────────────────────

CODE_VERSION = 12  # Increment on any schema change; add migration to _MIGRATIONS

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

CREATE TABLE IF NOT EXISTS cycle_checkpoints (
    date TEXT NOT NULL,
    shadow_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    step_completed INTEGER DEFAULT 0,
    analysis_json TEXT,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    PRIMARY KEY (date, shadow_id)
);
CREATE INDEX IF NOT EXISTS idx_cycle_checkpoints_date ON cycle_checkpoints(date);
CREATE INDEX IF NOT EXISTS idx_cycle_checkpoints_shadow_date ON cycle_checkpoints(shadow_id, date);

CREATE TABLE IF NOT EXISTS shadow_analyses (
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
CREATE INDEX IF NOT EXISTS idx_shadow_analyses_date ON shadow_analyses(date);
CREATE INDEX IF NOT EXISTS idx_shadow_analyses_shadow_date ON shadow_analyses(shadow_id, date);

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



# ── Migration registry (module-level, after class definition) ───────────────

def _migration_1_add_discount_rate(conn: sqlite3.Connection) -> None:
    """Phase D: add discount_rate column to daily_snapshots."""
    try:
        conn.execute(
            "ALTER TABLE daily_snapshots ADD COLUMN discount_rate REAL DEFAULT 0.20"
        )
    except sqlite3.OperationalError:
        pass


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
    """Phase B audit: add outcome_label + outcome_return_pct to shadow_analyses."""
    for col, col_type in [("outcome_label", "TEXT DEFAULT NULL"),
                           ("outcome_return_pct", "REAL DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE shadow_analyses ADD COLUMN {col} {col_type}")
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


_MIGRATIONS: list[tuple[int, callable]] = [
    (1, _migration_1_add_discount_rate),
    (2, _migration_2_add_belief_tables),
    (3, _migration_3_add_market_prices),
    (4, _migration_4_add_cycle_checkpoints),
    (5, _migration_5_add_signal_quality),
    (6, _migration_6_add_access_audit_log),
    (7, _migration_7_add_phase_c_tables),
    (8, _migration_8_add_quarantine_column),
    (9, _migration_9_add_beta_and_retired),
    (10, _migration_10_rename_shadow_votes_to_shadow_analyses),
    (11, _migration_11_upgrade_cycle_checkpoints),
    (12, _migration_12_add_phase_c_independent_tools),
]


# ── Schema initialization (extracted from ShadowStateDB) ──────────────


def init_shadow_db_schema(conn: sqlite3.Connection) -> None:
    """Initialize DB schema: create tables + apply pending migrations."""
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


def migrate_add_column(conn: sqlite3.Connection, table: str,
                        column: str, col_type: str) -> None:
    """Safe ALTER TABLE ADD COLUMN — ignores if column already exists."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        logger.info("Migration: added %s.%s %s", table, column, col_type)
    except sqlite3.OperationalError:
        pass
