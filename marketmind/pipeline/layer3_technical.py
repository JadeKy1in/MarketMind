"""Layer 3: technical review — 3-light gate + entry/exit levels (INDEPENDENT from L1-L2).

SPEC_v3 §5 step 3: every number here is computed by code from real price
history (pipeline/l3_indicators.py). No LLM call. A ticker whose history cannot
be fetched is reported red with data_available=False — never estimated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from marketmind.gateway.price_history import completed_history, get_price_histories
from marketmind.notification.alert_schema import ImpactScope
from marketmind.notification.monitor_decorator import monitor
from marketmind.pipeline.l3_indicators import (
    DEFAULT_MAX_HOLD_DAYS, TechnicalSnapshot, compute_snapshot, describe,
)

logger = logging.getLogger("marketmind.pipeline.layer3")


@dataclass
class Layer3Result:
    ticker: str
    light: str                     # green | yellow | red
    above_200wma: bool
    daily_structure_intact: bool
    near_key_resistance: bool
    resistance_distance_pct: float
    support_zone_low: float
    support_zone_high: float
    resistance_zone_low: float
    resistance_zone_high: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    target_price: float
    max_hold_days: int
    reward_risk_ratio: float
    recommendation: str            # enter | wait | avoid
    daily_return_pct: float | None = None
    raw_analysis: str = ""
    data_available: bool = True
    close: float | None = None
    as_of: str = ""


@dataclass
class Layer3BatchResult:
    results: list[Layer3Result] = field(default_factory=list)

    @property
    def green_lights(self) -> list[Layer3Result]:
        return [r for r in self.results if r.light == "green"]

    @property
    def red_lights(self) -> list[Layer3Result]:
        return [r for r in self.results if r.light == "red"]

    def get(self, ticker: str) -> Layer3Result | None:
        for r in self.results:
            if r.ticker == ticker:
                return r
        return None


@monitor(source="l3_technical", impact=ImpactScope.MAIN_PIPELINE)
async def analyze_layer3(tickers: list[str], market_data: dict | None = None,
                         calibration_context: str = "") -> Layer3BatchResult:
    """Code-computed 3-light review for `tickers`.

    `market_data` and `calibration_context` are accepted for call-site
    compatibility and ignored: L3 pulls its own price history and has no prompt.
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))  # dedupe, keep order
    if not tickers:
        return Layer3BatchResult()
    histories = await get_price_histories(tickers)
    results = []
    for t in tickers:
        hist = histories.get(t)
        # a running session's partial bar would move close, ATR and levels intraday
        snap = compute_snapshot(completed_history(hist)) if hist is not None else None
        if snap is None:
            results.append(unavailable_result(t))
        else:
            results.append(from_snapshot(snap))
    green = sum(r.light == "green" for r in results)
    missing = sum(not r.data_available for r in results)
    logger.info("L3: %d tickers, %d green, %d without data", len(results), green, missing)
    return Layer3BatchResult(results=results)


def from_snapshot(s: TechnicalSnapshot) -> Layer3Result:
    res = s.key_resistance or 0.0
    return Layer3Result(
        ticker=s.ticker, light=s.light,
        above_200wma=s.above_200wma, daily_structure_intact=s.structure_intact,
        near_key_resistance=s.near_key_resistance,
        resistance_distance_pct=s.resistance_distance_pct or 0.0,
        support_zone_low=s.support_low, support_zone_high=s.support_high,
        resistance_zone_low=res, resistance_zone_high=res,
        entry_zone_low=s.entry_low, entry_zone_high=s.entry_high,
        stop_loss=s.stop_loss, target_price=s.target_price,
        max_hold_days=DEFAULT_MAX_HOLD_DAYS, reward_risk_ratio=s.reward_risk_ratio,
        recommendation=s.recommendation, daily_return_pct=s.daily_return_pct,
        raw_analysis=describe(s), data_available=True, close=s.close, as_of=s.as_of,
    )


def unavailable_result(ticker: str) -> Layer3Result:
    return Layer3Result(
        ticker=ticker, light="red",
        above_200wma=False, daily_structure_intact=False,
        near_key_resistance=False, resistance_distance_pct=0.0,
        support_zone_low=0.0, support_zone_high=0.0,
        resistance_zone_low=0.0, resistance_zone_high=0.0,
        entry_zone_low=0.0, entry_zone_high=0.0,
        stop_loss=0.0, target_price=0.0,
        max_hold_days=0, reward_risk_ratio=0.0,
        recommendation="avoid",
        raw_analysis=f"{ticker}: price history unavailable — no technical view (not estimated)",
        data_available=False,
    )
