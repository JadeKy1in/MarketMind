"""Tests for Gate 3 position decision interaction loop."""
from __future__ import annotations

import pytest
from marketmind.pipeline.gate3_interaction import (
    DecisionTicket,
    Gate3Session,
    Gate2Session,
    run_gate3,
    _parse_field_update,
    _format_ticket_template,
    _format_checklist_results,
)
from marketmind.pipeline.position_sizing import PositionSizeResult
from marketmind.pipeline.pre_trade_checklist import (
    PreTradeReport,
    ChecklistItem,
)
from marketmind.pipeline.investigation_loop import HypothesisResult
from marketmind.pipeline.verification_chain import VerificationResult


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_vr(confidence: float = 0.81) -> VerificationResult:
    return VerificationResult(
        claim="Test claim",
        layer_1_market=confidence,
        layer_2_fundamental=confidence,
        layer_3_multisource=confidence,
        layer_4_historical=confidence,
        weighted_confidence=confidence,
        verdict="VERIFIED",
        sources_used=["source_a"],
    )


def make_hypothesis(confidence: float = 0.81, direction: str = "EUR/USD 看涨",
                    core_logic: str = "ECB加息推动EUR走强") -> HypothesisResult:
    return HypothesisResult(
        hypothesis="Test hypothesis",
        expectation_gap=0.15,
        verification=_make_vr(confidence),
        refined_hypothesis="Refined test hypothesis",
        confidence=confidence,
        bear_case="Bear case text",
        bear_case_confidence=0.35,
        verdict="ACTIONABLE",
        logic_chain=["Step 1"],
        direction=direction,
        risk_level="中等",
        time_window="2-4周",
        layer_1_narrative="L1 narrative",
        layer_2_narrative="L2 narrative",
        layer_3_narrative="L3 narrative",
        layer_4_narrative="L4 narrative",
        core_logic=core_logic,
    )


def make_gate2_session(**overrides) -> Gate2Session:
    kwargs = {
        "session_id": "g2-test-001",
        "selected_direction": "EUR/USD 看涨",
        "state": "END",
        "user_initial_conviction": "8",     # "8" → 0.8 parsed
        "final_conviction": "STRONG",
        "key_risks_acknowledged": ["Risk 1"],
        "kill_criteria_confirmed": ["KC-001"],
        "signal_conflicts_resolved": True,
        "turns": 5,
        "outcome": "CONTINUE",
    }
    kwargs.update(overrides)
    return Gate2Session(**kwargs)


def make_all_pass_report() -> PreTradeReport:
    return PreTradeReport(
        items=[
            ChecklistItem("MARKET_DATA_FRESH", True, "Data is fresh.", "BLOCK"),
            ChecklistItem("STOP_NOT_TOO_TIGHT", True, "Stop distance sufficient.", "BLOCK"),
            ChecklistItem("STOP_NOT_TOO_LOOSE", True, "Max loss within budget.", "BLOCK"),
            ChecklistItem("STOP_AT_MEANINGFUL_LEVEL", True, "Near support.", "WARN"),
            ChecklistItem("POSITION_WITHIN_LIMIT", True, "Within limit.", "BLOCK"),
            ChecklistItem("NO_CONFLICTING_POSITIONS", True, "No conflicts.", "BLOCK"),
            ChecklistItem("KILL_CRITERIA_MONITORED", True, "All monitored.", "WARN"),
        ],
        all_blockers_passed=True,
        warnings=[],
    )


# ── Data type tests ──────────────────────────────────────────────────────────

class TestDecisionTicket:
    def test_create_ticket(self):
        ticket = DecisionTicket(
            direction="long",
            instrument="EUR/USD",
            position_size_pct=0.122,
            entry_level=188.60,
            stop_loss=182.50,
            take_profit=200.0,
            risk_budget_consumed_bps=1220.0,
            conviction_score="STRONG",
            correlation_overlay="No existing positions",
            catalyst_timeline="ECB meeting in 2 weeks",
            max_hold_days=90,
            pre_trade_checks=None,
            created_at="2026-05-18T00:00:00+00:00",
        )
        assert ticket.direction == "long"
        assert ticket.instrument == "EUR/USD"
        assert ticket.position_size_pct == 0.122
        assert ticket.max_hold_days == 90


class TestGate3Session:
    def test_initial_state(self):
        session = Gate3Session(
            session_id="test-3",
            state="PRESENTING_TICKET",
            ticket=None,
            turns=0,
            outcome="DEFERRED",
            started_at="2026-05-18T00:00:00+00:00",
        )
        assert session.state == "PRESENTING_TICKET"
        assert session.outcome == "DEFERRED"
        assert session.ticket is None
        assert session.turns == 0


# ── Display formatting tests ─────────────────────────────────────────────────

class TestTicketTemplateFormatting:
    def test_template_includes_direction(self):
        result = _format_ticket_template(
            direction="EUR/USD 看涨",
            instrument_hint="EUR/USD",
            entry_hint="参考 L3",
            stop_hint="参考 ATR",
            tp_hint="参考 L3",
            sizing_result=None,
            conviction_level="STRONG",
            catalyst_hint="ECB meeting",
        )
        assert "EUR/USD 看涨" in result
        assert "STRONG" in result
        assert "ECB meeting" in result
        assert "DECISION TICKET" in result

    def test_template_includes_sizing(self):
        sizing = PositionSizeResult(
            raw_kelly_pct=0.4000,
            half_kelly_pct=0.2000,
            quarter_kelly_pct=0.1000,
            volatility_adjustment=0.72,
            correlation_discount=0.85,
            recommended_pct=0.122,
            capped=False,
            risk_bps=1220.0,
        )
        result = _format_ticket_template(
            direction="EUR/USD 看涨",
            instrument_hint="EUR/USD",
            entry_hint="",
            stop_hint="",
            tp_hint="",
            sizing_result=sizing,
            conviction_level="STRONG",
            catalyst_hint="",
        )
        assert "40.00%" in result
        assert "20.00%" in result
        assert "12.20%" in result
        assert "1220" in result


class TestChecklistResultsFormatting:
    def test_all_pass_formatting(self):
        ticket = DecisionTicket(
            direction="long", instrument="EUR/USD", position_size_pct=0.10,
            entry_level=188.60, stop_loss=182.50, take_profit=200.0,
            risk_budget_consumed_bps=500.0, conviction_score="STRONG",
            correlation_overlay="", catalyst_timeline="", max_hold_days=90,
            pre_trade_checks=make_all_pass_report(),
            created_at="2026-05-18T00:00:00+00:00",
        )
        output = _format_checklist_results(ticket)
        assert "所有阻塞项通过" in output
        assert "[PASS]" in output

    def test_null_checklist_handled(self):
        ticket = DecisionTicket(
            direction="long", instrument="EUR/USD", position_size_pct=0.10,
            entry_level=188.60, stop_loss=182.50, take_profit=200.0,
            risk_budget_consumed_bps=500.0, conviction_score="STRONG",
            correlation_overlay="", catalyst_timeline="", max_hold_days=90,
            pre_trade_checks=None,
            created_at="2026-05-18T00:00:00+00:00",
        )
        output = _format_checklist_results(ticket)
        assert "预交易检查未运行" in output


# ── Input parsing tests ──────────────────────────────────────────────────────

class TestFieldUpdateParsing:
    def _make_ticket(self):
        return DecisionTicket(
            direction="long", instrument="EUR/USD", position_size_pct=0.10,
            entry_level=188.60, stop_loss=182.50, take_profit=200.0,
            risk_budget_consumed_bps=500.0, conviction_score="STRONG",
            correlation_overlay="", catalyst_timeline="", max_hold_days=90,
            pre_trade_checks=None,
            created_at="2026-05-18T00:00:00+00:00",
        )

    def test_parse_stop_loss_chinese(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("止损: 180.50", ticket)
        assert updates["stop_loss"] == 180.50

    def test_parse_stop_loss_english(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("stop: 175.0", ticket)
        assert updates["stop_loss"] == 175.0

    def test_parse_entry_level(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("入场: 190.0", ticket)
        assert updates["entry_level"] == 190.0

    def test_parse_instrument(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("标的: XAU/USD", ticket)
        assert updates["instrument"] == "XAU/USD"

    def test_parse_position_size_percentage(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("仓位: 15%", ticket)
        assert updates["position_size_pct"] == 0.15

    def test_parse_max_hold_days(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("最大持有: 30", ticket)
        assert updates["max_hold_days"] == 30

    def test_parse_no_match_returns_empty(self):
        ticket = self._make_ticket()
        updates = _parse_field_update("今天天气不错", ticket)
        assert updates == {}


# ── Main orchestration tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_gate3_set_stop_then_cancel():
    """User sets stop loss, then cancels — verifies field update path."""
    hyps = [make_hypothesis(confidence=0.81)]
    g2 = make_gate2_session()

    responses = ["止损: 178.0", "取消"]
    msgs = []

    async def mock_io(prompt):
        return responses.pop(0) if responses else ""

    async def mock_status(msg):
        msgs.append(msg)

    result = await run_gate3(g2, hyps, "test-g3-stop-cancel",
                             io_handler=mock_io, status_handler=mock_status)

    assert result is not None
    assert result.ticket is not None
    assert result.ticket.stop_loss == 178.0
    assert result.outcome == "CANCELLED"


@pytest.mark.asyncio
async def test_run_gate3_cancel():
    """User cancels → outcome CANCELLED."""
    hyps = [make_hypothesis(confidence=0.81)]
    g2 = make_gate2_session()

    responses = ["取消"]
    msgs = []

    async def mock_io(prompt):
        return responses.pop(0) if responses else ""

    async def mock_status(msg):
        msgs.append(msg)

    result = await run_gate3(g2, hyps, "test-g3-cancel",
                             io_handler=mock_io, status_handler=mock_status)

    assert result is not None
    assert result.outcome == "CANCELLED"


@pytest.mark.asyncio
async def test_run_gate3_modify_fields_then_cancel():
    """User modifies multiple fields, then cancels — verifies all field updates."""
    hyps = [make_hypothesis(confidence=0.81)]
    g2 = make_gate2_session()

    responses = ["入场: 190.0", "标的: XAU/USD", "止损: 178.0", "取消"]
    msgs = []

    async def mock_io(prompt):
        return responses.pop(0) if responses else ""

    async def mock_status(msg):
        msgs.append(msg)

    result = await run_gate3(g2, hyps, "test-g3-modify",
                             io_handler=mock_io, status_handler=mock_status)

    assert result.ticket is not None
    assert result.ticket.entry_level == 190.0
    assert result.ticket.instrument == "XAU/USD"
    assert result.ticket.stop_loss == 178.0


@pytest.mark.asyncio
async def test_run_gate3_keyboard_interrupt():
    """KeyboardInterrupt saves partial state."""
    hyps = [make_hypothesis(confidence=0.81)]
    g2 = make_gate2_session()

    call_count = [0]

    async def mock_io(prompt):
        call_count[0] += 1
        if call_count[0] >= 3:
            raise KeyboardInterrupt()
        return "止损: 178.0"

    msgs = []

    async def mock_status(msg):
        msgs.append(msg)

    result = await run_gate3(g2, hyps, "test-g3-interrupt",
                             io_handler=mock_io, status_handler=mock_status)

    assert result is not None
    assert result.session_id == "test-g3-interrupt"


@pytest.mark.asyncio
async def test_run_gate3_uses_hypothesis_hints():
    """Gate 3 should derive instrument hints from hypothesis direction names."""
    hyps = [make_hypothesis(confidence=0.81, direction="XAU/USD 看涨",
                            core_logic="Gold safe-haven demand on geopolitical risk")]
    g2 = make_gate2_session(
        selected_direction="XAU/USD 看涨",
        final_conviction="MODERATE",
        user_initial_conviction="7",
    )

    responses = ["取消"]
    msgs = []

    async def mock_io(prompt):
        return responses.pop(0) if responses else ""

    async def mock_status(msg):
        msgs.append(msg)

    result = await run_gate3(g2, hyps, "test-g3-hints",
                             io_handler=mock_io, status_handler=mock_status)

    assert result.ticket is not None
    # Direction from hypothesis should be extracted
    assert "XAU" in result.ticket.direction
    # Instrument hint derived from direction name
    assert result.ticket.instrument and "XAU" in result.ticket.instrument
    assert result.ticket.catalyst_timeline is not None


@pytest.mark.asyncio
async def test_run_gate3_conviction_discount_in_ticket_sizing():
    """Higher conviction parsing (user_initial_conviction) → larger sizing.

    Uses cancel path; verifies position_size_pct reflects the parsed conviction.
    """
    hyps = [make_hypothesis(confidence=0.81)]
    g2_strong = make_gate2_session(user_initial_conviction="8")
    g2_weak = make_gate2_session(user_initial_conviction="4")

    responses = ["取消"]
    msgs_strong = []

    async def mock_io(resps):
        async def handler(prompt):
            return resps.pop(0) if resps else ""
        return handler

    async def mock_status(msg):
        msgs_strong.append(msg)

    result_strong = await run_gate3(
        g2_strong, hyps, "test-g3-strong",
        io_handler=await mock_io(["取消"]),
        status_handler=mock_status,
    )

    msgs_weak = []
    async def mock_status_w(msg):
        msgs_weak.append(msg)

    result_weak = await run_gate3(
        g2_weak, hyps, "test-g3-weak",
        io_handler=await mock_io(["取消"]),
        status_handler=mock_status_w,
    )

    assert result_strong.ticket is not None
    assert result_weak.ticket is not None
    # Strong conviction (8→0.8) should give larger or equal position than weak (4→0.4)
    assert result_strong.ticket.position_size_pct >= result_weak.ticket.position_size_pct
