"""Layer 2: Fundamental analysis — 5-tier progressive: macro → asset → sector → factor → ticker."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("marketmind.pipeline.layer2")
from dataclasses import dataclass, field

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.pipeline.layer1_narrative import Layer1Result


@dataclass
class Layer2Result:
    macro_quadrant: str = "unknown"           # expansion | slowdown | contraction | recovery
    macro_direction: str = "unknown"          # risk_on | risk_off
    preferred_assets: list[str] = field(default_factory=list)
    sector_shortlist: list[str] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)
    ticker_candidates: list[str] = field(default_factory=list)
    ticker_weights: dict[str, float] = field(default_factory=dict)
    sector_momentum: dict[str, str] = field(default_factory=dict)
    red_team_notes: list[str] = field(default_factory=list)
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
All scores must be evidence-based. Mark estimates with EST:.

CRITICAL: Output ONLY the JSON object. Do NOT include any reasoning, thinking process, chain-of-thought, or commentary. The ENTIRE response must be valid JSON.
"""


async def analyze_layer2(l1: Layer1Result, market_context: dict | None = None,
                         l1_context: str | None = None) -> Layer2Result:
    """Run Layer 2 fundamental analysis, incorporating Layer 1 narrative context."""
    context_str = _build_context(l1, market_context)
    if l1_context:
        context_str += f"\n\n## User's L1 Discussion Context (DEFANG filtered)\n{l1_context}"
    user_prompt = f"Perform 5-tier fundamental analysis:\n\n{context_str}"
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    yr = today[:4]
    date_note = (
        f"\n\n[TODAY: {today}. All sector/factor/ticker analysis must reflect current ({yr}) conditions. "
        f"Do NOT treat {int(yr)-2}-{int(yr)-1} data as 'current'. "
        f"If unsure about post-training-cutoff data, flag it and use the news context provided.]"
    )
    try:
        result = await chat_pro(
            system_prompt=LAYER2_SYSTEM_PROMPT + date_note,
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
    content = strip_markdown_fences(content)

    def _try_parse(text: str) -> dict | None:
        """Try to extract a valid JSON object from text, with repair attempts."""
        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Extract { } block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            block = text[start:end + 1]
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass
            # Remove trailing commas before } or ]
            import re
            repaired = re.sub(r",\s*([}\]])", r"\1", block)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        return None

    data = _try_parse(content)
    if data is None:
        # Fallback: extract what we can with regex
        import re
        tickers = re.findall(r'"ticker_candidates"\s*:\s*\[(.*?)\]', content, re.DOTALL)
        sectors = re.findall(r'"sector_shortlist"\s*:\s*\[(.*?)\]', content, re.DOTALL)
        quadrant_match = re.search(r'"macro_quadrant"\s*:\s*"(\w+)"', content)
        direction_match = re.search(r'"macro_direction"\s*:\s*"(\w+)"', content)
        logger.warning("L2 JSON parse failed — using regex extraction from %d chars", len(content))
        data = {
            "macro_quadrant": quadrant_match.group(1) if quadrant_match else "contraction",
            "macro_direction": direction_match.group(1) if direction_match else "risk_off",
            "sector_shortlist": [],
            "ticker_candidates": [],
            "preferred_assets": [],
            "factor_scores": {},
            "ticker_weights": {},
            "sector_momentum": {},
            "tier_challenges": ["L2 JSON parsing failed — partial results may be missing"],
        }

    # If sector_shortlist is populated but ticker_candidates is empty,
    # fall back to asset universe matching so L3 has something to analyze
    sectors = data.get("sector_shortlist", [])
    tickers = data.get("ticker_candidates", [])
    if sectors and not tickers:
        try:
            from marketmind.config.asset_universe import ASSET_UNIVERSE
            sector_keywords = {s.lower(): s for s in sectors}
            for asset in ASSET_UNIVERSE.values():
                if hasattr(asset, 'sector') and asset.sector.lower() in sector_keywords:
                    tickers.append(asset.ticker)
                if len(tickers) >= 15:
                    break
            if tickers:
                logger.info("L2 fallback: filled %d tickers from asset universe for sectors %s",
                           len(tickers), sectors[:3])
        except Exception:
            pass

    return Layer2Result(
        macro_quadrant=data.get("macro_quadrant", "contraction"),
        macro_direction=data.get("macro_direction", "risk_off"),
        preferred_assets=data.get("preferred_assets", []),
        sector_shortlist=sectors,
        factor_scores=data.get("factor_scores", {}),
        ticker_candidates=tickers,
        ticker_weights=data.get("ticker_weights", {}),
        sector_momentum=data.get("sector_momentum", {}),
        red_team_notes=data.get("tier_challenges", []),
        raw_analysis=content,
    )
