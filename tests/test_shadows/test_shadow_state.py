"""Tests for ShadowStateDB -- SQLite-backed shadow persistence."""
import pytest
import sqlite3
import tempfile
from pathlib import Path

from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, DailySnapshot,
    IntegrityEvent, EmergencyQuotaRequest, CollusionFlag
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_shadows.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


def test_init_schema_creates_all_tables(temp_db):
    """Verify all 7 tables exist after init_schema()."""
    conn = sqlite3.connect(temp_db.db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    expected = {"shadows", "virtual_trades", "daily_snapshots", "ranking_history",
                "integrity_events", "emergency_quotas", "collusion_flags"}
    assert expected.issubset(table_names)
    conn.close()


def test_create_and_get_shadow(temp_db):
    config = ShadowConfig(
        shadow_id="expert:gold:test_01",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold expert.",
        virtual_capital=50000.0,
        domain="gold"
    )
    shadow_id = temp_db.create_shadow(config)
    assert shadow_id == "expert:gold:test_01"
    retrieved = temp_db.get_shadow(shadow_id)
    assert retrieved is not None
    assert retrieved.display_name == "Test Gold Bug"
    assert retrieved.virtual_capital == 50000.0


def test_create_shadow_duplicate_id_fails(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    with pytest.raises(ValueError, match="already exists"):
        temp_db.create_shadow(config)


def test_get_active_shadows_filters_by_type(temp_db):
    for i in range(3):
        config = ShadowConfig(shadow_id=f"expert:{i}", shadow_type="expert",
                              display_name=f"E{i}", methodology_prompt="...",
                              virtual_capital=10000)
        temp_db.create_shadow(config)
    for i in range(2):
        config = ShadowConfig(shadow_id=f"daredevil:{i}", shadow_type="daredevil",
                              display_name=f"D{i}", methodology_prompt="...",
                              virtual_capital=10000)
        temp_db.create_shadow(config)
    experts = temp_db.get_active_shadows("expert")
    assert len(experts) == 3
    daredevils = temp_db.get_active_shadows("daredevil")
    assert len(daredevils) == 2
    all_active = temp_db.get_active_shadows()
    assert len(all_active) == 5


def test_get_visible_shadows_excludes_challengers(temp_db):
    for idx, shadow_type in enumerate(["expert", "expert", "challenger"]):
        config = ShadowConfig(
            shadow_id=f"{shadow_type}:test_{shadow_type}_{idx}",
            shadow_type=shadow_type,
            display_name=f"{shadow_type} shadow {idx}",
            methodology_prompt="...",
            virtual_capital=10000,
            parent_shadow_id="expert:test_expert_0" if shadow_type == "challenger" else None
        )
        temp_db.create_shadow(config)
    visible = temp_db.get_visible_shadows()
    assert len(visible) == 2
    assert all(s.shadow_type != "challenger" for s in visible)


def test_record_and_get_trades(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    trade = VirtualTradeOpen(
        shadow_id="test", ticker="AAPL", direction="long",
        entry_price=150.0, position_size_pct=0.10,
        entry_date="2026-05-11"
    )
    trade_id = temp_db.record_trade_open("test", trade)
    assert trade_id > 0
    temp_db.record_trade_close(trade_id, 160.0, "target", 0.0667)
    history = temp_db.get_trade_history("test", limit=90)
    assert len(history) == 1
    assert history[0].ticker == "AAPL"
    assert history[0].pnl_pct == pytest.approx(0.0667, rel=0.01)


def test_save_and_get_snapshot(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    snap = DailySnapshot(
        shadow_id="test", date="2026-05-11", virtual_capital=10100.0,
        daily_return_pct=0.01, cumulative_return_pct=0.01,
        max_drawdown_pct=0.0, win_rate_pct=100.0,
        sharpe_ratio=1.5, calmar_ratio=2.0, omega_ratio=3.0,
        mppm_score=0.85, composite_score=0.82, deflated_score=0.73,
        percentile_rank=0.85, achievement_tier="elite",
        flash_quota_used=5, pro_quota_used=0, emergency_quotas_used=0,
        insights_generated=1
    )
    temp_db.save_snapshot("test", snap)
    history = temp_db.get_snapshot_history("test", days=90)
    assert len(history) == 1
    assert history[0].achievement_tier == "elite"


def test_save_rankings(temp_db):
    # Create shadows first so FK constraints are satisfied
    for sid in ["shadow_a", "shadow_b"]:
        config = ShadowConfig(shadow_id=sid, shadow_type="expert",
                              display_name=sid, methodology_prompt="...",
                              virtual_capital=10000)
        temp_db.create_shadow(config)
    rankings = [
        ("shadow_a", 0.85, 0.76, {"mppm": 0.9, "calmar": 0.7, "omega": 0.8, "wr": 0.9}),
        ("shadow_b", 0.70, 0.62, {"mppm": 0.7, "calmar": 0.6, "omega": 0.7, "wr": 0.8}),
    ]
    temp_db.save_rankings("2026-05-11", rankings)
    history = temp_db.get_ranking_history("shadow_a", days=90)
    assert len(history) == 1
    assert history[0]["rank"] == 1


def test_eliminate_shadow_marks_eliminated_at(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    temp_db.eliminate_shadow("test", "Failed challenger comparison")
    shadow = temp_db.get_shadow("test")
    assert shadow.status == "eliminated"
    assert shadow.eliminated_at is not None


def test_integrity_events_crud(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    event = IntegrityEvent(
        shadow_id="test", date="2026-05-11",
        event_type="verified_true", claim_detail='{"claim": "test"}',
        score_change=1, new_score=101
    )
    temp_db.record_integrity_event("test", event)
    score = temp_db.get_integrity_score("test")
    assert score == 101
    history = temp_db.get_integrity_history("test", days=90)
    assert len(history) == 1
    assert history[0].event_type == "verified_true"


def test_emergency_quota_crud(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    quota = EmergencyQuotaRequest(
        shadow_id="test", requested_at="2026-05-11T10:00:00",
        confidence_self_report=9, opportunity_description="Gold breakout"
    )
    quota_id = temp_db.record_emergency_quota("test", quota)
    assert quota_id > 0
    temp_db.update_emergency_result(quota_id, "profitable", 0.05, "none")
    pending = temp_db.get_pending_emergency_audits()
    assert len(pending) == 0


def test_collusion_flags_crud(temp_db):
    flag = CollusionFlag(
        date="2026-05-11", agreement_pct=85.0, consecutive_days=3,
        market_signal_strength=0.45, verdict="herding"
    )
    temp_db.record_collusion_flag(flag)
    recent = temp_db.get_recent_collusion_flags(days=30)
    assert len(recent) == 1
    assert recent[0].verdict == "herding"
    assert recent[0].agreement_pct == 85.0


def test_wal_mode_enabled(temp_db):
    """Verify WAL mode is set for concurrent access."""
    conn = sqlite3.connect(temp_db.db_path)
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.upper() == "WAL"
    conn.close()
