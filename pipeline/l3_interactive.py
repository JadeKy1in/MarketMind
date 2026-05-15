"""L3 Interactive — technical analysis + review loop (Phase 1: LOWEST density).

Extracted from app.py per Red Team-approved refactoring plan.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.layer3_technical import analyze_layer3, Layer3BatchResult
from marketmind.pipeline.session_context import SessionContext

logger = logging.getLogger("marketmind.pipeline.l3_interactive")


async def run_l3_interactive(ctx: SessionContext, cli_handler) -> bool:
    """Run L3 technical analysis + interactive review loop.

    Args:
        ctx: Session context (reads selected_tickers; writes l3_result)
        cli_handler: async callable(str) -> str for user input

    Returns:
        True if user confirmed (proceed to Decision), False if user chose to observe
    """
    selected_tickers = ctx.selected_tickers

    # Run L3 analysis
    try:
        l3_result = await analyze_layer3(selected_tickers, {})
    except Exception as e:
        logger.warning("L3 analysis failed: %s", e)
        l3_result = Layer3BatchResult()

    ctx.l3_result = l3_result

    green_lights = l3_result.green_lights if hasattr(l3_result, 'green_lights') else []
    results = l3_result.results if hasattr(l3_result, 'results') else []

    # Display results
    print(f"\n{'─'*60}")
    print(f"  [L3] 技术面分析完成 — 共分析 {len(results)} 个标的")

    if green_lights:
        print(f"\n  绿灯标的 (入场信号确认):")
        print(f"  {'标的':<6} {'入场区间':<16} {'止损':<8} {'目标':<8} {'R:R':<6} {'持有天数':<8}")
        print(f"  {'─'*58}")
        for g in green_lights[:10]:
            entry = f"${g.entry_zone_low:.1f}-${g.entry_zone_high:.1f}" if g.entry_zone_low else "N/A"
            stop = f"${g.stop_loss:.1f}" if g.stop_loss else "N/A"
            target = f"${g.target_price:.1f}" if g.target_price else "N/A"
            rr = f"1:{g.reward_risk_ratio:.1f}" if g.reward_risk_ratio else "N/A"
            days = str(g.max_hold_days) if g.max_hold_days else "N/A"
            print(f"  {g.ticker:<6} {entry:<16} {stop:<8} {target:<8} {rr:<6} {days:<8}")

    yellow_red = [r for r in results if r.light in ("yellow", "red")] if hasattr(l3_result, 'results') else []
    if yellow_red:
        print(f"\n  黄/红灯标的 ({len(yellow_red)}): {', '.join(r.ticker for r in yellow_red[:8])}")
    if not green_lights:
        print(f"\n  无绿灯标的 — 技术面未发现入场信号")

    print(f"  {'─'*60}")

    # Interaction loop
    l3_confirmed = False
    while not l3_confirmed:
        if green_lights:
            print(f"  输入'好'进入决策 | 输入'observe'观望 | 输入标的代码查看详情 | 或输入问题")
        else:
            print(f"  输入'好'进入决策 | 输入'observe'观望 | 或输入问题（如'为什么没信号'）")
        l3_response = await cli_handler("> ")
        l3_text = l3_response.strip().lower() if l3_response else ""
        if not l3_text:
            continue

        if l3_text in ("observe", "等等看", "等等", "观望", "跳过", "不买", "skip", "pass", "wait", "先不看"):
            print("\n同意——今日观望。现金也是一种仓位。\n")
            return False

        if l3_text in ("好", "ok", "yes", "行", "可以", "go", "sure"):
            l3_confirmed = True
            break

        # Check for ticker detail query (single or comma/space separated)
        queries = [t.strip().upper() for t in l3_text.replace(",", " ").split() if t.strip()]
        if queries:
            found_any = False
            for q in queries[:5]:
                found = [r for r in results if r.ticker.upper() == q] if results else []
                if found:
                    r = found[0]
                    print(f"  {r.ticker}: light={r.light} entry=${r.entry_zone_low:.1f}-${r.entry_zone_high:.1f} "
                          f"stop=${r.stop_loss:.1f} target=${r.target_price:.1f} R:R=1:{r.reward_risk_ratio:.1f}")
                    found_any = True
            if found_any:
                continue

        # User asked a question — use AI to respond
        await _handle_l3_question(l3_text, green_lights, yellow_red, results)

    return True


async def _handle_l3_question(user_text: str, green_lights: list, yellow_red: list, results: list) -> None:
    """Handle free-form user questions during L3 review."""
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    summary = f"绿灯{len(green_lights)}个, 黄/红灯{len(yellow_red)}个" if results else "无数据"

    print("  ...", end="", flush=True)
    try:
        resp = await chat_pro(
            system_prompt=(
                f"你是技术面分析师。用户正在查看L3分析结果。今天是{today}。用中文，简洁回答。\n"
                f"L3结果摘要: {summary}\n"
                f"如果用户问'为什么没有信号'，解释：可能原因包括价格在阻力位附近、"
                f"日线结构破坏、200周均线下方、或缺乏明确入场区间。"
                f"这不是失败——现金持仓也是一种有效策略。"
            ),
            user_prompt=f"用户问题: {user_text}\n\n直接回答。不超过150字。",
            temperature=0.3,
            max_tokens=512, reasoning_effort="minimal",
        )
        reply = resp.get("content", "抱歉，无法处理。输入'好'进入决策或'observe'观望。")
    except Exception:
        reply = "回复生成失败。输入'好'进入决策或'observe'观望。"
    print(f"\n\n{reply}")
