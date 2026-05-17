"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketmind.config.settings import MarketMindConfig
from marketmind.gateway.async_client import init_gateway


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    import logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level)


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
        from marketmind.shadows.shadow_state import ShadowStateDB
        from marketmind.shadows.shadow_mother import ShadowMother
        shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
        shadow_db.init_schema()

        # Initialize permanent shadows (experts + daredevils + catfish)
        from marketmind.shadows.expert_shadows import create_expert_shadows
        from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
        from marketmind.shadows.catfish_agent import create_catfish_agent
        create_expert_shadows(shadow_db, config.shadow)
        create_daredevil_shadows(shadow_db, config.shadow)
        create_catfish_agent(shadow_db, config.shadow)

        mother = ShadowMother(config.shadow, shadow_db)
        tracker.result(f"Shadow ecosystem initialized with "
                       f"{len(shadow_db.get_visible_shadows())} shadows")

        # Phase F: Initialize background scheduler (disabled by default)
        if getattr(config.shadow, 'scheduler_enabled', False):
            from marketmind.shadows.background_scheduler import (
                BackgroundScheduler, SchedulerConfig,
            )
            from marketmind.shadows.shadow_memory import ShadowMemoryStore
            memory_store = ShadowMemoryStore(shadow_db)
            scheduler_config = SchedulerConfig(
                reflection_interval_minutes=config.shadow.reflection_interval_minutes,
                crystallization_interval_hours=config.shadow.crystallization_interval_hours,
                max_concurrent_tasks=config.shadow.max_concurrent_tasks,
                enabled=True,
            )
            scheduler = BackgroundScheduler(
                memory_store, shadow_db, mother, scheduler_config,
            )
            scheduler.start()
            tracker.result("Background scheduler started")

        # Phase F: Initialize Gemini Flash multimodal adapter (disabled by default)
        if getattr(config.shadow, 'gemini_flash_enabled', False):
            from marketmind.gateway.multimodal_adapter import MultimodalAdapter
            multimodal = MultimodalAdapter()
            tracker.result("Gemini Flash multimodal adapter initialized")

    # 1. News collection
    tracker.advance(1, "Scout: fetching news from all sources...")
    from marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    tracker.result(f"{len(news_items)} articles collected")

    # 2. Flash preprocessing
    tracker.advance(2, "Flash: preprocessing signals...")
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    signals = await preprocess_batch(news_items[:50])
    tracker.result(f"{len(signals)} signals extracted")

    # 3. Layer 1 Narrative analysis
    tracker.advance(3, "Layer 1: narrative analysis...")
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    l1_result = await analyze_layer1(signals[:15], news_items)
    tracker.result(f"grade={l1_result.event_grade}, quadrant={l1_result.matrix_quadrant}")

    # 4. Layer 2 + Layer 3 in parallel
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    from marketmind.config.asset_universe import ASSET_UNIVERSE

    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:10]]
    l2_task = analyze_layer2(l1_result)
    l3_task = analyze_layer3(tickers, {})

    l2_result, l3_result = await asyncio.gather(l2_task, l3_task)
    tracker.result(f"L2: {len(l2_result.ticker_candidates)} candidates, "
                   f"L3: {len(l3_result.results)} tickers ({len(l3_result.green_lights)} green)")

    # 5. Shadow ecosystem run
    shadow_votes = None  # DESIGN: shadows are internal competition, never vote on decisions
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(5, "Shadows: running analysis cycle...")
        orchestration = await mother.orchestrate_daily_cycle(
            news_items, {},
        )
        tracker.result(f"{orchestration.active_shadows} shadows, "
                       f"{orchestration.temp_shadows_created} temp created")

        # Phase F integration: memory update + crystallization (if enabled)
        # These are already wired in shadow_mother.orchestrate_daily_cycle()
        # as step 6.5 (memory update) and step 6.6 (crystallization check)
        if getattr(config.shadow, 'crystallization_enabled', False):
            tracker.result("Memory updated, crystallization check complete")

    # 6. Red Team challenge
    tracker.advance(6, "Red Team: adversarial challenge...")
    from marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(
        l1_result.raw_analysis,
        l2_result.raw_analysis,
        l2_result.ticker_candidates,
    )
    tracker.result(f"{len(red_team_report.challenges)} challenges, "
                   f"A-grade: {red_team_report.a_grade_count}")

    # 7. Signal Resonance
    tracker.advance(7, "Resonance: statistical validation...")
    from marketmind.pipeline.resonance import evaluate_resonance
    resonance = evaluate_resonance(
        signal_returns={},
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=0.5,
    )

    # 8. Decision (shadow_votes always None — shadows are internal competition only)
    tracker.advance(8, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
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
    from marketmind.storage.archivist import get_archivist
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
    from marketmind.ui.main_window import MainWindow
    from marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


async def run_interactive(config: MarketMindConfig, mock: bool = False,
                          verbose: bool = False, shadow_count: int | None = None) -> int:
    """Run the full interactive pipeline with CLI prompts at each stage."""
    from marketmind.gateway.async_client import init_gateway
    from marketmind.pipeline.session_context import SessionContext
    from marketmind.pipeline.layer1_interactive import run_l1_interactive
    from marketmind.pipeline.l2_interactive import run_l2_interactive
    from marketmind.pipeline.l3_interactive import run_l3_interactive
    from marketmind.pipeline.decision_interactive import run_decision_interactive

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    ctx = SessionContext(config=config)

    async def cli_handler(prompt: str) -> str:
        if mock:
            return "好"
        print(prompt, end="")
        return input()

    # Stage 1: L1 narrative
    l1_result, skip, _ = await run_l1_interactive(config, mock=mock, verbose=verbose,
                                                   shadow_count=shadow_count)
    ctx.l1_result = l1_result
    if skip:
        return 0

    # Stage 2: L2 fundamental
    if not await run_l2_interactive(ctx, cli_handler):
        return 0

    # Stage 3: L3 technical
    if not await run_l3_interactive(ctx, cli_handler):
        return 0

    # Stage 4: Decision
    if not await run_decision_interactive(ctx, cli_handler):
        return 0

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


def _run_backtest(config: MarketMindConfig, args) -> int:
    """Run multi-day backtest on shadow consensus signal quality."""
    from datetime import datetime, timezone
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.backtest_runner import BacktestRunner

    import logging
    logging.basicConfig(level=logging.INFO)

    shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
    shadow_db.init_schema()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = args.start or "2026-01-01"
    end = args.end or today

    try:
        runner = BacktestRunner(shadow_db)
        report = runner.run(start, end, args.output)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] Backtest failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected backtest error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2) if not args.output else
          f"Backtest report written to {args.output}")

    return 0


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
    parser.add_argument("--backtest", action="store_true",
                        help="Run multi-day backtest on shadow consensus signal quality")
    parser.add_argument("--start", type=str, default=None, metavar="DATE",
                        help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, metavar="DATE",
                        help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default=None, metavar="PATH",
                        help="Backtest output path (JSON)")
    args = parser.parse_args()

    config = MarketMindConfig.from_env()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return 1

    if args.backtest:
        return _run_backtest(config, args)

    if args.mode == "gui":
        return run_gui(config)
    else:
        shadow_n = 0 if args.no_shadows else args.shadows
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose,
                                      shadow_count=shadow_n))


if __name__ == "__main__":
    sys.exit(main())
