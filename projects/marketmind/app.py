"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketmind.config.settings import MarketMindConfig
from marketmind.pipeline.interactive_orchestration import run_interactive

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
    parser.add_argument("--playground", action="store_true",
                        help="Run Playground experimental agents after main pipeline")
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
        ret = asyncio.run(run_shadows_only(config, verbose=args.verbose))
        asyncio.run(_run_playground_if_requested(args))
        return ret
    elif args.mode == "shadows":
        from marketmind.pipeline.orchestration import run_shadows_only
        ret = asyncio.run(run_shadows_only(config, verbose=args.verbose))
        asyncio.run(_run_playground_if_requested(args))
        return ret
    elif args.mode == "interactive":
        ret = asyncio.run(run_interactive(config, mock=args.mock, verbose=args.verbose,
                                          shadow_count=0 if args.no_shadows else args.shadows))
        asyncio.run(_run_playground_if_requested(args))
        return ret
    elif args.mode == "gui":
        from marketmind.pipeline.orchestration import run_gui
        return run_gui(config)
    else:
        from marketmind.pipeline.orchestration import _run_daily_with_shadows
        ret = asyncio.run(_run_daily_with_shadows(config, args))
        asyncio.run(_run_playground_if_requested(args))
        return ret


async def _run_playground_if_requested(args, news_items=None):
    """Run Playground experimental agents if --playground flag is set."""
    if not args.playground:
        return
    from marketmind.playground.playground_runner import run_all_agents
    print("\n" + "=" * 60)
    print("  [PLAYGROUND] Running experimental agents...")
    print("=" * 60)
    result = await run_all_agents(
        news_items=news_items,
        mock=args.mock,
        fetch_playground_sources=not args.mock,
    )
    print(f"  Agents: {result.agents_attempted} attempted, "
          f"{result.agents_succeeded} succeeded, {result.agents_failed} failed")
    if result.decisions:
        total_calls = sum(len(d.directional_calls) for d in result.decisions)
        print(f"  Directional calls: {total_calls}")
        for d in result.decisions:
            for call in d.directional_calls:
                print(f"    {call['ticker']} {call['direction']} "
                      f"(confidence={call['confidence']:.2f}) "
                      f"research_backed={call.get('research_backed', False)}")
    if result.errors:
        for e in result.errors:
            print(f"  [ERROR] {e['agent_id']}: {e['error'][:200]}")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
