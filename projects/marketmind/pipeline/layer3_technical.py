"""Layer 3: Technical review — 3-light review + entry/exit calculation (INDEPENDENT from L1-L2)."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

logger = logging.getLogger("marketmind.pipeline.layer3")
import json
from typing import Any

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences


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
    daily_return_pct: float | None = None  # daily return % from market data
    raw_analysis: str = ""


@dataclass
class Layer3BatchResult:
    results: list[Layer3Result] = field(default_factory=list)

    @property
    def green_lights(self) -> list[Layer3Result]:
        return [r for r in self.results if r.light == "green"]

    @property
    def red_lights(self) -> list[Layer3Result]:
        return [r for r in self.results if r.light == "red"]


LAYER3_SYSTEM_PROMPT = """You are a technical analyst. Your ONLY job is to determine whether to buy, wait, or avoid — you do NOT generate trade ideas.

IMPORTANT: You receive ONLY raw market data and a list of tickers. You do NOT see Layer 1 or Layer 2 analysis. This is intentional — you must provide an independent technical opinion.

For each ticker, perform the 3-light review:
1. Price > 200 WMA? (Weekly Moving Average)
2. Daily structure intact? (higher highs/lows in uptrend, lower highs/lows in downtrend)
3. Not within 3% of key resistance?

Lights:
- GREEN: All 3 conditions pass → proceed to entry calculation
- YELLOW: 1-2 conditions fail → WAIT, do not add
- RED: All 3 fail → DO NOT BUY regardless of fundamental thesis

For GREEN lights only, calculate:
- Support zone (who is buying: ETF flows, institutional, volume nodes)
- Resistance zone (option open interest clusters, historical sellers, round numbers)
- Entry zone (2-3% wide, not exact price points)
- Stop-loss (below support structure)
- Target price (next major resistance)
- Max hold days

Output JSON array:
[{
  "ticker": "TICKER",
  "light": "green|yellow|red",
  "above_200wma": true|false,
  "daily_structure_intact": true|false,
  "near_key_resistance": true|false,
  "resistance_distance_pct": 0.0,
  "support_zone_low": 0.0,
  "support_zone_high": 0.0,
  "resistance_zone_low": 0.0,
  "resistance_zone_high": 0.0,
  "entry_zone_low": 0.0,
  "entry_zone_high": 0.0,
  "stop_loss": 0.0,
  "target_price": 0.0,
  "max_hold_days": 30,
  "reward_risk_ratio": 0.0,
  "recommendation": "enter|wait|avoid"
}]

Druckenmiller principle: if fundamentals bullish but technicals bearish → lean toward no buy. Price is the final arbiter.

IMPORTANT: All price data must be verifiable. Never fabricate levels."""


@monitor(source="l3_technical", impact=ImpactScope.MAIN_PIPELINE)
async def analyze_layer3(tickers: list[str], market_data: dict | None = None) -> Layer3BatchResult:
    """Run Layer 3 technical review. Receives ONLY ticker list and raw market data — NOT L1/L2 results."""
    if not tickers:
        return Layer3BatchResult()
    data_str = _format_market_data(market_data)
    user_prompt = f"Review these tickers independently. Do NOT consider any fundamental thesis.\n\nTickers: {', '.join(tickers)}\n\nMarket Data:\n{data_str}"
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    yr = today[:4]
    date_note = (
        f"\n\n[TODAY: {today}. All support/resistance/entry levels must be current ({yr}) levels. "
        f"Do NOT use {int(yr)-2}-{int(yr)-1} price levels as current. "
        f"If you lack current price data, flag it and estimate from provided market context.]"
    )
    try:
        result = await chat_pro(
            system_prompt=LAYER3_SYSTEM_PROMPT + date_note,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=8192,
        )
        raw = result["content"]
        parsed = _parse_layer3_response(raw)
        # Fill missing tickers with avoid results
        seen = {r.ticker for r in parsed}
        for t in tickers:
            if t not in seen:
                parsed.append(Layer3Result(
                    ticker=t, light="red",
                    above_200wma=False, daily_structure_intact=False,
                    near_key_resistance=True, resistance_distance_pct=0,
                    support_zone_low=0, support_zone_high=0,
                    resistance_zone_low=0, resistance_zone_high=0,
                    entry_zone_low=0, entry_zone_high=0,
                    stop_loss=0, target_price=0,
                    max_hold_days=0, reward_risk_ratio=0,
                    recommendation="avoid"
                ))
        return Layer3BatchResult(results=parsed)
    except Exception as e:
        logger.warning("Layer 3 analysis failed: %s", e)
        return Layer3BatchResult()


def _format_market_data(data: dict | None) -> str:
    if not data:
        return "No market data available."
    return "\n".join(f"- {k}: {v}" for k, v in data.items())


def _parse_layer3_response(content: str) -> list[Layer3Result]:
    content = strip_markdown_fences(content)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return []
    results = []
    for d in data:
        results.append(Layer3Result(
            ticker=d.get("ticker", "UNKNOWN"),
            light=d.get("light", "red"),
            above_200wma=d.get("above_200wma", False),
            daily_structure_intact=d.get("daily_structure_intact", False),
            near_key_resistance=d.get("near_key_resistance", True),
            resistance_distance_pct=float(d.get("resistance_distance_pct") or 0),
            support_zone_low=float(d.get("support_zone_low") or 0),
            support_zone_high=float(d.get("support_zone_high") or 0),
            resistance_zone_low=float(d.get("resistance_zone_low") or 0),
            resistance_zone_high=float(d.get("resistance_zone_high") or 0),
            entry_zone_low=float(d.get("entry_zone_low") or 0),
            entry_zone_high=float(d.get("entry_zone_high") or 0),
            stop_loss=float(d.get("stop_loss") or 0),
            target_price=float(d.get("target_price") or 0),
            max_hold_days=int(d.get("max_hold_days") or 0),
            reward_risk_ratio=float(d.get("reward_risk_ratio") or 0),
            recommendation=d.get("recommendation", "avoid"),
            daily_return_pct=float(d.get("daily_return_pct")) if d.get("daily_return_pct") is not None else None,
            raw_analysis=content,
        ))
    return results
