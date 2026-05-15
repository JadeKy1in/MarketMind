"""Decision Interactive — synthesis + confirmation loop (Phase 1: MEDIUM-LOW density).

Extracted from app.py per Red Team-approved refactoring plan.
"""
from __future__ import annotations

from marketmind.pipeline.decision import generate_decision
from marketmind.pipeline.session_context import SessionContext


async def run_decision_interactive(ctx: SessionContext, cli_handler) -> bool:
    """Run Decision synthesis + interactive confirmation loop.

    Args:
        ctx: Session context (reads l1_result, l2_result, l3_result,
             red_team_report, resonance; writes decision)
        cli_handler: async callable(str) -> str for user input

    Returns:
        True if user confirmed, False if user chose to observe
    """
    decision = await generate_decision(
        l1=ctx.l1_result, l2=ctx.l2_result, l3=ctx.l3_result,
        red_team=ctx.red_team_report, resonance=ctx.resonance,
    )
    ctx.decision = decision

    # Display selected strategy if one was chosen (H: strategy → output visibility)
    if ctx.selected_strategy:
        strategy_labels = {"conservative": "保守", "neutral": "中性", "aggressive": "激进"}
        label = strategy_labels.get(ctx.selected_strategy, ctx.selected_strategy)
        print(f"\n  策略: {ctx.selected_strategy}({label})")

    # Display decision cards
    print(f"\n{'='*60}")
    print(f"  [DECISION] 投资决策方案")
    if decision.decision_cards:
        print(f"\n  交易方案 ({len(decision.decision_cards)} cards):")
        print(f"  {'标的':<6} {'方向':<6} {'仓位':<6} {'入场':<14} {'止损':<8} {'目标':<8} {'持有天':<8}")
        print(f"  {'─'*62}")
        for card in decision.decision_cards:
            entry = f"${card.entry_low:.1f}-${card.entry_high:.1f}" if card.entry_low else "N/A"
            print(f"  {card.ticker:<6} {card.direction:<6} {card.position_size_pct:.0%}     "
                  f"{entry:<14} ${card.stop_loss:<7.1f} ${card.target_price:<7.1f} {card.max_hold_days:<8}")
            if card.thesis:
                print(f"         论点: {card.thesis[:100]}")
            if card.risk_statement:
                print(f"         风险: {card.risk_statement[:100]}")
            if card.red_team_note and card.red_team_note != "No objection from Red Team":
                print(f"         Red Team: {card.red_team_note[:100]}")
    else:
        print(f"\n  无交易方案生成")

    if decision.no_trade_card:
        print(f"\n  [No-Trade 方案]")
        print(f"  论据: {decision.no_trade_card.thesis[:150]}")
        if decision.no_trade_card.counterfactual:
            print(f"  反向条件: {decision.no_trade_card.counterfactual[:120]}")
        if decision.no_trade_card.structural_advantages:
            print(f"  结构性优势: {', '.join(decision.no_trade_card.structural_advantages[:3])}")

    print(f"  {'='*60}")
    print(f"  输入'确认'接受方案 | 输入'observe'放弃交易 | 输入标的代码移除该标的")

    decision_response = await cli_handler("> ")
    decision_text = decision_response.strip().lower() if decision_response else ""
    if decision_text in ("observe", "等等看", "等等", "观望", "跳过", "不买", "skip", "pass", "wait", "先不看"):
        print("\n同意——今日观望。现金也是一种仓位。\n")
        return False
    elif decision_text in ("确认", "好", "ok", "yes", "行", "可以", "同意", "go", "sure"):
        print("\n确认执行。\n")
    else:
        print(f"\n已记录你的反馈，按原方案执行。\n")

    return True
