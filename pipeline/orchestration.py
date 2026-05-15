"""MarketMind pipeline orchestration — daily, shadows, backtest, GUI runners.

Extracted from app.py to provide standalone execution paths. All functions
import directly from gateway, pipeline, and shadows modules — no dependency on app.py.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Module-level globals (H1: pipeline separation)
# ══════════════════════════════════════════════════════════════════════════════

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
            logger.info("Shadows complete: %s shadows, %s temp created",
                        result.active_shadows, result.temp_shadows_created)
            global _shadow_result
            _shadow_result = result
    except Exception:
        logger.exception("Shadows error")


# ══════════════════════════════════════════════════════════════════════════════
# _StageTracker — shared helper used by all pipeline modes
# ══════════════════════════════════════════════════════════════════════════════

class _StageTracker:
    def __init__(self, verbose: bool):
        self.verbose = verbose

    def advance(self, stage: int, msg: str) -> None:
        if self.verbose:
            print(f"[{stage}/9] {msg}")

    def result(self, msg: str) -> None:
        if self.verbose:
            print(f"       {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# _archive_session — used by both daily legacy and interactive modes
# ══════════════════════════════════════════════════════════════════════════════

async def _archive_session(config, l1_result, l2_result, l3_result, verdict: str) -> None:
    """Archive a pipeline session."""
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


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline execution functions
# ══════════════════════════════════════════════════════════════════════════════

async def run_daily_legacy(config, mock: bool = False, verbose: bool = False,
                            shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline WITH blocking shadow cycle.

    This is the PRE-SEPARATION legacy behavior. Shadows run synchronously
    and block the main pipeline until complete. Use run_daily() for the
    new non-blocking shadow pipeline.
    """
    from marketmind.config.settings import MarketMindConfig
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


async def run_daily(config, mock: bool = False, verbose: bool = False,
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


async def run_shadows_only(config, verbose: bool = False) -> int:
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


def run_gui(config) -> int:
    """Launch CustomTkinter GUI."""
    from marketmind.ui.main_window import MainWindow
    from marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


def _run_backtest(config, args) -> int:
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


async def _run_daily_with_shadows(config, args) -> int:
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
