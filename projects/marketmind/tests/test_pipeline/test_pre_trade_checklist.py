"""Tests for pre-trade checklist validation."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from marketmind.pipeline.pre_trade_checklist import (
    ChecklistItem,
    PreTradeReport,
    run_pre_trade_checklist,
)


def _fresh_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_timestamp() -> str:
    return "2020-01-01T00:00:00+00:00"


def _make_ticket(**overrides) -> dict:
    defaults = {
        "direction": "long",
        "instrument": "EUR/USD",
        "position_size_pct": 0.10,
        "entry_level": 188.60,
        "stop_loss": 182.50,
        "take_profit": 200.0,
        "risk_budget_consumed_bps": 500.0,
    }
    defaults.update(overrides)
    return defaults


def _make_market_data(**overrides) -> dict:
    defaults = {
        "current_price": 188.60,
        "atr_20": 4.15,
        "support_levels": [182.0, 180.0],
        "resistance_levels": [195.0, 200.0],
        "timestamp": _fresh_timestamp(),
        "existing_positions": [],
        "kill_criteria_have_hooks": True,
    }
    defaults.update(overrides)
    return defaults


class TestStopTooTight:
    @pytest.mark.asyncio
    async def test_stop_too_tight_fails(self):
        """Stop distance < ATR x 2 should fail."""
        ticket = _make_ticket(stop_loss=186.0, entry_level=188.60)
        # stop_distance = 2.60, atr x 2 = 8.30 → too tight
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_NOT_TOO_TIGHT"].passed is False
        assert items["STOP_NOT_TOO_TIGHT"].severity == "BLOCK"

    @pytest.mark.asyncio
    async def test_stop_sufficient_distance_passes(self):
        """Stop distance > ATR x 2 should pass."""
        ticket = _make_ticket(stop_loss=178.0, entry_level=188.60)
        # stop_distance = 10.60, atr x 2 = 8.30 → sufficient
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_NOT_TOO_TIGHT"].passed is True


class TestStopTooLoose:
    @pytest.mark.asyncio
    async def test_stop_in_budget_passes(self):
        """Max loss within risk budget should pass."""
        ticket = _make_ticket(
            entry_level=188.60, stop_loss=182.50,
            position_size_pct=0.10, risk_budget_consumed_bps=500.0,
        )
        # entry_stop_pct = (188.60 - 182.50) / 188.60 = 0.0323
        # max_loss_bps = 0.0323 * 0.10 * 10000 = 32.34 bps < 500 bps → OK
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_NOT_TOO_LOOSE"].passed is True

    @pytest.mark.asyncio
    async def test_stop_exceeding_budget_fails(self):
        """Max loss exceeding risk budget should fail."""
        ticket = _make_ticket(
            entry_level=100.0, stop_loss=80.0,
            position_size_pct=0.10, risk_budget_consumed_bps=100.0,
        )
        # entry_stop_pct = 20 / 100 = 0.20
        # max_loss_bps = 0.20 * 0.10 * 10000 = 200 bps > 100 bps → fails
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_NOT_TOO_LOOSE"].passed is False


class TestStopAtMeaningfulLevel:
    @pytest.mark.asyncio
    async def test_stop_near_support_passes(self):
        """Stop near a known support level should pass."""
        ticket = _make_ticket(stop_loss=182.20)
        # 182.20 is near support 182.0 (within atr * 0.5 = 2.075)
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_AT_MEANINGFUL_LEVEL"].passed is True

    @pytest.mark.asyncio
    async def test_stop_far_from_levels_warns(self):
        """Stop not near any S/R level should warn."""
        ticket = _make_ticket(stop_loss=170.0)
        # 170.0 is far from 182.0 and 180.0
        market = _make_market_data()
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["STOP_AT_MEANINGFUL_LEVEL"].passed is False
        assert items["STOP_AT_MEANINGFUL_LEVEL"].severity == "WARN"


class TestPositionWithinLimit:
    @pytest.mark.asyncio
    async def test_position_within_limit_passes(self):
        ticket = _make_ticket(position_size_pct=0.10)
        market = _make_market_data(portfolio_pct_limit=0.25)
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["POSITION_WITHIN_LIMIT"].passed is True

    @pytest.mark.asyncio
    async def test_position_exceeds_limit_fails(self):
        ticket = _make_ticket(position_size_pct=0.30)
        market = _make_market_data(portfolio_pct_limit=0.25)
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["POSITION_WITHIN_LIMIT"].passed is False
        assert items["POSITION_WITHIN_LIMIT"].severity == "BLOCK"


class TestNoConflictingPositions:
    @pytest.mark.asyncio
    async def test_no_existing_positions_passes(self):
        ticket = _make_ticket(direction="long", instrument="EUR/USD")
        market = _make_market_data(existing_positions=[])
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["NO_CONFLICTING_POSITIONS"].passed is True

    @pytest.mark.asyncio
    async def test_same_direction_passes(self):
        ticket = _make_ticket(direction="long", instrument="EUR/USD")
        market = _make_market_data(existing_positions=[
            {"instrument": "EUR/USD", "direction": "long", "size_pct": 0.05},
        ])
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["NO_CONFLICTING_POSITIONS"].passed is True

    @pytest.mark.asyncio
    async def test_opposite_direction_fails(self):
        ticket = _make_ticket(direction="long", instrument="EUR/USD")
        market = _make_market_data(existing_positions=[
            {"instrument": "EUR/USD", "direction": "short", "size_pct": 0.05},
        ])
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["NO_CONFLICTING_POSITIONS"].passed is False
        assert items["NO_CONFLICTING_POSITIONS"].severity == "BLOCK"

    @pytest.mark.asyncio
    async def test_different_instrument_no_conflict(self):
        ticket = _make_ticket(direction="long", instrument="EUR/USD")
        market = _make_market_data(existing_positions=[
            {"instrument": "XAU/USD", "direction": "short", "size_pct": 0.05},
        ])
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["NO_CONFLICTING_POSITIONS"].passed is True


class TestMarketDataStaleness:
    @pytest.mark.asyncio
    async def test_fresh_data_succeeds(self):
        ticket = _make_ticket()
        market = _make_market_data(timestamp=_fresh_timestamp())
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["MARKET_DATA_FRESH"].passed is True

    @pytest.mark.asyncio
    async def test_stale_data_blocks_all_price_checks(self):
        ticket = _make_ticket()
        market = _make_market_data(timestamp=_stale_timestamp())
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["MARKET_DATA_FRESH"].passed is False
        # When data is stale, STOP checks are skipped as failures
        assert items["STOP_NOT_TOO_TIGHT"].passed is False

    @pytest.mark.asyncio
    async def test_missing_timestamp_treated_as_stale(self):
        ticket = _make_ticket()
        market = _make_market_data()
        del market["timestamp"]
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["MARKET_DATA_FRESH"].passed is False


class TestKillCriteriaMonitored:
    @pytest.mark.asyncio
    async def test_all_hooks_present_passes(self):
        ticket = _make_ticket()
        market = _make_market_data(kill_criteria_have_hooks=True)
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["KILL_CRITERIA_MONITORED"].passed is True

    @pytest.mark.asyncio
    async def test_missing_hooks_warns(self):
        ticket = _make_ticket()
        market = _make_market_data(kill_criteria_have_hooks=False)
        report = await run_pre_trade_checklist(ticket, market)
        items = {i.name: i for i in report.items}
        assert items["KILL_CRITERIA_MONITORED"].passed is False
        assert items["KILL_CRITERIA_MONITORED"].severity == "WARN"
        assert len(report.warnings) > 0


class TestAllBlockersPassed:
    @pytest.mark.asyncio
    async def test_all_checks_pass(self):
        """With valid inputs, all blockers should pass."""
        ticket = _make_ticket(
            entry_level=188.60, stop_loss=178.0,
            position_size_pct=0.10, risk_budget_consumed_bps=1000.0,
        )
        market = _make_market_data(
            support_levels=[178.0, 175.0],
            portfolio_pct_limit=0.25,
        )
        report = await run_pre_trade_checklist(ticket, market)
        assert report.all_blockers_passed is True

    @pytest.mark.asyncio
    async def test_single_blocker_fails_all(self):
        """A single BLOCK failure should make all_blockers_passed False."""
        ticket = _make_ticket(position_size_pct=0.30)  # exceeds cap
        market = _make_market_data(portfolio_pct_limit=0.25)
        report = await run_pre_trade_checklist(ticket, market)
        assert report.all_blockers_passed is False
