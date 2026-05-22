"""L1 Interactive Narrative Analysis — Socratic multi-turn protocol (Phase C H2).

Replaces single-shot analyze_layer1() with a multi-turn dialogue:
  1. Main AI receives signals + news → deep internal analysis → archive
  2. Presents concise conclusions to user (ABC format: conclusion + logic + evidence + gaps)
  3. User challenges, asks questions, provides ideas
  4. Main AI defends with data, evaluates user input independently (non-sycophantic)
  5. Directed data mining via Flash searches (user-directed or AI-suggested)
  6. AI proposes "enough info" → user confirms → proceed to L2/L3
  7. Or both agree to observe → skip L2/L3 (no missed_path)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.gateway.async_client import chat_pro, chat_flash
from marketmind.pipeline.layer1_narrative import Layer1Result, FlashSignal, _format_signals, _parse_layer1_response
from marketmind.shadows.shadow_agent import defang_text

logger = logging.getLogger("marketmind.pipeline.layer1_interactive")


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class ToolState:
    """Phase G: L1 tool invocation tracking (sub-dataclass per Red Team A12)."""
    calls_used: int = 0
    tool_results: list[Any] = field(default_factory=list)  # list[ToolResult]
    fact_broadcast: list[dict] = field(default_factory=list)  # accumulated facts for shadow broadcast
    tool_registry: Any = None  # L1ToolRegistry (injected by app.py)
    gnews_remaining: int = 10  # mirrors MAX_GNEWS_CALLS_PER_SESSION for display
    yfinance_remaining: int = 50  # mirrors MAX_YFINANCE_CALLS_HARD for display


@dataclass
class InteractiveState:
    """Mutable state tracked across L1 dialogue turns."""
    turn: int = 0
    deep_analysis: str = ""              # full archived analysis
    concise_summary: str = ""            # last concise report to user
    evidence_chain: list[str] = field(default_factory=list)
    info_gaps: list[str] = field(default_factory=list)
    confirmed_direction: str = ""        # investment direction (if confirmed)
    user_ideas: list[str] = field(default_factory=list)
    ai_evaluations: list[str] = field(default_factory=list)
    data_mining_results: list[str] = field(default_factory=list)
    forecast_predictions: list[dict] = field(default_factory=list)  # directional scenarios: dominant, alternative, tail-risk
    stage: str = "initial"              # initial | discussing | mining | confirming | done
    should_observe: bool = False         # both agree to skip trading today
    elite_registry: Any = None            # EliteRegistry (injected by app.py)
    tools: ToolState = field(default_factory=ToolState)  # Phase G: tool invocation state
    source_numbers: set[float] = field(default_factory=set)  # Phase G: dynamic whitelist for output_filter



from marketmind.pipeline.l1_prompts import (
    L1_DEEP_ANALYSIS_PROMPT, L1_DISCUSSION_PROMPT, L1_DATA_MINING_PROMPT,
)
from marketmind.pipeline.l1_mock_data import (
    MOCK_DEEP_ANALYSIS, MOCK_DISCUSSION_RESPONSE, MOCK_MINING_RESPONSE,
    MOCK_FUNDAMENTALS_AAPL, MOCK_NEWS_SEARCH_RESULTS, MOCK_ELITE_OPINIONS,
)

# ── Interactive L1 Pipeline ─────────────────────────────────────────────────

async def run_l1_interactive(
    signals: list[FlashSignal],
    news_items: list,
    user_input_handler=None,  # async callable(str) -> str
    mock: bool = False,       # use canned responses, no API calls
    elite_registry=None,      # EliteRegistry (injected by app.py)
    tool_registry=None,        # L1ToolRegistry (Phase G, injected by app.py)
    **kwargs,                 # extensible: insider_items, etc.
) -> tuple[Layer1Result, bool, dict]:
    """Run L1 as an interactive Socratic dialogue.

    Args:
        signals: Preprocessed Flash signals
        news_items: Raw news articles
        user_input_handler: Async function that presents text to user and returns their response.
                           If None, falls back to a single-shot non-interactive analysis.
        mock: If True, use hardcoded responses instead of calling LLM APIs.
        tool_registry: Optional L1ToolRegistry for AI-initiated tool calls (Phase G).

    Returns:
        (Layer1Result, should_observe, session_data)
        session_data = {"user_ideas": [...], "discussion_text": "...", "fact_broadcast": [...]}
    """
    state = InteractiveState(elite_registry=elite_registry)
    if tool_registry is not None:
        state.tools.tool_registry = tool_registry
        if elite_registry is not None:
            tool_registry.set_elite_registry(elite_registry)

    # Inject current date — factual only, no meta-commentary that triggers cutoff thinking
    today_str = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    date_context = (
        f"\n\nTODAY IS {today_str}."
        f" The provided NEWS HEADLINES and MARKET SIGNALS are real-time data as of this date."
        f" Your analysis must be grounded in this provided information."
        f" Do NOT reference your training data as a limitation — the news and signals ARE your data."
    )

    # ── Step 1: Deep analysis + concise summary ──────────────────────────
    # Build analysis text from signals if available, otherwise from raw news
    # CRITICAL-2: insider_items + social_items bypass Flash and are formatted alongside signals
    insider_items = kwargs.get("insider_items", []) if kwargs else []
    social_items = kwargs.get("social_items", []) if kwargs else []
    if signals:
        signal_text = _format_signals(signals, news_items, insider_items=insider_items, social_items=social_items)
    elif news_items:
        # Fallback: use raw news headlines when Flash preprocessing produced no signals
        headlines = [f"[{getattr(n, 'source_name', 'news')}] {getattr(n, 'title', '')}"
                     for n in news_items[:30]]
        signal_text = "News headlines (no preprocessed signals available):\n" + "\n".join(f"- {h}" for h in headlines)
    else:
        # No data at all — use mock news to keep interactive test working
        # Generic themes only — avoid hardcoding specific events that go stale
        print(f"\n[L1] 无可用新闻数据（{today_str}），使用测试模拟信号继续。")
        signal_text = f"Mock market signals for interactive testing ({today_str}):\n"
        signal_text += "- [Gateway] Central bank policy decision: no change in benchmark rate\n"
        signal_text += "- [Commodity] Energy markets volatile on geopolitical developments\n"
        signal_text += "- [Tech] Sector earnings broadly in line; AI demand remains a key theme\n"
        signal_text += "- [Macro] Mixed economic data from major economies\n"
        signal_text += "- [Trade] Export data varies by region; currency markets fluctuate\n"

    deep_result = await chat_pro(
        system_prompt=L1_DEEP_ANALYSIS_PROMPT + date_context,
        user_prompt=f"Analyze these market signals for narrative structure:\n\n{defang_text(signal_text)}",
        temperature=0.3,
        max_tokens=8192,
    ) if not mock else {"content": MOCK_DEEP_ANALYSIS}

    raw_content = deep_result.get("content", "")
    # P0: filter out meta-commentary + fabricated numbers
    from marketmind.pipeline.output_filter import strip_meta_commentary
    state.deep_analysis = strip_meta_commentary(raw_content)
    state.stage = "discussing"

    # Extract concise summary for user (second half of the output)
    concise_summary = _extract_concise_summary(state.deep_analysis)
    if _response_looks_truncated(concise_summary) and len(state.deep_analysis) > 500:
        concise_summary += "\n\n[注意：简报可能因长度限制被截断。可在讨论中要求AI补充遗漏部分。]"
    state.concise_summary = concise_summary

    # ── Step 1.5: Attempt to parse structured result for backward compat ──
    l1_result = _try_parse_l1_result(state.deep_analysis)

    # ── Step 2: If interactive, present to user ──────────────────────────
    if user_input_handler is None:
        # Non-interactive mode: return what we have
        l1_result.raw_analysis = state.deep_analysis
        return l1_result, False, {"user_ideas": [], "discussion_text": ""}

    # Present concise summary to user
    print(f"\n{'='*60}")
    _safe_print(concise_summary)
    print(f"{'='*60}")
    print(f"\n你可以：提问 / 质疑推理 / 建议探索方向 / 回复'好'进入L2 / 回复'observe'观望")
    print(f"  输入 'elite' 查看可用的ELITE领域专家影子")

    # ── Step 3: Discussion loop ──────────────────────────────────────────
    discussion_history: list[dict] = [
        {"role": "assistant", "content": f"Concise Summary:\n{concise_summary}"}
    ]

    while state.stage != "done":
        state.turn += 1

        # Get user input — handler manages its own prompt
        user_response = await user_input_handler("> ")
        if not user_response or not user_response.strip():
            continue

        user_text = user_response.strip()

        # Handle proceed to L2 — only trigger on short confirmations, not casual mentions
        # Exact short confirmations (<=5 chars in Chinese, single words in English)
        short_confirm = user_text.strip().lower()
        is_short_confirm = short_confirm in (
            "好", "好的", "ok", "okay", "yes", "行", "可以", "同意", "继续",
            "开始", "没问题", "go", "sure", "yep", "yeah",
        )
        # Longer confirmations that explicitly reference L2 or proceeding
        is_explicit_proceed = short_confirm in (
            "proceed", "go ahead", "进入l2", "进入L2", "进入 L2", "下一步",
            "就这么办", "lets go", "let's go", "done", "enough",
        ) or short_confirm.startswith("进入l2") or short_confirm.startswith("进入 l2")
        # DO NOT match "好，那我们再看看..." — those are conversation, not confirmation

        if is_short_confirm or is_explicit_proceed:
            state.stage = "done"
            state.confirmed_direction = concise_summary[:200]
            print("\n[L1] 进入 L2 标的筛选...\n")
            break

        if short_confirm in ("observe", "等等看", "等等", "观望", "跳过", "不买",
                              "skip", "pass", "wait", "hold", "先不看"):
            state.should_observe = True
            state.stage = "done"
            print(
                "\n[L1] 同意——今日观望。现金也是一种仓位。\n"
            )
            break

        # Handle ELITE shadow query
        if user_text.lower().startswith("elite") or user_text.lower() == "影子":
            await _handle_elite_query(user_text, state)
            continue

        # Check if user wants data mining
        if _is_data_mining_request(user_text):
            state.stage = "mining"
            search_results = await _execute_data_mining(user_text, state)
            state.data_mining_results.append(search_results)

            # Feed results back to AI for analysis
            mining_prompt = L1_DATA_MINING_PROMPT.format(direction=user_text[:200])
            analysis = await chat_pro(
                system_prompt=mining_prompt + date_context,
                user_prompt=f"Search results:\n{search_results}\n\nOriginal hypothesis: {defang_text(user_text)}\n\nAnalyze:",
                temperature=0.3,
                max_tokens=4096,
            ) if not mock else {"content": MOCK_MINING_RESPONSE}
            ai_response = analysis.get("content", "Analysis unavailable.")
            if _response_looks_truncated(ai_response):
                ai_response += ("\n\n[注意：数据挖掘结果可能因长度限制被截断。"
                                "可输入'继续说'让AI补充遗漏的方向。]")

            _safe_print(f"\n[L1 Data Mining]\n{ai_response}")
            discussion_history.append({"role": "assistant", "content": ai_response})
            state.stage = "discussing"
            continue

        # Normal discussion turn
        discussion_history.append({"role": "user", "content": user_text})
        state.user_ideas.append(user_text)

        # Build discussion prompt
        history_text = _format_history(discussion_history[-20:])  # last 10 exchanges (was 3 — too little context)
        discussion_prompt = (
            f"## Discussion Context\n{history_text}\n\n"
            f"## Investor's Latest Point\n{defang_text(user_text)}\n\n"
            f"Respond following the Rules of Engagement. Be direct, evidence-based, "
            f"and label your confidence levels."
        )

        # Show "thinking" indicator
        print("  ...", end="", flush=True)
        try:
            ai_response_result = await chat_pro(
                system_prompt=L1_DISCUSSION_PROMPT + date_context,
                user_prompt=discussion_prompt,
                temperature=0.3,
                max_tokens=4096,
            ) if not mock else {"content": MOCK_DISCUSSION_RESPONSE}
            ai_response = ai_response_result.get("content", "")
            ai_response = strip_meta_commentary(ai_response)
            if not ai_response.strip():
                ai_response = "[AI 返回了空回复，可能是网络波动。请重试你的问题。]"
            elif _response_looks_truncated(ai_response):
                ai_response += ("\n\n[注意：AI回复可能因长度限制被截断。"
                                "可输入'继续说'让AI补充，或输入'好'进入L2。]")
        except Exception as e:
            logger.warning("L1 discussion LLM call failed: %s", e)
            ai_response = f"[系统提示：AI 响应失败，请重试或输入'好'进入 L2]"

        # ── Phase G: Check for AI-initiated tool calls ──────────────────
        tool_calls_executed = False
        if state.tools.tool_registry is not None and not mock:
            tool_calls_executed = await _execute_ai_tool_calls(
                ai_response, state, discussion_history, date_context, mock
            )
        elif state.tools.tool_registry is not None and mock:
            # Mock mode: parse for tool calls and inject mock responses
            tool_calls_executed = await _execute_ai_tool_calls_mock(
                ai_response, state, discussion_history
            )

        # Re-generate with tool results if tools were executed
        if tool_calls_executed:
            try:
                second_prompt = discussion_prompt
                # Inject tool results into the prompt (bypasses _format_history)
                from marketmind.pipeline.l1_tools import inject_tool_results_into_prompt
                second_prompt = inject_tool_results_into_prompt(
                    second_prompt, state.tools.tool_results[-3:]  # last 3 max
                )
                print("  ...", end="", flush=True)
                ai_response_result = await chat_pro(
                    system_prompt=L1_DISCUSSION_PROMPT + date_context,
                    user_prompt=second_prompt,
                    temperature=0.3,
                    max_tokens=4096,
                ) if not mock else {"content": MOCK_DISCUSSION_RESPONSE}
                ai_response = ai_response_result.get("content", "")
                ai_response = strip_meta_commentary(ai_response)
                if not ai_response.strip():
                    ai_response = "[AI 收到工具结果后返回了空回复。]"
            except Exception as e:
                logger.warning("L1 tool-followup LLM call failed: %s", e)
                ai_response = f"[AI 收到工具结果后响应失败: {e}]"

        state.ai_evaluations.append(ai_response)
        discussion_history.append({"role": "assistant", "content": ai_response})

        # Show response
        _safe_print(f"\n\n{ai_response}")
        if _ai_suggests_proceeding(ai_response):
            print(f"\n[L1] AI 认为信息已充足。输入 'proceed' 进入 L2，或继续讨论。")


    # ── Phase G: Tool usage summary ──────────────────────────────────────
    if state.tools.tool_registry is not None and state.tools.tool_registry.tool_calls:
        print(f"\n{state.tools.tool_registry.summarize()}")

    # ── Step 3.5: Red Team background bias check (H8 PMV) ────────────────
    if state.turn >= 2 and not mock:
        _run_bias_check(state)

    # ── Step 4: Return result ────────────────────────────────────────────
    # Build session data for broadcast to shadows (user ideas + chat, no main AI analysis)
    # Phase G: Include fact_broadcast data from L1 tool calls
    fact_broadcast = []
    if state.tools.tool_registry is not None:
        fact_broadcast = state.tools.tool_registry.fact_broadcast
    session_data = {
        "user_ideas": state.user_ideas,
        "discussion_text": _build_discussion_text(discussion_history),
        "fact_broadcast": fact_broadcast,
    }

    if state.should_observe:
        result = Layer1Result.empty_default()
        result.raw_analysis = state.deep_analysis
        return result, True, session_data

    # Always attach deep analysis text for L2 consumption
    l1_result.raw_analysis = state.deep_analysis
    return l1_result, False, session_data


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _execute_ai_tool_calls(
    ai_text: str,
    state: "InteractiveState",
    discussion_history: list[dict],
    date_context: str,
    mock: bool,
) -> bool:
    """Phase G: Parse AI text for <tool> tags, execute tools, inject results.

    Returns True if any tool calls were executed and results injected.
    Resolves Red Team finding 1.1 (structured tool-call protocol via delimiter pattern).
    """
    from marketmind.pipeline.l1_tools import inject_tool_results_into_prompt, extract_numbers_from_tool_result
    from marketmind.pipeline.output_filter import update_whitelist

    registry = state.tools.tool_registry
    if registry is None:
        return False

    # Parse for tool calls
    tool_calls = registry.parse_tool_calls(ai_text)
    if not tool_calls:
        return False

    # Strip tool call tags from AI text before display (they're protocol, not content)
    clean_text = _strip_tool_tags(ai_text)
    # Show what's being checked
    tool_descriptions = [f"{name}({arg})" for name, arg in tool_calls]
    print(f"\n  [工具调用] {', '.join(tool_descriptions)}")
    if clean_text.strip():
        _safe_print(f"\n{clean_text}")

    # Execute tools in parallel (Red Team A8: batch parallel execution)
    print(f"  [运行工具中...]", end="", flush=True)
    results = []
    async def _execute_one(name: str, arg: str):
        try:
            return await registry.execute(name, arg)
        except Exception as e:
            logger.warning("Tool execution failed: %s(%s): %s", name, arg, e)
            from marketmind.pipeline.l1_tools import ToolResult
            from datetime import datetime, timezone
            return ToolResult(
                tool_name=name, query=arg, data={},
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    results = await asyncio.gather(*[_execute_one(name, arg) for name, arg in tool_calls])

    # Filter out None results (rejected by caps)
    valid_results = [r for r in results if r is not None]

    # Track in state
    state.tools.tool_results.extend(valid_results)
    state.tools.calls_used += len(valid_results)

    # Update output_filter whitelist with tool-derived numbers (Red Team finding 1.2)
    for tr in valid_results:
        new_nums = extract_numbers_from_tool_result(tr)
        if new_nums:
            state.source_numbers = update_whitelist(state.source_numbers, new_nums)

    # Inject tool results as assistant message (with clear delimiter)
    # Using assistant role with [TOOL RESULT] prefix avoids role confusion (Red Team finding 6.1)
    for tr in valid_results:
        tool_msg = f"[TOOL RESULT] {tr.to_prompt_text()}"
        discussion_history.append({"role": "assistant", "content": tool_msg})

    print(f" 完成 ({len(valid_results)}个)", flush=True)
    return len(valid_results) > 0


async def _execute_ai_tool_calls_mock(
    ai_text: str,
    state: "InteractiveState",
    discussion_history: list[dict],
) -> bool:
    """Phase G mock mode: parse tool calls and inject canned responses (Red Team A11)."""
    from marketmind.pipeline.l1_tools import ToolResult
    from datetime import datetime, timezone

    registry = state.tools.tool_registry
    if registry is None:
        return False

    tool_calls = registry.parse_tool_calls(ai_text)
    if not tool_calls:
        return False

    clean_text = _strip_tool_tags(ai_text)
    tool_descriptions = [f"{name}({arg})" for name, arg in tool_calls]
    print(f"\n  [工具调用-MOCK] {', '.join(tool_descriptions)}")
    if clean_text.strip():
        _safe_print(f"\n{clean_text}")

    timestamp = datetime.now(timezone.utc).isoformat()
    for name, arg in tool_calls:
        name = name.lower()
        if name == "lookup_fundamentals":
            result = ToolResult(
                tool_name="lookup_fundamentals", query=arg.strip().upper(),
                data=MOCK_FUNDAMENTALS_AAPL, timestamp=timestamp,
            )
        elif name == "search_news":
            result = ToolResult(
                tool_name="search_news", query=arg,
                data=MOCK_NEWS_SEARCH_RESULTS, timestamp=timestamp,
            )
        elif name == "get_elite_opinion":
            result = ToolResult(
                tool_name="get_elite_opinion", query=arg,
                data=MOCK_ELITE_OPINIONS, timestamp=timestamp,
            )
        else:
            result = ToolResult(
                tool_name=name, query=arg, data={},
                error=f"Unknown tool: '{name}'",
                timestamp=timestamp,
            )
        state.tools.tool_results.append(result)
        state.tools.calls_used += 1
        discussion_history.append({"role": "assistant", "content": f"[TOOL RESULT-MOCK] {result.to_prompt_text()}"})

        # Also accumulate in registry for consistency
        registry.tool_calls.append(result)

    return len(tool_calls) > 0


def _strip_tool_tags(text: str) -> str:
    """Remove <tool>...</tool> tags from text for clean display."""
    import re
    return re.sub(r'<tool>[^<]*</tool>', '', text, flags=re.IGNORECASE).strip()


def _run_bias_check(state: InteractiveState) -> None:
    """H8 PMV: Quick bias check on L1 interaction — no LLM call, pattern-based."""
    warnings: list[str] = []

    # 1. Confirmation bias: AI agrees too readily
    agree_markers = ["同意", "支持", "合理", "有道理", "agree", "correct", "valid"]
    if state.ai_evaluations:
        agree_count = sum(
            1 for resp in state.ai_evaluations
            if any(m in resp.lower() for m in agree_markers)
        )
        if agree_count >= len(state.ai_evaluations) * 0.8 and len(state.ai_evaluations) >= 2:
            warnings.append("[偏差预警] AI 同意率过高 — 可能存在阿谀偏差 (sycophancy)")

    # 2. Counterfactual check
    counterfactual_phrases = ["如果", "万一", "反过来", "what if", "相反"]
    if state.user_ideas:
        has_cf = any(
            any(p in idea for p in counterfactual_phrases)
            for idea in state.user_ideas
        )
        if not has_cf and len(state.user_ideas) >= 2:
            warnings.append("[偏差预警] 未探索反向情景 — 建议考虑'如果判断错误会怎样'")

    if warnings:
        print(f"\n[Red Team 后台]")
        for w in warnings:
            print(f"  {w}")


async def _handle_elite_query(user_text: str, state: InteractiveState) -> None:
    """Query ELITE shadow opinions. Parses 'elite <domain>' or 'elite <name>'."""
    if state.elite_registry is None:
        print("\n[ELITE] 影子系统未初始化。请等待影子分析完成后重试。")
        return

    # Extract domain/name from user text
    # e.g., "elite energy" -> query energy domain
    #       "elite" alone -> show available domains
    query = user_text.replace("elite", "").strip()
    # Also handle "影子" Chinese variant and mixed forms
    if not query:
        query = user_text.replace("影子", "").strip()

    if not query:
        # Show available domains with ELITE shadows
        domains = list(state.elite_registry.DOMAIN_KEYWORDS.keys())
        print(f"\n[ELITE] 可用领域: {', '.join(domains[:10])}")
        print("输入 'elite <领域>' 查询影子意见（如 'elite gold'）")
        return

    # Detect domain from query
    matched_domains = state.elite_registry.detect_domain_trigger(query)
    if not matched_domains:
        domain_list = ", ".join(list(state.elite_registry.DOMAIN_KEYWORDS.keys())[:10])
        print(f"\n[ELITE] 未识别领域 '{query}'。可用领域: {domain_list}")
        return

    # Get eligible contributors
    # Need shadow_db to get achievement_tier — but EliteRegistry already has contributions registered
    # Check if any contributions exist for matched domains
    domain = matched_domains[0]
    contributions = getattr(state.elite_registry, '_contributions', {})

    # Find contributions matching the domain
    matched = []
    for sid, contrib in contributions.items():
        if contrib.domain == domain or domain in contrib.domain:
            matched.append(contrib)

    if not matched:
        print(f"\n[ELITE] {domain} 领域影子正在分析中（预计30-60秒）。请稍后再试。")
        return

    # Display shadow opinions
    print(f"\n┌─ ELITE 影子 — {domain} 领域 ─────────────────┐")
    for contrib in matched[:3]:
        name = getattr(contrib, 'shadow_name', 'unknown')
        text = getattr(contrib, 'opinion', '')[:300]
        print(f"│ [{name}] {text}")
    print(f"└{'─'*46}┘")
    print("（以上为影子独立分析意见，仅供参考）")


def _build_discussion_text(history: list[dict]) -> str:
    """Build a flattened chat transcript from discussion history (user+AI only, no main AI analysis)."""
    lines = []
    for msg in history:
        role = "用户" if msg["role"] == "user" else "分析师"
        content = msg.get("content", "")[:500]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _response_looks_truncated(text: str) -> bool:
    """Check if text appears to have been cut off mid-sentence."""
    if len(text) < 80:
        return False  # short responses are fine
    sentence_end = {'.', '!', '?', '。', '！', '？', '”', '’', ')', ']', '》'}
    return text.rstrip()[-1] not in sentence_end

def _safe_print(text: str) -> None:
    """Print text safely on Windows GBK consoles (handle emoji in AI output)."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace characters the console encoding can't represent
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding))

def _extract_concise_summary(deep_analysis: str) -> str:
    """Extract the user-facing concise summary from the deep analysis output."""
    markers = [
        "## Concise Summary",
        "## 简报格式",
        "=== CONCISE ===",
        "简明版",
        "面向用户",
        "——— 以下为面向用户的简明版",
        "**投资方向**",
        "**Direction**",
    ]
    for marker in markers:
        idx = deep_analysis.find(marker)
        if idx != -1:
            return deep_analysis[idx:].strip()
    # Fallback: return last ~1200 chars
    return deep_analysis[-1200:].strip()


def _try_parse_l1_result(text: str) -> Layer1Result:
    """Attempt to parse a structured Layer1Result from analysis text.
    Falls back to text-based extraction when JSON parsing fails (interactive mode).
    """
    try:
        return _parse_layer1_response(text)
    except Exception:
        pass  # not JSON — extract from structured text

    # Text-based extraction for interactive mode (structured text, not JSON)
    import re
    result = Layer1Result.empty_default()

    # Extract event_grade from text patterns like "grade=B" or "等级: B"
    grade_match = re.search(r'(?:event_?grade|等级|grade)\s*[=:：]\s*([A-E])', text, re.IGNORECASE)
    if grade_match:
        result.event_grade = grade_match.group(1).upper()

    # Extract sentiment direction
    if re.search(r'(?:sentiment|情绪|市场情绪).*(?:bullish|看多|乐观|risk.on)', text, re.IGNORECASE):
        result.sentiment_direction = "bullish"
    elif re.search(r'(?:sentiment|情绪|市场情绪).*(?:bearish|看空|悲观|risk.off)', text, re.IGNORECASE):
        result.sentiment_direction = "bearish"

    # Extract matrix quadrant
    quad_match = re.search(r'(?:matrix_?quadrant|象限|quadrant)\s*[=:：]\s*(\w+)', text, re.IGNORECASE)
    if quad_match:
        result.matrix_quadrant = quad_match.group(1).lower()

    # Extract price-in score
    price_match = re.search(r'(?:price.?in|已定价|price.in.score)\s*[=:：]\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if price_match:
        try:
            result.price_in_score = float(price_match.group(1))
        except ValueError:
            pass

    return result


def _is_data_mining_request(user_text: str) -> bool:
    """Detect if user is requesting data mining / Flash search."""
    mining_keywords = [
        "search for", "look up", "find data", "check", "verify",
        "what does the data say", "get data on", "research",
        "查一下", "搜索", "查查", "查", "找一下", "核实",
        "cross reference", "cross-reference",
    ]
    text_lower = user_text.lower()
    return any(kw in text_lower for kw in mining_keywords)


async def _execute_data_mining(direction: str, state: InteractiveState) -> str:
    """Execute knowledge-base data mining (training data only; no live web search)."""
    try:
        result = await chat_flash(
            system_prompt=(
                "You are a data retrieval assistant working from your training knowledge "
                "(cutoff: early 2025). You do NOT have live web search. If you do not know "
                "something or the information may be outdated, clearly state that limitation. "
                "Summarize what you know concisely."
            ),
            user_prompt=f"Find data related to: {defang_text(direction)[:500]}. Summarize key findings concisely. ",
            temperature=0.1,
            max_tokens=1024,
        )
        return result.get("content", "No search results available.")
    except Exception as e:
        logger.warning("Data mining Flash call failed: %s", e)
        return f"Search unavailable: {e}"


def _ai_suggests_proceeding(ai_response: str) -> bool:
    """Check if the AI is suggesting to proceed to L2."""
    proceed_phrases = [
        "enough information to proceed",
        "move to L2",
        "proceed to L2",
        "move to sector",
        "sufficient information",
        "we have enough",
        "shall we proceed",
        "ready for L2",
        # Chinese keywords for bilingual users
        "继续",
        "进入",
        "可以开始",
        "准备好了",
        "信息足够",
        "足够了",
    ]
    response_lower = ai_response.lower()
    return any(p in response_lower for p in proceed_phrases)


def _format_history(history: list[dict]) -> str:
    """Format recent discussion history for the prompt."""
    lines = []
    for msg in history:
        role = "Investor" if msg["role"] == "user" else "Analyst"
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"**{role}**: {content}")
    return "\n\n".join(lines)
