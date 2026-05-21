"""Data archivist: JSON filesystem archive + SQLite FTS5 full-text index."""
from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timezone
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
        now = datetime.now(timezone.utc)
        return self.base_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"

    def ensure_dirs(self) -> Path:
        for sub in ("raw", "analysis", "decisions", "review", "gates"):
            (self.today_path() / sub).mkdir(parents=True, exist_ok=True)
        return self.today_path()

    def save_json(self, subdir: str, filename: str, data: Any) -> Path:
        dir_path = self.today_path() / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
        filepath = dir_path / f"{filename}.json"
        # Atomic write: temp file → rename, prevents corruption on crash
        tmp = filepath.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(filepath)
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

    # ── Shadow ecosystem FTS5 tables ────────────────────────────────────

    def init_shadow_tables(self) -> None:
        db = self._get_db()
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS shadow_analyses_fts USING fts5(
                shadow_id, date, ticker, direction, thesis, risk_note,
                tokenize='porter unicode61'
            )
        """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS shadow_rankings_fts USING fts5(
                shadow_id, date, tier, rank_info,
                tokenize='porter unicode61'
            )
        """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS shadow_trades_fts USING fts5(
                shadow_id, ticker, direction, exit_reason,
                tokenize='porter unicode61'
            )
        """)
        db.commit()

    def index_shadow_snapshot(self, shadow_id: str, date: str,
                               votes: list[dict]) -> None:
        db = self._get_db()
        for v in votes:
            db.execute(
                """INSERT INTO shadow_analyses_fts
                   (shadow_id, date, ticker, direction, thesis, risk_note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shadow_id, date,
                 v.get("ticker", ""), v.get("direction", ""),
                 v.get("thesis", ""), v.get("risk_note", ""))
            )
        db.commit()

    def index_shadow_ranking(self, shadow_id: str, date: str,
                              tier: str, rank: int) -> None:
        db = self._get_db()
        db.execute(
            """INSERT INTO shadow_rankings_fts (shadow_id, date, tier, rank_info)
               VALUES (?, ?, ?, ?)""",
            (shadow_id, date, tier, f"rank={rank}")
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

    # ── SHARP rule audit (P3-2a) ──────────────────────────────────────────

    def save_rule_audit(self, rule_id: str, audit_data: dict) -> None:
        """Save attribution hypothesis and backtest result for a rule.

        Each audit entry is appended to a daily JSONL file under
        <base_dir>/rule_audit/. This provides an append-only audit trail
        for walk-forward backtest validation.

        Args:
            rule_id: The rule being audited (e.g. "RRSK-A1B2C3D4").
            audit_data: Dict with event type, hypothesis, outcome, etc.
                        Must include an 'event' key describing what happened.
        """
        entry = {
            "rule_id": rule_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **audit_data,
        }
        audit_dir = self.base_dir / "rule_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_file = audit_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_rule_audit_history(
        self, rule_id: str, days: int = 90
    ) -> list[dict]:
        """Get audit history for a rule for WFA backtest.

        Scans daily JSONL files in <base_dir>/rule_audit/ and returns
        all entries matching the given rule_id within the time window.

        Args:
            rule_id: The rule to retrieve history for.
            days: Number of days to look back (default 90).

        Returns:
            List of audit entry dicts, newest first.
        """
        from datetime import timedelta

        audit_dir = self.base_dir / "rule_audit"
        if not audit_dir.exists():
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries: list[dict] = []

        for f in sorted(audit_dir.glob("*.jsonl"), reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            ts = datetime.fromisoformat(entry.get("timestamp", ""))
                            if ts < cutoff:
                                continue
                            if entry.get("rule_id") != rule_id:
                                continue
                            entries.append(entry)
                        except (json.JSONDecodeError, KeyError, ValueError):
                            continue
            except OSError:
                continue

        return entries


def get_archivist(base_dir: str | Path = "data/archive") -> MarketMindArchive:
    return MarketMindArchive(base_dir)
