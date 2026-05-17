"""L3 interactive technical review loop.

Compatibility adapter: wraps layer3_technical.analyze_layer3 for the
older interactive API. New callers should use layer3_technical directly.
"""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

from marketmind.pipeline.layer3_technical import (
    Layer3Result, Layer3BatchResult, analyze_layer3,
)
from marketmind.pipeline.session_context import SessionContext
from marketmind.gateway.async_client import chat_pro

logger = logging.getLogger("marketmind.pipeline.l3_interactive")


async def run_l3_interactive(
    ctx: SessionContext, cli_handler: Callable[[str], Awaitable[str]]
) -> bool:
    """Run the interactive L3 technical review loop.

    1. Calls analyze_layer3 for the selected tickers.
    2. Shows the green/yellow/red light summary.
    3. Allows the user to ask questions (answered via chat_pro).
    4. User confirms ("好") or observes ("observe").
    Returns True if proceeding, False if observing.
    """
    tickers = ctx.selected_tickers if ctx.selected_tickers else []
    if not tickers:
        print("  L3: 无待审查标的，自动 proceeding。")
        return True

    # Run technical analysis
    batch: Layer3BatchResult = await analyze_layer3(tickers)

    # Display summary
    green_count = len(batch.green_lights)
    yellow_count = len([r for r in batch.results if r.light == "yellow"])
    red_count = len(batch.red_lights)
    print(f"\n=== L3 技术面审查 ===")
    print(f"  绿灯: {green_count} | 黄灯: {yellow_count} | 红灯: {red_count}")

    for r in batch.results:
        light_emoji = {"green": "绿", "yellow": "黄", "red": "红"}.get(r.light, "?")
        print(f"  [{light_emoji}] {r.ticker} — {r.recommendation} "
              f"(R:R {r.reward_risk_ratio:.1f})")

    # Interactive loop: answer questions until confirm/observe
    while True:
        response = await cli_handler("\n确认继续 / 提问 / observe (好/问题/observe): ")
        response = response.strip().lower()

        if response == "observe":
            ctx.l3_result = batch
            return False
        if response in ("好", "y", "yes", "continue", "confirm", ""):
            ctx.l3_result = batch
            return True

        # Treat as a question — use chat_pro to answer
        try:
            result = await chat_pro(
                system_prompt="你是技术面分析师，回答用户关于技术指标的问题。简洁、准确。",
                user_prompt=f"用户提问: {response}\n\n当前标的技术面结果: {batch}",
                temperature=0.3,
                max_tokens=1024,
            )
            print(f"\n  > {result.get('content', '(无回复)')}")
        except Exception as e:
            logger.warning("chat_pro failed during L3 question: %s", e)
            print(f"\n  > 回答失败: {e}")
