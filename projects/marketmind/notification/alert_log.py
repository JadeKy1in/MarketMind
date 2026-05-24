"""AlertLog — SQLite persistence with Python logging fallback."""
from __future__ import annotations
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("marketmind.alert")


class AlertLog:
    def __init__(self, db_path: str = "data/alerts.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._available = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS alerts ("
                "  id TEXT PRIMARY KEY, severity TEXT, source TEXT,"
                "  impact_scope TEXT, title TEXT, detail TEXT,"
                "  action_advice TEXT, degraded_output INTEGER,"
                "  timestamp TEXT, resolved INTEGER, repeat_count INTEGER"
                ")"
            )
            self._conn.commit()
            self._available = True
        except Exception as e:
            logger.warning("AlertLog DB unavailable, falling back to logging: %s", e)
            self._available = False

    def insert(self, alert_dict: dict) -> None:
        if self._available and self._conn:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO alerts VALUES ("
                    ":id,:severity,:source,:impact_scope,:title,:detail,"
                    ":action_advice,:degraded_output,:timestamp,:resolved,:repeat_count"
                    ")", alert_dict
                )
                self._conn.commit()
            except Exception as e:
                logger.warning("AlertLog insert failed: %s", e)
        logger.info("ALERT [%s] %s: %s", alert_dict.get("severity"),
                     alert_dict.get("source"), alert_dict.get("title"))

    def recent(self, limit: int = 50) -> list[dict]:
        if not self._available or not self._conn:
            return []
        try:
            rows = self._conn.execute(
                "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[0] for d in self._conn.execute("PRAGMA table_info(alerts)")]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def health(self) -> dict:
        return {"available": self._available, "path": str(self.db_path)}
