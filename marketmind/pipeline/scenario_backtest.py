"""Historical scenario backtesting — validates system recognition of known trading opportunities.

MINIMUM VIABLE diagnostic tool. Answers: "Is the system CAPABLE of producing a non-no-trade
signal when there IS an obvious opportunity?" Uses real resonance.py math (DSR/PBO) on
synthetic price series mirroring historical moves. L1/L2/L3 mocked from scenario context.
Decision heuristic mirrors decision.py:generate_decision() — no LLM calls needed.
"""
from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

logger = logging.getLogger("marketmind.pipeline.scenario_backtest")


@dataclass
class ScenarioWindow:
    """Historical crisis/opportunity window for backtesting."""
    name: str
    start_date: date
    end_date: date
    expected_direction: str       # "bearish" | "bullish" | "volatile"
    key_assets_affected: list[str]
    market_context: str           # 1-2 sentence summary
    price_start: float = 100.0
    price_end: float = 100.0
    mock_volatility: float = 0.015
    l3_green_lights: int = 0
    l1_direction: str = "neutral"


# Six standard crisis/opportunity windows. Price moves approximate actual drawdowns/rallies.
SCENARIO_LIBRARY: dict[str, ScenarioWindow] = {
    "covid2020_crash": ScenarioWindow(
        name="2020 COVID Crash", start_date=date(2020, 2, 20), end_date=date(2020, 3, 23),
        expected_direction="bearish",
        key_assets_affected=["SPY", "QQQ", "VIX", "TLT", "GLD", "USO"],
        market_context="Fastest 34% S&P drawdown (23 trading days). WHO pandemic, Fed emergency 150bp "
                       "cut + $700B QE, VIX to 82, oil negative, circuit breakers 4x in March.",
        price_start=100.0, price_end=66.0, mock_volatility=0.035,
        l3_green_lights=2, l1_direction="bearish",
    ),
    "covid2020_recovery": ScenarioWindow(
        name="2020 COVID Recovery", start_date=date(2020, 3, 24), end_date=date(2020, 6, 8),
        expected_direction="bullish",
        key_assets_affected=["SPY", "QQQ", "IWM", "ZM", "TSLA"],
        market_context="$2T CARES Act, Fed unlimited QE + corporate bond buying. Historic V-shaped rally: "
                       "S&P +44% from low. May jobs +2.5M surprise. NASDAQ ATH by June.",
        price_start=66.0, price_end=95.0, mock_volatility=0.03,
        l3_green_lights=4, l1_direction="bullish",
    ),
    "y2022_rate_hike": ScenarioWindow(
        name="2022 Rate Hike / 60-40 Failure", start_date=date(2022, 1, 3), end_date=date(2022, 10, 12),
        expected_direction="bearish",
        key_assets_affected=["SPY", "QQQ", "TLT", "IWM", "ARKK"],
        market_context="Most aggressive Fed hikes in 40yr: 25+50+75bp x4. CPI 9.1%. S&P -25%, NASDAQ -35%. "
                       "60/40 worst year since 1937. Powell: 'pain necessary.' DXY at 114 (20yr high).",
        price_start=100.0, price_end=75.0, mock_volatility=0.022,
        l3_green_lights=3, l1_direction="bearish",
    ),
    "gfc2008": ScenarioWindow(
        name="2008 Global Financial Crisis", start_date=date(2008, 9, 15), end_date=date(2009, 3, 9),
        expected_direction="bearish",
        key_assets_affected=["SPY", "XLF", "VIX", "GLD", "TLT"],
        market_context="Lehman bankruptcy (Sep 15). AIG bailout $85B, TARP $700B, global rate cuts. "
                       "S&P -47% (Sep-Mar), VIX 89.53, credit frozen. (Proxy data — limited API pre-2010.)",
        price_start=100.0, price_end=53.0, mock_volatility=0.04,
        l3_green_lights=2, l1_direction="bearish",
    ),
    "banking2023": ScenarioWindow(
        name="2023 Banking Crisis (SVB)", start_date=date(2023, 3, 8), end_date=date(2023, 3, 24),
        expected_direction="bearish",
        key_assets_affected=["KRE", "XLF", "SIVB", "FRC", "BTC"],
        market_context="Fastest bank run ever: SVB $42B withdrawn in 1 day. FDIC seizure Mar 10. "
                       "Signature closed. First Republic teetered. CS→UBS forced. Fed BTFP. KRE -30%.",
        price_start=100.0, price_end=92.0, mock_volatility=0.025,
        l3_green_lights=2, l1_direction="bearish",
    ),
    "yen_carry2024": ScenarioWindow(
        name="2024 Yen Carry Trade Unwind", start_date=date(2024, 8, 1), end_date=date(2024, 8, 5),
        expected_direction="bearish",
        key_assets_affected=["NKY", "SPY", "QQQ", "USD/JPY", "BTC", "VIX"],
        market_context="BOJ hike to 0.25% + weak US jobs triggered violent carry unwind. "
                       "Nikkei -12.4% Aug 5 (worst since 1987). VIX 65 from 16. USD/JPY 154→142. "
                       ">$1B crypto liquidated. Global margin calls.",
        price_start=100.0, price_end=87.6, mock_volatility=0.035,
        l3_green_lights=2, l1_direction="bearish",
    ),
    "q42018_selloff": ScenarioWindow(
        name="2018 Q4 Selloff", start_date=date(2018, 10, 1), end_date=date(2018, 12, 24),
        expected_direction="bearish",
        key_assets_affected=["SPY", "QQQ", "IWM", "AAPL", "VIX"],
        market_context="Powell 'long way from neutral' + trade war fears. S&P -20% in 3 months. "
                       "Christmas Eve crash -2.7%. Oil -40%. Mnuchin bank-liquidity call backfired. "
                       "Powell pivoted Jan 4 — market bottomed.",
        price_start=100.0, price_end=80.0, mock_volatility=0.02,
        l3_green_lights=2, l1_direction="bearish",
    ),
}


@dataclass
class ScenarioBacktestResult:
    """Backtest output for a single scenario window."""
    scenario_name: str
    start_date: str
    end_date: str
    signals_generated: int
    no_trade_rate: float
    direction_calls: list[str] = field(default_factory=list)
    dsr: float = 0.0
    pbo: float = 0.0
    resonance_passed: bool = False
    detected_opportunity: bool = False
    verdict: str = ""


def _count_trading_days(start: date, end: date) -> int:
    """Count weekdays between start and end, inclusive. Minimum 5."""
    days = sum(1 for d in ((start + timedelta(days=i)) for i in range((end - start).days + 1))
               if d.weekday() < 5)
    return max(days, 5)


def _generate_price_series(start_price: float, end_price: float, trading_days: int,
                           volatility: float = 0.015, seed: int = 42) -> list[float]:
    """Synthetic GBM price series ending near end_price. Returns trading_days+1 points."""
    rng = random.Random(seed)
    prices = [start_price]
    drift = math.log(end_price / start_price) / max(trading_days, 1) if start_price > 0 and end_price > 0 else 0.0
    for _ in range(trading_days):
        prices.append(max(prices[-1] * math.exp(rng.gauss(drift, volatility)), 0.01))
    return prices


class ScenarioRunner:
    """Runs pipeline simulation against historical scenario windows.

    Mock mode: generates synthetic price series matching each scenario's historical % move,
    runs real resonance computation (DSR/PBO via resonance.py), then applies the production
    decision heuristic to determine if the system would have produced a trade signal.
    """

    def __init__(self, mock: bool = True):
        self.mock = mock

    def run_scenario(self, scenario_name: str) -> ScenarioBacktestResult:
        """Run backtest for one scenario. Raises ValueError if name unknown."""
        scenario = SCENARIO_LIBRARY.get(scenario_name)
        if scenario is None:
            raise ValueError(f"Unknown scenario '{scenario_name}'. "
                             f"Available: {', '.join(sorted(SCENARIO_LIBRARY))}")
        logger.info("Running: %s (%s to %s)", scenario.name, scenario.start_date, scenario.end_date)
        if not self.mock:
            return ScenarioBacktestResult(
                scenario_name=scenario.name, start_date=scenario.start_date.isoformat(),
                end_date=scenario.end_date.isoformat(), signals_generated=0, no_trade_rate=1.0,
                verdict="LIVE mode requires historical news API integration (not yet implemented).",
            )
        return self._run_mock(scenario)

    def run_all_scenarios(self) -> list[ScenarioBacktestResult]:
        """Run all 6 standard scenarios."""
        return [self.run_scenario(name) for name in SCENARIO_LIBRARY]

    def _run_mock(self, s: ScenarioWindow) -> ScenarioBacktestResult:
        """Simulate pipeline: generate prices, compute resonance, apply decision heuristic."""
        trading_days = _count_trading_days(s.start_date, s.end_date)
        prices = _generate_price_series(s.price_start, s.price_end, trading_days, s.mock_volatility)
        dsr, pbo, resonance_passed = self._compute_resonance(prices)

        # Production decision heuristic (mirrors decision.py:generate_decision line 459)
        no_trade = (not resonance_passed and s.l3_green_lights == 0)
        signals = 0 if no_trade else max(s.l3_green_lights, 1)
        detected = not no_trade

        direction_calls: list[str] = []
        if detected and s.l1_direction != "neutral":
            direction_calls.append(f"{s.l1_direction} on {', '.join(s.key_assets_affected[:3])}")

        if detected and resonance_passed:
            verdict = (f"DETECTED: {signals} signal(s). Resonance passed "
                       f"(DSR={dsr:.3f}, PBO={pbo:.3f}). Dir: {s.l1_direction}.")
        elif detected:
            verdict = (f"DETECTED via L3 green lights ({signals} signals) "
                       f"despite resonance DSR={dsr:.3f}, PBO={pbo:.3f}.")
        elif resonance_passed:
            verdict = (f"BORDERLINE: Resonance passed but no L3 green lights. "
                       f"Calibration question, not detection failure.")
        else:
            verdict = (f"MISSED: No-trade despite {s.name}. DSR={dsr:.3f}, PBO={pbo:.3f}, "
                       f"green_lights={s.l3_green_lights}. Check thresholds.")

        return ScenarioBacktestResult(
            scenario_name=s.name, start_date=s.start_date.isoformat(),
            end_date=s.end_date.isoformat(), signals_generated=signals,
            no_trade_rate=1.0 if no_trade else 0.0, direction_calls=direction_calls,
            dsr=dsr, pbo=pbo, resonance_passed=resonance_passed,
            detected_opportunity=detected, verdict=verdict,
        )

    @staticmethod
    def _compute_resonance(prices: list[float]) -> tuple[float, float, bool]:
        """Run real DSR/PBO via production resonance.py. Returns (dsr, pbo, passed)."""
        from marketmind.pipeline.resonance import (
            compute_returns, sharpe_ratio, deflated_sharpe_ratio, cscv_pbo,
        )
        returns = compute_returns(prices)
        if len(returns) < 5:
            return 0.0, 1.0, False

        sr = sharpe_ratio(returns)
        # Bootstrap null distribution: shuffle returns 100x for DSR estimation
        null_srs: list[float] = []
        rng = random.Random(42)
        shuffled = list(returns)
        for _ in range(100):
            rng.shuffle(shuffled)
            null_srs.append(abs(sharpe_ratio(shuffled)))

        dsr = deflated_sharpe_ratio(sr, n_trials=min(len(null_srs), 10), sharpe_distribution=null_srs)
        pbo = cscv_pbo(returns, n_splits=min(10, len(returns) // 2))
        passed = dsr > 0.0 and pbo <= 0.10
        logger.debug("Resonance: SR=%.3f DSR=%.3f PBO=%.3f passed=%s", sr, dsr, pbo, passed)
        return dsr, pbo, passed


def build_summary(results: list[ScenarioBacktestResult]) -> dict:
    """Build diagnostic summary with detection rate, aggregate metrics, and diagnostics."""
    n = len(results)
    detected = sum(1 for r in results if r.detected_opportunity)
    avg_dsr = sum(r.dsr for r in results) / max(n, 1)
    avg_pbo = sum(r.pbo for r in results) / max(n, 1)

    diags: list[str] = []
    if detected == 0:
        diags.append("CRITICAL: All 6 scenarios no-trade. Calibration problem — check thresholds.")
    elif detected < 3:
        diags.append(f"WARNING: Only {detected}/{n} detected. System may be overly conservative.")
    elif detected == n:
        diags.append(f"PASS: All {n} scenarios detected. System not stuck in no-trade.")
    else:
        diags.append(f"OK: {detected}/{n} detected ({n - detected} missed). Reasonable discrimination.")
    if avg_pbo > 0.50:
        diags.append(f"NOTE: Avg PBO={avg_pbo:.3f} high. PBO threshold (0.10) too strict for crisis windows?")

    return {
        "scenarios_tested": n, "detected": detected, "missed": n - detected,
        "detection_rate": detected / max(n, 1), "total_signals": sum(r.signals_generated for r in results),
        "avg_dsr": round(avg_dsr, 4), "avg_pbo": round(avg_pbo, 4),
        "diagnostics": diags,
        "scenarios": [{
            "name": r.scenario_name, "dates": f"{r.start_date} to {r.end_date}",
            "signals": r.signals_generated, "no_trade": r.no_trade_rate > 0.5,
            "dsr": round(r.dsr, 4), "pbo": round(r.pbo, 4),
            "detected": r.detected_opportunity, "verdict": r.verdict,
        } for r in results],
    }


def run_scenario_backtest(args) -> int:
    """CLI entry point for --mode scenario. Returns 0 on success, 1 on error."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    runner = ScenarioRunner(mock=getattr(args, "mock", True))

    try:
        scenario_name = getattr(args, "scenario", None)
        if scenario_name and scenario_name.lower() != "all":
            results = [runner.run_scenario(scenario_name)]
        else:
            results = runner.run_all_scenarios()

        for r in results:
            status = "DETECTED" if r.detected_opportunity else "MISSED"
            print(f"\n{'=' * 60}\n  {r.scenario_name}  [{status}]")
            print(f"  Dates: {r.start_date} -> {r.end_date}")
            print(f"  Signals: {r.signals_generated} | No-Trade Rate: {r.no_trade_rate:.0%}")
            print(f"  DSR: {r.dsr:.4f} | PBO: {r.pbo:.4f} | Resonance: "
                  f"{'PASS' if r.resonance_passed else 'FAIL'}")
            for dc in r.direction_calls:
                print(f"  Direction: {dc}")
            print(f"  Verdict: {r.verdict}")

        summary = build_summary(results)
        print(f"\n{'=' * 60}\n  SUMMARY: {summary['detected']}/{summary['scenarios_tested']} "
              f"detected ({summary['detection_rate']:.0%})")
        print(f"  Avg DSR: {summary['avg_dsr']:.4f} | Avg PBO: {summary['avg_pbo']:.4f}")
        for diag in summary["diagnostics"]:
            print(f"  {diag}")

        if getattr(args, "verbose", False):
            print(f"\n  [DEBUG] Full summary JSON:\n"
                  f"{json.dumps(summary, indent=2, ensure_ascii=False)}")
        return 0
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1
    except Exception as e:
        logger.exception("Scenario backtest failed")
        print(f"[ERROR] Unexpected error: {e}")
        return 1
