"""Data archivist: JSON filesystem archive + SQLite FTS5 full-text index."""
from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("marketmind.storage.archivist")


class MarketMindArchive:
    def __init__(self, base_dir: str | Path = "data/archive"):
        self.base_dir = Path(base_dir)
        self.db_path = Path(base_dir) / "archive.db"
        self._db: sqlite3.Connection | None = None

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.db_path))
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
        return self._db

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def today_path(self) -> Path:
        now = datetime.now()
        return self.base_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"

    def ensure_dirs(self) -> Path:
        for sub in ("raw", "analysis", "decisions", "review"):
            (self.today_path() / sub).mkdir(parents=True, exist_ok=True)
        return self.today_path()

    def save_json(self, subdir: str, filename: str, data: Any) -> Path:
        dir_path = self.today_path() / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
        filepath = dir_path / f"{filename}.json"
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return filepath

    def load_json(self, subdir: str, filename: str) -> Any:
        filepath = self.today_path() / subdir / f"{filename}.json"
        if not filepath.exists():
            return None
        return json.loads(filepath.read_text(encoding="utf-8"))

    def init_fts(self) -> None:
        db = self._get_db()
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(
                date, category, title, content,
                tokenize='porter unicode61'
            )
        """)
        db.commit()

    def index_document(self, date: str, category: str, title: str, content: str) -> None:
        db = self._get_db()
        db.execute(
            "INSERT INTO archive_fts (date, category, title, content) VALUES (?, ?, ?, ?)",
            (date, category, title, content)
        )
        db.commit()

    def search(self, query: str, limit: int = 20) -> list[dict]:
        db = self._get_db()
        results = db.execute(
            "SELECT date, category, title, snippet(archive_fts, 2, '<b>', '</b>', '...', 40) "
            "FROM archive_fts WHERE archive_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        return [{"date": r[0], "category": r[1], "title": r[2], "snippet": r[3]} for r in results]


def get_archivist(base_dir: str | Path = "data/archive") -> MarketMindArchive:
    return MarketMindArchive(base_dir)
