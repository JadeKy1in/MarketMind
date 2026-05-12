"""Layer 2: Fundamental analysis — 5-tier progressive: macro → asset → sector → factor → ticker."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("marketmind.pipeline.layer2")
from dataclasses import dataclass, field

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.layer1_narrative import Layer1Result


@dataclass
class Layer2Result:
    macro_quadrant: str             # expansion | slowdown | contraction | recovery
    macro_direction: str            # risk_on | risk_off
    preferred_assets: list[str]     # ["equities", "bonds", "gold", "commodities"]
    sector_shortlist: list[str]     # 3-5 sector names
    factor_scores: dict[str, float] # {ticker: macro_match_score}
    ticker_candidates: list[str]    # 5-10 ticker candidates
    ticker_weights: dict[str, float]  # {ticker: allocation_weight}
    sector_momentum: dict[str, str]   # {sector: accelerating|decelerating|stable}
    red_team_notes: list[str]      # challenges raised at each tier
    raw_analysis: str = ""


LAYER2_SYSTEM_PROMPT = """You are a fundamental macro analyst. Perform a 5-tier progressive analysis.

Tiers:
L2.1 Macro Quadrant: growth(accelerating/decelerating) x inflation(rising/falling) → current cycle position
L2.2 Asset Allocation: based on quadrant, where does capital flow? (equities/bonds/commodities/gold/crypto)
L2.3 Sector Selection: macro + Layer 1 narrative → 3-5 beneficiary sectors
L2.4 Factor Scan: for each candidate ticker, score macro sensitivity (rate/oil/dollar/growth beta)
L2.5 Ticker Recommendation: composite scoring → 5-10 ranked candidates with weights

Output JSON:
{
  "macro_quadrant": "expansion|slowdown|contraction|recovery",
  "macro_direction": "risk_on|risk_off",
  "preferred_assets": ["asset_class1", "asset_class2"],
  "sector_shortlist": ["sector1", "sector2", "sector3"],
  "sector_momentum": {"sector1": "accelerating|decelerating|stable"},
  "factor_scores": {"TICKER": 0.0-1.0},
  "ticker_candidates": ["TICKER1", "TICKER2"],
  "ticker_weights": {"TICKER1": 0.3, "TICKER2": 0.2},
  "tier_challenges": ["challenge at L2.2: ...", "challenge at L2.4: ..."]
}

Key principle: rate of change > absolute level. Sector acceleration/deceleration matters more than current position.
All scores must be evidence-based. Mark estimates with EST:."""


async def analyze_layer2(l1: Layer1Result, market_context: dict | None = None) -> Layer2Result:
    """Run Layer 2 fundamental analysis, incorporating Layer 1 narrative context."""
    context_str = _build_context(l1, market_context)
    user_prompt = f"Perform 5-tier fundamental analysis:\n\n{context_str}"
    try:
        result = await chat_pro(
            system_prompt=LAYER2_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        return _parse_layer2_response(result["content"])
    except Exception as e:
        logger.warning("Layer 2 analysis failed: %s", e)
        return Layer2Result(
            macro_quadrant="contraction", macro_direction="risk_off",
            preferred_assets=[], sector_shortlist=[], factor_scores={},
            ticker_candidates=[], ticker_weights={}, sector_momentum={},
            red_team_notes=["Layer 2 analysis failed to produce output"]
        )


def _build_context(l1: Layer1Result, market_context: dict | None) -> str:
    lines = [f"## Layer 1 Context",
             f"Event Grade: {l1.event_grade}",
             f"Matrix Quadrant: {l1.matrix_quadrant}",
             f"Sentiment: {l1.sentiment_direction} (intensity={l1.sentiment_intensity})",
             f"Price-in Score: {l1.price_in_score}",
             f"Cascade Hub: {l1.cascade_hub}"]
    if market_context:
        lines.append("\n## Market Data")
        for k, v in market_context.items():
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _parse_layer2_response(content: str) -> Layer2Result:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            raise
    return Layer2Result(
        macro_quadrant=data.get("macro_quadrant", "contraction"),
        macro_direction=data.get("macro_direction", "risk_off"),
        preferred_assets=data.get("preferred_assets", []),
        sector_shortlist=data.get("sector_shortlist", []),
        factor_scores=data.get("factor_scores", {}),
        ticker_candidates=data.get("ticker_candidates", []),
        ticker_weights=data.get("ticker_weights", {}),
        sector_momentum=data.get("sector_momentum", {}),
        red_team_notes=data.get("tier_challenges", []),
        raw_analysis=content,
    )
