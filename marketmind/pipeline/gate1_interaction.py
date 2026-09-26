"""Gate 1 conversation loop — human direction confirmation for MarketMind.

First human touchpoint in the investment pipeline. Presents hypothesis cards
from Stage 0-3 analysis, collects user feedback, and confirms the investment
direction before proceeding to deeper analysis.

No LLM calls — this module orchestrates, doesn't analyze.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.pipeline.hypothesis_card import HypothesisCard, generate_cards
from marketmind.pipeline.investigation_types import HypothesisResult
from marketmind.integrity.input_guard import sanitize_for_llm_prompt
from marketmind.storage.gate_archiver import GateArchiver, GateTurn
from marketmind.storage.archivist import MarketMindArchive
from marketmind.storage.session import SessionManager, SessionState, GateCheckpoint


# ── Constants ─────────────────────────────────────────────────────────────────

_TURN_LIMIT = 50
_TURN_WARNING = 40

_OPENING_MESSAGE = "在展示分析结果前——你最近有没有在关注某个方向或话题？"
_GUIDANCE_MESSAGE = "这些是我分析出的方向。你的第一反应是什么？"

# ── Intent regex patterns ─────────────────────────────────────────────────────

_CARD_NUMBER_RE = re.compile(r"(?:第\s*)?([一二三1-3])(?:\s*个)?")
_NUMBER_MAP = {"一": 0, "二": 1, "三": 2, "1": 0, "2": 1, "3": 2}

_COMPARISON_RE = re.compile(r"对比|比较|vs|哪个更强|区别|差异")
_CONFIRMATION_RE = re.compile(r"确定|就选|我觉得|同意|确认|就这样|就这个")
_DETAIL_RE = re.compile(r"详细|深入|为什么|证据|多看|展开|具体|数据溯源")
_PIVOT_RE = re.compile(r"不对|换个|还有别的|其他|别的方向|再看看|都不")
_NEW_DIRECTION_RE = re.compile(r"怎么看|分析一下|研究一下|看看")
_PARKING_LOT_RE = re.compile(r"先放着|稍后|以后|晚点|保留|暂存|parking", re.IGNORECASE)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Gate1Session:
    session_id: str
    mode: str                      # "full" | "quick" | "catchup"
    state: str                     # current state machine state
    cards: list[HypothesisCard]    # generated hypothesis cards
    turns: int                     # conversation turn counter
    parking_lot: list[str]         # deferred topics
    selected_direction: str | None # final selection
    rejected_directions: list[str] # explicitly rejected
    started_at: str


# ── Display helpers ───────────────────────────────────────────────────────────

def _format_card_layer1(card: HypothesisCard, index: int) -> str:
    return (
        f"[{index + 1}] **{card.direction}** ({card.strength_label})\n"
        f"    {card.frequency_frame} | 预期区间: {card.expected_range}\n"
        f"    {card.one_line_thesis[:120]}\n"
        f"    风险: {card.risk_level} | 时间窗口: {card.time_window}"
    )


def _format_card_layer2(card: HypothesisCard) -> str:
    lines = [
        f"## {card.direction} — 深层分析",
        f"",
        f"**核心逻辑**: {card.one_line_thesis}",
        f"**上涨**: {card.upside_scenario[:200]}",
        f"**下行风险**: {card.downside_scenario[:200]}",
        f"**最大下行**: {card.max_downside_pct}% (概率 {card.max_downside_prob:.0%})",
        f"",
        f"### 证据层",
    ]
    for label, text in card.layer_evidence.items():
        if text:
            lines.append(f"- **{label}**: {text[:150]}")
    lines.append("")
    lines.append(f"### 熊市论证: {card.bear_case_summary[:200]}")
    lines.append("")
    lines.append("### 退出触发条件:")
    for i, trigger in enumerate(card.pre_mortem_triggers, 1):
        lines.append(f"  {i}. {trigger}")
    return "\n".join(lines)


def _format_card_layer3(card: HypothesisCard) -> str:
    lines = [
        f"## {card.direction} — 数据溯源",
        f"",
        f"**原始置信度**: {card.raw_confidence:.2f}",
        f"",
        f"### GSCP 分解:",
    ]
    for criterion, score in card.gscp_breakdown.items():
        lines.append(f"  - {criterion}: {score:.2f}")
    lines.append("")
    lines.append(f"### 数据来源: {card.source_detail[:300]}")
    return "\n".join(lines)


# ── Input parsing ─────────────────────────────────────────────────────────────

def _match_card(text: str, cards: list[HypothesisCard]) -> int | None:
    """Match user text to a card index via number patterns or direction name."""
    num_match = _CARD_NUMBER_RE.search(text)
    if num_match:
        idx = _NUMBER_MAP.get(num_match.group(1))
        if idx is not None and idx < len(cards):
            return idx
    text_lower = text.lower()
    for i, card in enumerate(cards):
        name_lower = card.direction.lower()
        tokens = re.split(r'[\s/]+', name_lower)
        for token in tokens:
            if len(token) >= 2 and token in text_lower:
                return i
    return None


def _parse_user_intent(text: str, cards: list[HypothesisCard]) -> dict:
    """Parse user input for intent. Heuristic only, no LLM.

    Returns dict with 'type' key and contextual fields.
    """
    result: dict = {"type": "unknown", "text": text}

    if _PARKING_LOT_RE.search(text):
        result["type"] = "parking_lot"
        return result

    if _PIVOT_RE.search(text):
        result["type"] = "pivot"
        return result

    if _COMPARISON_RE.search(text):
        result["type"] = "compare"
        matched = []
        for i in range(len(cards)):
            for token in cards[i].direction.lower().split():
                if len(token) >= 2 and token in text.lower():
                    matched.append(i)
                    break
        result["card_indices"] = matched if len(matched) >= 2 else ([0, 1] if len(cards) >= 2 else ([0] if cards else []))
        return result

    if _CONFIRMATION_RE.search(text):
        result["type"] = "confirm"
        matched = _match_card(text, cards)
        if matched is not None:
            result["card_index"] = matched
        return result

    if _DETAIL_RE.search(text):
        result["type"] = "detail"
        matched = _match_card(text, cards)
        if matched is not None:
            result["card_index"] = matched
        return result

    if _NEW_DIRECTION_RE.search(text):
        result["type"] = "new_direction"
        result["direction_text"] = text
        return result

    matched = _match_card(text, cards)
    if matched is not None:
        result["type"] = "select"
        result["card_index"] = matched
        return result

    return result


# ── Main orchestration ────────────────────────────────────────────────────────

async def run_gate1(
    hypotheses: list[HypothesisResult],
    session_id: str,
    mode: str = "full",
    io_handler: callable = None,
    status_handler: callable = None,
) -> Gate1Session:
    """Run the Gate 1 direction confirmation conversation loop.

    Args:
        hypotheses: Investigation results from the HVR loop.
        session_id: Stable session identifier.
        mode: "full" (top-3), "quick" (top-1), "catchup" (top-3).
        io_handler: async function(prompt: str) -> str for user input.
        status_handler: async function(message: str) for status display.

    Returns:
        Gate1Session with final state, selection, and conversation log.
    """
    archive = MarketMindArchive()
    archiver = GateArchiver(archive)
    await archiver.start_session(gate_number=1, session_id=session_id)

    session_mgr = SessionManager()

    session = Gate1Session(
        session_id=session_id,
        mode=mode,
        state="START",
        cards=[],
        turns=0,
        parking_lot=[],
        selected_direction=None,
        rejected_directions=[],
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
        sanitized = sanitize_for_llm_prompt(text, source="gate1_chat")
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
        # ── Step 1: User-agenda-first opening ───────────────────────────
        session.state = "USER_AGENDA_OPENING"
        await _log("AI", "system", "ai_response", _OPENING_MESSAGE)
        user_agenda = await _ask(_OPENING_MESSAGE)
        session.turns += 1
        await _log("USER", "agenda_response", "user_free_text", user_agenda)

        # ── Step 2: Generate and present cards ──────────────────────────
        session.cards = await generate_cards(hypotheses, mode, session_id)
        session.state = "PRESENTING_CARDS"

        await _say("\n── 分析方向 ──")
        for i, card in enumerate(session.cards):
            await _say(_format_card_layer1(card, i))
            await _say("")

        # Scout monitor AFTER cards
        await _say("── 侦察监测 ──")
        await _say(f"共处理 {len(hypotheses)} 个假设，筛选 {len(session.cards)} 个供审阅。")
        await _say("")

        await _log("AI", "hypothesis_card", "structured_data",
                   f"Presented {len(session.cards)} cards",
                   {"card_count": len(session.cards),
                    "directions": [c.direction for c in session.cards]})

        # ── Step 3: Main interaction loop ───────────────────────────────
        session.state = "AWAITING_USER_CHOICE"
        await _say(_GUIDANCE_MESSAGE)

        while session.turns < _TURN_LIMIT:
            user_input = await _ask("> ")
            if not user_input or not user_input.strip():
                continue

            session.turns += 1
            await _log("USER", "direction_response", "user_free_text", user_input)

            if session.turns >= _TURN_WARNING:
                remaining = _TURN_LIMIT - session.turns
                await _say(f"[提示] 已进行 {session.turns}/{_TURN_LIMIT} 轮，剩余 {remaining} 轮。")

            intent = _parse_user_intent(user_input, session.cards)

            if intent["type"] == "pivot":
                await _say("理解。你想关注什么方向？我可以调整分析重点。")
                session.state = "AWAITING_USER_CHOICE"

            elif intent["type"] == "parking_lot":
                session.parking_lot.append(user_input[:200])
                await _say(f"[已暂存 #{len(session.parking_lot)}] 继续。")
                await _log("AI", "system", "system_decision",
                           f"Parking lot add: {user_input[:200]}",
                           {"parking_lot_size": len(session.parking_lot)})

            elif intent["type"] == "select":
                idx = intent.get("card_index", 0)
                if idx < len(session.cards):
                    card = session.cards[idx]
                    session.state = "EXPLORING_DIRECTION"
                    await _say(_format_card_layer2(card))
                    await _log("AI", "bear_case_detail", "ai_response",
                               f"Layer 2 for: {card.direction}",
                               {"direction": card.direction, "layer": 2})
                    await _say("需要看数据溯源吗？(回复'详细'/'证据'查看)")

            elif intent["type"] == "detail":
                idx = intent.get("card_index", 0)
                if idx < len(session.cards):
                    card = session.cards[idx]
                    await _say(_format_card_layer3(card))
                    await _log("AI", "bear_case_detail", "ai_response",
                               f"Layer 3 for: {card.direction}",
                               {"direction": card.direction, "layer": 3})

            elif intent["type"] == "compare":
                indices = intent.get("card_indices", [0, 1])
                valid = [i for i in indices if i < len(session.cards)]
                if len(valid) >= 2:
                    session.state = "COMPARING_DIRECTIONS"
                    await _say(f"对比 {session.cards[valid[0]].direction} vs {session.cards[valid[1]].direction}:")
                    for vi in valid:
                        c = session.cards[vi]
                        await _say(f"  {c.direction}: {c.strength_label} | {c.frequency_frame} | 下行{c.max_downside_pct}%")
                    await _log("AI", "system", "ai_response",
                               f"Compared: {[session.cards[i].direction for i in valid]}")

            elif intent["type"] == "new_direction":
                session.state = "SCOPE_DISAMBIGUATION"
                await _say("理解。让我确认范围：此方向是否在现有能力范围内？与已筛选方向有无重叠？")
                await _say(f"请确认: \"{user_input[:100]}\" (回复'确定'继续分析)")
                await _log("AI", "system", "ai_response", "Scope disambiguation",
                           {"proposed_direction": user_input[:200]})

                clarification = await _ask("> ")
                if clarification.strip():
                    session.turns += 1
                    await _log("USER", "scope_clarification", "user_free_text", clarification)

                session.state = "ANALYZING_NEW_DIRECTION"
                await _say(f"[已记录新方向: {user_input[:100]}]")
                await _log("AI", "system", "system_decision",
                           f"New direction: {user_input[:200]}",
                           {"new_direction": user_input[:200]})

            elif intent["type"] == "confirm":
                session.state = "CONFIRMING"
                matched_idx = intent.get("card_index")
                if matched_idx is not None and matched_idx < len(session.cards):
                    session.selected_direction = session.cards[matched_idx].direction
                elif session.cards:
                    session.selected_direction = session.cards[0].direction

                await _say(f"已确认方向: {session.selected_direction}")
                await _log("AI", "direction_selection", "system_decision",
                           f"Confirmed: {session.selected_direction}",
                           {"selected_direction": session.selected_direction})

                if session.parking_lot:
                    await _say(f"\n── 待议清单 ({len(session.parking_lot)} 项) ──")
                    for i, item in enumerate(session.parking_lot, 1):
                        await _say(f"  {i}. {item[:120]}")
                    await _say("以上话题可在下个会话中优先讨论。")

                break

            else:
                await _say("理解。你可以：选择方向深入了解 / 对比两个方向 / 提出新方向 / 直接确认。")
                session.state = "AWAITING_USER_CHOICE"

        # ── Force close at limit ────────────────────────────────────────
        if session.turns >= _TURN_LIMIT and not session.selected_direction:
            if session.cards:
                session.selected_direction = session.cards[0].direction
            await _say(f"[已达上限] 默认选择: {session.selected_direction}")
            await _log("AI", "system", "system_decision",
                       f"Turn limit reached, default: {session.selected_direction}",
                       {"forced": True, "turn_count": session.turns})

        # ── Archive decision ────────────────────────────────────────────
        await archiver.log_decision({
            "direction": session.selected_direction,
            "turn_count": session.turns,
            "parking_lot": session.parking_lot,
            "rejected": session.rejected_directions,
        })

        # ── Save checkpoint ─────────────────────────────────────────────
        session_mgr.save(SessionState(
            session_id=session_id,
            mode=session.mode,
            current_gate=1,
            gate1=GateCheckpoint(
                gate_number=1,
                completed=True,
                data={
                    "selected_direction": session.selected_direction,
                    "turn_count": session.turns,
                    "mode": session.mode,
                    "parking_lot": session.parking_lot,
                    "rejected": session.rejected_directions,
                },
            ),
        ))

        return session

    except KeyboardInterrupt:
        if session.selected_direction:
            session_mgr.save(SessionState(
                session_id=session_id,
                mode=session.mode,
                current_gate=1,
                gate1=GateCheckpoint(
                    gate_number=1,
                    completed=False,
                    data={
                        "selected_direction": session.selected_direction,
                        "turn_count": session.turns,
                        "interrupted": True,
                        "parking_lot": session.parking_lot,
                    },
                ),
            ))
            await _say("\n[已中断] 当前状态已保存。")
        return session

    finally:
        await archiver.close_session()
