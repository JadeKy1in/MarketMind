"""L2 interactive two-phase flow — sector selection + strategy group drill-down.

Compatibility adapter: wraps layer2_fundamental.analyze_layer2 for the
older two-phase interactive API. New callers should use layer2_fundamental directly.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Callable, Awaitable

from marketmind.pipeline.layer2_fundamental import Layer2Result, analyze_layer2
from marketmind.pipeline.session_context import SessionContext

logger = logging.getLogger("marketmind.pipeline.l2_interactive")


# ── Strategy group display ──────────────────────────────────────────────────

def _display_strategy_groups(drill_result: dict) -> None:
    """Print strategy groups to console for user selection."""
    groups = drill_result.get("strategy_groups", {})
    labels = {"conservative": "保守", "neutral": "中性", "aggressive": "激进"}
    print(f"\n  {drill_result.get('sector', 'Unknown')} 行业 — 策略组:")
    for key, group in groups.items():
        tickers = ", ".join(group.get("tickers", []))
        print(f"    [{labels.get(key, key)}] {group.get('thesis', '')}")
        print(f"      标的: {tickers}")


def _select_strategy_group(
    drill_result: dict, cli_handler: Callable[[str], Awaitable[str]]
) -> tuple[str, list[str]] | None:
    """Prompt user to select a strategy group. Returns (group_name, tickers) or None."""
    groups = drill_result.get("strategy_groups", {})
    if not groups:
        return None
    options = list(groups.keys())
    print(f"\n  策略组: {' | '.join(f'[{i+1}] {k}' for i, k in enumerate(options))}")

    choice_map = {}
    for i, key in enumerate(options):
        choice_map[str(i + 1)] = key
        choice_map[key] = key  # allow typing the name directly

    while True:
        user_input = yield from _await_handler(cli_handler, "选择策略组 (conservative/neutral/aggressive): ")
        user_input = user_input.strip().lower()
        if user_input == "observe":
            return None
        if user_input in choice_map:
            key = choice_map[user_input]
            group = groups[key]
            return (key, group.get("tickers", []))
        print(f"  无效输入，请重试。可选: {', '.join(choice_map.keys())}")


async def _await_handler(handler, prompt: str) -> str:
    """Call the CLI handler with a prompt and return the response."""
    return await handler(prompt)


# ── Sector drill-down ───────────────────────────────────────────────────────

async def _run_sector_drilldown(
    sector: dict, ctx: SessionContext
) -> dict | None:
    """Run a focused L2 analysis on a single sector. Returns drill-down JSON or None."""
    from marketmind.pipeline.layer1_narrative import Layer1Result
    # Build a focused L1 result for the sector
    l1 = ctx.l1_result or Layer1Result(
        event_grade="B", surprise_level="low", market_size="medium",
        matrix_quadrant="core_opportunity", price_in_score=0.5,
        cascade_rank=1, cascade_hub=False,
        sentiment_direction="bullish", sentiment_intensity=0.6,
        sentiment_vs_attention="high_sentiment",
        expert_signals=[], institutional_surprise="",
        key_characters=[], tail_risk_flags=[],
        raw_analysis="",
    )
    sector_context = {
        "sector_focus": sector.get("sector", "Unknown"),
        "sector_direction": sector.get("direction", "neutral"),
    }
    try:
        result = await analyze_layer2(l1, sector_context)
        # Expect the LLM to return JSON in raw_analysis
        raw = result.raw_analysis
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                return json.loads(raw[start:end + 1])
        return None
    except Exception as e:
        logger.warning("Sector drill-down failed: %s", e)
        return None


# ── Single-phase fallback ───────────────────────────────────────────────────

async def _confirm_single_phase(
    ctx: SessionContext, l2_result: Layer2Result, cli_handler
) -> bool:
    """Fallback: confirm ticker candidates from the single-pass L2 result."""
    candidates = l2_result.ticker_candidates[:10]
    if not candidates:
        print("  L2 未生成有效的持仓候选。")
        return False
    print(f"\n  L2 单阶段结果 — 候选标的: {', '.join(candidates)}")
    response = await cli_handler("是否确认这些候选并继续？(好/observe): ")
    response = response.strip().lower()
    if response in ("好", "y", "yes", "continue", "confirm"):
        ctx.selected_tickers = candidates
        ctx.selected_strategy = "neutral"
        return True
    return False


# ── Main two-phase entry point ──────────────────────────────────────────────

async def _run_two_phase_l2(
    ctx: SessionContext, l2_result: Layer2Result, cli_handler
) -> bool:
    """Run the two-phase L2 interactive flow.

    Phase 1 — Sector selection: user picks a sector or types '全部'/'observe'.
    Phase 2 — Strategy group drill-down: user selects risk appetite.
    Returns True if confirmed, False if user chose to observe.
    """
    sector_directions = getattr(l2_result, "sector_directions", None)
    if not sector_directions:
        # No sector data — fall back to single-phase
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    # Phase 1: Sector selection
    print("\n=== L2 双阶段分析 ===")
    for i, sd in enumerate(sector_directions):
        direction_cn = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(
            sd.get("direction", ""), sd.get("direction", "")
        )
        print(f"  [{i+1}] {sd['sector']} — {direction_cn} — {sd.get('rationale', '')}")

    sector_input = await cli_handler("\n选择行业 (1-{}, 全部, observe): ".format(len(sector_directions)))
    sector_input = sector_input.strip().lower()

    if sector_input == "observe":
        return False

    if sector_input == "全部":
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    # Parse sector index
    try:
        sector_idx = int(sector_input) - 1
        if sector_idx < 0 or sector_idx >= len(sector_directions):
            return await _confirm_single_phase(ctx, l2_result, cli_handler)
    except (ValueError, IndexError):
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    chosen_sector = sector_directions[sector_idx]

    # Phase 2: Drill-down + strategy selection
    drill_result = await _run_sector_drilldown(chosen_sector, ctx)
    if drill_result is None:
        # Drill-down failed — fall back to single-phase
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    _display_strategy_groups(drill_result)

    strategy_input = await cli_handler("\n选择策略组 (conservative/neutral/aggressive/observe): ")
    strategy_input = strategy_input.strip().lower()

    if strategy_input == "observe":
        return False

    groups = drill_result.get("strategy_groups", {})
    choice_map = {"1": "conservative", "2": "neutral", "3": "aggressive",
                  "conservative": "conservative", "neutral": "neutral", "aggressive": "aggressive"}
    key = choice_map.get(strategy_input)

    if key is None or key not in groups:
        return await _confirm_single_phase(ctx, l2_result, cli_handler)

    group = groups[key]
    ctx.selected_tickers = group.get("tickers", [])
    ctx.selected_strategy = key
    return True


async def run_l2_interactive(ctx: SessionContext, cli_handler) -> bool:
    """Top-level L2 interactive entry point.

    Runs analyze_layer2 to get initial results, then enters the two-phase flow.
    Returns True if the user confirmed and proceeded.
    """
    from marketmind.pipeline.layer1_narrative import Layer1Result
    l1 = ctx.l1_result or Layer1Result(
        event_grade="B", surprise_level="low", market_size="medium",
        matrix_quadrant="core_opportunity", price_in_score=0.5,
        cascade_rank=1, cascade_hub=False,
        sentiment_direction="bullish", sentiment_intensity=0.6,
        sentiment_vs_attention="high_sentiment",
        expert_signals=[], institutional_surprise="",
        key_characters=[], tail_risk_flags=[],
        raw_analysis="",
    )
    try:
        l2_result = await analyze_layer2(l1)
    except Exception:
        l2_result = Layer2Result(
            macro_quadrant="contraction", macro_direction="risk_off",
            preferred_assets=[], sector_shortlist=[], factor_scores={},
            ticker_candidates=[], ticker_weights={}, sector_momentum={},
            red_team_notes=["analysis failed"],
        )
    ctx.l2_result = l2_result
    return await _run_two_phase_l2(ctx, l2_result, cli_handler)
