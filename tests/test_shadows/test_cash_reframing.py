"""Tests for cash reframing A/B test."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.cash_reframing import (
    CashReframingTest, CashReframingResult,
)
from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen,
)
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def reframing_test(temp_shadow_db, settings):
    return CashReframingTest(temp_shadow_db, settings)


def _make_config(shadow_id, shadow_type="expert", capital=50000.0, domain=None):
    return ShadowConfig(
        shadow_id=shadow_id,
        shadow_type=shadow_type,
        display_name=f"Test {shadow_id}",
        methodology_prompt=f"You are a {domain or 'market'} analyst.",
        virtual_capital=capital,
        domain=domain,
    )


def _add_closed_trade(db, shadow_id, ticker, direction, entry, exit_price, entry_date,
                       exit_date, pnl, pos_size=0.1, exit_reason="signal"):
    trade = VirtualTradeOpen(
        shadow_id=shadow_id, ticker=ticker, direction=direction,
        entry_price=entry, position_size_pct=pos_size, entry_date=entry_date,
    )
    trade_id = db.record_trade_open(shadow_id, trade)
    db.record_trade_close(trade_id, exit_price, exit_reason, pnl)


# ── Test 1: cohorts are balanced 6 and 6 ──────────────────────────────────

def test_cohorts_are_balanced_6_and_6(reframing_test, temp_shadow_db):
    """allocate_cohorts produces exactly 6 treatment and 6 control shadows."""
    # Create 12 shadows
    for i in range(12):
        config = _make_config(f"expert:tech:reframe_{i:02d}", "expert", domain="tech")
        temp_shadow_db.create_shadow(config)

    treatment, control = reframing_test.allocate_cohorts()
    assert len(treatment) == 6
    assert len(control) == 6
    # No overlap
    assert set(treatment).isdisjoint(set(control))
    # All 12 shadows accounted for
    assert len(set(treatment) | set(control)) == 12


# ── Test 2: same shadow always same cohort ─────────────────────────────────

def test_same_shadow_always_same_cohort(reframing_test, temp_shadow_db):
    """Same shadow_id always maps to the same cohort (seeded deterministically)."""
    for i in range(12):
        config = _make_config(f"expert:tech:stable_{i:02d}", "expert", domain="tech")
        temp_shadow_db.create_shadow(config)

    t1, c1 = reframing_test.allocate_cohorts()
    t2, c2 = reframing_test.allocate_cohorts()

    assert t1 == t2
    assert c1 == c2


# ── Test 3: disposition effect greater than 1 for losers held ─────────────

def test_disposition_effect_greater_than_1_for_losers_held(reframing_test, temp_shadow_db):
    """DE > 1 when winners are closed but losers are held (classic disposition)."""
    shadow_id = "expert:tech:de_test"
    temp_shadow_db.create_shadow(_make_config(shadow_id, domain="tech"))

    # 5 winning trades (all closed)
    for i in range(5):
        _add_closed_trade(temp_shadow_db, shadow_id, "AAPL", "long",
                          100.0, 110.0, "2026-01-15", "2026-02-01", 0.10, 0.1)

    # 3 losing trades (all still open — not closed)
    # To simulate held losers, we open but don't close them
    for i in range(3):
        trade = VirtualTradeOpen(
            shadow_id=shadow_id, ticker="AAPL", direction="long",
            entry_price=120.0, position_size_pct=0.1, entry_date="2026-01-15",
        )
        temp_shadow_db.record_trade_open(shadow_id, trade)

    de = reframing_test.compute_disposition_effect(shadow_id, days=90)
    assert de is not None
    assert de >= 1.0, f"Expected DE >= 1 with winners closed and losers held, got {de}"


# ── Test 4: Mann-Whitney on DE ────────────────────────────────────────────

def test_mann_whitney_on_de(reframing_test, temp_shadow_db):
    """Mann-Whitney U test detects lower DE in treatment group."""
    # Create 6 treatment + 6 control shadows
    for i in range(12):
        stype = "expert"
        sid = f"expert:tech:mw_{i:02d}"
        config = _make_config(sid, stype, domain="tech")
        temp_shadow_db.create_shadow(config)

    # Force-allocate cohorts for deterministic testing
    all_active = [s.shadow_id for s in temp_shadow_db.get_active_shadows()]
    treatment = sorted(all_active[:6])
    control = sorted(all_active[6:12])

    # Treatment: low DE (realize gains AND losses similarly)
    for sid in treatment:
        for i in range(3):
            _add_closed_trade(temp_shadow_db, sid, "AAPL", "long",
                              100.0, 110.0, "2026-01-15", "2026-02-01", 0.10, 0.1)
        for i in range(3):
            _add_closed_trade(temp_shadow_db, sid, "AAPL", "long",
                              100.0, 90.0, "2026-01-15", "2026-02-01", -0.10, 0.1)

    # Control: high DE (realize gains but hold losers)
    for sid in control:
        for i in range(3):
            _add_closed_trade(temp_shadow_db, sid, "AAPL", "long",
                              100.0, 110.0, "2026-01-15", "2026-02-01", 0.10, 0.1)
        # Open losers but do NOT close them
        for i in range(3):
            trade = VirtualTradeOpen(
                shadow_id=sid, ticker="AAPL", direction="long",
                entry_price=120.0, position_size_pct=0.1, entry_date="2026-01-15",
            )
            temp_shadow_db.record_trade_open(sid, trade)

    # Override cohort allocation (set _allocated=True to prevent re-allocation)
    reframing_test._treatment_ids = treatment
    reframing_test._control_ids = control
    reframing_test._allocated = True

    result = reframing_test.run_statistical_test()
    assert result.mann_whitney_pvalue is not None
    assert isinstance(result.treatment_de_mean, float)
    assert isinstance(result.control_de_mean, float)
    # Treatment DE should be lower (PGR/PLR with both realized vs only gains realized)
    assert result.treatment_de_mean < result.control_de_mean


# ── Test 5: non-inferiority TOST on returns ────────────────────────────────

def test_non_inferiority_tost_on_returns(reframing_test, temp_shadow_db):
    """TOST test confirms treatment returns are non-inferior to control."""
    for i in range(12):
        config = _make_config(f"expert:tech:tost_{i:02d}", "expert", domain="tech")
        temp_shadow_db.create_shadow(config)

    all_active = [s.shadow_id for s in temp_shadow_db.get_active_shadows()]
    treatment = sorted(all_active[:6])
    control = sorted(all_active[6:12])

    # Both groups have similar returns (non-inferiority should pass)
    for sid in treatment + control:
        for i in range(5):
            _add_closed_trade(temp_shadow_db, sid, "AAPL", "long",
                              100.0, 108.0, "2026-05-01", "2026-05-10", 0.08, 0.1)

    reframing_test._treatment_ids = treatment
    reframing_test._control_ids = control
    reframing_test._allocated = True

    result = reframing_test.run_statistical_test()
    # Treatment cumulative return should be positive
    assert result.treatment_cumulative_return > 0
    # Non-inferiority should pass since both groups perform similarly
    assert result.non_inferiority_passed


# ── Test 6: cash reframing injection in gateway ────────────────────────────

@pytest.mark.asyncio
async def test_cash_reframing_injection_in_gateway():
    """Verify that cash_reframing_ticker triggers M1 injection in gateway."""
    from marketmind.gateway.async_client import (
        chat_with_integrity, init_gateway,
    )

    mock_response = {
        "choices": [{"message": {"content": "I would not buy AAPL today."}}],
        "usage": {"total_tokens": 200}
    }
    mock_http = AsyncMock()
    mock_http.post.return_value.json = MagicMock(return_value=mock_response)
    mock_http.post.return_value.status_code = 200

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        result = await chat_with_integrity(
            model="flash",
            system_prompt="You are a portfolio manager.",
            user_prompt="Should we sell?",
            caller_agent="test-shadow",
            cash_reframing_ticker="AAPL",
            cash_reframing_capital=10000.0,
        )
        assert result["content"] == "I would not buy AAPL today."
        # Verify CASH_REFRAMING_PROTOCOL was injected
        call_args = mock_http.post.call_args
        sent_messages = call_args[1]["json"]["messages"]
        assert "CASH_REFRAMING_PROTOCOL" in sent_messages[0]["content"]
        assert "AAPL" in sent_messages[0]["content"]


@pytest.mark.asyncio
async def test_cash_reframing_injection_not_applied_without_ticker():
    """Without cash_reframing_ticker, no injection should occur."""
    from marketmind.gateway.async_client import (
        chat_with_integrity, init_gateway,
    )

    mock_response = {
        "choices": [{"message": {"content": "Hold position."}}],
        "usage": {"total_tokens": 100}
    }
    mock_http = AsyncMock()
    mock_http.post.return_value.json = MagicMock(return_value=mock_response)
    mock_http.post.return_value.status_code = 200

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        result = await chat_with_integrity(
            model="flash",
            system_prompt="You are a portfolio manager.",
            user_prompt="Should we sell?",
            caller_agent="test-shadow",
            # No cash_reframing_ticker
        )
        assert result["content"] == "Hold position."
        call_args = mock_http.post.call_args
        sent_messages = call_args[1]["json"]["messages"]
        assert "CASH_REFRAMING_PROTOCOL" not in sent_messages[0]["content"]
