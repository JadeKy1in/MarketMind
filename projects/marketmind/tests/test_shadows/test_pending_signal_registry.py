"""Tests for PendingSignalRegistry — manage awaiting signals."""
import pytest
import tempfile
from pathlib import Path

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.pending_signal_registry import (
    PendingSignalRegistry,
    STATUS_AWAITING,
    STATUS_TRIGGERED,
    STATUS_EXPIRED,
)


@pytest.fixture
def registry(populated_db):
    """Create a PendingSignalRegistry backed by populated DB (shadows exist)."""
    return PendingSignalRegistry(populated_db.db_path)


@pytest.fixture
def populated_registry(registry, populated_db):
    """Registry with pre-registered signals for testing."""
    # Ensure system:owner shadow exists for orphan transfer
    try:
        populated_db.create_shadow(ShadowConfig(
            shadow_id="system:owner",
            shadow_type="expert",
            display_name="System Owner",
            methodology_prompt="System owner for orphaned signals.",
            virtual_capital=1.0,
            domain="system",
        ))
    except ValueError:
        pass  # Already exists

    # Use shadow IDs that exist in populated_db:
    # expert:gold:agent_00 and expert:crypto:agent_01 exist
    registry.register_signal(
        shadow_id="expert:gold:agent_00",
        signal_type="earnings",
        description="AAPL Q2 earnings beat",
        trigger_condition="AAPL earnings release",
        ticker="AAPL",
        expected_date="2026-05-25",
    )
    registry.register_signal(
        shadow_id="expert:crypto:agent_01",
        signal_type="fomc",
        description="FOMC rate decision impact on BTC",
        trigger_condition="FOMC meeting",
        ticker="BTC-USD",
        expected_date="2026-06-15",
    )
    registry.register_signal(
        shadow_id="expert:gold:agent_00",
        signal_type="macro",
        description="CPI print for gold reaction",
        trigger_condition="CPI release",
        ticker="GLD",
        expected_date="2026-05-10",  # Already past
    )
    return registry


# ── Test 1: Register and retrieve pending signals ────────────────────────

def test_register_and_get_pending(populated_registry, temp_shadow_db):
    """Register signals and verify they appear in get_pending_for_shadow."""
    sigs = populated_registry.get_pending_for_shadow(
        "expert:gold:agent_00", max_count=20
    )
    assert len(sigs) == 2  # AAPL + GLD

    # Priority-sorted: closest expected_date first
    assert sigs[0]["ticker"] == "GLD"     # 2026-05-10
    assert sigs[1]["ticker"] == "AAPL"    # 2026-05-25

    # Verify signal structure
    sig = sigs[0]
    assert sig["shadow_id"] == "expert:gold:agent_00"
    assert sig["signal_type"] == "macro"
    assert sig["status"] == STATUS_AWAITING


# ── Test 2: Check triggers returns signals whose date has arrived ────────

def test_check_triggers(populated_registry):
    """Signals with expected_date <= check_date should be returned."""
    # At date 2026-05-15, the GLD signal (May 10) should trigger
    triggered = populated_registry.check_triggers("2026-05-15")

    triggered_tickers = [s["ticker"] for s in triggered]
    assert "GLD" in triggered_tickers
    assert "AAPL" not in triggered_tickers  # May 25, not yet
    assert "BTC-USD" not in triggered_tickers  # June 15

    # At date 2026-05-25, both GLD and AAPL should trigger
    triggered2 = populated_registry.check_triggers("2026-05-25")
    triggered_tickers2 = [s["ticker"] for s in triggered2]
    assert "GLD" in triggered_tickers2
    assert "AAPL" in triggered_tickers2
    assert len(triggered2) == 2


# ── Test 3: Expire old signals ──────────────────────────────────────────

def test_expire_signals(populated_registry):
    """Signals past expected_date + 7 days should be expired."""
    # At date 2026-06-01: GLD was May 10 (+22 days) → should expire
    # AAPL was May 25 (+7 days, at boundary) → depends on strict/lenient
    expired_count = populated_registry.expire_signals("2026-06-01")

    assert expired_count >= 1  # At least GLD expired

    # GLD should now be expired
    remaining = populated_registry.get_pending_for_shadow(
        "expert:gold:agent_00", max_count=20
    )
    remaining_tickers = [s["ticker"] for s in remaining]
    assert "GLD" not in remaining_tickers  # Expired

    # Count awaiting
    awaiting_count = populated_registry.count_awaiting("expert:gold:agent_00")
    assert awaiting_count == len(remaining)


# ── Test 4: Transfer orphaned signals on shadow elimination ──────────────

def test_transfer_orphaned_signals(populated_registry):
    """When a shadow is eliminated, its signals transfer to system:owner."""
    # Verify original owner
    sigs_before = populated_registry.get_pending_for_shadow(
        "expert:gold:agent_00", max_count=20
    )
    assert len(sigs_before) >= 1

    # Transfer
    count = populated_registry.transfer_orphaned_signals("expert:gold:agent_00")
    assert count >= 1

    # Original shadow should have no signals now
    sigs_after = populated_registry.get_pending_for_shadow(
        "expert:gold:agent_00", max_count=20
    )
    assert len(sigs_after) == 0

    # System owner should have them
    system_sigs = populated_registry.get_pending_for_shadow(
        "system:owner", max_count=20
    )
    assert len(system_sigs) >= 1


# ── Test 5: Validation ──────────────────────────────────────────────────

def test_validation_errors(registry):
    """Empty shadow_id, empty ticker, and invalid date should raise ValueError."""
    with pytest.raises(ValueError, match="shadow_id must not be empty"):
        registry.register_signal(
            shadow_id="", signal_type="test", description="d",
            trigger_condition="t", ticker="AAPL", expected_date="2026-06-01",
        )

    with pytest.raises(ValueError, match="ticker must not be empty"):
        registry.register_signal(
            shadow_id="s1", signal_type="test", description="d",
            trigger_condition="t", ticker="", expected_date="2026-06-01",
        )

    with pytest.raises(ValueError, match="expected_date must be YYYY-MM-DD"):
        registry.register_signal(
            shadow_id="s1", signal_type="test", description="d",
            trigger_condition="t", ticker="AAPL", expected_date="not-a-date",
        )

    with pytest.raises(ValueError, match="date must be YYYY-MM-DD"):
        registry.expire_signals("not-a-date")
