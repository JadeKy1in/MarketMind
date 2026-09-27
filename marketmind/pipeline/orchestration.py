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
from marketmind.pipeline.stage_tracker import StageTracker, _report_stage_progress
_StageTracker = StageTracker  # backward-compat alias for interactive_orchestration.py

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Module-level globals (H1: pipeline separation)
# ══════════════════════════════════════════════════════════════════════════════

_shadow_task: "asyncio.Task | None" = None
_shadow_result = None  # stores ShadowOrchestrationResult when background task completes

# Only interactive_orchestration still evaluates resonance (legacy path, to be
# redesigned with alert-driven interaction). The daily pipeline no longer does.
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

async def _do_news_collection(config, tracker: StageTracker, mock: bool = False) -> list:
    tracker.advance(1, "Scout: fetching news from all sources...")
    from marketmind.pipeline.scout import fetch_all_sources
    # Mock runs must not touch the cross-run novelty cache, or they mark real
    # articles as already seen before the next live run.
    items = await fetch_all_sources(config, use_cross_run_cache=not mock) or []
    repeats = sum(getattr(i, "seen_before", False) for i in items)
    tracker.result(f"{len(items)} articles collected ({repeats} seen in last 72h, down-weighted)")
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
            logger.warning("_do_l1_analysis: non-blocking step failed", exc_info=True)
        # Layer 2: weekly tactical audit suggestions
        try:
            from marketmind.pipeline.weekly_tactical_audit import get_suggestion_context
            weekly = get_suggestion_context(shadow_db)
            if weekly:
                calib = (calib or "") + "\n" + weekly
        except Exception:
            logger.warning("_do_l1_analysis: non-blocking step failed", exc_info=True)
    result = await analyze_layer1(signals[:15], news_items, calibration_context=calib)
    if result is None:
        from marketmind.pipeline.layer1_narrative import Layer1Result
        result = Layer1Result.empty_default()
    _record_z0_l1(result)
    tracker.result(f"grade={result.event_grade}, quadrant={result.matrix_quadrant}")
    return result


def _core_l3_tickers(limit: int = 10) -> list[str]:
    """Market-context tickers L3 always reviews (index/sector ETFs from the universe)."""
    from marketmind.config.asset_universe import ASSET_UNIVERSE
    return [a.ticker for a in list(ASSET_UNIVERSE.values())[:limit]]


async def _do_l2_l3_parallel(l1_result, tracker: StageTracker, shadow_db=None):
    """L2 then L3. L3 reviews L2's ticker list (design spec §4.3: it receives the
    list, never L2's reasoning) plus the core market tickers. L3 is code-only and
    fast, so running it after L2 costs no LLM time."""
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    l2_calib = _get_stage_calibration("l2", shadow_db) if shadow_db else ""
    l2 = await (analyze_layer2(l1_result, calibration_context=l2_calib) if l2_calib
                else analyze_layer2(l1_result))
    if l2 is None:
        from marketmind.pipeline.layer2_fundamental import Layer2Result
        l2 = Layer2Result()
    l2_list = [str(t).strip().upper() for t in (l2.ticker_candidates or []) if str(t).strip()]
    l3 = await analyze_layer3(l2_list + _core_l3_tickers())
    if l3 is None:
        from marketmind.pipeline.layer3_technical import Layer3BatchResult
        l3 = Layer3BatchResult()
    # L2→L3 fallback: if L2 found tickers but L3 all red, flag for re-selection next run
    l2_tickers = set(l2.ticker_candidates or [])
    l3_green = {r.ticker for r in (l3.results or []) if getattr(r, 'light', 'red') == 'green'}
    if l2_tickers and not (l2_tickers & l3_green):
        tracker.result(f"L2: {len(l2.ticker_candidates)} candidates, "
                       f"L3: {len(l3.results)} tickers ({len(l3.green_lights)} green) "
                       f"[WARN: L2-L3 mismatch — all L2 picks are L3 red]")
    else:
        tracker.result(f"L2: {len(l2.ticker_candidates)} candidates, "
                       f"L3: {len(l3.results)} tickers ({len(l3.green_lights)} green)")
    return l2, l3


def _get_stage_calibration(stage: str, shadow_db, days: int = 7) -> str:
    """Load per-stage calibration context for L2/L3/Decision prompt injection."""
    try:
        from marketmind.pipeline.daily_calibration import get_stage_calibration
        return get_stage_calibration(stage, shadow_db, days)
    except Exception:
        logger.warning("stage calibration for %s unavailable", stage, exc_info=True)
        return ""


async def _do_fragility_scan(tracker: StageTracker):
    """Stage 7b: Market fragility scan — zero-LLM, fed with live inputs."""
    tracker.advance(7, "Fragility: scanning market thresholds...")
    from marketmind.pipeline.fragility_scanner import scan_fragility, FragilityReport
    from marketmind.gateway.fragility_inputs import fetch_fragility_inputs
    try:
        inputs = await fetch_fragility_inputs()
        report = await scan_fragility(inputs.values, unavailable=inputs.unavailable)
        tracker.result(f"fragility={report.overall_fragility_score:.2f}, "
                       f"crossed={len(report.crossed)}, evaluated={len(report.alerts)}, "
                       f"unavailable={len(report.unavailable)}")
        return report
    except Exception:
        logger.exception("Fragility scan failed")
        tracker.result("Fragility scan FAILED — not evaluated (see log)")
        return FragilityReport(alerts=[], crossed=[], warnings=[],
                               overall_fragility_score=0.0, staleness_warnings=[],
                               summary="fragility not evaluated (scan failed)",
                               unavailable={"*": "scan failed"})


def _resonance_not_evaluated():
    """SPEC_v3 §5 step 7: DSR/PBO is a promotion-review tool, not a daily gate.
    Downstream code still expects a ResonanceResult, so pass an explicit
    NOT_EVALUATED marker instead of a fabricated NO_SIGNAL."""
    from marketmind.pipeline.resonance import ResonanceResult
    return ResonanceResult(passed=False, dsr=0.0, pbo=0.0, forward_validation_ratio=0.0,
                           signal_count=0, dimensions_active=[], verdict="NOT_EVALUATED")


async def _do_red_team(l1_result, l2_result, selected_tickers: list, tracker: StageTracker):
    tracker.advance(6, "Red Team: adversarial challenge...")
    from marketmind.pipeline.red_team import run_red_team, RedTeamReport
    report = await run_red_team(l1_result.raw_analysis, l2_result.raw_analysis, selected_tickers)
    if report is None:
        tracker.result("Red Team timed out — returning empty report")
        return RedTeamReport()
    tracker.result(f"{len(report.challenges)} challenges, A-grade: {report.a_grade_count}")
    return report


async def _do_decision(l1_result, l2_result, l3_result, red_team, resonance,
                       fragility, tracker: StageTracker):
    tracker.advance(8, "Decision: synthesis...")
    from marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(l1=l1_result, l2=l2_result, l3=l3_result,
                                        red_team=red_team, resonance=resonance,
                                        fragility=fragility)
    if decision is None:
        # @monitor returns None on timeout/exception. "No trade" must still be explicit.
        from marketmind.pipeline.decision import DecisionOutput, NoTradeCard, _pick_paper_trade
        logger.warning("Decision stage returned nothing (timeout or error) — explicit no-trade")
        decision = DecisionOutput(
            no_trade_card=NoTradeCard(
                thesis="Decision synthesis did not complete (timeout or error); defaulting to no trade.",
                supporting_evidence=["decision stage returned None — see log"],
                counterfactual="A completed decision synthesis with at least one validated card.",
                structural_advantages=["safe default when synthesis is unavailable"],
                no_trade_score=100.0,
            ),
            paper_trade=_pick_paper_trade(l1_result, l2_result, l3_result, red_team, resonance),
            summary="decision stage unavailable",
        )
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
        logger.debug("_record_z0_flash: non-blocking step failed", exc_info=True)


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
        logger.debug("_record_z0_l1: non-blocking step failed", exc_info=True)


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
    create_expert_shadows(db, config.shadow)
    create_daredevil_shadows(db, config.shadow)
    from marketmind.shadows.zombie_detector import detect_zombies
    detect_zombies(db)
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
    news_items = await _do_news_collection(config, tracker, mock=mock)
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
    resonance = _resonance_not_evaluated()
    fragility = await _do_fragility_scan(tracker)
    decision = await _do_decision(l1_result, l2_result, l3_result, red_team, resonance,
                                   fragility, tracker)
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

    # Settle whatever in the ledger has come due before making new calls (SPEC_v3 §7)
    if not mock:
        await settle_ledger(config)

    # Steps 1-3: Scout → Flash → L1
    news_items = await _do_news_collection(config, tracker, mock=mock)
    signals = await _do_flash_preprocessing(news_items, tracker)
    l1_result = await _do_l1_analysis(signals, news_items, tracker, shadow_db=shadow_db)

    # Gate: L1 early terminate — if nothing actionable, skip expensive downstream stages
    skip_to_decision = (
        l1_result.event_grade == 'E'
        and l1_result.matrix_quadrant in ('observe_skip',)
        and len(signals) == 0
    )
    resonance = _resonance_not_evaluated()
    if skip_to_decision:
        tracker.advance(4, "No actionable signals (grade=E, observe_skip, 0 signals) — "
                           "skipping L2+Shadows+RedTeam (LLM); L3 + fragility still run (code-only)")
        from marketmind.pipeline.layer2_fundamental import Layer2Result
        from marketmind.pipeline.layer3_technical import analyze_layer3
        from marketmind.pipeline.red_team import RedTeamReport
        l2_result = Layer2Result()
        l3_result = await analyze_layer3(_core_l3_tickers())
        red_team = RedTeamReport()
        tracker.result(f"L3 market context: {len(l3_result.results)} tickers, "
                       f"{len(l3_result.green_lights)} green")
        fragility = await _do_fragility_scan(tracker)
    else:
        # Steps 4: L2+L3 with per-stage calibration
        l2_result, l3_result = await _do_l2_l3_parallel(l1_result, tracker, shadow_db=shadow_db)

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
                logger.warning("run_daily: non-blocking step failed", exc_info=True)
            _shadow_progress_started()
            _shadow_task = asyncio.create_task(mother.orchestrate_daily_cycle(news_items, {}))
            _shadow_task.add_done_callback(_shadow_progress_done)
            tracker.result("Shadows launched in background (non-blocking)")
            if getattr(config.shadow, 'crystallization_enabled', False):
                tracker.result("Memory update + crystallization will run in background")

        # Steps 6-7b: Red Team → Fragility (Resonance moved to promotion review, SPEC_v3 §5)
        red_team = await _do_red_team(l1_result, l2_result, l2_result.ticker_candidates, tracker)
        fragility = await _do_fragility_scan(tracker)

    # Step 8: Decision — always runs (with fragility + per-stage calibration)
    decision = await _do_decision(l1_result, l2_result, l3_result, red_team, resonance,
                                   fragility, tracker)
    await _do_daily_archive(config, l1_result, l2_result, resonance, tracker)

    # Save today's prediction for tomorrow's calibration feedback loop
    _save_daily_prediction(l1_result, l2_result, l3_result, decision)

    # Save full reasoning brief for dashboard drill-down
    _save_decision_brief(l1_result, l2_result, l3_result, red_team, resonance,
                         decision, fragility=fragility)

    # Every card / forced paper trade goes into the unified ledger (mock runs never do)
    if not mock:
        await _record_to_ledger(config, decision, l3_result)

    # Record pipeline metrics for weekly tactical audit
    _record_pipeline_metrics(
        flash_results=signals, l1_result=l1_result, l2_result=l2_result,
        l3_result=l3_result, red_team_report=red_team, resonance=resonance,
        decision=decision, mock=mock,
    )

    # Trigger weekly audit if due (every 7 days)
    await _maybe_run_weekly_audit(shadow_db)

    print("\nMarketMind daily pipeline complete.")
    _report_stage_progress(9, "Pipeline complete", "done")
    if _shadow_task and not _shadow_task.done():
        print("(Shadow ecosystem still running in background)")
    return 0


def _ledger_store(config):
    from marketmind.ledger.store import LedgerStore
    return LedgerStore(Path(config.data_dir) / "ledger.db")


async def settle_ledger(config) -> str:
    """Settle due ledger records; never blocks the pipeline, but failures are logged."""
    try:
        from marketmind.ledger.prices import HistoryPriceSource
        from marketmind.ledger.settlement import settle_all
        report = await settle_all(_ledger_store(config), HistoryPriceSource())
        print(f"  [ledger] {report.summary()}")
        return report.summary()
    except Exception:
        logger.error("Ledger settlement failed (records stay unsettled)", exc_info=True)
        return "ledger settlement failed"


async def _record_to_ledger(config, decision, l3_result) -> None:
    try:
        from marketmind.ledger.prices import HistoryPriceSource
        from marketmind.ledger.recorder import record_main_decision
        ids = await record_main_decision(decision, l3_result, _ledger_store(config),
                                         HistoryPriceSource())
        print(f"  [ledger] recorded {len(ids)} entr{'y' if len(ids) == 1 else 'ies'}")
    except Exception:
        logger.error("Ledger recording failed — today's calls are NOT in the ledger", exc_info=True)


def _save_daily_prediction(l1_result, l2_result, l3_result, decision) -> None:
    """Persist today's pipeline output for next-day calibration (all stages)."""
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
            # Per-stage outcomes for calibration
            l2_sectors=getattr(l2_result, "sector_shortlist", []) or [],
            l2_sector_directions=getattr(l2_result, "sector_directions", {}) or {},
            l3_green_tickers=[
                r.ticker for r in (getattr(l3_result, "results", []) or [])
                if getattr(r, "light", "red") == "green"
            ],
            l3_red_tickers=[
                r.ticker for r in (getattr(l3_result, "results", []) or [])
                if getattr(r, "light", "red") == "red"
            ],
            decision_no_trade=getattr(decision, "no_trade_card", None) is not None,
        )
        save_prediction(pred)
    except Exception:
        logger.warning("_save_daily_prediction: non-blocking step failed", exc_info=True)


def _save_decision_brief(l1_result, l2_result, l3_result, red_team, resonance, decision,
                          fragility=None) -> None:
    """Save full reasoning chain for dashboard drill-down."""
    import json
    from datetime import datetime as _dt, timezone as _tz
    from pathlib import Path

    try:
        today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
        brief_dir = Path(__file__).resolve().parent.parent / ".claude" / "briefs"
        brief_dir.mkdir(parents=True, exist_ok=True)

        # L1
        l1_text = ""
        if l1_result:
            l1_text = getattr(l1_result, 'raw_analysis', '') or ''
        # L2
        l2_tickers = []
        if l2_result:
            candidates = getattr(l2_result, 'ticker_candidates', []) or []
            l2_tickers = [str(t) for t in candidates[:10]]
        # L3
        l3_green = []
        l3_yellow = []
        l3_red = []
        if l3_result:
            for r in getattr(l3_result, 'green_lights', []) or []:
                l3_green.append(getattr(r, 'ticker', '?'))
            for r in getattr(l3_result, 'yellow_lights', []) or []:
                l3_yellow.append(getattr(r, 'ticker', '?'))
            for r in getattr(l3_result, 'red_lights', []) or []:
                l3_red.append(getattr(r, 'ticker', '?'))
        # Red Team
        rt_challenges = []
        if red_team:
            for c in getattr(red_team, 'challenges', []) or []:
                rt_challenges.append({
                    "severity": getattr(c, 'severity', 'medium'),
                    "challenge": getattr(c, 'challenge', '')[:300],
                })
        # Resonance
        res_verdict = ""
        res_dsr = 0.0
        if resonance:
            res_verdict = getattr(resonance, 'verdict', '') or ''
            res_dsr = getattr(resonance, 'dsr', 0.0) or 0.0
        # Decision
        from dataclasses import asdict, is_dataclass
        dec_summary = ""
        dec_cards = []
        has_no_trade = False
        no_trade_thesis = ""
        if decision:
            dec_summary = getattr(decision, 'summary', '') or ''
            for c in getattr(decision, 'decision_cards', []) or []:
                full = asdict(c) if is_dataclass(c) else {}
                dec_cards.append({
                    **full,
                    # legacy keys the dashboard reads ("confidence" was always the size %)
                    "ticker": getattr(c, 'ticker', ''),
                    "direction": getattr(c, 'direction', ''),
                    "confidence": getattr(c, 'position_size_pct', 0),
                    "thesis": getattr(c, 'thesis', '')[:200],
                })
            ntc = getattr(decision, 'no_trade_card', None)
            if ntc:
                has_no_trade = True
                no_trade_thesis = getattr(ntc, 'thesis', '') or ''
                if not dec_cards:
                    dec_summary = no_trade_thesis or dec_summary

        # Paper trade (virtual investment when no_trade)
        paper_trade = None
        pt = getattr(decision, 'paper_trade', None)
        if pt:
            paper_trade = {
                "ticker": pt.ticker,
                "direction": pt.direction,
                "confidence": pt.confidence,
                "thesis": pt.thesis,
                "source": pt.source,
            }

        # Fragility
        fragility_score = 0.0
        fragility_crossed = 0
        if fragility:
            fragility_score = getattr(fragility, 'overall_fragility_score', 0.0) or 0.0
            fragility_crossed = len(getattr(fragility, 'crossed', []) or [])

        brief = {
            "date": today,
            "has_no_trade": has_no_trade,
            "decision_summary": dec_summary[:2000],
            "no_trade_thesis": no_trade_thesis[:1000],
            "decision_cards": dec_cards,
            "decision_raw": getattr(decision, 'raw_response', '') if decision else '',
            "l3_details": [getattr(r, 'raw_analysis', '') for r in (getattr(l3_result, 'results', []) or [])],
            "l1_analysis": l1_text[:1500],
            "l2_ticker_candidates": l2_tickers,
            "l3_green": l3_green,
            "l3_yellow": l3_yellow,
            "l3_red": l3_red,
            "red_team_challenges": rt_challenges,
            "resonance_verdict": res_verdict,
            "resonance_dsr": res_dsr,
            "fragility_score": fragility_score,
            "fragility_crossed": fragility_crossed,
            "fragility_summary": getattr(fragility, 'summary', '') if fragility else '',
            "fragility_unavailable": getattr(fragility, 'unavailable', {}) if fragility else {},
            "paper_trade": paper_trade,
        }
        fpath = brief_dir / f"{today}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning("_save_decision_brief: non-blocking step failed", exc_info=True)


def _record_pipeline_metrics(flash_results=None, l1_result=None, l2_result=None,
                             l3_result=None, red_team_report=None, resonance=None,
                             decision=None, mock: bool = False) -> None:
    """Record daily pipeline metrics for weekly tactical audit."""
    try:
        from marketmind.pipeline.pipeline_metrics import (
            PipelineMetrics, collect_metrics_from_session, record_metrics,
        )
        m = collect_metrics_from_session(
            flash_results=flash_results, l1_result=l1_result, l2_result=l2_result,
            l3_result=l3_result, red_team_report=red_team_report, resonance=resonance,
            decision=decision, mock=mock,
        )
        record_metrics(m)
    except Exception:
        logger.warning("_record_pipeline_metrics: non-blocking step failed", exc_info=True)


async def _maybe_run_weekly_audit(shadow_db) -> None:
    """Run weekly tactical audit if 7+ days since last audit."""
    from pathlib import Path
    from datetime import datetime as _dt, timezone as _tz, timedelta

    audit_dir = Path(__file__).resolve().parent.parent / ".claude" / "metrics"
    audit_path = audit_dir / "weekly_audit_latest.json"

    if audit_path.exists():
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                last = __import__('json').loads(f.read())
            last_date = last.get("week_end", "")
            if last_date:
                last_dt = _dt.strptime(last_date, "%Y-%m-%d").date()
                if (_dt.now(_tz.utc).date() - last_dt).days < 7:
                    return  # Not due yet
        except Exception:
            logger.warning("_maybe_run_weekly_audit: non-blocking step failed", exc_info=True)

    try:
        from marketmind.pipeline.weekly_tactical_audit import (
            run_weekly_audit, save_latest_audit,
        )
        result = await run_weekly_audit(shadow_db)
        if result and result.suggestions:
            save_latest_audit(result)
            logger.info("Weekly audit complete: %d suggestions", len(result.suggestions))
    except Exception:
        logger.warning("_maybe_run_weekly_audit: non-blocking step failed", exc_info=True)

    # Layer 3: Cross-stage attribution (when direction accuracy is poor)
    try:
        from marketmind.pipeline.methodology_evolution import run_cross_stage_attribution
        from marketmind.pipeline.pipeline_metrics import load_recent_metrics
        metrics = load_recent_metrics(days=30)
        attrib_batch = await run_cross_stage_attribution(metrics, shadow_db=shadow_db)
        if attrib_batch and attrib_batch.attributions:
            for attr in attrib_batch.attributions:
                logger.info("Attribution: %s (confidence=%.2f) — %s",
                            attr.primary_failure_stage, attr.confidence,
                            attr.evidence[:150])
            if attrib_batch.hypotheses:
                logger.info("Attribution: %d hypotheses generated for RuleValidator",
                            len(attrib_batch.hypotheses))
    except Exception:
        logger.warning("_maybe_run_weekly_audit: non-blocking step failed", exc_info=True)


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

    # Initialize permanent shadows (16 experts + 8 daredevils)
    from marketmind.shadows.expert_shadows import create_expert_shadows
    from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    create_expert_shadows(shadow_db, config.shadow)
    create_daredevil_shadows(shadow_db, config.shadow)
    from marketmind.shadows.zombie_detector import detect_zombies
    detect_zombies(shadow_db)

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
        logger.warning("run_shadows_only: non-blocking step failed", exc_info=True)

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
