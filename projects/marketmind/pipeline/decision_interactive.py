"""Decision interactive module.

Compatibility adapter for the older interactive decision flow.
New callers should use pipeline/decision.py directly.
"""
from __future__ import annotations
from typing import Callable, Awaitable

from marketmind.pipeline.session_context import SessionContext


async def run_decision_interactive(
    ctx: SessionContext, cli_handler: Callable[[str], Awaitable[str]]
) -> bool:
    """Run interactive decision confirmation. Returns True if proceeding."""
    print("\n=== 决策确认 ===")
    response = await cli_handler("是否确认并执行？(好/observe): ")
    response = response.strip().lower()
    return response not in ("observe", "no", "n", "skip")
