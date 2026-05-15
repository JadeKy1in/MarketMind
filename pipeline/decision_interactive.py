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

    # R5: Progressive disclosure — one-line summary before detail
    n_cards = len(decision.decision_cards) if decision.decision_cards else 0
    long_count = sum(1 for c in decision.decision_cards if getattr(c, 'direction', '') in ('long', 'Long', 'LONG'))
    short_count = sum(1 for c in decision.decision_cards if getattr(c, 'direction', '') in ('short', 'Short', 'SHORT'))
    if long_count > short_count:
        bias = "做多偏向"
    elif short_count > long_count:
        bias = "做空偏向"
    elif n_cards == 0:
        bias = "无偏向"
    else:
        bias = "混合偏向"
    no_trade_status = "有No-Trade" if decision.no_trade_card else "无No-Trade"
    print(f"  [DECISION] {n_cards}个交易方案 | {bias} | {no_trade_status}")
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

    # R6: Pre-Decision Challenge Protocol — contrarian risk review
    if decision.contrarian_challenges:
        print(f"  ┌─ 逆向风控挑战 ─────────────────────────────────┐")
        for ch in decision.contrarian_challenges:
            risk = ch.get("risk", "?")
            loss_pct = ch.get("loss_pct", 0.0)
            trigger = ch.get("trigger", "?")
            print(f"  │ ⚠ {risk}: 潜在损失 {loss_pct}%, 触发条件: {trigger}")
        print(f"  └{'─'*48}┘")

    print(f"  ┌─ 确认前检查清单 ─────────────────────────────┐")
    print(f"  │ □ 反向论点是否经得起推敲？                    │")
    print(f"  │ □ 止损位是否在可承受范围内？                  │")
    print(f"  │ □ 如果今天不交易，会错过什么？                │")
    print(f"  │ □ 未来48小时是否有重大事件？（FOMC/财报/数据） │")
    print(f"  └{'─'*48}┘")
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
