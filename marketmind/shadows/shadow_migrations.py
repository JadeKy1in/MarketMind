"""Recent schema migrations extracted from shadow_schema.py per S3.1 modular architecture rules.

Migrations 7-12: Phase C tables, quarantine column, beta/retired lifecycle,
shadow_votes rename, cycle_checkpoints upgrade, Phase C independent tools.

Imported by shadow_schema.py into _MIGRATIONS registry.
"""
from __future__ import annotations

import sqlite3


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


def _migration_9_add_beta_and_retired(conn: sqlite3.Connection) -> None:
    """Shadow Phase 2: add retired_at/retirement_reason columns + beta_analyses table."""
    for col, col_type in [("retired_at", "TEXT DEFAULT NULL"),
                           ("retirement_reason", "TEXT DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE shadows ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS beta_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_id TEXT NOT NULL,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('long','short','abstain')),
            confidence REAL NOT NULL,
            thesis TEXT,
            risk_note TEXT,
            methodology_variant TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (shadow_id) REFERENCES shadows(id)
        );
        CREATE INDEX IF NOT EXISTS idx_beta_analyses_date ON beta_analyses(date);
        CREATE INDEX IF NOT EXISTS idx_beta_analyses_shadow_date ON beta_analyses(shadow_id, date);
    """)


def _migration_10_rename_shadow_votes_to_shadow_analyses(conn: sqlite3.Connection) -> None:
    """2026-05-18: rename shadow_votes table -> shadow_analyses (no voting, internal only)."""
    try:
        conn.execute("ALTER TABLE shadow_votes RENAME TO shadow_analyses")
    except sqlite3.OperationalError:
        pass  # Table already renamed or fresh DB (shadow_analyses created directly)


def _migration_11_upgrade_cycle_checkpoints(conn: sqlite3.Connection) -> None:
    """P3-4: upgrade cycle_checkpoints from cycle-level to per-shadow schema.

    The old v4 migration created a cycle-level table (date PRIMARY KEY, one row
    per day). P3-4 needs per-shadow granularity with composite PK (date, shadow_id)
    for partial-state recovery after crashes mid-cycle.
    """
    # Drop old cycle-level table (data is non-critical checkpoint state)
    conn.execute("DROP TABLE IF EXISTS cycle_checkpoints")
    # Create new per-shadow table with analysis cache
    conn.executescript("""
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
    """)


def _migration_12_add_phase_c_independent_tools(conn: sqlite3.Connection) -> None:
    """Phase C independent tools: add pending_signals + event_tracks tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pending_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            trigger_condition TEXT DEFAULT '',
            ticker TEXT NOT NULL,
            expected_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'awaiting',
            created_at TEXT NOT NULL,
            triggered_at TEXT,
            FOREIGN KEY (shadow_id) REFERENCES shadows(id)
        );
        CREATE INDEX IF NOT EXISTS idx_pending_signals_shadow ON pending_signals(shadow_id);
        CREATE INDEX IF NOT EXISTS idx_pending_signals_status ON pending_signals(status);

        CREATE TABLE IF NOT EXISTS event_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            category TEXT NOT NULL,
            key_metric TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT DEFAULT '',
            outcome TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            closed_at TEXT,
            FOREIGN KEY (shadow_id) REFERENCES shadows(id)
        );
        CREATE INDEX IF NOT EXISTS idx_event_tracks_shadow ON event_tracks(shadow_id);
        CREATE INDEX IF NOT EXISTS idx_event_tracks_status ON event_tracks(status);
    """)
