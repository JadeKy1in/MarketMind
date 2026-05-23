"""L1 Tool Executor — Phase G AI-initiated tool calls.

Extracted from layer1_interactive.py per modular architecture rules (§3.1).
Handles parsing <tool> tags from AI output, executing tools via registry,
and injecting results back into the discussion history.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.layer1_interactive import InteractiveState

logger = logging.getLogger("marketmind.pipeline.l1_tool_executor")


async def execute_ai_tool_calls(
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
    from marketmind.pipeline.l1_tools import (
        inject_tool_results_into_prompt,
        extract_numbers_from_tool_result,
        ToolResult,
    )
    from marketmind.pipeline.output_filter import update_whitelist
    from marketmind.pipeline.l1_display import safe_print as _safe_print

    registry = state.tools.tool_registry
    if registry is None:
        return False

    tool_calls = registry.parse_tool_calls(ai_text)
    if not tool_calls:
        return False

    clean_text = strip_tool_tags(ai_text)
    tool_descriptions = [f"{name}({arg})" for name, arg in tool_calls]
    print(f"  [工具调用] {', '.join(tool_descriptions)}")
    if clean_text.strip():
        _safe_print(f"\n{clean_text}")

    print(f"  [运行工具中...]", end="", flush=True)

    async def _execute_one(name: str, arg: str):
        try:
            return await registry.execute(name, arg)
        except Exception as e:
            logger.warning("Tool execution failed: %s(%s): %s", name, arg, e)
            return ToolResult(
                tool_name=name, query=arg, data={},
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    results = await asyncio.gather(
        *[_execute_one(name, arg) for name, arg in tool_calls]
    )

    valid_results = [r for r in results if r is not None]

    state.tools.tool_results.extend(valid_results)
    state.tools.calls_used += len(valid_results)

    for tr in valid_results:
        new_nums = extract_numbers_from_tool_result(tr)
        if new_nums:
            state.source_numbers = update_whitelist(state.source_numbers, new_nums)

    for tr in valid_results:
        tool_msg = f"[TOOL RESULT] {tr.to_prompt_text()}"
        discussion_history.append({"role": "assistant", "content": tool_msg})

    print(f" 完成 ({len(valid_results)}个)", flush=True)
    return len(valid_results) > 0


async def execute_ai_tool_calls_mock(
    ai_text: str,
    state: "InteractiveState",
    discussion_history: list[dict],
) -> bool:
    """Phase G mock mode: parse tool calls and inject canned responses (Red Team A11)."""
    from marketmind.pipeline.l1_tools import ToolResult
    from marketmind.pipeline.l1_display import safe_print as _safe_print
    from marketmind.pipeline.l1_mock_data import (
        MOCK_FUNDAMENTALS_AAPL,
        MOCK_NEWS_SEARCH_RESULTS,
        MOCK_ELITE_OPINIONS,
    )

    registry = state.tools.tool_registry
    if registry is None:
        return False

    tool_calls = registry.parse_tool_calls(ai_text)
    if not tool_calls:
        return False

    clean_text = strip_tool_tags(ai_text)
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
        discussion_history.append({
            "role": "assistant",
            "content": f"[TOOL RESULT-MOCK] {result.to_prompt_text()}",
        })
        registry.tool_calls.append(result)

    return len(tool_calls) > 0


def strip_tool_tags(text: str) -> str:
    """Remove <tool>...</tool> tags from text for clean display."""
    import re
    return re.sub(r'<tool>[^<]*</tool>', '', text, flags=re.IGNORECASE).strip()
