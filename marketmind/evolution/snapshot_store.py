"""SnapshotStore — weekly evolution snapshots in evolution.db."""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


class SnapshotStore:
    def __init__(self, db_path: str = "data/evolution.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "  snapshot_id TEXT PRIMARY KEY,"
            "  scope TEXT,"
            "  entity_id TEXT,"
            "  week_start TEXT,"
            "  metrics_json TEXT,"
            "  created_at TEXT"
            ")"
        )
        self._conn.commit()

    def save_snapshot(self, scope: str, entity_id: str, week_start: str, metrics: dict) -> str:
        sid = f"{scope}|{entity_id}|{week_start}"
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?)",
            (sid, scope, entity_id, week_start, json.dumps(metrics),
             datetime.now(timezone.utc).isoformat())
        )
        self._conn.commit()
        return sid

    def get_history(self, scope: str, entity_id: str, limit: int = 12) -> list[dict]:
        rows = self._conn.execute(
            "SELECT week_start, metrics_json FROM snapshots "
            "WHERE scope=? AND entity_id=? ORDER BY week_start DESC LIMIT ?",
            (scope, entity_id, limit)
        ).fetchall()
        return [{"week_start": r[0], "metrics": json.loads(r[1])} for r in reversed(rows)]

    def get_baseline(self, scope: str, entity_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT metrics_json FROM snapshots "
            "WHERE scope=? AND entity_id=? ORDER BY week_start ASC LIMIT 1",
            (scope, entity_id)
        ).fetchone()
        return json.loads(row[0]) if row else None
