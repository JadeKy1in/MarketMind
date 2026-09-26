"""Tests for DailyBriefingGenerator -- personalized shadow briefing generation."""
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from marketmind.shadows.daily_briefing import DailyBriefingGenerator


# ── Helpers ─────────────────────────────────────────────────────────────────

def _setup_mock_db():
    """Create a mock ShadowStateDB with in-memory SQLite.

    Returns:
        (mock_db, connection) tuple. mock_db is a MagicMock wrapping
        the real sqlite3.Connection for _connect().
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create schema tables needed for tests
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shadow_configs (
            shadow_id TEXT PRIMARY KEY,
            config_json TEXT
        );
        CREATE TABLE IF NOT EXISTS belief_nodes (
            node_id TEXT PRIMARY KEY,
            proposition TEXT,
            tier TEXT,
            status TEXT DEFAULT 'active',
            alpha REAL DEFAULT 1.0,
            beta REAL DEFAULT 1.0,
            updated_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS belief_observations (
            observation_id TEXT PRIMARY KEY,
            node_id TEXT,
            shadow_id TEXT,
            value REAL,
            confidence REAL,
            source_type TEXT,
            extracted_text TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pending_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            signal_description TEXT NOT NULL,
            trigger_condition TEXT,
            related_ticker TEXT,
            expected_date TEXT,
            status TEXT DEFAULT 'awaiting',
            created_date TEXT,
            resolved_date TEXT,
            resolution_notes TEXT
        );
    """)
    conn.commit()

    mock_db = MagicMock()
    mock_db._connect.return_value = conn

    # Simulate entering context manager for _connect()
    # The code uses try/finally with conn.close(), so we need conn to be reusable
    return mock_db, conn


def _insert_config(conn, shadow_id, persona):
    """Insert a shadow config record."""
    conn.execute(
        "INSERT OR REPLACE INTO shadow_configs (shadow_id, config_json) VALUES (?, ?)",
        (shadow_id, json.dumps({"persona": persona})),
    )
    conn.commit()


def _insert_observation(conn, obs_id, node_id, shadow_id, value, confidence,
                        text, created_at, tier="episodic"):
    """Insert a belief observation and its node."""
    conn.execute(
        "INSERT OR REPLACE INTO belief_nodes "
        "(node_id, proposition, tier, status, alpha, beta, updated_at, created_at) "
        "VALUES (?, ?, ?, 'active', 2.0, 1.0, ?, ?)",
        (node_id, f"test:{shadow_id}:obs", tier, created_at, created_at),
    )
    conn.execute(
        "INSERT OR REPLACE INTO belief_observations "
        "(observation_id, node_id, shadow_id, value, confidence, "
        " source_type, extracted_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'text', ?, ?)",
        (obs_id, node_id, shadow_id, value, confidence, text, created_at),
    )
    conn.commit()


def _insert_signal(conn, shadow_id, sig_type, desc, ticker, expected_date, status="awaiting"):
    """Insert a pending signal."""
    conn.execute(
        "INSERT INTO pending_signals "
        "(shadow_id, signal_type, signal_description, trigger_condition, "
        " related_ticker, expected_date, status, created_date) "
        "VALUES (?, ?, ?, '', ?, ?, ?, '2026-05-20')",
        (shadow_id, sig_type, desc, ticker, expected_date, status),
    )
    conn.commit()


@pytest.fixture
def briefing_gen():
    """Fixture: DailyBriefingGenerator with mock DB and populated data."""
    mock_db, conn = _setup_mock_db()
    gen = DailyBriefingGenerator(mock_db)

    # Insert test data
    _insert_config(conn, "expert:gold:bullion_broker",
                   "You are the Bullion Broker. Conservative precious metals analyst. "
                   "Trusts gold more than fiat. Uses FRED real rates, CFTC COT, and "
                   "central bank gold purchase data for analysis.")

    _insert_observation(conn, "obs-001", "node-001",
                        "expert:gold:bullion_broker", 0.8, 0.85,
                        "Gold rallied 2.3% on dovish Fed minutes. COT shows spec longs "
                        "adding. Central bank purchases from China continued for 4th month.",
                        "2026-05-18T10:00:00Z")
    _insert_observation(conn, "obs-002", "node-002",
                        "expert:gold:bullion_broker", 0.6, 0.70,
                        "Silver underperformed gold this week. Gold/Silver ratio at 85, "
                        "suggesting potential silver catch-up.",
                        "2026-05-15T10:00:00Z")
    _insert_observation(conn, "obs-003", "node-003",
                        "expert:gold:bullion_broker", 0.4, 0.55,
                        "Old observation from weeks ago. Mining costs rising in South "
                        "Africa due to energy crisis.",
                        "2026-04-20T10:00:00Z")

    _insert_signal(conn, "expert:gold:bullion_broker",
                   "earnings", "Gold miners Q1 earnings", "GDX",
                   "2026-05-25", "awaiting")
    _insert_signal(conn, "expert:gold:bullion_broker",
                   "macro", "FOMC minutes release", "GLD",
                   "2026-05-22", "awaiting")
    _insert_signal(conn, "expert:gold:bullion_broker",
                   "data", "CFTC COT weekly update", "GC=F",
                   "2026-05-23", "awaiting")

    return gen


@pytest.fixture
def market_context():
    """Sample market context dict."""
    return {
        "indices": {"SPX": 6120.5, "DJI": 44100.0, "IXIC": 21500.0},
        "volatility": {"VIX": 18.2, "VVIX": 92.0},
        "rates": {"US10Y": 4.45, "US2Y": 4.28, "Real10Y": 1.95},
        "commodities": {"Gold": 2650.0, "Silver": 31.20, "Copper": 4.85},
        "fx": {"DXY": 104.5, "EURUSD": 1.085, "USDJPY": 154.2},
    }


# ── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_returns_structured_briefing(briefing_gen, market_context):
    """Generate should return a string with all 5 section markers."""
    briefing = await briefing_gen.generate(
        "expert:gold:bullion_broker", market_context
    )

    assert isinstance(briefing, str)
    assert len(briefing) > 0

    # All 5 sections should be present
    assert "[1] PERSONA & STRATEGY" in briefing
    assert "[2] CUMULATIVE EXPERIENCE" in briefing
    assert "[3] PENDING SIGNALS" in briefing
    assert "[4] TODAY'S MARKET" in briefing
    assert "[5] INSTRUCTION" in briefing

    # Sections should be separated
    assert briefing.count("---") >= 4  # 4 section separators


@pytest.mark.asyncio
async def test_generate_handles_cold_start_shadow(briefing_gen, market_context):
    """Generate should not crash for a shadow with no config or memory."""
    briefing = await briefing_gen.generate(
        "expert:tech:silicon_oracle", market_context
    )

    assert isinstance(briefing, str)
    assert len(briefing) > 0
    assert "[1] PERSONA & STRATEGY" in briefing
    assert "[2] CUMULATIVE EXPERIENCE" in briefing
    # Should have fallback message for no experience
    assert "first session" in briefing.lower() or "no prior" in briefing.lower()


def test_load_persona_retrieves_config(briefing_gen):
    """_load_persona should return persona text from shadow_configs."""
    persona = briefing_gen._load_persona("expert:gold:bullion_broker")
    assert "Bullion Broker" in persona
    assert len(persona) > 0


def test_load_persona_fallback_for_unknown_shadow(briefing_gen):
    """_load_persona should derive persona from shadow_id when config missing."""
    persona = briefing_gen._load_persona("expert:crypto:chain_oracle")
    assert "expert:crypto:chain_oracle" in persona or "Strategy:" in persona
    assert len(persona) > 0


def test_load_experience_with_observations(briefing_gen):
    """_load_experience should return decay-weighted observation list."""
    exp = briefing_gen._load_experience("expert:gold:bullion_broker")
    assert len(exp) > 0
    # Should contain one of our observations
    assert "Gold rallied" in exp or "Silver underperformed" in exp or "Mining costs" in exp
    # Should have decay weight labels
    assert "decay_weight" in exp or "No prior" in exp


def test_load_experience_empty_for_unknown_shadow(briefing_gen):
    """_load_experience should return fallback message for unknown shadow."""
    exp = briefing_gen._load_experience("expert:bonds:yield_whisperer")
    assert "No prior" in exp or "first session" in exp.lower() or "available" in exp.lower()


def test_load_pending_signals_includes_awaiting(briefing_gen):
    """_load_pending_signals should include signals with status='awaiting'."""
    signals = briefing_gen._load_pending_signals("expert:gold:bullion_broker")
    assert "Gold miners" in signals or "FOMC" in signals or "CFTC" in signals
    # Should show count
    assert "3/" in signals or "2/" in signals or "1/" in signals


def test_load_pending_signals_empty_for_unknown_shadow(briefing_gen):
    """_load_pending_signals should return empty message when no signals exist."""
    signals = briefing_gen._load_pending_signals("momentum:intraday:scalper")
    assert "No pending signals" in signals


def test_derive_persona_from_id():
    """_derive_persona_from_id should parse standard shadow_id format."""
    gen = DailyBriefingGenerator(MagicMock())
    result = gen._derive_persona_from_id("expert:gold:bullion_broker")
    assert "expert:gold:bullion_broker" in result
    assert "Domain expert" in result
    assert "Gold" in result

    # Short format
    result2 = gen._derive_persona_from_id("momentum:weekly:trend_rider")
    assert "momentum:weekly:trend_rider" in result2
    assert "Momentum trader" in result2


def test_truncate_text():
    """_truncate_text should truncate long text with ellipsis."""
    gen = DailyBriefingGenerator(MagicMock())
    text = "A" * 100

    # Truncation at max_chars=50: result is text[:47] + "..." = 50 chars total
    assert gen._truncate_text(text, max_chars=50) == "A" * 47 + "..."
    # Text shorter than max
    assert gen._truncate_text("hello", max_chars=10) == "hello"
    # Exact match
    assert gen._truncate_text("hi", max_chars=2) == "hi"
    # At boundary: text exactly at max_chars, no truncation needed
    assert gen._truncate_text("abc", max_chars=3) == "abc"
