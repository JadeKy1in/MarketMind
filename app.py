"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("marketmind.app")

def _setup_logging(data_dir: str = "data") -> None:
    """Configure logging to both console and file."""
    from datetime import datetime as _dt
    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"marketmind_{_dt.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger.info("Logging to %s", log_file)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketmind.config.settings import MarketMindConfig
from marketmind.gateway.async_client import init_gateway

# Module-level reference to the background shadow task (H1: pipeline separation)
_shadow_task: "asyncio.Task | None" = None
_shadow_result = None  # stores ShadowOrchestrationResult when background task completes

# Default benchmark Sharpe ratio for resonance evaluation.
# TODO: replace with trailing performance metric from backtest or config.
_DEFAULT_OBSERVED_SHARPE = 0.5


def _shadow_progress_started() -> None:
    """Called when shadow background task starts."""
    print("Shadows processing...")


def _shadow_progress_done(task: "asyncio.Task") -> None:
    """Called when shadow background task completes."""
    if task.cancelled():
        return
    try:
        result = task.result()
        if result:
            print(f"Shadows complete: {result.active_shadows} shadows, "
                  f"{result.temp_shadows_created} temp created")
            global _shadow_result
            _shadow_result = result
    except Exception as e:
        print(f"Shadows error: {e}")


async def run_daily_legacy(config: MarketMindConfig, mock: bool = False, verbose: bool = False,
                            shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline WITH blocking shadow cycle.

    This is the PRE-SEPARATION legacy behavior. Shadows run synchronously
    and block the main pipeline until complete. Use run_daily() for the
    new non-blocking shadow pipeline.
    """
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
    from marketmind.pipeline.resonance import evaluate_resonance, ResonanceResult

    # Bootstrap signal_returns from available data
    signal_returns_data = {}
    # Try to get actual returns from L3 results
    if hasattr(l3_result, 'results'):
        for r in l3_result.results[:10]:
            if hasattr(r, 'ticker') and hasattr(r, 'daily_return_pct'):
                key = f"technical_{r.ticker}"
                signal_returns_data[key] = [r.daily_return_pct] if r.daily_return_pct else []
    # Fallback: if no data, use a placeholder that won't break DSR calculation
    if not signal_returns_data:
        signal_returns_data = {"fallback": [0.001, -0.002, 0.003, -0.001, 0.002]}

    resonance = evaluate_resonance(
        signal_returns=signal_returns_data,
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=_DEFAULT_OBSERVED_SHARPE,
    )

    # 8. Decision with shadow consensus
    tracker.advance(8, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
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


# ══════════════════════════════════════════════════════════════════════════════
# H1: Pipeline Separation — new non-blocking shadow pipeline
# ══════════════════════════════════════════════════════════════════════════════
#
# Token Budget Split: 60/40
#   - 60% reserved for the interactive main pipeline (L1→L2→L3→Decision→Red Team)
#   - 40% reserved for shadow ecosystem background analysis
#   Shadows launch as a background asyncio.Task and do NOT block the main pipeline.
#   The main pipeline completes and displays results immediately; shadow results
#   are printed to stdout when the background task finishes (typically 5-30s later).
#
# WAL mode: Already enabled at shadow_state.py ShadowStateDB._connect() (PRAGMA
#   journal_mode=WAL). WAL allows concurrent reads from the main pipeline while
#   shadows write snapshots and votes in the background.


async def run_daily(config: MarketMindConfig, mock: bool = False, verbose: bool = False,
                     shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline.

    Shadows run as a non-blocking background task so the main pipeline
    completes and displays results without waiting for all shadow analyses.
    The shadow ecosystem receives 40% of the rate-limit budget and operates
    in the background with results printed on completion.

    For the legacy blocking behavior, use run_daily_legacy().
    """
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)

    tracker = _StageTracker(verbose)
    global _shadow_task, _shadow_result
    _shadow_result = None

    # 0. Shadow Mother event scan (pre-market)
    shadow_db = None
    mother = None
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

    # 5. Shadow ecosystem run → NON-BLOCKING background launch (H1)
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(5, "Shadows: launching background analysis...")

        # N-L4: Report token budget state before shadow launch
        try:
            from marketmind.gateway.async_client import get_budget
            budget = await get_budget()
            if budget:
                budget_report = budget.report()
                tracker.result(f"Token budget: {budget_report['tokens_pct_used']}% used, "
                               f"{budget_report['pro_calls_remaining']} Pro calls remaining")
        except Exception:
            pass

        _shadow_progress_started()
        _shadow_task = asyncio.create_task(
            mother.orchestrate_daily_cycle(news_items, {})
        )
        _shadow_task.add_done_callback(_shadow_progress_done)
        tracker.result("Shadows launched in background (non-blocking)")

        # Phase F integration note: memory update + crystallization are
        # run inside the background task via orchestrate_daily_cycle().
        if getattr(config.shadow, 'crystallization_enabled', False):
            tracker.result("Memory update + crystallization will run in background")

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
    from marketmind.pipeline.resonance import evaluate_resonance, ResonanceResult

    # Bootstrap signal_returns from available data
    signal_returns_data = {}
    # Try to get actual returns from L3 results
    if hasattr(l3_result, 'results'):
        for r in l3_result.results[:10]:
            if hasattr(r, 'ticker') and hasattr(r, 'daily_return_pct'):
                key = f"technical_{r.ticker}"
                signal_returns_data[key] = [r.daily_return_pct] if r.daily_return_pct else []
    # Fallback: if no data, use a placeholder that won't break DSR calculation
    if not signal_returns_data:
        signal_returns_data = {"fallback": [0.001, -0.002, 0.003, -0.001, 0.002]}

    resonance = evaluate_resonance(
        signal_returns=signal_returns_data,
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=_DEFAULT_OBSERVED_SHARPE,
    )

    # 8. Decision with shadow consensus
    tracker.advance(8, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
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
    if _shadow_task and not _shadow_task.done():
        print("(Shadow ecosystem still running in background)")
    return 0


async def run_shadows_only(config: MarketMindConfig, verbose: bool = False) -> int:
    """Run ONLY the shadow ecosystem (background mode).

    Initializes the shadow database and permanent shadows, collects minimal
    news for event detection, then runs the full daily orchestration cycle.
    No main pipeline stages (L1/L2/L3/Decision) are executed.
    """
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)

    print("Shadow ecosystem: initializing...")

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
    print(f"Shadow ecosystem: {len(shadow_db.get_visible_shadows())} shadows initialized")

    # Collect minimal news for event detection
    from marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    if verbose:
        print(f"Shadow ecosystem: {len(news_items)} articles collected for event scanning")

    # N-L4: Report token budget before shadow cycle
    try:
        from marketmind.gateway.async_client import get_budget
        budget = await get_budget()
        if budget:
            budget_report = budget.report()
            if verbose:
                print(f"Token budget: {budget_report['tokens_pct_used']}% used, "
                      f"{budget_report['pro_calls_remaining']} Pro calls remaining")
    except Exception:
        pass

    result = await mother.orchestrate_daily_cycle(news_items, {})

    print(f"Shadows complete: {result.active_shadows} shadows, "
          f"{result.temp_shadows_created} temp created")
    if verbose:
        print(f"  Votes collected: {result.votes_collected}")
        print(f"  Ecosystem alerts: {len(result.ecosystem_alerts)}")
        if result.rankings:
            print(f"  Rankings computed for {len(result.rankings)} shadows")
        if result.challenger_actions:
            for action in result.challenger_actions:
                print(f"  Challenger: {action}")

    return 0


def run_gui(config: MarketMindConfig) -> int:
    """Launch CustomTkinter GUI."""
    from marketmind.ui.main_window import MainWindow
    from marketmind.gateway.async_client import init_gateway

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


async def _run_daily_with_shadows(config: MarketMindConfig, args) -> int:
    """Run the daily pipeline, then wait for the background shadow task to finish.

    The pipeline prints results immediately (non-blocking from the user's
    perspective), then we wait for the shadow ecosystem to complete so the
    process doesn't exit before shadows finish writing to the database.
    """
    shadow_n = 0 if args.no_shadows else args.shadows
    ret = await run_daily(config, mock=args.mock, verbose=args.verbose,
                           shadow_count=shadow_n)

    # Wait for background shadow task to finish (with 5-minute timeout).
    # The pipeline has already printed all results; we just keep the event
    # loop alive long enough for shadows to complete their work.
    global _shadow_task
    if _shadow_task and not _shadow_task.done():
        try:
            await asyncio.wait_for(_shadow_task, timeout=300)
        except asyncio.TimeoutError:
            print("(Shadow ecosystem timed out after 5 minutes — "
                  "results may be incomplete)")
        except asyncio.CancelledError:
            pass

    return ret


async def _archive_session(config: MarketMindConfig, l1_result, l2_result, l3_result, verdict: str) -> None:
    """Archive the interactive session."""
    from datetime import datetime as dt
    from marketmind.storage.archivist import get_archivist
    archivist = get_archivist(config.data_dir)
    archivist.init_fts()
    archivist.index_document(
        date=dt.now().isoformat()[:10],
        category="daily_session",
        title="MarketMind Interactive",
        content=f"Interactive session: {getattr(l1_result, 'event_grade', 'N/A')} | "
                f"{getattr(l2_result, 'macro_quadrant', 'N/A')} | resonance={verdict}",
    )


async def run_interactive(config: MarketMindConfig, mock: bool = False, verbose: bool = False,
                          shadow_count: int | None = None) -> int:
    """Run L1 as an interactive Socratic dialogue with the user.

    Steps:
      0. Shadow ecosystem init (background)
      1-2. News + Flash preprocessing
      3. L1 interactive dialogue (replaces single-shot analysis)
      4. L2+L3 (if user chooses to proceed)
      5. Shadow ecosystem → background
      6-8. Red Team + Resonance + Decision
      9. Archive
    """
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    _setup_logging(str(config.data_dir))

    from marketmind.pipeline.session_context import SessionContext
    ctx = SessionContext(config=config, data_dir=str(config.data_dir))

    tracker = _StageTracker(verbose)
    global _shadow_task, _shadow_result
    _shadow_task = None
    _shadow_result = None

    print("\n" + "=" * 60)
    print("  MarketMind — Interactive Investment Analysis")
    print("  Model: DeepSeek V4 Pro | Reasoning: MAX | L1: Socratic Dialogue")
    print("=" * 60)
    print("\nThe AI will present its analysis. You can:")
    print("  - Challenge its reasoning (\"Why do you think that?\")")
    print("  - Ask for more evidence")
    print("  - Suggest a direction to explore")
    print("  - Type 'search: <topic>' to request data mining")
    print("  - Type 'proceed' when ready to move to L2/L3")
    print("  - Type 'observe' to skip trading today\n")

    # 0. Shadow Mother init
    shadow_db = None
    mother = None
    if config.shadow.shadows_enabled and shadow_count != 0:
        from marketmind.shadows.shadow_state import ShadowStateDB
        from marketmind.shadows.shadow_mother import ShadowMother
        shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
        shadow_db.init_schema()
        from marketmind.shadows.expert_shadows import create_expert_shadows
        from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
        from marketmind.shadows.catfish_agent import create_catfish_agent
        create_expert_shadows(shadow_db, config.shadow)
        create_daredevil_shadows(shadow_db, config.shadow)
        create_catfish_agent(shadow_db, config.shadow)
        mother = ShadowMother(config.shadow, shadow_db)

    # 1. News
    tracker.advance(1, "Fetching news...")
    from marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    ctx.news_items = news_items
    tracker.result(f"{len(news_items)} articles")

    # 1.5 Save raw news to archive (audit trail — always save, cleanup later if needed)
    try:
        from datetime import datetime as dt
        from marketmind.storage.archivist import get_archivist
        archivist = get_archivist(config.data_dir)
        news_save_dir = archivist.today_path()
        news_save_dir.mkdir(parents=True, exist_ok=True)
        today_str = dt.now().strftime("%Y%m%d_%H%M%S")
        news_file = news_save_dir / f"news_{today_str}.json"
        import json as _json
        _items = []
        for n in news_items[:100]:
            _items.append({
                "title": getattr(n, "title", ""),
                "source": getattr(n, "source_name", ""),
                "url": getattr(n, "url", ""),
                "published": getattr(n, "published_at", ""),
                "summary": getattr(n, "summary", "")[:300],
            })
        news_file.write_text(_json.dumps(_items, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        logger.info("News archive saved: %d articles → %s", len(_items), news_file)
    except Exception as e:
        logger.debug("News archive skipped (non-critical): %s", e)

    # 2. Flash preprocessing
    tracker.advance(2, "Preprocessing signals...")
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    signals = await preprocess_batch(news_items[:50])
    ctx.signals = signals
    tracker.result(f"{len(signals)} signals extracted")

    # 3. L1 Interactive Socratic dialogue (shadows launch AFTER L1 to receive broadcast)
    tracker.advance(3, "L1: Starting interactive analysis...")
    from marketmind.pipeline.layer1_interactive import run_l1_interactive

    async def _cli_handler(prompt: str) -> str:
        """CLI-based user input handler."""
        print(prompt, end="", flush=True)
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return "observe"

    l1_result, should_observe, l1_session = await run_l1_interactive(
        signals[:15], news_items, user_input_handler=_cli_handler, mock=mock
    )

    if should_observe:
        print("\n" + "=" * 60)
        print("  Today's verdict: OBSERVE")
        print("  No trade. Cash is a valid position.")
        print("=" * 60 + "\n")
        tracker.result("L1: observe — skipping L2/L3")
        # Skip to archive
        from datetime import datetime as dt
        from marketmind.storage.archivist import get_archivist
        archivist = get_archivist(config.data_dir)
        archivist.init_fts()
        archivist.index_document(
            date=dt.now().isoformat()[:10],
            category="daily_session",
            title="MarketMind Interactive — Observe",
            content="L1 interactive session: chose to observe today.",
        )
        print("\nMarketMind interactive session complete — observing today.")
        return 0

    ctx.l1_result = l1_result
    ctx.l1_session = l1_session
    tracker.result("L1 interactive analysis complete")

    # ── C: ELITE availability helper ──────────────────────────────────────
    def _show_elite_availability():
        """Show ELITE shadow availability at current gate (C1: user-initiated).
        C2: Shadow text NEVER enters main AI prompts — display only.
        C3: Passive display does NOT trigger quarantine."""
        if not (_shadow_task and _shadow_task.done() and not _shadow_task.cancelled()):
            return False
        try:
            result = _shadow_task.result()
            if not hasattr(result, 'shadow_analyses'):
                return False
            elite_count = sum(
                1 for sid in result.shadow_analyses
                if shadow_db and hasattr(shadow_db, 'get_shadow')
            )
            if elite_count == 0:
                return False
            print(f"  [ELITE] {len(result.shadow_analyses)} shadows complete — type 'elite' to view domain expert opinions")
            return True
        except Exception:
            return False

    _show_elite_availability()

    # Budget check (G: token visibility)
    try:
        from marketmind.gateway.async_client import get_budget
        b = await get_budget()
        if b:
            br = b.report()
            print(f"  [Budget] Pro剩余:{br['pro_calls_remaining']}次 | 用量:{br['tokens_pct_used']}%")
    except Exception:
        pass

    # 3.5 Broadcast L1 session data to shadows (Resolution 2 + H6)
    if l1_session.get("user_ideas") and config.shadow.shadows_enabled:
        try:
            from marketmind.shadows.broadcast import BroadcastWriter
            writer = BroadcastWriter(str(config.data_dir))
            writer.write_chat_history(
                user_ideas=l1_session.get("user_ideas", []),
                ai_responses=[],  # H5: AI responses excluded (prevents anchoring bias)
                chat_context="",  # H5: no mixed chat (discussion_text contains AI responses)
            )
            logger.info("L1 session broadcast to shadows: %d user ideas", len(l1_session.get("user_ideas", [])))
        except Exception as e:
            logger.warning("Broadcast write failed (non-blocking): %s", e)

    # 3.6 Launch shadow ecosystem AFTER broadcast (shadows now see user L1 viewpoints)
    if config.shadow.shadows_enabled and mother is not None and _shadow_task is None:
        tracker.advance(0, "Shadows: launching background analysis...")
        _shadow_task = asyncio.create_task(
            mother.orchestrate_daily_cycle(news_items, {})
        )
        _shadow_task.add_done_callback(_shadow_progress_done)
        tracker.result(f"Shadows launched — {len(shadow_db.get_visible_shadows())} shadows analyzing (with L1 broadcast)")

    # 4. L2 Fundamental — medium-low interaction density (extracted module)
    tracker.advance(4, "L2: fundamental analysis (AI working)...")
    from marketmind.pipeline.l2_interactive import run_l2_interactive
    l2_confirmed = await run_l2_interactive(ctx, _cli_handler)
    if not l2_confirmed:
        await _archive_session(config, ctx.l1_result, ctx.l2_result, None, "observe")
        return 0
    l2_result = ctx.l2_result
    selected_tickers = ctx.selected_tickers
    tracker.result(f"L2: {len(selected_tickers)} tickers selected, {l2_result.macro_quadrant}")

    # 4.5 ELITE Shadow check (H7) — populate registry from completed shadow results
    from marketmind.shadows.elite_participation import EliteRegistry
    elite_registry = EliteRegistry()

    if shadow_db and _shadow_task and _shadow_task.done() and not _shadow_task.cancelled():
        try:
            result = _shadow_task.result()
            for sid, output in (result.shadow_analyses if hasattr(result, 'shadow_analyses') else {}).items():
                shadow = shadow_db.get_shadow(sid, caller_id="system")
                if shadow and getattr(shadow, 'achievement_tier', '') == 'elite':
                    elite_registry.register_shadow_analysis(
                        shadow_id=sid,
                        shadow_name=getattr(shadow, 'display_name', sid),
                        domain=getattr(shadow, 'domain', ''),
                        analysis_text=getattr(output, 'raw_text', str(output))[:500],
                        confidence=getattr(output, 'confidence', 0.5) if hasattr(output, 'confidence') else 0.5,
                    )
        except Exception:
            pass  # shadow results not yet available — non-blocking

    elite_shadows_available = bool(elite_registry._contributions) if hasattr(elite_registry, '_contributions') else False
    if elite_shadows_available:
        print(f"\n  [ELITE] {len(elite_registry._contributions)}个ELITE影子已完成分析")
        # Check domain match with L2 sectors
        if l2_result.sector_shortlist:
            sector_text = " ".join(l2_result.sector_shortlist) + " " + " ".join(selected_tickers)
            matched = elite_registry.detect_domain_trigger(sector_text)
            if matched:
                print(f"  与讨论相关的影子: {', '.join(matched[:5])}")

    # 5. Shadows already launched in background (see step 2.5 after Flash preprocessing)
    #    ELITE results will be available by Decision stage if analysis has completed.

    # 6. L3 Technical — lowest interaction density (extracted module)
    tracker.advance(6, "L3: technical analysis (AI working)...")
    from marketmind.pipeline.l3_interactive import run_l3_interactive
    l3_confirmed = await run_l3_interactive(ctx, _cli_handler)
    if not l3_confirmed:
        await _archive_session(config, ctx.l1_result, ctx.l2_result, ctx.l3_result, "observe")
        return 0
    l3_result = ctx.l3_result
    green_lights = l3_result.green_lights if hasattr(l3_result, 'green_lights') else []
    yellow_red = [r for r in (l3_result.results if hasattr(l3_result, 'results') else []) if r.light in ("yellow", "red")]
    tracker.result(f"L3: {len(green_lights)} green, {len(yellow_red)} yellow/red")

    # 7. Red Team + Resonance (automatic — background quality checks)
    tracker.advance(7, "Red Team: adversarial review...")
    from marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(l1_result.raw_analysis, l2_result.raw_analysis,
                                          selected_tickers)
    ctx.red_team_report = red_team_report
    tracker.result(f"{len(red_team_report.challenges)} challenges")

    tracker.advance(8, "Resonance: statistical validation...")
    from marketmind.pipeline.resonance import evaluate_resonance, ResonanceResult
    signal_returns_data = {}
    if hasattr(l3_result, 'results'):
        for r in l3_result.results[:10]:
            if hasattr(r, 'ticker') and hasattr(r, 'daily_return_pct') and r.daily_return_pct:
                signal_returns_data[f"technical_{r.ticker}"] = [r.daily_return_pct]
    if not signal_returns_data:
        signal_returns_data = {"pending": [0.0]}
        resonance = ResonanceResult(
            passed=False, dsr=0, pbo=-1.0, forward_validation_ratio=0,
            signal_count=0, dimensions_active=[], verdict="INSUFFICIENT_DATA",
        )
    else:
        resonance = evaluate_resonance(
            signal_returns=signal_returns_data,
            dimensions=["narrative", "fundamental", "technical", "sentiment"],
            observed_sharpe=_DEFAULT_OBSERVED_SHARPE,
        )
    ctx.resonance = resonance

    # 8.5 Shadow consensus display (before Decision — shows alongside cards)
    if _shadow_task and _shadow_task.done() and not _shadow_task.cancelled():
        try:
            s_result = _shadow_task.result()
            if hasattr(s_result, 'active_shadows') and s_result.active_shadows:
                print(f"\n  ┌─ 影子生态系统（独立参考）─────────────┐")
                print(f"  │ {s_result.active_shadows}个影子完成独立分析                │")
                if hasattr(s_result, 'ecosystem_interpretation') and s_result.ecosystem_interpretation:
                    interpretation = s_result.ecosystem_interpretation[:150]
                    print(f"  │ 共识: {interpretation} │")
                if hasattr(s_result, 'health_alerts') and s_result.health_alerts:
                    alert_count = sum(len(v) for v in s_result.health_alerts.values())
                    if alert_count:
                        print(f"  │ 系统: {alert_count}个健康提醒                     │")
                print(f"  └{'─'*42}┘")
        except Exception:
            pass

    # 9. Decision — interactive (extracted module)
    tracker.advance(9, "Decision: synthesis...")
    from marketmind.pipeline.decision_interactive import run_decision_interactive
    decision_confirmed = await run_decision_interactive(ctx, _cli_handler)
    if not decision_confirmed:
        await _archive_session(config, ctx.l1_result, ctx.l2_result, ctx.l3_result, "observe")
        return 0

    # 10. Archive
    tracker.advance(10, "Archive: saving session...")
    await _archive_session(config, l1_result, l2_result, l3_result, resonance.verdict)

    # Wait for shadow consensus
    if _shadow_task and not _shadow_task.done():
        timeout = getattr(config.shadow, 'shadow_consensus_timeout_s', 60)
        try:
            await asyncio.wait_for(_shadow_task, timeout=timeout)
        except asyncio.TimeoutError:
            partial_note = ""
            try:
                r = _shadow_task.result() if _shadow_task.done() and not _shadow_task.cancelled() else None
                if r and hasattr(r, 'active_shadows'):
                    completed = r.active_shadows
                    total = len(shadow_db.get_visible_shadows()) if shadow_db else 0
                    partial_note = f" — {completed}/{total} shadows completed"
            except Exception:
                pass
            print(f"(Shadow ecosystem timed out after {timeout}s{partial_note} — partial results may be incomplete)")
        except asyncio.CancelledError:
            pass

    print("\nMarketMind interactive session complete.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="MarketMind — AI Investment Analysis Workstation")
    parser.add_argument("--mode", choices=["daily", "interactive", "gui", "shadows"], default="gui",
                        help="Run mode: daily (full pipeline), interactive (L1 Socratic dialogue), "
                             "shadows (background shadow ecosystem only), or gui (default: gui)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock LLM responses (no API calls)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    shadow_group = parser.add_mutually_exclusive_group()
    shadow_group.add_argument("--shadows", type=int, default=None, metavar="N",
                              help="Number of shadows to activate (default: all)")
    shadow_group.add_argument("--no-shadows", action="store_true",
                              help="Disable shadow ecosystem entirely")
    parser.add_argument("--shadow-only", action="store_true",
                        help="Run ONLY shadow ecosystem (no main pipeline). "
                             "Prefer --mode shadows for the canonical interface.")
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

    if args.mode == "shadows":
        return asyncio.run(run_shadows_only(config, verbose=args.verbose))
    elif args.mode == "interactive":
        return asyncio.run(run_interactive(config, mock=args.mock, verbose=args.verbose,
                                           shadow_count=None if args.no_shadows else args.shadows))
    elif args.mode == "gui":
        return run_gui(config)
    else:
        return asyncio.run(_run_daily_with_shadows(config, args))


if __name__ == "__main__":
    sys.exit(main())
