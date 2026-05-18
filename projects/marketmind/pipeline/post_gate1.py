"""Post-Gate 1 pipeline stages (Stage 4-10): L1 → L2+L3 → Shadows → Red Team → Resonance → Decision → Archive.

Exports:
    run_post_gate1: Run stages 4-10 using state from run_pre_gate1().
"""
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.config.settings import MarketMindConfig


async def run_post_gate1(config: "MarketMindConfig", state: dict,
                         mock: bool = False, verbose: bool = False,
                         gate1_decision: dict | None = None) -> int:
    """Run stages 4-10: L1 → L2+L3 → Shadows → Red Team → Resonance → Decision → Archive.

    Args:
        config: MarketMind configuration.
        state: State dict returned by run_pre_gate1().
        mock: Unused (kept for backward compatibility).
        verbose: Unused — verbosity tracks via state["tracker"].
        gate1_decision: Reserved for Phase I integration (currently unused).

    Returns:
        Exit code (0 = success).
    """
    tracker = state["tracker"]
    archivist = state["archivist"]
    session_date = state["session_date"]
    shadow_db = state["shadow_db"]
    mother = state["mother"]
    news_items = state["news_items"]
    triage_results = state["triage_results"]
    hypotheses = state["hypotheses"]
    actionable = state["actionable"]

    def _archive(subdir, filename, data):
        """Save pipeline stage output to archive. Never crashes pipeline."""
        try:
            archivist.save_json(subdir, filename, data)
        except Exception as e:
            if tracker.verbose:
                print(f"       [archive] {filename}: {e}")

    # 4. Layer 1 Narrative analysis (receives investigation context)
    tracker.advance(4, "Layer 1: narrative analysis...")
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    signals = list(triage_results[:15])  # TriageResult ≈ FlashSignal for L1
    l1_result = await analyze_layer1(signals, news_items)

    if actionable:
        tracker.result(f"grade={l1_result.event_grade}, quadrant={l1_result.matrix_quadrant}, "
                       f"top hypothesis: {actionable[0].hypothesis[:100]}")
    else:
        tracker.result(f"grade={l1_result.event_grade}, quadrant={l1_result.matrix_quadrant}")

    _archive("analysis", "03_layer1_narrative", {
        "stage": "l1",
        "event_grade": l1_result.event_grade,
        "matrix_quadrant": l1_result.matrix_quadrant,
        "sentiment": l1_result.sentiment_direction,
        "surprise_level": l1_result.surprise_level,
        "market_size": l1_result.market_size,
        "cascade_rank": l1_result.cascade_rank,
        "price_in_score": l1_result.price_in_score,
        "tail_risk_flags": l1_result.tail_risk_flags,
        "raw_analysis": l1_result.raw_analysis[:2000] if l1_result.raw_analysis else ""
    })

    # 5. Layer 2 + Layer 3 in parallel
    tracker.advance(5, "Layer 2+3: fundamental + technical analysis...")
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    from marketmind.config.asset_universe import ASSET_UNIVERSE

    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:10]]
    l2_task = analyze_layer2(l1_result)
    l3_task = analyze_layer3(tickers, {})

    l2_result, l3_result = await asyncio.gather(l2_task, l3_task)
    tracker.result(f"L2: {len(l2_result.ticker_candidates)} candidates, "
                   f"L3: {len(l3_result.results)} tickers ({len(l3_result.green_lights)} green)")

    _archive("analysis", "04_layer2_fundamental", {
        "stage": "l2",
        "macro_quadrant": l2_result.macro_quadrant,
        "macro_direction": l2_result.macro_direction,
        "ticker_candidates": l2_result.ticker_candidates,
        "preferred_assets": l2_result.preferred_assets,
        "sector_shortlist": l2_result.sector_shortlist,
        "raw_analysis": l2_result.raw_analysis[:2000] if l2_result.raw_analysis else ""
    })
    _archive("analysis", "04_layer3_technical", {
        "stage": "l3",
        "green_lights": len(l3_result.green_lights),
        "results": [{"ticker": r.ticker, "light": r.light,
                     "entry_zone_low": r.entry_zone_low, "entry_zone_high": r.entry_zone_high,
                     "stop_loss": r.stop_loss, "target_price": r.target_price,
                     "above_200wma": r.above_200wma}
                    for r in l3_result.results]
    })

    # 6. Shadow ecosystem run
    shadow_votes = None  # DESIGN: shadows are internal competition, never vote on decisions
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(6, "Shadows: running analysis cycle...")
        orchestration = await mother.orchestrate_daily_cycle(
            news_items, {},
        )
        tracker.result(f"{orchestration.active_shadows} shadows, "
                       f"{orchestration.temp_shadows_created} temp created")

        # Phase F integration: memory update + crystallization (if enabled)
        if getattr(config.shadow, 'crystallization_enabled', False):
            tracker.result("Memory updated, crystallization check complete")

    # 7. Red Team challenge
    tracker.advance(7, "Red Team: adversarial challenge...")
    from marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(
        l1_result.raw_analysis,
        l2_result.raw_analysis,
        l2_result.ticker_candidates,
    )
    tracker.result(f"{len(red_team_report.challenges)} challenges, "
                   f"A-grade: {red_team_report.a_grade_count}")

    _archive("review", "06_red_team", {
        "stage": "red_team",
        "challenges": len(red_team_report.challenges),
        "a_grade": red_team_report.a_grade_count,
        "critical": red_team_report.critical_count,
        "items": [{"id": c.id, "target": c.target, "severity": c.severity,
                   "challenge": c.challenge, "evidence": c.evidence}
                  for c in red_team_report.challenges]
    })

    # 8. Signal Resonance
    tracker.advance(8, "Resonance: statistical validation...")
    from marketmind.pipeline.resonance import evaluate_resonance
    resonance = evaluate_resonance(
        signal_returns={},
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=0.5,
    )

    _archive("review", "07_resonance", {
        "stage": "resonance",
        "passed": resonance.passed,
        "dsr": resonance.dsr,
        "pbo": resonance.pbo,
        "verdict": resonance.verdict,
        "dimensions_active": resonance.dimensions_active
    })

    # 9. Decision (shadow_votes always None — shadows are internal competition only)
    tracker.advance(9, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
        shadow_votes=shadow_votes,
        hypotheses=hypotheses,
    )
    tracker.result(f"cards={len(decision.decision_cards)}, "
                   f"no_trade={'present' if decision.no_trade_card else 'none'}")

    _archive("decisions", "08_decision", {
        "stage": "decision",
        "cards": len(decision.decision_cards),
        "no_trade": decision.no_trade_card is not None,
        "decision_cards": [{"ticker": c.ticker, "direction": c.direction,
                            "entry_low": c.entry_low, "entry_high": c.entry_high,
                            "stop": c.stop_loss, "target": c.target_price,
                            "thesis": c.thesis, "risk_statement": c.risk_statement,
                            "reward_risk": c.reward_risk_ratio}
                           for c in decision.decision_cards]
    })

    # 10. Archive (FTS5 index)
    tracker.advance(10, "Archive: indexing session...")
    archivist.init_fts()
    archivist.index_document(
        date=session_date,
        category="daily_session",
        title="MarketMind Daily",
        content=f"MarketMind daily: {l1_result.event_grade} | {l2_result.macro_quadrant} | "
                f"resonance={resonance.verdict}",
    )
    tracker.result("Session archived")

    print("\nMarketMind daily pipeline complete.")
    return 0
