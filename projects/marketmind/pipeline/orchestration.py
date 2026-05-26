"""MarketMind pipeline orchestration — daily, shadows, backtest, GUI runners.

Extracted from app.py to provide standalone execution paths. All functions
import directly from gateway, pipeline, and shadows modules — no dependency on app.py.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from marketmind.gateway.async_client import init_gateway

# ── StageTracker extracted to pipeline/stage_tracker.py ─────────────────
from marketmind.pipeline.stage_tracker import StageTracker
_StageTracker = StageTracker  # backward-compat alias for interactive_orchestration.py

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
# _archive_session — used by both daily legacy and interactive modes
# ══════════════════════════════════════════════════════════════════════════════

async def _archive_session(config, l1_result, l2_result, l3_result, verdict: str) -> None:
    """Archive a pipeline session."""
    from datetime import datetime as dt
    from marketmind.storage.archivist import get_archivist
    with get_archivist(config.data_dir) as archivist:
        archivist.init_fts()
        archivist.index_document(
            date=dt.now().isoformat()[:10],
            category="daily_session",
            title="MarketMind Interactive",
            content=f"Interactive session: {getattr(l1_result, 'event_grade', 'N/A')} | "
                    f"{getattr(l2_result, 'macro_quadrant', 'N/A')} | resonance={verdict}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Shared pipeline step helpers (deduplicated from run_daily / run_daily_legacy)
# ══════════════════════════════════════════════════════════════════════════════

async def _do_news_collection(config, tracker: StageTracker) -> list:
    tracker.advance(1, "Scout: fetching news from all sources...")
    from marketmind.pipeline.scout import fetch_all_sources
    items = await fetch_all_sources(config)
    tracker.result(f"{len(items)} articles collected")
    return items


async def _do_flash_preprocessing(news_items: list, tracker: StageTracker) -> list:
    tracker.advance(2, "Flash: preprocessing signals...")
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    signals = await preprocess_batch(news_items[:50])
    _record_z0_flash(len(news_items[:50]), len(signals))
    tracker.result(f"{len(signals)} signals extracted")
    return signals


async def _do_l1_analysis(signals: list, news_items: list, tracker: StageTracker,
                          shadow_db=None):
    tracker.advance(3, "Layer 1: narrative analysis...")
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    # Inject calibration context from past prediction accuracy
    calib = ""
    if shadow_db is not None:
        try:
            from marketmind.pipeline.daily_calibration import get_calibration_context
            calib = get_calibration_context(shadow_db, days=7)
        except Exception:
            pass
    result = await analyze_layer1(signals[:15], news_items, calibration_context=calib)
    if result is None:
        from marketmind.pipeline.layer1_narrative import Layer1Result
        result = Layer1Result.empty_default()
    _record_z0_l1(result)
    tracker.result(f"grade={result.event_grade}, quadrant={result.matrix_quadrant}")
    return result


async def _do_l2_l3_parallel(l1_result, tracker: StageTracker):
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    from marketmind.config.asset_universe import ASSET_UNIVERSE
    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:10]]
    l2_task = analyze_layer2(l1_result)
    l3_task = analyze_layer3(tickers, {})
    l2, l3 = await asyncio.gather(l2_task, l3_task)
    if l2 is None:
        from marketmind.pipeline.layer2_fundamental import Layer2Result
        l2 = Layer2Result()
    if l3 is None:
        from marketmind.pipeline.layer3_technical import Layer3Result
        l3 = Layer3Result()
    tracker.result(f"L2: {len(l2.ticker_candidates)} candidates, "
                   f"L3: {len(l3.results)} tickers ({len(l3.green_lights)} green)")
    return l2, l3


async def _do_red_team(l1_result, l2_result, selected_tickers: list, tracker: StageTracker):
    tracker.advance(6, "Red Team: adversarial challenge...")
    from marketmind.pipeline.red_team import run_red_team, RedTeamReport
    report = await run_red_team(l1_result.raw_analysis, l2_result.raw_analysis, selected_tickers)
    if report is None:
        tracker.result("Red Team timed out — returning empty report")
        return RedTeamReport()
    tracker.result(f"{len(report.challenges)} challenges, A-grade: {report.a_grade_count}")
    return report


async def _do_resonance(l3_result, tracker: StageTracker):
    tracker.advance(7, "Resonance: statistical validation...")
    from marketmind.pipeline.resonance import evaluate_resonance, ResonanceResult
    signal_returns_data = {}
    if hasattr(l3_result, 'results'):
        for r in l3_result.results[:10]:
            if hasattr(r, 'ticker') and hasattr(r, 'daily_return_pct'):
                key = f"technical_{r.ticker}"
                signal_returns_data[key] = [r.daily_return_pct] if r.daily_return_pct else []
    if not signal_returns_data:
        signal_returns_data = {"fallback": [0.001, -0.002, 0.003, -0.001, 0.002]}
    return evaluate_resonance(
        signal_returns=signal_returns_data,
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=_DEFAULT_OBSERVED_SHARPE,
    )


async def _do_decision(l1_result, l2_result, l3_result, red_team, resonance, tracker: StageTracker):
    tracker.advance(8, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(l1=l1_result, l2=l2_result, l3=l3_result,
                                        red_team=red_team, resonance=resonance)
    if decision is None:
        from marketmind.pipeline.decision import DecisionOutput
        decision = DecisionOutput()
    tracker.result(f"cards={len(decision.decision_cards)}, "
                   f"no_trade={'present' if decision.no_trade_card else 'none'}")
    return decision


async def _do_daily_archive(config, l1_result, l2_result, resonance, tracker: StageTracker) -> None:
    tracker.advance(9, "Archive: saving session...")
    from datetime import datetime as dt
    from marketmind.storage.archivist import get_archivist
    with get_archivist(config.data_dir) as a:
        a.init_fts()
        a.index_document(
            date=dt.now().isoformat()[:10],
            category="daily_session",
            title="MarketMind Daily",
            content=f"MarketMind daily: {getattr(l1_result, 'event_grade', 'E')} | "
                    f"{getattr(l2_result, 'macro_quadrant', 'unknown')} | "
                    f"resonance={getattr(resonance, 'verdict', 'unknown')}",
        )
    tracker.result("Session archived")


# ══════════════════════════════════════════════════════════════════════════════
# Shadow ecosystem init (deduplicated from run_daily / run_daily_legacy)
# ══════════════════════════════════════════════════════════════════════════════

def _record_z0_flash(input_count: int, signal_count: int) -> None:
    """Z0: append Flash batch metrics to baseline.jsonl."""
    import json as _j, os as _o
    from datetime import datetime, timezone
    try:
        d = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", ".claude", "metrics")
        _o.makedirs(d, exist_ok=True)
        r = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": "flash",
             "articles_in": input_count, "signals_out": signal_count}
        with open(_o.path.join(d, "baseline.jsonl"), "a", encoding="utf-8") as f:
            f.write(_j.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record_z0_l1(l1_result) -> None:
    """Z0: append L1 analysis metrics to baseline.jsonl."""
    import json as _j, os as _o
    from datetime import datetime, timezone
    try:
        d = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", ".claude", "metrics")
        _o.makedirs(d, exist_ok=True)
        r = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": "l1",
             "event_grade": getattr(l1_result, "event_grade", "N/A"),
             "matrix_quadrant": getattr(l1_result, "matrix_quadrant", "N/A"),
             "sentiment": getattr(l1_result, "sentiment_direction", "N/A")}
        with open(_o.path.join(d, "baseline.jsonl"), "a", encoding="utf-8") as f:
            f.write(_j.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _init_shadow_ecosystem(config, shadow_count: int | None, tracker: StageTracker):
    """Init shadow DB + permanent shadows + optional Phase F modules."""
    if not (config.shadow.shadows_enabled and shadow_count != 0):
        return None, None
    tracker.advance(0, "Shadow Mother: scanning events...")
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.shadows.shadow_mother import ShadowMother
    db = ShadowStateDB(config.shadow.shadows_db_path)
    db.init_schema()
    from marketmind.shadows.expert_shadows import create_expert_shadows
    from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    from marketmind.shadows.catfish_agent import create_catfish_agent
    create_expert_shadows(db, config.shadow)
    create_daredevil_shadows(db, config.shadow)
    create_catfish_agent(db, config.shadow)
    mother = ShadowMother(config.shadow, db)
    tracker.result(f"Shadow ecosystem initialized with {len(db.get_visible_shadows())} shadows")
    if getattr(config.shadow, 'scheduler_enabled', False):
        from marketmind.shadows.background_scheduler import BackgroundScheduler, SchedulerConfig
        from marketmind.shadows.shadow_memory import ShadowMemoryStore
        ms = ShadowMemoryStore(db)
        sc = SchedulerConfig(reflection_interval_minutes=config.shadow.reflection_interval_minutes,
                             crystallization_interval_hours=config.shadow.crystallization_interval_hours,
                             max_concurrent_tasks=config.shadow.max_concurrent_tasks, enabled=True)
        BackgroundScheduler(ms, db, mother, sc).start()
        tracker.result("Background scheduler started")
    if getattr(config.shadow, 'gemini_flash_enabled', False):
        from marketmind.gateway.multimodal_adapter import MultimodalAdapter
        MultimodalAdapter()
        tracker.result("Gemini Flash multimodal adapter initialized")
    return db, mother


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

    tracker = StageTracker(verbose)
    shadow_db, mother = _init_shadow_ecosystem(config, shadow_count, tracker)

    # Steps 1-4: Shared pipeline core
    news_items = await _do_news_collection(config, tracker)
    signals = await _do_flash_preprocessing(news_items, tracker)
    l1_result = await _do_l1_analysis(signals, news_items, tracker, shadow_db=shadow_db)
    l2_result, l3_result = await _do_l2_l3_parallel(l1_result, tracker)

    # Step 5: Shadow ecosystem run (BLOCKING — legacy behavior)
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(5, "Shadows: running analysis cycle...")
        orchestration = await mother.orchestrate_daily_cycle(news_items, {})
        tracker.result(f"{orchestration.active_shadows} shadows, "
                       f"{orchestration.temp_shadows_created} temp created")
        if getattr(config.shadow, 'crystallization_enabled', False):
            tracker.result("Memory updated, crystallization check complete")

    # Steps 6-9: Shared pipeline core
    red_team = await _do_red_team(l1_result, l2_result, l2_result.ticker_candidates, tracker)
    resonance = await _do_resonance(l3_result, tracker)
    decision = await _do_decision(l1_result, l2_result, l3_result, red_team, resonance, tracker)
    await _do_daily_archive(config, l1_result, l2_result, resonance, tracker)

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
    from marketmind.gateway.async_client import set_mock_mode
    set_mock_mode(mock)

    tracker = StageTracker(verbose)
    global _shadow_task, _shadow_result
    _shadow_result = None
    shadow_db, mother = _init_shadow_ecosystem(config, shadow_count, tracker)

    # Steps 1-4: Shared pipeline core
    news_items = await _do_news_collection(config, tracker)
    signals = await _do_flash_preprocessing(news_items, tracker)
    l1_result = await _do_l1_analysis(signals, news_items, tracker, shadow_db=shadow_db)
    l2_result, l3_result = await _do_l2_l3_parallel(l1_result, tracker)

    # Step 5: Shadow ecosystem → NON-BLOCKING background launch (H1)
    if config.shadow.shadows_enabled and mother is not None:
        tracker.advance(5, "Shadows: launching background analysis...")
        try:
            from marketmind.gateway.async_client import get_budget
            budget = await get_budget()
            if budget:
                br = budget.report()
                tracker.result(f"Token budget: {br['tokens_pct_used']}% used, "
                               f"{br['pro_calls_remaining']} Pro calls remaining")
        except Exception:
            pass
        _shadow_progress_started()
        _shadow_task = asyncio.create_task(mother.orchestrate_daily_cycle(news_items, {}))
        _shadow_task.add_done_callback(_shadow_progress_done)
        tracker.result("Shadows launched in background (non-blocking)")
        if getattr(config.shadow, 'crystallization_enabled', False):
            tracker.result("Memory update + crystallization will run in background")

    # Steps 6-9: Shared pipeline core
    red_team = await _do_red_team(l1_result, l2_result, l2_result.ticker_candidates, tracker)
    resonance = await _do_resonance(l3_result, tracker)
    decision = await _do_decision(l1_result, l2_result, l3_result, red_team, resonance, tracker)
    await _do_daily_archive(config, l1_result, l2_result, resonance, tracker)

    # Save today's prediction for tomorrow's calibration feedback loop
    _save_daily_prediction(l1_result, l2_result, decision)

    print("\nMarketMind daily pipeline complete.")
    if _shadow_task and not _shadow_task.done():
        print("(Shadow ecosystem still running in background)")
    return 0


def _save_daily_prediction(l1_result, l2_result, decision) -> None:
    """Persist today's pipeline output for next-day calibration."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        from marketmind.pipeline.daily_calibration import DailyPrediction, save_prediction
        pred = DailyPrediction(
            date=_dt.now(_tz.utc).strftime("%Y-%m-%d"),
            l1_grade=getattr(l1_result, "event_grade", "E"),
            l1_quadrant=getattr(l1_result, "matrix_quadrant", "observe_skip"),
            l1_direction=getattr(l1_result, "sentiment_direction", "neutral"),
            ticker_candidates=getattr(l2_result, "ticker_candidates", []) or [],
            decisions=[
                {"ticker": c.ticker, "direction": c.direction}
                for c in getattr(decision, "decision_cards", [])
            ],
        )
        save_prediction(pred)
    except Exception:
        pass


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
        print(f"  Decisions collected: {result.decisions_collected}")
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
