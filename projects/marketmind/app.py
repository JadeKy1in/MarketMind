"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.marketmind.config.settings import MarketMindConfig
from projects.marketmind.gateway.async_client import init_gateway


async def run_daily(config: MarketMindConfig, mock: bool = False, verbose: bool = False,
                     shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)

    tracker = _StageTracker(verbose)

    # 0. Shadow Mother event scan (pre-market)
    shadow_db = None
    mother = None
    orchestration = None
    if config.shadow.shadows_enabled and shadow_count != 0:
        tracker.advance(0, "Shadow Mother: scanning events...")
        from projects.marketmind.shadows.shadow_state import ShadowStateDB
        from projects.marketmind.shadows.shadow_mother import ShadowMother
        shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
        shadow_db.init_schema()

        # Initialize permanent shadows (experts + daredevils + catfish)
        from projects.marketmind.shadows.expert_shadows import create_expert_shadows
        from projects.marketmind.shadows.daredevil_shadows import create_daredevil_shadows
        from projects.marketmind.shadows.catfish_agent import create_catfish_agent
        create_expert_shadows(shadow_db, config.shadow)
        create_daredevil_shadows(shadow_db, config.shadow)
        create_catfish_agent(shadow_db, config.shadow)

        mother = ShadowMother(config.shadow, shadow_db)
        tracker.result(f"Shadow ecosystem initialized with "
                       f"{len(shadow_db.get_visible_shadows())} shadows")

    # 1. News collection
    tracker.advance(1, "Scout: fetching news from all sources...")
    from projects.marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    tracker.result(f"{len(news_items)} articles collected")

    # 2. Flash preprocessing
    tracker.advance(2, "Flash: preprocessing signals...")
    from projects.marketmind.pipeline.flash_preprocessor import preprocess_batch
    signals = await preprocess_batch(news_items[:50])
    tracker.result(f"{len(signals)} signals extracted")

    # 3. Layer 1 Narrative analysis
    tracker.advance(3, "Layer 1: narrative analysis...")
    from projects.marketmind.pipeline.layer1_narrative import analyze_layer1
    l1_result = await analyze_layer1(signals[:15], news_items)
    tracker.result(f"grade={l1_result.event_grade}, quadrant={l1_result.matrix_quadrant}")

    # 4. Layer 2 + Layer 3 in parallel
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from projects.marketmind.pipeline.layer2_fundamental import analyze_layer2
    from projects.marketmind.pipeline.layer3_technical import analyze_layer3
    from projects.marketmind.config.asset_universe import ASSET_UNIVERSE

    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:10]]
    l2_task = analyze_layer2(l1_result)
    l3_task = analyze_layer3(tickers, {})

    l2_result, l3_result = await asyncio.gather(l2_task, l3_task)
    tracker.result(f"L2: {len(l2_result.ticker_candidates)} candidates, "
                   f"L3: {len(l3_result.results)} tickers ({len(l3_result.green_lights)} green)")

    # 5. Shadow ecosystem run
    shadow_votes = None
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(5, "Shadows: running analysis cycle...")
        orchestration = await mother.orchestrate_daily_cycle(
            news_items, {},
        )
        tracker.result(f"{orchestration.active_shadows} shadows, "
                       f"{orchestration.temp_shadows_created} temp created")

    # 6. Red Team challenge
    tracker.advance(6, "Red Team: adversarial challenge...")
    from projects.marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(
        l1_result.raw_analysis,
        l2_result.raw_analysis,
        l2_result.ticker_candidates,
    )
    tracker.result(f"{len(red_team_report.challenges)} challenges, "
                   f"A-grade: {red_team_report.a_grade_count}")

    # 7. Signal Resonance
    tracker.advance(7, "Resonance: statistical validation...")
    from projects.marketmind.pipeline.resonance import evaluate_resonance
    resonance = evaluate_resonance(
        signal_returns={},
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=0.5,
    )

    # 8. Decision with shadow consensus
    tracker.advance(8, "Decision: synthesis...")
    from projects.marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
        shadow_votes=shadow_votes,
    )
    tracker.result(f"cards={len(decision.decision_cards)}, "
                   f"no_trade={'present' if decision.no_trade_card else 'none'}")

    # 9. Archive
    tracker.advance(9, "Archive: saving session...")
    from datetime import datetime as dt
    from projects.marketmind.storage.archivist import get_archivist
    archivist = get_archivist(config.data_dir)
    archivist.init_fts()
    archivist.index_document(
        date=dt.now().isoformat()[:10],
        category="daily_session",
        title="MarketMind Daily",
        content=f"MarketMind daily: {l1_result.event_grade} | {l2_result.macro_quadrant} | "
                f"resonance={resonance.verdict}",
    )
    tracker.result("Session archived")

    print("\nMarketMind daily pipeline complete.")
    return 0


def run_gui(config: MarketMindConfig) -> int:
    """Launch CustomTkinter GUI."""
    from projects.marketmind.ui.main_window import MainWindow
    from projects.marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


class _StageTracker:
    def __init__(self, verbose: bool):
        self.verbose = verbose

    def advance(self, stage: int, msg: str) -> None:
        if self.verbose:
            print(f"[{stage}/9] {msg}")

    def result(self, msg: str) -> None:
        if self.verbose:
            print(f"       {msg}")


def main():
    parser = argparse.ArgumentParser(description="MarketMind — AI Investment Analysis Workstation")
    parser.add_argument("--mode", choices=["daily", "gui"], default="gui",
                        help="Run mode: daily CLI report or GUI (default: gui)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock LLM responses (no API calls)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--shadows", type=int, default=None, metavar="N",
                        help="Number of shadows to activate (default: all)")
    parser.add_argument("--no-shadows", action="store_true",
                        help="Disable shadow ecosystem entirely")
    parser.add_argument("--shadow-only", action="store_true",
                        help="Run ONLY shadow ecosystem (no main pipeline)")
    args = parser.parse_args()

    config = MarketMindConfig.from_env()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return 1

    if args.mode == "gui":
        return run_gui(config)
    else:
        shadow_n = 0 if args.no_shadows else args.shadows
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose,
                                      shadow_count=shadow_n))


if __name__ == "__main__":
    sys.exit(main())
