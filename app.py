"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
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
    from marketmind.pipeline import orchestration
    from marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    _setup_logging(str(config.data_dir))

    from marketmind.pipeline.session_context import SessionContext
    ctx = SessionContext(config=config, data_dir=str(config.data_dir))

    tracker = orchestration._StageTracker(verbose)
    orchestration._shadow_task = None
    orchestration._shadow_result = None

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
        if not (orchestration._shadow_task and orchestration._shadow_task.done()
                and not orchestration._shadow_task.cancelled()):
            return False
        try:
            result = orchestration._shadow_task.result()
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
    if config.shadow.shadows_enabled and mother is not None and orchestration._shadow_task is None:
        tracker.advance(0, "Shadows: launching background analysis...")
        orchestration._shadow_task = asyncio.create_task(
            mother.orchestrate_daily_cycle(news_items, {})
        )
        orchestration._shadow_task.add_done_callback(orchestration._shadow_progress_done)
        tracker.result(f"Shadows launched — {len(shadow_db.get_visible_shadows())} shadows analyzing (with L1 broadcast)")

    # 4. L2 Fundamental — medium-low interaction density (extracted module)
    tracker.advance(4, "L2: fundamental analysis (AI working)...")
    from marketmind.pipeline.l2_interactive import run_l2_interactive
    l2_confirmed = await run_l2_interactive(ctx, _cli_handler)
    if not l2_confirmed:
        await orchestration._archive_session(config, ctx.l1_result, ctx.l2_result, None, "observe")
        return 0
    l2_result = ctx.l2_result
    selected_tickers = ctx.selected_tickers
    tracker.result(f"L2: {len(selected_tickers)} tickers selected, {l2_result.macro_quadrant}")

    # 4.5 ELITE Shadow check (H7) — populate registry from completed shadow results
    from marketmind.shadows.elite_participation import EliteRegistry
    elite_registry = EliteRegistry()

    if shadow_db and orchestration._shadow_task and orchestration._shadow_task.done() \
            and not orchestration._shadow_task.cancelled():
        try:
            result = orchestration._shadow_task.result()
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
        await orchestration._archive_session(config, ctx.l1_result, ctx.l2_result, ctx.l3_result, "observe")
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
            observed_sharpe=orchestration._DEFAULT_OBSERVED_SHARPE,
        )
    ctx.resonance = resonance

    # 8.5 Shadow consensus display (before Decision — shows alongside cards)
    if orchestration._shadow_task and orchestration._shadow_task.done() \
            and not orchestration._shadow_task.cancelled():
        try:
            s_result = orchestration._shadow_task.result()
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
        await orchestration._archive_session(config, ctx.l1_result, ctx.l2_result, ctx.l3_result, "observe")
        return 0

    # 10. Archive
    tracker.advance(10, "Archive: saving session...")
    await orchestration._archive_session(config, l1_result, l2_result, l3_result, resonance.verdict)

    # Wait for shadow consensus
    if orchestration._shadow_task and not orchestration._shadow_task.done():
        timeout = getattr(config.shadow, 'shadow_consensus_timeout_s', 60)
        try:
            await asyncio.wait_for(orchestration._shadow_task, timeout=timeout)
        except asyncio.TimeoutError:
            partial_note = ""
            try:
                r = orchestration._shadow_task.result() if orchestration._shadow_task.done() \
                    and not orchestration._shadow_task.cancelled() else None
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
        from marketmind.pipeline.orchestration import _run_backtest
        return _run_backtest(config, args)

    if args.shadow_only:
        from marketmind.pipeline.orchestration import run_shadows_only
        return asyncio.run(run_shadows_only(config, verbose=args.verbose))
    elif args.mode == "shadows":
        from marketmind.pipeline.orchestration import run_shadows_only
        return asyncio.run(run_shadows_only(config, verbose=args.verbose))
    elif args.mode == "interactive":
        return asyncio.run(run_interactive(config, mock=args.mock, verbose=args.verbose,
                                           shadow_count=0 if args.no_shadows else args.shadows))
    elif args.mode == "gui":
        from marketmind.pipeline.orchestration import run_gui
        return run_gui(config)
    else:
        from marketmind.pipeline.orchestration import _run_daily_with_shadows
        return asyncio.run(_run_daily_with_shadows(config, args))


if __name__ == "__main__":
    sys.exit(main())
