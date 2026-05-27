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
        asyncio.run(_run_playground_if_requested(args, config))
        return ret
    elif args.mode == "shadows":
        from marketmind.pipeline.orchestration import run_shadows_only
        ret = asyncio.run(run_shadows_only(config, verbose=args.verbose))
        asyncio.run(_run_playground_if_requested(args, config))
        return ret
    elif args.mode == "interactive":
        ret = asyncio.run(run_interactive(config, mock=args.mock, verbose=args.verbose,
                                          shadow_count=0 if args.no_shadows else args.shadows))
        asyncio.run(_run_playground_if_requested(args, config))
        return ret
    elif args.mode == "gui":
        from marketmind.pipeline.orchestration import run_gui
        return run_gui(config)
    else:
        from marketmind.pipeline.orchestration import _run_daily_with_shadows
        ret = asyncio.run(_run_daily_with_shadows(config, args))
        asyncio.run(_run_playground_if_requested(args, config))
        return ret


async def _run_playground_if_requested(args, config, news_items=None):
    """Run Playground experimental agents if --playground flag is set."""
    if not args.playground:
        return
    # Re-init gateway: the previous asyncio.run() closed the event loop,
    # invalidating the httpx client. We need a fresh client for this loop.
    from marketmind.gateway.async_client import init_gateway
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    from marketmind.playground.playground_runner import run_all_agents, generate_daily_report
    from marketmind.playground.playground_tracker import load_performance_history

    print("\n" + "=" * 60)
    print("  [PLAYGROUND] Running experimental agents...")
    print("=" * 60)
    result = await run_all_agents(
        news_items=news_items,
        mock=args.mock,
        fetch_playground_sources=not args.mock,
    )

    print(f"\n  Agents: {result.agents_attempted} attempted, "
          f"{result.agents_succeeded} succeeded, {result.agents_failed} failed")

    for d in result.decisions:
        agent_id = d.agent_id
        calls = d.directional_calls
        output = d.output

        # Load historical performance for reliability context
        perf_history = load_performance_history(agent_id)
        hist_acc = None
        if perf_history:
            latest = perf_history[-1]
            hist_acc = latest.get("direction_accuracy")

        print(f"\n  {'─' * 56}")
        print(f"  {agent_id}")
        if hist_acc is not None:
            acc_str = f"{hist_acc:.0%}"
            tag = " ✓" if hist_acc >= 0.55 else " ⚠"
            obs_days = perf_history[-1].get("observation_days", 0) if perf_history else 0
            print(f"  历史准确率: {acc_str}{tag} | day {obs_days} | {len(perf_history)} snapshots")
        else:
            obs_days = perf_history[-1].get("observation_days", 0) if perf_history else 0
            print(f"  历史准确率: — (观察中, day {obs_days}/60)")

        data_tag = "enhanced_data" if d.metadata.get("enhanced_data") else "standard"
        print(f"  数据质量: {data_tag} | research_passes: {output.get('_passes', 1)}")

        if calls:
            print(f"  方向判断 ({len(calls)}):")
            for call in calls:
                icon = "🔬" if call.get("research_backed") else "📡"
                print(f"    {icon} {call['ticker']} {call['direction']:<8} "
                      f"conf={call['confidence']:.2f}")
                thesis = call.get('thesis', '')
                if thesis:
                    print(f"       {thesis[:120]}")
        else:
            reason = output.get("no_calls_reason", "No signals found")[:120]
            print(f"  无方向判断 — {reason}")

        # Observations
        obs = output.get("supply_chain_observations", [])
        if obs:
            print(f"  供应链观察 ({len(obs)}):")
            for o in obs[:3]:
                print(f"    · {o[:100]}")

    if result.errors:
        print(f"\n  [ERRORS]")
        for e in result.errors:
            print(f"    ✗ {e['agent_id']}: {e['error'][:150]}")

    print("\n" + "=" * 60)

    # Generate daily markdown report
    if not args.mock:
        generate_daily_report(result)


if __name__ == "__main__":
    sys.exit(main())
