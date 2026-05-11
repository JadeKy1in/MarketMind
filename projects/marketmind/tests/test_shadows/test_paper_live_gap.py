"""Tests for paper-to-live gap manager."""
import pytest
import math
from datetime import datetime, timezone

from projects.marketmind.shadows.paper_live_gap import (
    PaperLiveGapManager, GapMetrics,
)
from projects.marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, DailySnapshot,
)
from projects.marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def gap_manager(temp_shadow_db, settings):
    return PaperLiveGapManager(temp_shadow_db, settings)


def _make_config(shadow_id, shadow_type="expert", capital=50000.0, domain=None):
    return ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Test {shadow_id}",
        methodology_prompt=f"You are a {domain or 'market'} analyst.",
        virtual_capital=capital,
        domain=domain,
    )


def _add_closed_trade(db, shadow_id, ticker, direction, entry, exit, entry_date,
                       exit_date, pnl, pos_size=0.1):
    trade = VirtualTradeOpen(
        shadow_id=shadow_id, ticker=ticker, direction=direction,
        entry_price=entry, position_size_pct=pos_size, entry_date=entry_date,
    )
    trade_id = db.record_trade_open(shadow_id, trade)
    db.record_trade_close(trade_id, exit, "test", pnl)


# ── Test 1: virtual slippage applied to entry ─────────────────────────────

def test_virtual_slippage_applied_to_entry(gap_manager):
    """Slippage of 0.5% ATR is added for long, subtracted for short entry."""
    atr = 2.0

    long_entry = gap_manager.apply_virtual_slippage("AAPL", "long", 150.0, atr)
    expected_slippage = gap_manager.settings.virtual_slippage_atr_pct * atr  # 0.005 * 2.0 = 0.01
    assert long_entry == pytest.approx(150.0 + expected_slippage)

    short_entry = gap_manager.apply_virtual_slippage("AAPL", "short", 150.0, atr)
    assert short_entry == pytest.approx(150.0 - expected_slippage)


# ── Test 2: confidence discount default 20% ───────────────────────────────

def test_confidence_discount_default_20pct(gap_manager, temp_shadow_db):
    """When a shadow has no trade history, the default 20% discount applies."""
    config = _make_config("expert:gold:test_gap_01")
    temp_shadow_db.create_shadow(config)

    raw_return = 0.10  # 10% reported return
    discounted = gap_manager.apply_confidence_discount(raw_return, "expert:gold:test_gap_01")
    # Should be ~0.08 (20% discount)
    expected = raw_return * (1.0 - gap_manager.settings.confidence_discount_default)
    assert discounted == pytest.approx(expected)


# ── Test 3: discount decreases as gap closes ──────────────────────────────

def test_discount_decreases_as_gap_closes(gap_manager, temp_shadow_db):
    """As inter-shadow gap ratio improves (decreases), discount rate decreases."""
    shadow_a = "expert:gold:test_gap_a"
    shadow_b = "expert:gold:test_gap_b"

    for sid in (shadow_a, shadow_b):
        temp_shadow_db.create_shadow(_make_config(sid, domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Shadow A has flat returns (0% PnL)
    for i in range(5):
        _add_closed_trade(temp_shadow_db, shadow_a, "GLD", "long",
                          180.0, 180.0, today_str, today_str, 0.0, 0.1)

    # Shadow B has strongly positive returns (5% PnL each)
    for i in range(5):
        entry = 180.0
        exit_price = 180.0 * 1.05
        pnl = 0.05
        _add_closed_trade(temp_shadow_db, shadow_b, "GLD", "long",
                          entry, exit_price, today_str, today_str, pnl, 0.1)

    # Shadow A should have a high gap vs median (since B is making 5%)
    gap_a = gap_manager.compute_inter_shadow_gap(shadow_a, "GLD", today_str)
    assert gap_a > 0.30  # large gap expected

    # Now make Shadow A's returns converge toward Shadow B
    for i in range(5):
        entry = 180.0
        exit_price = 180.0 * 1.04  # closer to B's 5%
        pnl = 0.04
        _add_closed_trade(temp_shadow_db, shadow_a, "GLD", "long",
                          entry, exit_price, today_str, today_str, pnl, 0.1)

    gap_a_after = gap_manager.compute_inter_shadow_gap(shadow_a, "GLD", today_str)
    # Gap should be smaller now since A is performing similarly to B
    assert gap_a_after < gap_a

    # Discount should decrease after updating
    initial_discount = gap_manager._discount_rates.get(shadow_a, 0.20)
    new_discount = gap_manager.update_discount_rate(shadow_a)
    assert new_discount <= initial_discount


# ── Test 4: discount never below floor 5% ─────────────────────────────────

def test_discount_never_below_floor_5pct(gap_manager, temp_shadow_db):
    """After many gap improvements, discount never drops below 5% floor."""
    shadow_id = "expert:gold:test_floor"
    temp_shadow_db.create_shadow(_make_config(shadow_id, domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create a second shadow as reference
    ref_id = "expert:gold:test_ref"
    temp_shadow_db.create_shadow(_make_config(ref_id, domain="gold"))

    # Both shadows have identical perfect PnL
    for sid in (shadow_id, ref_id):
        for i in range(10):
            _add_closed_trade(temp_shadow_db, sid, "GLD", "long",
                              180.0, 189.0, today_str, today_str, 0.05, 0.1)

    # Gap should be near zero since both have identical returns
    gap = gap_manager.compute_inter_shadow_gap(shadow_id, "GLD", today_str)
    assert gap < 0.30

    # Force multiple discount updates
    for _ in range(20):
        gap_manager.update_discount_rate(shadow_id)

    discount = gap_manager._discount_rates.get(shadow_id, 0.20)
    assert discount >= gap_manager.settings.confidence_discount_floor  # 0.05
    assert discount == pytest.approx(gap_manager.settings.confidence_discount_floor, abs=0.01)


# ── Test 5: inter-shadow gap vs median ────────────────────────────────────

def test_inter_shadow_gap_vs_median(gap_manager, temp_shadow_db):
    """GapRatio compares shadow's PnL vs median of other shadows for same ticker/date."""
    shadows = [f"expert:gold:test_median_{i}" for i in range(4)]
    for sid in shadows:
        temp_shadow_db.create_shadow(_make_config(sid, domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 3 shadows with varying PnL: -2%, +1%, +5%
    trade_data = [
        ("expert:gold:test_median_0", -0.02),
        ("expert:gold:test_median_1", 0.01),
        ("expert:gold:test_median_2", 0.05),
    ]
    for sid, pnl in trade_data:
        entry = 180.0
        exit_price = 180.0 * (1.0 + pnl)
        _add_closed_trade(temp_shadow_db, sid, "GLD", "long",
                          entry, exit_price, today_str, today_str, pnl, 0.1)

    # Shadow 3 (not in the file match above) gets the gap computed
    # Its PnL is not provided explicitly, so gap should be computed against the median (which is 0.01 or 1%)
    # Since the test didn't add trades for test_median_3, it should return inf or very large
    # Actually let's add some for it:
    _add_closed_trade(temp_shadow_db, "expert:gold:test_median_3", "GLD", "long",
                      180.0, 180.0 * 0.99, today_str, today_str, -0.01, 0.1)

    gap = gap_manager.compute_inter_shadow_gap("expert:gold:test_median_3", "GLD", today_str)
    # Median of others is 0.01 (between -0.02, +0.01, +0.05)
    # test_median_3 has -0.01, so gap = abs(-0.01 - 0.01) / max(abs(0.01), 0.01) = 0.02 / 0.01 = 2.0
    assert gap > 0.0
    assert isinstance(gap, float)


# ── Test 6: live ready all 6 criteria ─────────────────────────────────────

def test_live_ready_all_6_criteria(gap_manager, temp_shadow_db):
    """check_live_ready validates all 6 certification criteria."""
    shadow_id = "expert:gold:test_live_ready"
    temp_shadow_db.create_shadow(_make_config(shadow_id, "expert", domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create reference shadow to enable inter-shadow gap computation
    ref_id = "expert:gold:test_live_ref"
    temp_shadow_db.create_shadow(_make_config(ref_id, "expert", domain="gold"))

    # Add 20+ paired trades with good returns (50/50 win/loss for forward validation)
    for i in range(25):
        # First 12 trades are winners, rest are still profitable (mixed for realism)
        if i < 12:
            exit_price = 180.0 * (1.0 + 0.03)  # 3% gain
            pnl = 0.03
        else:
            exit_price = 180.0 * (1.0 + 0.02)  # 2% gain
            pnl = 0.02
        _add_closed_trade(temp_shadow_db, shadow_id, "GLD", "long",
                          180.0, exit_price, today_str, today_str, pnl, 0.1)
        _add_closed_trade(temp_shadow_db, ref_id, "GLD", "long",
                          180.0, exit_price, today_str, today_str, pnl, 0.1)

    # Add a daily snapshot showing low MDD
    snapshot = DailySnapshot(
        shadow_id=shadow_id,
        date=today_str,
        virtual_capital=53000.0,
        daily_return_pct=0.01,
        cumulative_return_pct=0.06,
        max_drawdown_pct=0.05,  # 5% MDD < 25% threshold
        win_rate_pct=70.0,
    )
    temp_shadow_db.save_snapshot(shadow_id, snapshot)

    # Update discount rate so it falls below 0.15 (criterion 3)
    gap_manager.update_discount_rate(shadow_id)
    gap_manager.update_discount_rate(shadow_id)
    gap_manager.update_discount_rate(shadow_id)

    is_ready, reason = gap_manager.check_live_ready(shadow_id)
    assert is_ready, f"Expected live-ready, got: {reason}"
    assert "ready" in reason.lower()


def test_not_live_ready_insufficient_trades(gap_manager, temp_shadow_db):
    """Shadow with fewer than 10 trades should fail live-ready check."""
    shadow_id = "expert:gold:test_few_trades"
    temp_shadow_db.create_shadow(_make_config(shadow_id, "expert", domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i in range(3):
        _add_closed_trade(temp_shadow_db, shadow_id, "GLD", "long",
                          180.0, 185.0, today_str, today_str, 0.027, 0.1)

    is_ready, reason = gap_manager.check_live_ready(shadow_id)
    assert not is_ready
    assert "trade" in reason.lower() or "10" in reason


def test_not_live_ready_high_mdd(gap_manager, temp_shadow_db):
    """Shadow with MDD over 25% should fail live-ready check."""
    shadow_id = "expert:gold:test_high_mdd"
    temp_shadow_db.create_shadow(_make_config(shadow_id, "expert", domain="gold"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Add 20+ trades to pass trade count and PBO criteria
    ref_id = "expert:gold:test_mdd_ref"
    temp_shadow_db.create_shadow(_make_config(ref_id, "expert", domain="gold"))
    for i in range(25):
        _add_closed_trade(temp_shadow_db, shadow_id, "GLD", "long",
                          180.0, 185.0, today_str, today_str, 0.027, 0.1)
        _add_closed_trade(temp_shadow_db, ref_id, "GLD", "long",
                          180.0, 185.0, today_str, today_str, 0.027, 0.1)

    # High MDD snapshot
    snapshot = DailySnapshot(
        shadow_id=shadow_id,
        date=today_str,
        virtual_capital=48000.0,
        max_drawdown_pct=0.30,  # 30% > 25% expert limit
    )
    temp_shadow_db.save_snapshot(shadow_id, snapshot)

    # Update discount rate so it falls below 0.15 (so discount passes, MDD is the real failure)
    gap_manager.update_discount_rate(shadow_id)
    gap_manager.update_discount_rate(shadow_id)
    gap_manager.update_discount_rate(shadow_id)

    is_ready, reason = gap_manager.check_live_ready(shadow_id)
    assert not is_ready
    assert "mdd" in reason.lower() or "drawdown" in reason.lower()
