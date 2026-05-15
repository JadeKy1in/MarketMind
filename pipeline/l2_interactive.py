"""L2 Interactive — fundamental analysis + ticker selection (Phase 1: MEDIUM-LOW density).

Extracted from app.py per Red Team-approved refactoring plan.
"""
from __future__ import annotations

import logging
import re as _re
from datetime import datetime, timezone

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.layer2_fundamental import analyze_layer2, Layer2Result
from marketmind.pipeline.session_context import SessionContext
from marketmind.shadows.shadow_agent import defang_text
from marketmind.config.ticker_labels import ticker_cn

logger = logging.getLogger("marketmind.pipeline.l2_interactive")

# In-memory cache to avoid duplicate LLM calls for identical explain/compare commands.
# Key: (user_text_normalized, raw_analysis_hash) -> response string.
# Max 32 entries; oldest evicted on overflow.
_l2_response_cache: dict[tuple, str] = {}
_L2_CACHE_MAX_SIZE = 32


def _l2_cache_key(user_text: str, l2_result: Layer2Result) -> tuple:
    """Generate a cache key from normalized user text and L2 analysis content hash."""
    analysis_hash = hash(l2_result.raw_analysis[:1200])
    return (user_text.strip().lower(), analysis_hash)


async def run_l2_interactive(ctx: SessionContext, cli_handler) -> bool:
    """Run L2 fundamental analysis + interactive ticker selection.

    Args:
        ctx: Session context (reads l1_result, l1_session; writes l2_result, selected_tickers)
        cli_handler: async callable(str) -> str for user input

    Returns:
        True if user confirmed (proceed to L3), False if user chose to observe
    """
    from marketmind.config.asset_universe import ASSET_UNIVERSE

    # H: Pass L1 discussion context to L2 (H1: _DEFANG filtered, H2: ≤500 chars)
    l1_context = ""
    if ctx.l1_session.get("discussion_text"):
        raw_context = ctx.l1_session["discussion_text"]
        l1_context = defang_text(raw_context)[:500]

    # Run L2 analysis
    try:
        l2_result = await analyze_layer2(ctx.l1_result, l1_context=l1_context if l1_context else None)
    except Exception as e:
        logger.warning("L2 analysis failed: %s", e)
        print(f"\n  [L2] 分析调用失败 — 可能是API超时或JSON解析错误。使用空结果继续。")
        l2_result = Layer2Result(
            macro_quadrant="unknown", macro_direction="unknown",
            preferred_assets=[], sector_shortlist=[], factor_scores={},
            ticker_candidates=[], ticker_weights={}, sector_momentum={},
            red_team_notes=[f"L2 analysis call failed: {e}"],
            raw_analysis="",
        )

    ctx.l2_result = l2_result

    # Display results
    print(f"\n{'─'*60}")
    print(f"  [L2] 基本面分析 — 宏观象限: {l2_result.macro_quadrant} | 方向: {l2_result.macro_direction}")
    if l2_result.sector_shortlist:
        momentum_str = ""
        if l2_result.sector_momentum:
            momentum_str = " (动量: " + ", ".join(
                f"{k}:{v}" for k, v in l2_result.sector_momentum.items()
                if k in l2_result.sector_shortlist
            ) + ")"
        print(f"  推荐板块{momentum_str}: {', '.join(l2_result.sector_shortlist[:6])}")
    if l2_result.preferred_assets:
        print(f"  偏好资产: {', '.join(l2_result.preferred_assets[:5])}")
    if l2_result.ticker_candidates:
        print(f"\n  候选标的 (宏观匹配度):")
        for tc in l2_result.ticker_candidates[:15]:
            score = l2_result.factor_scores.get(tc, 0)
            weight = l2_result.ticker_weights.get(tc, 0)
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            label = ticker_cn(tc)
            print(f"    {label:<20} 匹配:{bar} {score:.2f}  权重:{weight:.1%}")
    else:
        _display_no_candidates(l2_result)

    print(f"  {'─'*60}")

    # Interaction loop
    selected_tickers = list(l2_result.ticker_candidates[:10])
    l2_confirmed = False
    while not l2_confirmed:
        print(f"  [好/进入L3=确认] [observe=观望] [explain <代码>=查看] [compare <A> <B>=对比]")
        print(f"  [all=全选] 或输入标的代码 | 或输入任何问题")
        l2_response = await cli_handler("> ")
        l2_text = l2_response.strip().lower() if l2_response else ""
        if not l2_text:
            continue

        if l2_text in ("observe", "等等看", "等等", "观望", "跳过", "不买", "skip", "pass", "wait", "先不看"):
            print("\n同意——今日观望。现金也是一种仓位。\n")
            return False

        if (l2_text in ("好", "ok", "yes", "行", "可以", "go", "sure", "all")
            or "进入l3" in l2_text or "进入L3" in l2_text
            or "进入 l3" in l2_text or "进去l3" in l2_text
            or "下一" in l2_text):
            l2_confirmed = True
            break

        # Ticker selection by code
        requested = [t.strip().upper() for t in l2_text.replace(",", " ").split() if t.strip()]
        valid_tickers = [t for t in requested if t in l2_result.ticker_candidates]
        if valid_tickers:
            selected_tickers = valid_tickers
            print(f"  已选择: {', '.join(ticker_cn(t) for t in selected_tickers)}")
            l2_confirmed = True
            break

        # Structured or free-form question → AI response
        await _handle_l2_question(l2_text, l2_result)

    ctx.selected_tickers = selected_tickers
    return True


def _display_no_candidates(l2_result: Layer2Result) -> None:
    """Display helpful info when L2 found no ticker candidates."""
    print(f"\n  无候选标的")
    if l2_result.raw_analysis:
        clean = l2_result.raw_analysis
        if clean.strip().startswith("{"):
            sectors = _re.findall(r'"sector_shortlist"\s*:\s*\[(.*?)\]', clean, _re.DOTALL)
            assets = _re.findall(r'"preferred_assets"\s*:\s*\[(.*?)\]', clean, _re.DOTALL)
            if sectors:
                print(f"  推荐板块: {sectors[0][:200]}")
            if assets:
                print(f"  偏好资产: {assets[0][:200]}")
        else:
            print(f"  L2分析摘要: {clean[:400]}")
    if l2_result.red_team_notes:
        for note in l2_result.red_team_notes[:3]:
            if note and "JSON parsing failed" not in note:
                print(f"  注意: {note[:120]}")
    print(f"\n  你可以：输入'observe'观望 | 输入'好'强行进入L3 | 或输入任何问题讨论L2结果")


async def _handle_l2_question(user_text: str, l2_result: Layer2Result) -> None:
    """Handle structured commands or free-form user questions during L2.

    Responses are cached in-memory (keyed by user_text + L2 analysis content hash)
    to avoid duplicate LLM calls for identical queries within the same session.
    """
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")

    # --- cache lookup ---
    cache_key = _l2_cache_key(user_text, l2_result)
    if cache_key in _l2_response_cache:
        print(f"\n\n{_l2_response_cache[cache_key]}")
        return

    if user_text.startswith("explain ") or user_text.startswith("compare "):
        print("  ...", end="", flush=True)
        try:
            resp = await chat_pro(
                system_prompt=(
                    f"你是基本面分析师。今天是{today}。用中文，简洁回答。\n"
                    f"L2结果: {l2_result.raw_analysis[:600]}"
                ),
                user_prompt=f"用户请求: {user_text}\n\n直接回答，不超过200字。",
                temperature=0.3, max_tokens=512, reasoning_effort="minimal",
            )
            reply = resp.get("content", "无法处理。")
        except Exception:
            reply = "回复生成失败。"

        _l2_store_cache(cache_key, reply)
        print(f"\n\n{reply}")
        return

    # Free-form fallback
    print("  ...", end="", flush=True)
    try:
        resp = await chat_pro(
            system_prompt=(
                f"你是基本面分析师。今天是{today}。用中文，简明扼要。\n"
                f"L2结果: {l2_result.raw_analysis[:600]}"
            ),
            user_prompt=f"用户问题: {user_text}\n\n直接回答。",
            temperature=0.3, max_tokens=512, reasoning_effort="minimal",
        )
        reply = resp.get("content", "无法处理。输入'好'进入L3或'observe'观望。")
    except Exception:
        reply = "回复生成失败。输入'好'进入L3或'observe'观望。"

    _l2_store_cache(cache_key, reply)
    print(f"\n\n{reply}")


def _l2_store_cache(key: tuple, value: str) -> None:
    """Store a response in the in-memory cache, evicting oldest if at capacity."""
    if len(_l2_response_cache) >= _L2_CACHE_MAX_SIZE:
        try:
            del _l2_response_cache[next(iter(_l2_response_cache))]
        except (StopIteration, RuntimeError):
            _l2_response_cache.clear()
    _l2_response_cache[key] = value
