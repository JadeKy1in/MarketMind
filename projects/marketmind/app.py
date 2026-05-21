"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketmind.config.settings import MarketMindConfig


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    import logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level)


def run_gui(config: MarketMindConfig) -> int:
    """Launch CustomTkinter GUI."""
    from marketmind.ui.main_window import MainWindow
    from marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


def main():
    parser = argparse.ArgumentParser(description="MarketMind — AI Investment Analysis Workstation")
    parser.add_argument("--mode", choices=["daily", "interactive", "backtest", "gui", "gate1", "full"],
                        default="gui",
                        help="Run mode: daily, interactive, backtest, gui, gate1, or full pipeline")
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
    parser.add_argument("--inject", type=str, default=None, metavar="TEXT",
                        help="Inject external information before analysis")
    parser.add_argument("--inject-files", type=str, nargs="*", default=None, metavar="PATH",
                        help="Inject files (images/PDFs) before analysis")
    args = parser.parse_args()

    config = MarketMindConfig.from_env()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return 1

    if args.backtest or args.mode == "backtest":
        from marketmind.pipeline.backtest_entry import run_backtest
        return run_backtest(config, args)

    if args.mode == "gui":
        return run_gui(config)

    from marketmind.pipeline.orchestration import (
        run_daily, run_interactive, run_full, run_gate1_mode,
    )
    shadow_n = 0 if args.no_shadows else args.shadows

    # ── Info injection (before pipeline start) ──
    inject_result = None
    if args.inject or args.inject_files:
        from marketmind.pipeline.info_injector import inject_user_info
        inject_result = asyncio.run(inject_user_info(
            text=args.inject or "",
            files=args.inject_files,
        ))
        if inject_result.has_content:
            print(f"\n[外部信息] 已注入 {len(inject_result.items)} 项, {inject_result.total_chars} 字符\n")

    if args.mode == "daily":
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose,
                                      shadow_count=shadow_n,
                                      inject_result=inject_result))
    elif args.mode == "interactive":
        return asyncio.run(run_interactive(config, mock=args.mock, verbose=args.verbose,
                                            shadow_count=shadow_n))
    elif args.mode == "gate1":
        return asyncio.run(run_gate1_mode(config, mock=args.mock, verbose=args.verbose,
                                           shadow_count=shadow_n))
    elif args.mode == "full":
        return asyncio.run(run_full(config, mock=args.mock, verbose=args.verbose,
                                     shadow_count=shadow_n))
    else:
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose,
                                      shadow_count=shadow_n))


if __name__ == "__main__":
    sys.exit(main())
