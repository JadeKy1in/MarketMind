"""Tests for JSON archive + SQLite FTS5."""
import tempfile
from pathlib import Path
from projects.marketmind.storage.archivist import MarketMindArchive, get_archivist


def test_today_path():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        path = archive.today_path()
        assert td in str(path)
        assert path.is_absolute()
        archive.close()


def test_ensure_dirs_creates_subdirs():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archive.ensure_dirs()
        today = archive.today_path()
        assert (today / "raw").exists()
        assert (today / "analysis").exists()
        assert (today / "decisions").exists()
        assert (today / "review").exists()
        archive.close()


def test_save_and_load_json():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archive.ensure_dirs()
        data = {"key": "value", "number": 42}
        filepath = archive.save_json("analysis", "test_analysis", data)
        assert filepath.exists()
        loaded = archive.load_json("analysis", "test_analysis")
        assert loaded == data
        archive.close()


def test_load_json_missing():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        assert archive.load_json("raw", "nonexistent") is None
        archive.close()


def test_init_fts():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archive.init_fts()
        db_path = Path(td) / "archive.db"
        assert db_path.exists()
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='archive_fts'").fetchall()
        conn.close()
        assert len(tables) == 1
        archive.close()


def test_index_and_search():
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archive.init_fts()
        archive.index_document("2026-05-11", "analysis", "Fed Rate Decision",
                               "The Federal Reserve decided to raise interest rates by 25 basis points.")
        archive.index_document("2026-05-11", "analysis", "Apple Earnings",
                               "Apple Inc. reported quarterly earnings above expectations.")
        results = archive.search("Federal Reserve rates")
        assert len(results) >= 1
        results2 = archive.search("Apple earnings")
        assert len(results2) >= 1
        results3 = archive.search("nonexistent_query_xyz")
        assert len(results3) == 0
        archive.close()


def test_get_archivist():
    a = get_archivist()
    assert isinstance(a, MarketMindArchive)
    a.close()
