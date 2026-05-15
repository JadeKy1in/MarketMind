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

    # Determine interaction mode: two-phase (Phase B) if sector_directions available,
    # otherwise fall back to single-phase (legacy behavior).
    if l2_result.sector_directions:
        confirmed = await _run_two_phase_l2(ctx, l2_result, cli_handler)
    else:
        confirmed = await _run_single_phase_l2(ctx, l2_result, cli_handler)

    return confirmed


async def _run_single_phase_l2(ctx: SessionContext, l2_result: Layer2Result, cli_handler) -> bool:
    """Legacy single-phase L2: display ticker list, single confirmation loop."""
    _display_l2_results(l2_result)

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

        await _handle_l2_question(l2_text, l2_result)

    ctx.selected_tickers = selected_tickers
    return True


async def _run_two_phase_l2(ctx: SessionContext, l2_result: Layer2Result, cli_handler) -> bool:
    """Phase B two-phase L2: sector selection → strategy group selection."""
    # Phase A: Display sector directions, let user pick a sector
    print(f"\n{'─'*60}")
    print(f"  [L2] 基本面分析 — 宏观象限: {l2_result.macro_quadrant} | 方向: {l2_result.macro_direction}")
    print(f"\n  行业方向判断:")
    for i, sd in enumerate(l2_result.sector_directions[:6], 1):
        direction_cn = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(sd.get("direction", ""), sd.get("direction", ""))
        momentum_cn = {"accelerating": "加速", "decelerating": "减速", "stable": "稳定"}.get(sd.get("momentum", ""), "")
        print(f"    {i}. {sd.get('sector', '?')} — {direction_cn} ({momentum_cn})")
        if sd.get("rationale"):
            print(f"       {sd['rationale'][:120]}")
    print(f"\n  输入行业编号选择方向 | 输入'全部'使用默认组合 | 输入'observe'观望")

    # Sector selection loop
    chosen_sector = None
    while chosen_sector is None:
        response = await cli_handler("> ")
        text = response.strip().lower() if response else ""
        if not text:
            continue
        if text in ("observe", "等等看", "等等", "观望", "跳过"):
            print("\n同意——今日观望。\n")
            return False
        if text in ("全部", "all", "好", "ok", "yes"):
            # Use all-sector default: fall back to flat ticker list
            _display_l2_results(l2_result)
            return await _confirm_single_phase(ctx, l2_result, cli_handler)

        # Try numeric sector selection
        try:
            idx = int(text) - 1
            if 0 <= idx < len(l2_result.sector_directions):
                chosen_sector = l2_result.sector_directions[idx]
                break
        except ValueError:
            pass
        print(f"  请输入1-{len(l2_result.sector_directions)}之间的编号")

    sector_name = chosen_sector.get("sector", "未知行业")

    # Phase B: Run sector drill-down
    print(f"\n  已选择: {sector_name} — 正在分析该行业投资工具...")
    drill_result = await _run_sector_drilldown(ctx, l2_result, chosen_sector)
    if drill_result is None:
        # Drill-down failed — fall back to flat ticker list
        print(f"  [L2] 行业分析调用失败 — 使用默认标的列表。")
        _display_l2_results(l2_result)
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    # Display strategy groups
    _display_strategy_groups(drill_result, sector_name)

    # Strategy group selection loop
    return await _select_strategy_group(ctx, drill_result, sector_name, cli_handler)


async def _run_sector_drilldown(ctx: SessionContext, l2_result: Layer2Result, chosen_sector: dict) -> dict | None:
    """Run the sector drill-down LLM call. Returns parsed JSON or None on failure."""
    from marketmind.pipeline.layer2_fundamental import LAYER2_SECTOR_DRILLDOWN_PROMPT
    from marketmind.gateway.response_parser import strip_markdown_fences
    import json as _json

    sector_name = chosen_sector.get("sector", "")
    direction = chosen_sector.get("direction", "neutral")
    rationale = chosen_sector.get("rationale", "")

    # Sanitize LLM-generated fields before re-injecting into new prompt (defense-in-depth)
    safe_rationale = defang_text(rationale)
    safe_assets = [defang_text(a) for a in l2_result.preferred_assets[:5]]

    user_prompt = (
        f"行业: {defang_text(sector_name)}\n"
        f"方向: {direction}\n"
        f"理由: {safe_rationale}\n"
        f"宏观背景: 象限={l2_result.macro_quadrant}, 方向={l2_result.macro_direction}\n"
        f"偏好资产: {', '.join(safe_assets)}"
    )

    try:
        resp = await chat_pro(
            system_prompt=LAYER2_SECTOR_DRILLDOWN_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3, max_tokens=3072, reasoning_effort="minimal",
        )
        content = strip_markdown_fences(resp.get("content", ""))
        result = _json.loads(content)
        # Post-hoc ticker validation against asset universe (prevents LLM hallucination)
        _validate_drilldown_tickers(result)
        return result
    except Exception as e:
        logger.warning("Sector drill-down failed for %s: %s", sector_name, e)
        return None


def _validate_drilldown_tickers(result: dict) -> None:
    """Remove hallucinated tickers from drill-down result. Mutates in-place."""
    from marketmind.config.asset_universe import ASSET_UNIVERSE
    valid_tickers = {a.ticker for a in ASSET_UNIVERSE.values()}

    # Validate strategy_groups
    for group in result.get("strategy_groups", {}).values():
        if "tickers" in group:
            group["tickers"] = [t for t in group["tickers"] if t in valid_tickers]
            group["weights"] = {t: w for t, w in group.get("weights", {}).items() if t in valid_tickers}

    # Validate tool_matrix
    for tool in result.get("tool_matrix", {}).values():
        if "tickers" in tool:
            tool["tickers"] = [t for t in tool["tickers"] if t in valid_tickers]
            tool["weights"] = {t: w for t, w in tool.get("weights", {}).items() if t in valid_tickers}


async def _confirm_single_phase(ctx: SessionContext, l2_result: Layer2Result, cli_handler) -> bool:
    """Explicit confirmation loop for single-phase (no strategy groups).

    Requires explicit confirmation ("好"/"ok"/"yes") to proceed. Empty input
    re-prompts. Unknown input shows a hint and re-prompts. Matches the
    pattern of _select_strategy_group which loops on unrecognized input.
    """
    while True:
        print(f"\n  {'─'*60}")
        print(f"  输入'好'进入L3 | 输入'observe'观望 | 或输入问题")
        response = await cli_handler("> ")
        text = response.strip().lower() if response else ""
        if not text:
            continue
        if text in ("observe", "等等看", "观望", "跳过"):
            print("\n同意——今日观望。\n")
            return False
        if text in ("好", "ok", "yes", "行", "可以", "go", "sure", "确认"):
            ctx.selected_tickers = list(l2_result.ticker_candidates[:10])
            return True
        print(f"  请输入'好'确认或'observe'观望")


async def _select_strategy_group(ctx: SessionContext, drill_result: dict, sector_name: str, cli_handler) -> bool:
    """Let user pick a strategy group (conservative/neutral/aggressive) and tickers."""
    strategy_groups = drill_result.get("strategy_groups", {})
    if not strategy_groups:
        # No strategy groups in drill-down result — fall back to tool matrix tickers
        all_tickers = []
        for tool_type, tool_data in drill_result.get("tool_matrix", {}).items():
            all_tickers.extend(tool_data.get("tickers", []))
        ctx.selected_tickers = all_tickers[:10]
        ctx.selected_strategy = ""
        return True

    chosen_group = None
    while chosen_group is None:
        print(f"  输入策略名称 (conservative/neutral/aggressive) | 输入'observe'观望 | 输入'好'接受中性")
        response = await cli_handler("> ")
        text = response.strip().lower() if response else ""
        if not text:
            continue
        if text in ("observe", "等等看", "观望", "跳过"):
            print("\n同意——今日观望。\n")
            return False
        if text in ("好", "ok", "yes", "neutral", "中性", "all"):
            chosen_group = "neutral"
            break
        if text in ("conservative", "保守", "conservative", "safe"):
            chosen_group = "conservative"
            break
        if text in ("aggressive", "激进", "aggressive", "risk"):
            chosen_group = "aggressive"
            break
        if text in strategy_groups:
            chosen_group = text
            break
        print(f"  请选择: conservative(保守) / neutral(中性) / aggressive(激进)")

    group_data = strategy_groups.get(chosen_group, {})
    tickers = group_data.get("tickers", [])
    ctx.selected_tickers = tickers if tickers else list(drill_result.get("tool_matrix", {}).get("direct_exposure", {}).get("tickers", []))
    ctx.selected_strategy = chosen_group

    thesis = group_data.get("thesis", "")
    if thesis:
        print(f"\n  策略论点: {thesis[:200]}")
    print(f"  已选择: {chosen_group} — {len(ctx.selected_tickers)} 个标的")
    return True


def _display_l2_results(l2_result: Layer2Result) -> None:
    """Display L2 macro results and ticker candidates (legacy single-phase)."""
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


def _display_strategy_groups(drill_result: dict, sector_name: str) -> None:
    """Display strategy groups from sector drill-down result."""
    print(f"\n{'─'*60}")
    print(f"  [{sector_name}] 投资工具矩阵 + 策略选择")

    tool_matrix = drill_result.get("tool_matrix", {})
    if tool_matrix:
        print(f"\n  可用工具类型:")
        for tool_type, tool_data in tool_matrix.items():
            desc = tool_data.get("description", tool_type)
            tickers = tool_data.get("tickers", [])
            labeled = [ticker_cn(t) for t in tickers]
            print(f"    {tool_type}: {', '.join(labeled)} — {desc}")

    strategy_groups = drill_result.get("strategy_groups", {})
    if strategy_groups:
        print(f"\n  策略选择:")
        for name, group in strategy_groups.items():
            name_cn = {"conservative": "保守", "neutral": "中性", "aggressive": "激进"}.get(name, name)
            tickers = group.get("tickers", [])
            thesis = group.get("thesis", "")
            print(f"    {name_cn} ({name}): {', '.join(ticker_cn(t) for t in tickers)}")
            if thesis:
                print(f"      {thesis[:150]}")
    print(f"  {'─'*60}")


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
                    f"L2结果: {defang_text(l2_result.raw_analysis)[:600]}"
                ),
                user_prompt=f"用户请求: {defang_text(user_text)}\n\n直接回答，不超过200字。",
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
                f"L2结果: {defang_text(l2_result.raw_analysis)[:600]}"
            ),
            user_prompt=f"用户问题: {defang_text(user_text)}\n\n直接回答。",
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
