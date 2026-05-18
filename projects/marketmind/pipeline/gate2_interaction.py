"""Gate 2 conversation loop — signal confirmation for MarketMind.

Second human touchpoint. Runs after the full analysis pipeline (Stages 4-8).
User has already selected a direction at Gate 1. Now they receive multi-angle
results and must confirm/adjust their conviction.

No LLM calls — pure orchestration and display formatting.
No shadow/ELITE integration — main AI pipeline data only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.investigation_types import HypothesisResult
    from marketmind.pipeline.fragility_scanner import FragilityReport
    from marketmind.pipeline.regime_mapper import RegimeMapping
    from marketmind.pipeline.decision import SignalConflict
    from marketmind.pipeline.kill_monitor import KillCriterion

from marketmind.integrity.input_guard import sanitize_for_llm_prompt
from marketmind.storage.gate_archiver import GateArchiver, GateTurn
from marketmind.storage.archivist import MarketMindArchive
from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint


# ── Constants ─────────────────────────────────────────────────────────────────

_TURN_LIMIT = 50
_TURN_WARNING = 40

_DEBIASING_NOTICE = (
    "── 注意：AI置信度校准提醒 ──\n"
    "AI模型在0.75-0.85置信度区间系统性过度自信约15%。\n"
    "请将此偏差纳入你的独立判断。你的初始信心评估不受此数据影响。\n"
    "── END ──"
)

_CONVICTION_MAP: dict[str, str] = {
    "8": "STRONG", "9": "STRONG", "10": "STRONG",
    "5": "MODERATE", "6": "MODERATE", "7": "MODERATE",
    "1": "WEAK", "2": "WEAK", "3": "WEAK", "4": "WEAK",
}

# ── Intent regex patterns ─────────────────────────────────────────────────────

_CONVICTION_RE = re.compile(r"(?<!\d)([1-9]|10)(?!\d)")
_CONFIRM_RE = re.compile(r"继续|确认|确定|不变|维持|yes|continue", re.IGNORECASE)
_MODIFY_RE = re.compile(r"修改|调整|换成|换个|降低|提高", re.IGNORECASE)
_PAUSE_RE = re.compile(r"暂停|暂缓|先放|等等|稍后|park", re.IGNORECASE)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Gate2Session:
    session_id: str
    selected_direction: str
    state: str  # START → CONVICTION_FIRST → ANALYSE → CONFIRMING → END
    user_initial_conviction: str = ""  # user's raw response (e.g. "7")
    final_conviction: str = ""         # STRONG | MODERATE | WEAK
    key_risks_acknowledged: list[str] = field(default_factory=list)
    kill_criteria_confirmed: list[str] = field(default_factory=list)
    signal_conflicts_resolved: bool = False
    turns: int = 0
    outcome: str = ""              # CONTINUE | MODIFY | PAUSE
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Display helpers ───────────────────────────────────────────────────────────

def _format_evidence_summary(hypotheses: list) -> str:
    """Format L1-L4 evidence from hypothesis verification results."""
    lines = ["── 多维度分析摘要 ──", ""]
    for i, h in enumerate(hypotheses, 1):
        lines.append(f"### 方向 {i}: {h.direction} (置信度: {h.confidence:.2f})")
        if h.layer_1_narrative:
            lines.append(f"  L1 市场定价: {h.layer_1_narrative[:150]}")
        if h.layer_2_narrative:
            lines.append(f"  L2 基本面: {h.layer_2_narrative[:150]}")
        if h.layer_3_narrative:
            lines.append(f"  L3 多数据源: {h.layer_3_narrative[:150]}")
        if h.layer_4_narrative:
            lines.append(f"  L4 历史验证: {h.layer_4_narrative[:150]}")
        lines.append("")
    lines.append("── END ──")
    return "\n".join(lines)


def _format_fragility(fragility_report) -> str:
    """Format fragility report summary."""
    lines = [
        "── 系统脆弱性 ──",
        f"整体脆弱度: {fragility_report.overall_fragility_score:.2f} (0=稳定, 1=极度脆弱)",
    ]
    if fragility_report.crossed:
        lines.append("已触发阈值:")
        for alert in fragility_report.crossed:
            lines.append(f"  [CRITICAL] {alert.threshold.name if hasattr(alert.threshold, 'name') else str(alert.threshold)}")
    if fragility_report.warnings:
        lines.append("警告:")
        for alert in fragility_report.warnings:
            lines.append(f"  [WARNING] {alert.threshold.name if hasattr(alert.threshold, 'name') else str(alert.threshold)}")
    if fragility_report.staleness_warnings:
        lines.append("数据过期警告:")
        for w in fragility_report.staleness_warnings:
            lines.append(f"  - {w}")
    if fragility_report.summary:
        lines.append(f"\n{fragility_report.summary[:300]}")
    lines.append("── END ──")
    return "\n".join(lines)


def _format_regime(regime_mapping) -> str:
    """Format historical regime analogues."""
    lines = [
        "── 历史制度类比 ──",
        f"当前象限: {regime_mapping.current_quadrant}",
        "",
        "Top 3 匹配:",
    ]
    for i, m in enumerate(regime_mapping.top_analogues[:3], 1):
        lines.append(
            f"  {i}. {m.regime_name} (相似度: {m.similarity:.2f}) — "
            f"前瞻3M权益: {m.forward_3m_equity:+.1%}, "
            f"前瞻6M权益: {m.forward_6m_equity:+.1%}"
        )
    lines.append("")
    lines.append("注意: 这些是历史类比，不是预测。")
    lines.append("── END ──")
    return "\n".join(lines)


def _format_signal_conflicts(conflicts: list) -> str:
    """Format signal conflicts from decision layer."""
    if not conflicts:
        return ""
    lines = ["── 信号冲突 ──", ""]
    for i, c in enumerate(conflicts, 1):
        lines.append(f"  {i}. {c.description}")
        lines.append(f"     分歧度: {c.divergence:.2f}")
        if hasattr(c, 'resolution') and c.resolution:
            lines.append(f"     建议处理: {c.resolution}")
    lines.append("")
    lines.append("未解决的冲突将在Gate 3被阻止。")
    lines.append("── END ──")
    return "\n".join(lines)


def _format_kill_criteria(criteria: list) -> str:
    """Format kill criteria."""
    if not criteria:
        return ""
    lines = ["── 退出标准 ──", ""]
    for i, kc in enumerate(criteria, 1):
        lines.append(f"  {i}. [{kc.criterion_id}] {kc.description}")
        lines.append(f"     观察指标: {kc.observable} | 方向: {kc.threshold_direction}")
        if kc.threshold_value is not None:
            lines.append(f"     阈值: {kc.threshold_value}")
    lines.append("── END ──")
    return "\n".join(lines)


def _parse_conviction(text: str) -> str | None:
    """Extract conviction number (1-10) from user text."""
    m = _CONVICTION_RE.search(text)
    if m:
        return m.group(1)
    return None


def _parse_outcome(text: str) -> str:
    """Parse user intent as one of CONTINUE | MODIFY | PAUSE."""
    if _PAUSE_RE.search(text):
        return "PAUSE"
    if _MODIFY_RE.search(text):
        return "MODIFY"
    if _CONFIRM_RE.search(text):
        return "CONTINUE"
    return ""


# ── Main orchestration ────────────────────────────────────────────────────────

async def run_gate2(
    direction: str,
    hypotheses: list,
    fragility_report,
    regime_mapping,
    session_id: str,
    io_handler: callable,
    status_handler: callable,
    red_team_report=None,
    signal_conflicts: list | None = None,
    kill_criteria: list | None = None,
) -> Gate2Session:
    """Run the Gate 2 signal confirmation conversation loop.

    Args:
        direction: Selected direction from Gate 1.
        hypotheses: Full analysis results (HypothesisResult list).
        fragility_report: From fragility_scanner (FragilityReport).
        regime_mapping: From regime_mapper (RegimeMapping).
        session_id: Stable session identifier.
        io_handler: async function(prompt: str) -> str for user input.
        status_handler: async function(message: str) for status display.
        red_team_report: Optional Red Team report.
        signal_conflicts: Optional signal conflicts from decision layer.
        kill_criteria: Optional kill criteria from kill_monitor.

    Returns:
        Gate2Session with final conviction, outcome, and conversation log.
    """
    archive = MarketMindArchive()
    archiver = GateArchiver(archive)
    await archiver.start_session(gate_number=2, session_id=session_id)

    session_mgr = SessionManager()

    session = Gate2Session(
        session_id=session_id,
        selected_direction=direction,
        state="START",
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
        sanitized = sanitize_for_llm_prompt(text, source=f"gate2_{content_type}")
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
        # ── Step 1: CONVICTION_FIRST ─────────────────────────────────────
        # User states independent conviction BEFORE seeing any AI analysis
        session.state = "CONVICTION_FIRST"
        conviction_prompt = (
            f"在你看到AI的分析结果之前，你对「{direction}」的信心是几成？(1-10分)\n"
            f"\n"
            f"8-10 → STRONG: 完全同意，愿意承担正常风险\n"
            f"5-7  → MODERATE: 方向对，但需要谨慎\n"
            f"1-4  → WEAK: 方向可能对，但信号不够强"
        )
        await _say(conviction_prompt)
        await _log("AI", "conviction_first", "ai_response", conviction_prompt)

        raw_conviction = await _ask("> ")
        session.turns += 1
        await _log("USER", "initial_conviction", "user_free_text", raw_conviction)

        parsed = _parse_conviction(raw_conviction)
        if parsed:
            session.user_initial_conviction = parsed
        else:
            session.user_initial_conviction = raw_conviction[:50]

        # ── Step 2: ANALYSE ──────────────────────────────────────────────
        # Present multi-angle AI analysis with debiasing notice
        session.state = "ANALYSE"

        await _say("\n" + _DEBIASING_NOTICE + "\n")

        # Evidence summary from hypotheses
        evidence = _format_evidence_summary(hypotheses)
        await _say(evidence)
        await _log("AI", "evidence_summary", "structured_data", evidence,
                   {"hypothesis_count": len(hypotheses)})

        # Red Team survivors (if available)
        if red_team_report and getattr(red_team_report, 'challenges', None):
            survivors = [c for c in red_team_report.challenges
                         if getattr(c, 'severity', '') in ('critical', 'major')
                         and not getattr(c, 'verified_correct', True)]
            if survivors:
                await _say("\n── RED TEAM 挑战 ──")
                for i, c in enumerate(survivors, 1):
                    await _say(f"  {i}. [{c.severity.upper()}] {c.challenge[:200]}")
                await _say("── END ──\n")
                await _log("AI", "red_team_survivors", "structured_data",
                           f"{len(survivors)} red team challenges",
                           {"survivor_count": len(survivors)})

        # Fragility
        if fragility_report:
            await _say(_format_fragility(fragility_report))
            await _log("AI", "fragility_summary", "structured_data",
                       f"Fragility: {fragility_report.overall_fragility_score:.2f}")

        # Regime analogues
        if regime_mapping and getattr(regime_mapping, 'top_analogues', None):
            await _say(_format_regime(regime_mapping))
            await _log("AI", "regime_analogues", "structured_data",
                       f"Top analogues: {[m.regime_name for m in regime_mapping.top_analogues[:3]]}")

        # Signal conflicts
        if signal_conflicts:
            conflict_text = _format_signal_conflicts(signal_conflicts)
            if conflict_text:
                await _say(conflict_text)
                await _log("AI", "signal_conflicts", "structured_data",
                           f"{len(signal_conflicts)} conflicts",
                           {"conflict_count": len(signal_conflicts)})

        # Kill criteria
        if kill_criteria:
            kill_text = _format_kill_criteria(kill_criteria)
            if kill_text:
                await _say(kill_text)
                await _log("AI", "kill_criteria", "structured_data",
                           f"{len(kill_criteria)} kill criteria",
                           {"criteria_count": len(kill_criteria)})

        # ── Step 3: CONFIRMING ───────────────────────────────────────────
        # User adjusts conviction based on AI input
        session.state = "CONFIRMING"

        confirm_prompt = (
            f"\n看完这些分析后，你对「{direction}」的信心是？\n"
            f"(你的初始评估: {session.user_initial_conviction}/10)\n"
            f"\n"
            f"回复: 维持原判 / 调整到X分 / 暂停此方向"
        )
        await _say(confirm_prompt)
        await _log("AI", "confirmation_prompt", "ai_response", confirm_prompt)

        while session.turns < _TURN_LIMIT:
            user_input = await _ask("> ")
            if not user_input or not user_input.strip():
                continue

            session.turns += 1
            await _log("USER", "final_conviction", "user_free_text", user_input)

            if session.turns >= _TURN_WARNING:
                remaining = _TURN_LIMIT - session.turns
                await _say(f"[提示] 已进行 {session.turns}/{_TURN_LIMIT} 轮，剩余 {remaining} 轮。")

            # Parse conviction update
            new_conviction = _parse_conviction(user_input)
            if new_conviction:
                session.final_conviction = _CONVICTION_MAP.get(new_conviction, "MODERATE")
                await _log("AI", "system", "system_decision",
                           f"Conviction updated: {new_conviction} → {session.final_conviction}",
                           {"conviction_value": new_conviction, "level": session.final_conviction})

            # Parse outcome
            outcome = _parse_outcome(user_input)
            if outcome:
                session.state = "END"
                session.outcome = outcome
                # Carry forward initial conviction if user didn't restate
                if not session.final_conviction and session.user_initial_conviction:
                    session.final_conviction = _CONVICTION_MAP.get(
                        session.user_initial_conviction, "MODERATE")
                break

            if not outcome and not new_conviction:
                await _say("请回复: 维持原判 / 调整到X分 / 暂停此方向")

        # ── Force close at limit ─────────────────────────────────────────
        if session.turns >= _TURN_LIMIT and not session.outcome:
            session.outcome = "CONTINUE"
            session.final_conviction = session.final_conviction or "MODERATE"
            await _say(f"[已达上限] 默认: 继续 (信心: {session.final_conviction})")
            await _log("AI", "system", "system_decision",
                       "Turn limit reached, default CONTINUE",
                       {"forced": True, "turn_count": session.turns})

        # ── Archive decision ─────────────────────────────────────────────
        await archiver.log_decision({
            "direction": session.selected_direction,
            "initial_conviction": session.user_initial_conviction,
            "final_conviction": session.final_conviction,
            "outcome": session.outcome,
            "turn_count": session.turns,
            "risks_acknowledged": session.key_risks_acknowledged,
            "kill_criteria_confirmed": session.kill_criteria_confirmed,
            "signal_conflicts_resolved": session.signal_conflicts_resolved,
        })

        # ── Save checkpoint ──────────────────────────────────────────────
        session_mgr.save(SessionState(
            session_id=session_id,
            mode="full",
            current_gate=2,
            gate1=GateCheckpoint(
                gate_number=1,
                completed=True,
                data={"selected_direction": direction},
            ),
            gate2=GateCheckpoint(
                gate_number=2,
                completed=True,
                data={
                    "selected_direction": session.selected_direction,
                    "initial_conviction": session.user_initial_conviction,
                    "final_conviction": session.final_conviction,
                    "outcome": session.outcome,
                    "turn_count": session.turns,
                },
            ),
        ))

        return session

    except KeyboardInterrupt:
        session_mgr.save(SessionState(
            session_id=session_id,
            mode="full",
            current_gate=2,
            gate1=GateCheckpoint(
                gate_number=1,
                completed=True,
                data={"selected_direction": direction},
            ),
            gate2=GateCheckpoint(
                gate_number=2,
                completed=False,
                data={
                    "selected_direction": session.selected_direction,
                    "initial_conviction": session.user_initial_conviction,
                    "turn_count": session.turns,
                    "interrupted": True,
                },
            ),
        ))
        await _say("\n[已中断] 当前状态已保存。")
        return session

    finally:
        await archiver.close_session()
