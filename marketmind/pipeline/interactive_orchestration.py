"""Interactive pipeline orchestration — extracted from app.py.

Orchestrates the full interactive pipeline: news fetching, Flash preprocessing,
L1 Socratic dialogue, L2 fundamental, S3 shadows (background), L3 technical,
Red Team, Resonance, and Decision stages.
"""
from __future__ import annotations
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from marketmind.config.settings import MarketMindConfig


async def run_interactive(config: MarketMindConfig, mock: bool = False, verbose: bool = False,
                          shadow_count: int | None = None) -> int:
    """Run L1 as an interactive Socratic dialogue with the user.

    Steps:
      1. News (S3 shadows launch in background right after)
      2. Flash preprocessing
      3. L1 interactive dialogue (replaces single-shot analysis)
      4. L2+L3 (if user chooses to proceed)
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

    print("\n" + "=" * 60)
    print("  MarketMind — Interactive Investment Analysis")
    print("  Model: DeepSeek V4 Pro | Reasoning: MAX | L1: Socratic Dialogue")
    print("=" * 60)

    # Market countdown — calculate next trading day (Mon-Fri)
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    market_h, market_m = map(int, config.market_open_utc.split(":"))
    market_open = now_utc.replace(hour=market_h, minute=market_m, second=0, microsecond=0)
    if now_utc > market_open:
        market_open += timedelta(days=1)
    # Skip weekends
    while market_open.weekday() >= 5:  # 5=Sat, 6=Sun
        market_open += timedelta(days=1)
    # Next trading day label
    day_labels = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五"}
    day_label = day_labels.get(market_open.weekday(), "")
    delta = market_open - now_utc
    total_h = delta.days * 24 + delta.seconds // 3600
    mins = (delta.seconds % 3600) // 60
    if total_h < 1:
        print(f"\n距美股开盘({day_label}): {mins}m")
    elif total_h < 24:
        print(f"\n距美股开盘({day_label}): {total_h}h{mins}m")
    else:
        days = total_h // 24
        print(f"\n距美股开盘({day_label}): {days}天{total_h % 24}h{mins}m")

    print("\nThe AI will present its analysis. You can:")
    print("  - Challenge its reasoning (\"Why do you think that?\")")
    print("  - Ask for more evidence")
    print("  - Suggest a direction to explore")
    print("  - Type 'search: <topic>' to request data mining")
    print("  - Type 'proceed' when ready to move to L2/L3")
    print("  - Type 'observe' to skip trading today")
    print("\nAI can also actively investigate using tools:")
    print("  - lookup_fundamentals: verify P/E, market cap, sector")
    print("  - search_news: search GNews for additional articles")
    print("  - get_elite_opinion: query ELITE shadow analysts")
    print("  - get_economic_calendar: upcoming FOMC, CPI, NFP events")
    print("  - get_earnings_date: earnings dates for ticker(s)\n")

    # 0.5 Economic calendar check (before news — informs pipeline confidence)
    from marketmind.pipeline.economic_calendar import check_economic_calendar, get_event_confidence_discount
    ctx.economic_events = await check_economic_calendar(
        lookahead_hours=24,
        fred_key=config.fred_key,
    )
    if ctx.economic_events.get("has_high_impact"):
        discount = get_event_confidence_discount(ctx.economic_events)
        print(f"\n  [Economic Calendar] HIGH-IMPACT event(s) detected — confidence discount: {discount:.0%}")
        for evt in ctx.economic_events.get("high_impact_events", [])[:3]:
            print(f"    - {evt['name']} ({evt['date']}, ~{evt['hours_until']}h)")

    # 1. News
    tracker.advance(1, "Fetching news...", ctx.stage_times)
    from marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    ctx.news_items = news_items

    # S3 shadows see news and prices only, never this session's L1 (SPEC §6.1, C26)
    if (config.shadow.shadows_enabled and shadow_count != 0
            and orchestration._shadow_task is None):
        orchestration._shadow_task = asyncio.create_task(
            orchestration.run_v3_shadows(config, news_items or [], shadow_count))
        print("  [shadows] daily decisions launched in background")
    tracker.result(f"{len(news_items)} articles")

    # 1.5 Save raw news to archive (audit trail — always save, cleanup later if needed)
    try:
        from datetime import datetime as dt
        from marketmind.storage.archivist import get_archivist
        with get_archivist(config.data_dir) as archivist:
            news_save_dir = archivist.today_path()
            news_save_dir.mkdir(parents=True, exist_ok=True)
            today_str = dt.now().strftime("%Y%m%d_%H%M%S")
            news_file = news_save_dir / f"news_{today_str}.json"
            import json as _json
            _items = []
            for n in news_items[:500]:
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

    # 2. Flash preprocessing (CRITICAL-2: route by content_type — only news_article items
    #    pass through Flash; insider_signal and social_mention items bypass Flash entirely
    #    and are formatted directly in L1 context alongside FlashSignals)
    tracker.advance(2, "Preprocessing signals...", ctx.stage_times)
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    news_article_items = [n for n in news_items if getattr(n, 'content_type', 'news_article') == 'news_article']
    non_news_items = [n for n in news_items if getattr(n, 'content_type', 'news_article') != 'news_article']
    signals = await preprocess_batch(news_article_items[:50])
    ctx.signals = signals
    ctx.insider_items = [n for n in non_news_items if getattr(n, 'content_type', '') == 'insider_signal']
    ctx.social_items = [n for n in non_news_items if getattr(n, 'content_type', '') == 'social_mention']
    tracker.result(f"{len(signals)} signals + {len(ctx.insider_items)} insider + {len(ctx.social_items)} social")

    # 3. L1 Interactive Socratic dialogue
    tracker.advance(3, "L1: Starting interactive analysis...", ctx.stage_times)
    from marketmind.pipeline.layer1_interactive import run_l1_interactive
    from marketmind.pipeline.l1_tools import L1ToolRegistry

    # Phase G: Create tool registry for AI-initiated investigation
    l1_tool_registry = L1ToolRegistry(
        config=config,
        gnews_key=config.gnews_key,
    )

    async def _cli_handler(prompt: str) -> str:
        """CLI-based user input handler."""
        print(prompt, end="", flush=True)
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return "observe"

    l1_result, should_observe, l1_session = await run_l1_interactive(
        signals[:15], news_items, user_input_handler=_cli_handler, mock=mock,
        elite_registry=None,
        tool_registry=l1_tool_registry,
        insider_items=ctx.insider_items,
        social_items=ctx.social_items,
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
        with get_archivist(config.data_dir) as archivist:
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

    # Phase G: Flush tool efficacy log for learning mechanism (Red Team Q4.3, Control 3)
    if l1_tool_registry and l1_tool_registry.tool_calls:
        try:
            eff_path = l1_tool_registry.flush_efficacy(str(config.data_dir))
            if eff_path:
                logger.info("Tool efficacy log saved: %s", eff_path)
        except Exception as e:
            logger.debug("Tool efficacy log skipped (non-critical): %s", e)

    # Budget check (G: token visibility)
    try:
        from marketmind.gateway.async_client import get_budget
        b = await get_budget()
        if b:
            br = b.report()
            print(f"  [Budget] Pro剩余:{br['pro_calls_remaining']}次 | 用量:{br['tokens_pct_used']}%")
    except Exception:
        pass

    # 4. L2 Fundamental — medium-low interaction density (extracted module)
    tracker.advance(4, "L2: fundamental analysis (AI working)...", ctx.stage_times)
    from marketmind.pipeline.l2_interactive import run_l2_interactive
    l2_confirmed = await run_l2_interactive(ctx, _cli_handler)
    if not l2_confirmed:
        await orchestration._archive_session(config, ctx.l1_result, ctx.l2_result, None, "observe")
        return 0
    l2_result = ctx.l2_result
    selected_tickers = ctx.selected_tickers
    tracker.result(f"L2: {len(selected_tickers)} tickers selected, {l2_result.macro_quadrant}")

    # 6. L3 Technical — lowest interaction density (extracted module)
    tracker.advance(6, "L3: technical analysis (AI working)...", ctx.stage_times)
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
    tracker.advance(7, "Red Team: adversarial review...", ctx.stage_times)
    from marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(l1_result.raw_analysis, l2_result.raw_analysis,
                                          selected_tickers)
    ctx.red_team_report = red_team_report
    tracker.result(f"{len(red_team_report.challenges)} challenges")

    # SPEC_v3 §5 step 7: DSR/PBO moved to promotion review; same marker as the daily path
    resonance = orchestration._resonance_not_evaluated()
    ctx.resonance = resonance

    # 9. Decision — interactive (extracted module)
    tracker.advance(9, "Decision: synthesis...", ctx.stage_times)
    from marketmind.pipeline.decision_interactive import run_decision_interactive
    decision_confirmed = await run_decision_interactive(ctx, _cli_handler)
    if not decision_confirmed:
        await orchestration._archive_session(config, ctx.l1_result, ctx.l2_result, ctx.l3_result, "observe")
        return 0

    # 10. Archive
    tracker.advance(10, "Archive: saving session...", ctx.stage_times)
    await orchestration._archive_session(config, l1_result, l2_result, l3_result, resonance.verdict)

    # Wait for the background S3 shadow task
    if orchestration._shadow_task and not orchestration._shadow_task.done():
        timeout = orchestration.SHADOW_WAIT_S
        try:
            await asyncio.wait_for(orchestration._shadow_task, timeout=timeout)
        except asyncio.TimeoutError:
            print(f"(Shadow ecosystem timed out after {timeout}s — partial results may be incomplete)")
        except asyncio.CancelledError:
            pass

    print("\nMarketMind interactive session complete.")
    return 0


