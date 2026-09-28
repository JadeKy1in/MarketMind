"""MarketMind pipeline orchestration — daily, shadows, settle, evidence, GUI runners.

Extracted from app.py to provide standalone execution paths. All functions
import directly from gateway, pipeline, and shadows.v3 modules — no dependency on app.py.
"""
from __future__ import annotations
import asyncio
import json
import logging
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
_evidence_task: "asyncio.Task | None" = None
_playground_task: "asyncio.Task | None" = None

# Only interactive_orchestration still evaluates resonance (legacy path, to be
# redesigned with alert-driven interaction). The daily pipeline no longer does.
_DEFAULT_OBSERVED_SHARPE = 0.5


# ══════════════════════════════════════════════════════════════════════════════
# _archive_session — used by interactive mode
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
# Shared pipeline step helpers
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


async def _do_l1_analysis(signals: list, news_items: list, tracker: StageTracker):
    tracker.advance(3, "Layer 1: narrative analysis...")
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    result = await analyze_layer1(signals[:15], news_items, calibration_context="")
    if result is None:
        from marketmind.pipeline.layer1_narrative import Layer1Result
        result = Layer1Result.empty_default()
    _record_z0_l1(result)
    tracker.result(f"grade={result.event_grade}, quadrant={result.matrix_quadrant}")
    return result


# Market-context tickers L3 always reviews, so it has a cross-asset read even when
# L1/L2 surface nothing: broad equity indices (large/small cap, Dow), long Treasuries,
# precious metals, energy and agriculture. A deliberate, small curated list for
# market context only -- which tickers are tradable is decided by marketmind.universe.
CORE_L3_TICKERS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV", "USO", "UNG", "DBA",
)


def _core_l3_tickers(limit: int = 10) -> list[str]:
    """Market-context tickers L3 always reviews (see CORE_L3_TICKERS)."""
    return list(CORE_L3_TICKERS[:limit])


async def _do_l2_l3_parallel(l1_result, tracker: StageTracker):
    """L2 then L3. L3 reviews L2's ticker list (design spec §4.3: it receives the
    list, never L2's reasoning) plus the core market tickers. L3 is code-only and
    fast, so running it after L2 costs no LLM time."""
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    l2 = await analyze_layer2(l1_result)
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


async def _do_fragility_scan(tracker: StageTracker):
    """Stage 7b: Market fragility scan — zero-LLM, fed with live inputs."""
    tracker.advance(7, "Fragility: scanning market thresholds...")
    from marketmind.pipeline.fragility_scanner import scan_fragility, FragilityReport
    from marketmind.gateway.fragility_inputs import fetch_fragility_inputs
    try:
        inputs = await fetch_fragility_inputs()
        report = await scan_fragility(inputs.values, unavailable=inputs.unavailable)
        score = report.overall_fragility_score
        tracker.result(f"fragility={'not evaluated' if score is None else f'{score:.2f}'}, "
                       f"crossed={len(report.crossed)}, evaluated={len(report.alerts)}, "
                       f"unavailable={len(report.unavailable)}")
        return report
    except Exception:
        logger.exception("Fragility scan failed")
        tracker.result("Fragility scan FAILED — not evaluated (see log)")
        return FragilityReport(alerts=[], crossed=[], warnings=[],
                               overall_fragility_score=None, staleness_warnings=[],
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


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline execution functions
# ══════════════════════════════════════════════════════════════════════════════

async def run_daily(config, mock: bool = False, verbose: bool = False,
                     shadow_count: int | None = None) -> int:
    """Execute full daily analysis pipeline.

    S3 shadows (marketmind.shadows.v3) run as a non-blocking background task
    so the main pipeline completes and displays results without waiting for them.
    """
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    from marketmind.gateway.async_client import set_mock_mode
    set_mock_mode(mock)

    tracker = StageTracker(verbose)
    global _shadow_task
    from marketmind.gateway import usage_tracker
    usage_tracker.reset()
    # Load the tradable universe off the event loop: its first download is a blocking
    # HTTP call that guard / ledger would otherwise make from inside async code.
    from marketmind.universe import get_equity_universe
    await asyncio.to_thread(get_equity_universe)

    # Settle whatever in the ledger has come due before making new calls (SPEC_v3 §7)
    if not mock:
        await settle_ledger(config)

    # Steps 1-3: Scout → Flash → L1
    news_items = await _do_news_collection(config, tracker, mock=mock)

    # S3 shadows: forced daily decisions into the ledger, in parallel with the main
    # pipeline; they see only news and prices, never main-pipeline output (§3.5).
    if config.shadow.shadows_enabled and shadow_count != 0 and not mock:
        _shadow_task = asyncio.create_task(run_v3_shadows(config, news_items, shadow_count))
        print("  [shadows] daily decisions launched in background")
    # S8 Playground candidates: their calls go into the ledger, in the background.
    if not mock:
        global _playground_task
        _playground_task = asyncio.create_task(run_playground(config, news_items))
    # S5 evidence layer: news claims checked against primary data, in the background.
    if not mock:
        global _evidence_task
        _evidence_task = asyncio.create_task(run_evidence(config, news_items))
        print("  [evidence] claim checks launched in background")

    signals = await _do_flash_preprocessing(news_items, tracker)
    l1_result = await _do_l1_analysis(signals, news_items, tracker)

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
        # Step 4: L2+L3
        l2_result, l3_result = await _do_l2_l3_parallel(l1_result, tracker)

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
        _record_missed_path(config)

    # Record pipeline metrics for weekly tactical audit
    _record_pipeline_metrics(
        flash_results=signals, l1_result=l1_result, l2_result=l2_result,
        l3_result=l3_result, red_team_report=red_team, resonance=resonance,
        decision=decision, mock=mock,
    )

    # Trigger weekly audit if due (every 7 days)
    await _maybe_run_weekly_audit()

    print(f"  [tokens] {usage_tracker.summary_line()}")
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
    from marketmind.gateway import usage_tracker

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
        fragility_score = None  # None = not evaluated (never shown as 0 = "no fragility")
        fragility_crossed = 0
        if fragility:
            fragility_score = getattr(fragility, 'overall_fragility_score', None)
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
            # LLM tokens so far this run; background shadows count under "other"
            "token_usage": usage_tracker.snapshot(),
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


async def _maybe_run_weekly_audit() -> None:
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
        result = await run_weekly_audit()
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
        attrib_batch = await run_cross_stage_attribution(metrics)
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


async def run_v3_shadows(config, news_items: list, limit: int | None = None):
    """S3 daily shadow decisions -> ledger; prints a one-line summary."""
    from marketmind.shadows.v3 import roster
    from marketmind.shadows.v3.runner import default_report_dir, run_shadow_day
    entries = roster.active()
    if limit:
        entries = entries[:limit]
    else:
        entries = entries + await _temp_shadow_entries(news_items, entries)
    report = await run_shadow_day(_ledger_store(config), news_items, entries=entries,
                                  report_dir=default_report_dir())
    print(f"  [shadows] {report.summary()}")
    return report


async def _temp_shadow_entries(news_items: list, long_term: list) -> list:
    """S7 temporary shadows that trade today: event shadows (detected now) + running trials."""
    from marketmind.gateway.price_history import get_price_histories
    from marketmind.shadows.v3 import temp_event, trials
    out = []
    try:
        tickers = sorted({t for e in long_term for t in e.watchlist})
        histories = await get_price_histories(tickers)      # shared cache with the shadow run
        summary = await temp_event.daily_events(news_items, histories)
        if summary.get("spawned"):
            print(f"  [temp_event] new: {'; '.join(summary['spawned'])}")
        today = summary["date"]
        out += temp_event.roster_entries(temp_event.load(), today)
    except Exception:
        logger.warning("event shadows unavailable today", exc_info=True)
    try:
        out += trials.roster_entries()
    except Exception:
        logger.warning("trial shadows unavailable today", exc_info=True)
    return out


def _record_missed_path(config) -> None:
    """S7 missed_path: main-pipeline candidates not traded, from today's brief."""
    import json
    from datetime import datetime as _dt, timezone as _tz
    from marketmind.shadows.v3 import missed_path
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    path = Path(__file__).resolve().parent.parent / ".claude" / "briefs" / f"{today}.json"
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
        ids = missed_path.record(_ledger_store(config), brief, today=today)
        print(f"  [missed_path] {len(ids)} passed-over candidates recorded")
    except Exception:
        logger.warning("missed_path not recorded", exc_info=True)


async def promotion_step(config) -> None:
    """S7: promotion ladder (writes data/advisors.json), trial verdicts, new challengers."""
    from marketmind.promotion.runner import run_promotion
    from marketmind.shadows.v3 import trials
    store = _ledger_store(config)
    try:
        from marketmind.shadows.v3 import roster as _roster
        candidates = playground_candidates()
        active = {r.shadow_id for r in _roster.active()} | {c.shadow_id for c in candidates}
        summary = run_promotion(store, data_dir=Path(config.data_dir),
                                roster=tuple(_roster.ROSTER) + tuple(candidates), active_ids=active)
        print(f"  [promotion] stages {summary.get('stages')}; advisors {len(summary.get('advisors', []))}")
    except Exception:
        logger.warning("promotion review failed", exc_info=True)
        print("  [promotion] failed (see log)")
        return
    try:
        for t in trials.evaluate(store):
            print(f"  [trials] {t.trial_id} ({t.kind} of {t.parent_id}): {t.status}")
        for ev in summary.get("events", []):
            if ev.get("type") != "challenge":
                continue
            try:
                t = await trials.propose(ev["shadow_id"], "challenger",
                                         "连续 3 个评估期综合分在后 20%：针对最弱的指标修改方法论。"
                                         + (f"指标：{ev.get('detail')}" if ev.get("detail") else ""),
                                         store=store)
                print(f"  [trials] challenger {t.trial_id} started for {t.parent_id}")
            except ValueError as e:
                print(f"  [trials] challenger for {ev['shadow_id']} not started: {e}")
    except Exception:
        logger.warning("trial step failed", exc_info=True)


async def run_playground(config, news_items: list):
    """S8: Playground agents -> ledger as promotion candidates (docs/S8_DESIGN.md)."""
    from marketmind.playground.agent_manifest import discover_agents
    from marketmind.playground.ledger_bridge import record_run
    from marketmind.playground.playground_runner import DEFAULT_PLAYGROUND_DIR, run_all_agents
    try:
        result = await run_all_agents(news_items=news_items, fetch_playground_sources=True)
        manifests = {m.agent_id: m for m in discover_agents(DEFAULT_PLAYGROUND_DIR)}
        summary = await record_run(_ledger_store(config), result, manifests)
    except Exception:
        logger.warning("playground run failed", exc_info=True)
        print("  [playground] failed (see log)")
        return None
    n = sum(len(v) for v in summary["recorded"].values())
    print(f"  [playground] {result.agents_succeeded}/{result.agents_attempted} agents, "
          f"{n} calls to ledger" + (f"; dropped {len(summary['dropped'])}" if summary["dropped"] else ""))
    return summary


def playground_candidates() -> list:
    """Playground agents as roster-like entries for the promotion ladder."""
    from marketmind.playground.agent_manifest import discover_agents
    from marketmind.playground.playground_runner import DEFAULT_PLAYGROUND_DIR
    from marketmind.shadows.v3.roster import RosterEntry
    return [RosterEntry(shadow_id=f"playground:{m.agent_id}", name=f"pg_{m.agent_id}",
                        display_name=f"{m.display_name}（Playground）", group="playground",
                        domain=m.description[:60], watchlist=tuple(m.domain_universe),
                        domain_benchmark=m.domain_benchmark, source_type="playground",
                        prompt_text="(playground adapter)")
            for m in discover_agents(DEFAULT_PLAYGROUND_DIR)]


async def run_evidence(config, news_items: list):
    """S5 evidence layer -> data/evidence/<date>.json + divergences into the ledger."""
    from marketmind.evidence.runner import run_evidence_day
    try:
        report = await run_evidence_day(_ledger_store(config), news_items)
    except Exception:
        logger.warning("evidence run failed", exc_info=True)
        print("  [evidence] failed (see log)")
        return None
    print(f"  [evidence] {report.summary()}")
    return report


async def alerts_step(config) -> None:
    """S8: big-move alert conditions, after shadows have filed today's decisions."""
    from marketmind.alerts.notify import send
    from marketmind.alerts.runner import OBSERVE, run_alerts
    try:
        report = await run_alerts(_ledger_store(config), notifier=send)
    except Exception:
        logger.warning("alerts step failed", exc_info=True)
        print("  [alerts] failed (see log)")
        return
    mode = "observe" if report["mode"] == OBSERVE else "live"
    fired = ", ".join(f["ticker"] for f in report["fired"]) or "none"
    print(f"  [alerts] {mode}: fired {fired}; near misses {len(report['near_misses'])}")


async def inspect_holdings_step(config) -> None:
    """S6: inspect the owner's real holdings last, so today's shadow picks can be alternatives."""
    from marketmind.holdings.inspect import run_inspection
    try:
        reports, path = await run_inspection(_ledger_store(config))
    except Exception:
        logger.warning("holdings inspection failed", exc_info=True)
        print("  [holdings] inspection failed (see log)")
        return
    if not reports:
        print("  [holdings] no holdings recorded")
        return
    flagged = [f"{r.ticker} {r.verdict_cn}" for r in reports if r.verdict in ("exit", "switch")]
    print(f"  [holdings] {len(reports)} inspected" + (f"; action: {', '.join(flagged)}" if flagged else ""))


def crypto_shadows() -> list:
    """Shadows whose domain trades on weekends (docs/AUTOMATION.md)."""
    from marketmind.shadows.v3 import roster
    return [e for e in roster.active() if ":crypto:" in e.shadow_id]


async def run_weekend(config) -> int:
    """`--mode weekend`: settle the ledger, then only the crypto shadows decide.
    Every other market is closed; their shadows would decide on Friday's data and
    fill at Monday's open, which the weekday pre-open run does better."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    from marketmind.gateway import usage_tracker
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.shadows.v3.runner import default_report_dir, run_shadow_day
    usage_tracker.reset()
    summary = await settle_ledger(config)
    print(f"  [ledger] {summary}")
    news_items = await fetch_all_sources(config) or []
    report = await run_shadow_day(_ledger_store(config), news_items, entries=crypto_shadows(),
                                  report_dir=default_report_dir())
    print(f"  [shadows] {report.summary()}")
    print(f"  [tokens] {usage_tracker.summary_line()}")
    usage_tracker.append_log("weekend")
    return 0 if "failed" not in summary else 1


async def run_evidence_only(config) -> int:
    """`--mode evidence`: collect news, run the evidence layer only."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    from marketmind.gateway import usage_tracker
    from marketmind.pipeline.scout import fetch_all_sources
    usage_tracker.reset()
    news_items = await fetch_all_sources(config) or []
    print(f"Evidence: {len(news_items)} articles collected")
    report = await run_evidence(config, news_items)
    print(f"  [tokens] {usage_tracker.summary_line()}")
    usage_tracker.append_log("evidence")
    return 0 if report is not None and report.status in ("ok", "skipped") else 1


async def run_shadows_only(config, verbose: bool = False) -> int:
    """Run ONLY the shadows: S3 daily decisions into the ledger."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    from marketmind.gateway import usage_tracker
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.universe import get_equity_universe
    usage_tracker.reset()
    await asyncio.to_thread(get_equity_universe)
    news_items = await fetch_all_sources(config) or []
    print(f"Shadows: {len(news_items)} articles collected")
    await run_v3_shadows(config, news_items)
    print(f"  [tokens] {usage_tracker.summary_line()}")
    usage_tracker.append_log("shadows")
    return 0


def run_gui(config) -> int:
    """Launch CustomTkinter GUI."""
    from marketmind.ui.main_window import MainWindow
    from marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


async def _run_daily_with_shadows(config, args) -> int:
    """Run the daily pipeline, then wait for the background shadow task to finish.

    The pipeline prints results immediately (non-blocking from the user's
    perspective), then we wait for the S3 shadows to complete so the
    process doesn't exit before they finish writing to the ledger.
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
            await asyncio.wait_for(_shadow_task, timeout=SHADOW_WAIT_S)
        except asyncio.TimeoutError:
            print(f"(Shadows timed out after {SHADOW_WAIT_S // 60} minutes — "
                  "results may be incomplete)")
        except asyncio.CancelledError:
            pass
        from marketmind.gateway import usage_tracker
        print(f"  [tokens incl. shadows] {usage_tracker.summary_line()}")
    global _evidence_task, _playground_task
    if _playground_task and not _playground_task.done():
        try:
            await asyncio.wait_for(_playground_task, timeout=EVIDENCE_WAIT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            print("(Playground timed out)")
    if _evidence_task and not _evidence_task.done():
        try:
            await asyncio.wait_for(_evidence_task, timeout=EVIDENCE_WAIT_S)
        except asyncio.TimeoutError:
            print(f"(Evidence layer timed out after {EVIDENCE_WAIT_S // 60} minutes)")
        except asyncio.CancelledError:
            pass
    if not args.mock:
        await inspect_holdings_step(config)
        await promotion_step(config)
        await alerts_step(config)
        from marketmind.gateway import usage_tracker
        usage_tracker.append_log("daily")

    return ret


# 23 shadows, 5 at a time, one Flash call each (+1 retry): allow 15 minutes.
SHADOW_WAIT_S = 900
# one Flash call plus up to ~15 primary-data checks (SEC requests are spaced)
EVIDENCE_WAIT_S = 600
