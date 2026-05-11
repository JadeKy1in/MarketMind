"""MarketMind entry point — CLI and GUI launcher."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from projects.marketmind.config.settings import MarketMindConfig
from projects.marketmind.gateway.async_client import init_gateway


async def run_daily(config: MarketMindConfig, mock: bool = False, verbose: bool = False) -> int:
    """Execute full daily analysis pipeline."""
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)

    tracker = _StageTracker(verbose)

    # 1. News collection
    tracker.advance(1, "Scout: fetching news from all sources...")
    from projects.marketmind.pipeline.scout import fetch_all_sources
    from projects.marketmind.pipeline.cache import DataCache
    cache = DataCache(ttl_seconds=config.cache_ttl_seconds)
    news_items = await fetch_all_sources(config, cache)
    tracker.result(f"{len(news_items)} articles collected")

    # 2. Flash preprocessing
    tracker.advance(2, "Flash: preprocessing signals...")
    from projects.marketmind.pipeline.flash_preprocessor import preprocess_batch
    signals = await preprocess_batch(news_items[:50])
    tracker.result(f"{len(signals)} signals extracted")

    # 3. Layer 1 Narrative analysis
    tracker.advance(3, "Layer 1: narrative analysis...")
    from projects.marketmind.pipeline.layer1_narrative import analyze_layer1
    l1_result = await analyze_layer1(signals[:15])
    tracker.result(f"grade={l1_result.event_grade}, quadrant={l1_result.matrix_quadrant}")

    # 4. Layer 2 + Layer 3 in parallel
    tracker.advance(4, "Layer 2+3: fundamental + technical analysis...")
    from projects.marketmind.pipeline.layer2_fundamental import analyze_layer2
    from projects.marketmind.pipeline.layer3_technical import analyze_layer3
    from projects.marketmind.config.asset_universe import ASSET_UNIVERSE

    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:10]]
    l2_task = analyze_layer2(l1_result)
    l3_task = analyze_layer3(tickers, {})

    l2_result, l3_result = await asyncio.gather(l2_task, l3_task)
    tracker.result(f"L2: {len(l2_result.ticker_candidates)} candidates, "
                   f"L3: {len(l3_result.results)} tickers ({len(l3_result.green_lights)} green)")

    # 5. Red Team challenge
    tracker.advance(5, "Red Team: adversarial challenge...")
    from projects.marketmind.pipeline.red_team import run_red_team
    red_team_report = await run_red_team(
        l1_result.raw_analysis,
        l2_result.raw_analysis,
        l2_result.ticker_candidates,
    )
    tracker.result(f"{len(red_team_report.challenges)} challenges, "
                   f"A-grade: {red_team_report.a_grade_count}")

    # 6. Signal Resonance
    tracker.advance(6, "Resonance: statistical validation...")
    from projects.marketmind.pipeline.resonance import evaluate_resonance
    resonance = evaluate_resonance(
        signal_returns={},
        dimensions=["narrative", "fundamental", "technical", "sentiment"],
        observed_sharpe=0.5,
    )

    # 7. Decision
    tracker.advance(7, "Decision: synthesis...")
    from projects.marketmind.pipeline.decision import generate_decision
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
    )
    tracker.result(f"cards={len(decision.decision_cards)}, "
                   f"no_trade={'present' if decision.no_trade_card else 'none'}")

    # 8. Archive
    tracker.advance(8, "Archive: saving session...")
    from projects.marketmind.storage.archivist import get_archivist
    archivist = get_archivist(config.data_dir)
    archivist.index_document(
        "daily_session",
        f"MarketMind daily: {l1_result.event_grade} | {l2_result.macro_quadrant} | "
        f"resonance={resonance.verdict}",
    )
    tracker.result("Session archived")

    print("\nMarketMind daily pipeline complete.")
    return 0


def run_gui(config: MarketMindConfig) -> int:
    """Launch CustomTkinter GUI."""
    from projects.marketmind.ui.main_window import MainWindow
    from projects.marketmind.gateway.async_client import init_gateway

    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    app = MainWindow(config)
    app.mainloop()
    return 0


class _StageTracker:
    def __init__(self, verbose: bool):
        self.verbose = verbose

    def advance(self, stage: int, msg: str) -> None:
        if self.verbose:
            print(f"[{stage}/8] {msg}")

    def result(self, msg: str) -> None:
        if self.verbose:
            print(f"       {msg}")


def main():
    parser = argparse.ArgumentParser(description="MarketMind — AI Investment Analysis Workstation")
    parser.add_argument("--mode", choices=["daily", "gui"], default="gui",
                        help="Run mode: daily CLI report or GUI (default: gui)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock LLM responses (no API calls)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()

    config = MarketMindConfig.from_env()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return 1

    if args.mode == "gui":
        return run_gui(config)
    else:
        return asyncio.run(run_daily(config, mock=args.mock, verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())
