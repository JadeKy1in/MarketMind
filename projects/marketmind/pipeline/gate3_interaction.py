"""Gate 3 conversation loop — position decision for MarketMind.

Final human touchpoint in the investment pipeline. Presents a structured decision
ticket template, runs pre-trade validation, and confirms execution parameters.

No LLM calls — this module orchestrates, doesn't analyze.
No shadow/ELITE functionality. No imports from shadows/.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.pipeline.investigation_loop import HypothesisResult
from marketmind.pipeline.position_sizing import (
    PositionSizeResult,
    compute_position_size,
)
from marketmind.pipeline.pre_trade_checklist import (
    PreTradeReport,
    run_pre_trade_checklist,
)
from marketmind.integrity.input_guard import sanitize_for_llm_prompt
from marketmind.storage.gate_archiver import GateArchiver, GateTurn
from marketmind.storage.archivist import MarketMindArchive
from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint


# ── Forward reference for Gate2Session ─────────────────────────────────────────
# gate2_interaction.py may not exist yet; define a minimal local type that
# provides the fields Gate 3 needs. When gate2_interaction.py is created,
# its Gate2Session should match this interface.
try:
    from marketmind.pipeline.gate2_interaction import Gate2Session
except ImportError:
    @dataclass
    class Gate2Session:
        session_id: str = ""
        selected_direction: str = ""
        state: str = ""
        user_initial_conviction: str = ""  # raw user response e.g. "7"
        final_conviction: str = ""          # "STRONG" | "MODERATE" | "WEAK"
        key_risks_acknowledged: list[str] = field(default_factory=list)
        kill_criteria_confirmed: list[str] = field(default_factory=list)
        signal_conflicts_resolved: bool = False
        turns: int = 0
        outcome: str = ""


# ── Constants ─────────────────────────────────────────────────────────────────

_TURN_LIMIT = 40
_TURN_WARNING = 30

# ── Intent regex patterns ─────────────────────────────────────────────────────

_CONFIRMATION_RE = re.compile(r"确定|确认|同意|就选|就这样|下单|执行|没问题|可以|好的")
_MODIFY_RE = re.compile(r"修改|改|调整|换|不对|不是|重新")
_CANCEL_RE = re.compile(r"取消|放弃|不要|算了|不做了|撤回|撤销")


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class DecisionTicket:
    direction: str
    instrument: str
    position_size_pct: float
    entry_level: float | None
    stop_loss: float
    take_profit: float | None
    risk_budget_consumed_bps: float
    conviction_score: str
    correlation_overlay: str
    catalyst_timeline: str
    max_hold_days: int
    pre_trade_checks: PreTradeReport | None
    created_at: str


@dataclass
class Gate3Session:
    session_id: str
    state: str
    ticket: DecisionTicket | None
    turns: int
    outcome: str          # "EXECUTED" | "DEFERRED" | "CANCELLED"
    started_at: str


# ── Display helpers ───────────────────────────────────────────────────────────

def _format_ticket_template(
    direction: str, instrument_hint: str, entry_hint: str, stop_hint: str,
    tp_hint: str, sizing_result: PositionSizeResult | None,
    conviction_level: str, catalyst_hint: str,
) -> str:
    lines = [
        "── DECISION TICKET ──",
        f"方向: {direction}",
        f"标的: [{instrument_hint or '请指定'}]",
        f"入场: [{entry_hint or '请指定'}]",
        f"止损: [{stop_hint or '请指定'}]",
        f"止盈: [{tp_hint or '请指定'}]",
    ]
    if sizing_result is not None:
        s = sizing_result
        lines.extend([
            "", "── 仓位计算 ──",
            f"Full Kelly: {s.raw_kelly_pct:.2%}  Half Kelly: {s.half_kelly_pct:.2%}  Quarter: {s.quarter_kelly_pct:.2%}",
            f"波动率调整: x{s.volatility_adjustment:.2f}  相关性折扣: x{s.correlation_discount:.2f}",
            f"推荐仓位: {s.recommended_pct:.2%}  风险消耗: {s.risk_bps:.0f} bps  {'[触及上限]' if s.capped else ''}",
        ])
    lines.extend([
        "", f"信心等级: {conviction_level}",
        f"催化剂: [{catalyst_hint or '请指定'}]  最大持有: [90天]",
        "", "输入'确定'确认，输入'取消'放弃。",
    ])
    return "\n".join(lines)


def _format_checklist_results(ticket: DecisionTicket) -> str:
    if ticket.pre_trade_checks is None:
        return "[预交易检查未运行]"
    lines = ["── 预交易检查结果 ──"]
    for item in ticket.pre_trade_checks.items:
        icon = "[PASS]" if item.passed else "[FAIL]"
        lines.append(f"  {icon} [{item.severity}] {item.name}: {item.detail}")
    if ticket.pre_trade_checks.warnings:
        lines.extend(["", "── 警告 ──"] + [f"  [WARN] {w}" for w in ticket.pre_trade_checks.warnings])
    lines.append("" if ticket.pre_trade_checks.all_blockers_passed else "")
    lines.append("所有阻塞项通过 — 可以执行。" if ticket.pre_trade_checks.all_blockers_passed else "存在未通过的阻塞项 — 请修正后重试。")
    return "\n".join(lines)


# ── Input parsing ─────────────────────────────────────────────────────────────

def _parse_field_update(text: str, ticket: DecisionTicket) -> dict[str, Any]:
    """Parse text for field assignments like '止损: 180.50' or 'stop: 180.50'.

    Returns dict of field_name -> value for recognized fields.
    """
    updates: dict[str, Any] = {}
    field_map = {
        "入场": "entry_level", "entry": "entry_level",
        "止损": "stop_loss", "stop": "stop_loss",
        "止盈": "take_profit", "tp": "take_profit", "take_profit": "take_profit",
        "标的": "instrument", "instrument": "instrument",
        "仓位": "position_size_pct", "size": "position_size_pct",
        "风险": "risk_budget_consumed_bps", "risk_budget": "risk_budget_consumed_bps",
        "催化剂": "catalyst_timeline", "catalyst": "catalyst_timeline",
        "最大持有": "max_hold_days", "max_hold": "max_hold_days",
        "信心": "conviction_score", "conviction": "conviction_score",
    }

    for key, field in field_map.items():
        pattern = rf"{key}\s*[:：=]\s*(\S+)"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = m.group(1).strip()
            if field in ("entry_level", "stop_loss", "take_profit", "position_size_pct",
                         "risk_budget_consumed_bps"):
                try:
                    updates[field] = float(value.rstrip("%"))
                    if field in ("position_size_pct",) and updates[field] > 1:
                        updates[field] = updates[field] / 100.0
                except ValueError:
                    pass
            elif field == "max_hold_days":
                try:
                    updates[field] = int(value)
                except ValueError:
                    pass
            else:
                updates[field] = value

    return updates


# ── Main orchestration ────────────────────────────────────────────────────────

async def run_gate3(
    gate2_session: Gate2Session,
    hypotheses: list[HypothesisResult],
    session_id: str,
    io_handler: callable = None,
    status_handler: callable = None,
) -> Gate3Session:
    """Run the Gate 3 position decision conversation loop.

    Args:
        gate2_session: Conviction record from Gate 2.
        hypotheses: Investigation results from the HVR loop.
        session_id: Stable session identifier.
        io_handler: async function(prompt: str) -> str for user input.
        status_handler: async function(message: str) for status display.

    Returns:
        Gate3Session with final state, decision ticket, and outcome.
    """
    archive = MarketMindArchive()
    archiver = GateArchiver(archive)
    await archiver.start_session(gate_number=3, session_id=session_id)

    session_mgr = SessionManager()

    direction = gate2_session.selected_direction or "未指定"
    conviction_level = gate2_session.final_conviction or "MODERATE"

    # ── Derive hints from hypotheses ──────────────────────────────────────
    if hypotheses:
        first = hypotheses[0]
        instrument_hint = first.direction.replace("看涨", "").replace("看跌", "").strip()
        catalyst_hint = first.core_logic[:80] if first.core_logic else ""
    else:
        instrument_hint = ""
        catalyst_hint = ""

    session = Gate3Session(
        session_id=session_id,
        state="PRESENTING_TICKET",
        ticket=None,
        turns=0,
        outcome="DEFERRED",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    async def _say(msg: str) -> None:
        if status_handler:
            await status_handler(msg)

    async def _ask(prompt: str) -> str:
        if io_handler:
            return await io_handler(prompt)
        return ""

    async def _log(speaker: str, turn_type: str, content_type: str,
                   text: str, data: dict = None):
        sanitized = sanitize_for_llm_prompt(text, source="gate3_chat")
        await archiver.log_turn(GateTurn(
            turn=session.turns,
            speaker=speaker,
            type=turn_type,
            content_type=content_type,
            text=sanitized.sanitized,
            data=data,
            warnings=sanitized.warnings if sanitized.warnings else None,
        ))

    try:
        # ── Step 3.1: Present decision ticket template ────────────────────
        session.state = "PRESENTING_TICKET"

        # Compute initial position sizing if we have confidence data
        sizing_result = None
        # Parse user_initial_conviction (e.g. "7") to float 0.0-1.0
        try:
            parsed_conviction = float(gate2_session.user_initial_conviction) / 10.0
        except (ValueError, TypeError):
            parsed_conviction = 0.0
        if parsed_conviction > 0 and hypotheses:
            # Derive win probability from the strongest hypothesis
            best_hyp = max(hypotheses, key=lambda h: h.confidence)
            try:
                sizing_result = compute_position_size(
                    win_probability=best_hyp.confidence,
                    win_loss_ratio=2.0,  # default: 2:1 reward-to-risk
                    user_conviction_discount=min(parsed_conviction / max(best_hyp.confidence, 0.01), 1.0),
                    volatility_percentile=0.5,
                    correlation_to_portfolio=0.0,
                )
            except ValueError:
                sizing_result = None

        template = _format_ticket_template(
            direction=direction, instrument_hint=instrument_hint,
            entry_hint="参考 L3 入场区域", stop_hint="参考 ATR(20) × 2",
            tp_hint="参考 L3 目标区域", sizing_result=sizing_result,
            conviction_level=conviction_level, catalyst_hint=catalyst_hint,
        )
        await _say(template)
        await _log("AI", "ticket_template", "structured_data",
                   f"Ticket template for {direction}",
                   {"direction": direction})

        # Build initial ticket
        ticket = DecisionTicket(
            direction=direction,
            instrument=instrument_hint,
            position_size_pct=sizing_result.recommended_pct if sizing_result else 0.0,
            entry_level=None,
            stop_loss=0.0,
            take_profit=None,
            risk_budget_consumed_bps=sizing_result.risk_bps if sizing_result else 0.0,
            conviction_score=conviction_level,
            correlation_overlay="未检查 — 需要投资组合数据",
            catalyst_timeline=catalyst_hint,
            max_hold_days=90,
            pre_trade_checks=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        session.ticket = ticket

        # ── Step 3.2-3.3: Interaction loop ────────────────────────────────
        session.state = "AWAITING_USER_INPUT"
        await _say("\n请填写/修改字段或确认。输入'确定'确认，输入'取消'放弃。")

        while session.turns < _TURN_LIMIT:
            user_input = await _ask("> ")
            if not user_input or not user_input.strip():
                continue

            session.turns += 1
            await _log("USER", "ticket_response", "user_free_text", user_input)

            if session.turns >= _TURN_WARNING:
                remaining = _TURN_LIMIT - session.turns
                await _say(f"[提示] 已进行 {session.turns}/{_TURN_LIMIT} 轮，剩余 {remaining} 轮。")

            # ── Check for cancel ──────────────────────────────────────────
            if _CANCEL_RE.search(user_input):
                session.outcome = "CANCELLED"
                session.state = "CANCELLED"
                await _say("已取消决策票据。")
                await _log("AI", "decision_cancelled", "system_decision",
                           "Ticket cancelled by user")
                break

            # ── Check for field updates (key: value syntax) ────────────────
            # Must run BEFORE confirm/modify intent checks so "止损: 178.0"
            # is parsed as an update, not treated as an unknown message.
            updates = _parse_field_update(user_input, ticket)
            if updates:
                for field, value in updates.items():
                    setattr(ticket, field, value)
                await _say(f"已更新: {', '.join(f'{k}={v}' for k, v in updates.items())}")
                await _log("AI", "field_update", "system_decision",
                           "Fields updated", updates)
                continue

            # ── Check for confirm ──────────────────────────────────────────
            if _CONFIRMATION_RE.search(user_input) and not _MODIFY_RE.search(user_input):
                session.state = "RUNNING_CHECKLIST"

                # Validate ticket has minimum required fields
                if ticket.stop_loss <= 0:
                    await _say("请先设置止损 (stop_loss)。")
                    session.state = "AWAITING_USER_INPUT"
                    continue
                if not ticket.instrument:
                    await _say("请先指定标的 (instrument)。")
                    session.state = "AWAITING_USER_INPUT"
                    continue

                # ── Run pre-trade checklist ────────────────────────────────
                await _say("\n正在运行预交易检查...")
                checklist_report = await run_pre_trade_checklist(
                    decision_ticket={
                        "direction": ticket.direction,
                        "instrument": ticket.instrument,
                        "position_size_pct": ticket.position_size_pct,
                        "entry_level": ticket.entry_level,
                        "stop_loss": ticket.stop_loss,
                        "take_profit": ticket.take_profit,
                        "risk_budget_consumed_bps": ticket.risk_budget_consumed_bps,
                    },
                    market_data={
                        "current_price": ticket.entry_level or 0.0,
                        "atr_20": 0.0,
                        "support_levels": [],
                        "resistance_levels": [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "existing_positions": [],
                        "kill_criteria_have_hooks": True,
                    },
                )
                ticket.pre_trade_checks = checklist_report
                await _say(_format_checklist_results(ticket))

                if not checklist_report.all_blockers_passed:
                    await _say("\n存在阻塞项未通过。请修改后重试，或输入'强制确认'覆盖。")
                    session.state = "AWAITING_USER_INPUT"
                    continue

                # All blockers passed → confirm
                session.state = "CONFIRMING"
                lines = [
                    "── 最终决策票据 ──",
                    f"方向: {ticket.direction}  标的: {ticket.instrument}",
                    f"仓位: {ticket.position_size_pct:.2%}  入场: {ticket.entry_level or '市价'}",
                    f"止损: {ticket.stop_loss}  止盈: {ticket.take_profit or '未设置'}",
                    f"风险预算: {ticket.risk_budget_consumed_bps:.0f} bps  信心: {ticket.conviction_score}  最大持有: {ticket.max_hold_days}天",
                ]
                await _say("\n" + "\n".join(lines))
                await _say("\n确认执行？(输入'确定'确认，'修改'返回)")
                final_confirm = await _ask("> ")
                if final_confirm.strip():
                    session.turns += 1
                    await _log("USER", "final_confirmation", "user_free_text", final_confirm)
                if _CONFIRMATION_RE.search(final_confirm) and not _MODIFY_RE.search(final_confirm):
                    session.outcome = "EXECUTED"
                    session.state = "EXECUTED"
                    await _say("\n决策票据已确认。执行中...")
                    await _log("AI", "decision_executed", "system_decision",
                               "Ticket executed",
                               {"direction": ticket.direction, "instrument": ticket.instrument,
                                "position_size_pct": ticket.position_size_pct,
                                "stop_loss": ticket.stop_loss})
                    break
                session.state = "AWAITING_USER_INPUT"
                continue

            # ── Default: re-display values ─────────────────────────────────
            await _say("可修改字段: 入场/止损/止盈/标的/仓位/风险/催化剂/最大持有")
            await _say(f"当前: instrument={ticket.instrument}, stop={ticket.stop_loss}, "
                       f"entry={ticket.entry_level}, tp={ticket.take_profit}")

        if session.turns >= _TURN_LIMIT and session.outcome == "DEFERRED":
            await _say(f"[已达上限] 决策票据已保存为延迟状态。")
            await _log("AI", "system", "system_decision",
                       f"Turn limit reached, deferred",
                       {"forced": True, "turn_count": session.turns})

        await archiver.log_decision({
            "outcome": session.outcome, "direction": ticket.direction,
            "instrument": ticket.instrument, "position_size_pct": ticket.position_size_pct,
            "stop_loss": ticket.stop_loss, "turn_count": session.turns,
        })

        session_mgr.save(SessionState(
            session_id=session_id, mode="full", current_gate=3,
            gate3=GateCheckpoint(gate_number=3, completed=(session.outcome == "EXECUTED"),
                data={"outcome": session.outcome, "direction": ticket.direction,
                      "instrument": ticket.instrument, "position_size_pct": ticket.position_size_pct,
                      "stop_loss": ticket.stop_loss, "turn_count": session.turns}),
        ))
        return session

    except KeyboardInterrupt:
        if session.ticket and session.outcome == "DEFERRED":
            session_mgr.save(SessionState(
                session_id=session_id, mode="full", current_gate=3,
                gate3=GateCheckpoint(gate_number=3, completed=False,
                    data={"outcome": "DEFERRED", "direction": session.ticket.direction,
                          "interrupted": True, "turn_count": session.turns}),
            ))
            await _say("\n[已中断] 当前状态已保存。")
        return session

    finally:
        await archiver.close_session()
        archive.close()
