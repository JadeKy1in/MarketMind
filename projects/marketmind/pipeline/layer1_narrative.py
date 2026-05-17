"""Layer 1: Narrative analysis — event grading, 2x2 matrix, price-in, cascade, sentiment."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("marketmind.pipeline.layer1")

from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.flash_preprocessor import FlashSignal
from marketmind.pipeline.scout import NewsItem


@dataclass
class Layer1Result:
    event_grade: str               # A-E
    surprise_level: str            # high | low
    market_size: str               # big | small
    matrix_quadrant: str           # core_opportunity | trend_opportunity | arbitrage | observe_skip
    price_in_score: float          # 0.0-1.0, higher = more priced in
    cascade_rank: int              # 1-3: first-order, second-order, third-order
    cascade_hub: bool              # true if triggers cascading effects
    sentiment_direction: str       # bullish | bearish | neutral
    sentiment_intensity: float     # 0.0-1.0
    sentiment_vs_attention: str    # high_sentiment | high_attention | both | neither
    expert_signals: list[dict]     # [{"expert": name, "position": str, "historical_accuracy": float}]
    institutional_surprise: str    # description of gap between official stance and market expectations
    key_characters: list[dict]     # [{"name": str, "capability": str, "will": str, "market_trust": str}]
    tail_risk_flags: list[str]     # triggered tail risk indicators
    raw_analysis: str = ""


LAYER1_SYSTEM_PROMPT = """You are a financial narrative analyst specializing in event-driven macro analysis.

Analyze the provided news signals and produce a structured narrative analysis. You must output valid JSON.

{
  "event_grade": "A|B|C|D|E",
  "surprise_level": "high|low",
  "market_size": "big|small",
  "matrix_quadrant": "core_opportunity|trend_opportunity|arbitrage|observe_skip",
  "price_in_score": 0.0-1.0,
  "cascade_rank": 1-3,
  "cascade_hub": true|false,
  "sentiment_direction": "bullish|bearish|neutral",
  "sentiment_intensity": 0.0-1.0,
  "sentiment_vs_attention": "high_sentiment|high_attention|both|neither",
  "expert_signals": [{"expert": "name", "position": "long/short/neutral", "historical_accuracy": 0.0-1.0}],
  "institutional_surprise": "brief description of gap between official stance and expectations",
  "key_characters": [{"name": "string", "capability": "has_power|needs_approval", "will": "real_intent|political_theater", "market_trust": "believed|skeptical"}],
  "tail_risk_flags": ["list of triggered risk indicators"],
  "narrative_summary": "2-3 sentence narrative synthesis"
}

Event grades: A=monetary_policy, B=corporate_actions, C=regulation, D=geopolitical, E=macro_data
Matrix: core_opportunity (high surprise + big market) | trend_opportunity (low surprise + big market) | arbitrage (high surprise + small market) | observe_skip (low surprise + small market)
Price-in: Compare option-implied vol, pre-event price drift, analyst consensus — 1.0 = fully priced in
Sentiment vs attention: high sentiment = reversal risk, high attention = continuation likely
Tail risk: implied correlation spikes, VIX term structure inversion, volatility clustering

IMPORTANT: All numeric values must cite a verifiable source or be marked EST:. Never fabricate data."""


async def analyze_layer1(signals: list[FlashSignal], news_items: list[NewsItem]) -> Layer1Result:
    """Run Layer 1 narrative analysis on preprocessed signals."""
    if not signals:
        return Layer1Result(
            event_grade="E", surprise_level="low", market_size="small",
            matrix_quadrant="observe_skip", price_in_score=0.5, cascade_rank=1,
            cascade_hub=False, sentiment_direction="neutral", sentiment_intensity=0.0,
            sentiment_vs_attention="neither", expert_signals=[],
            institutional_surprise="", key_characters=[], tail_risk_flags=[]
        )
    signal_text = _format_signals(signals, news_items)
    user_prompt = f"Analyze these market signals for narrative structure:\n\n{signal_text}"
    try:
        result = await chat_pro(
            system_prompt=LAYER1_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        content = result["content"]
        return _parse_layer1_response(content)
    except Exception as e:
        logger.warning("Layer 1 analysis failed: %s", e)
        return Layer1Result(
            event_grade="E", surprise_level="low", market_size="small",
            matrix_quadrant="observe_skip", price_in_score=0.5, cascade_rank=1,
            cascade_hub=False, sentiment_direction="neutral", sentiment_intensity=0.0,
            sentiment_vs_attention="neither", expert_signals=[],
            institutional_surprise="", key_characters=[], tail_risk_flags=[]
        )


def _format_signals(signals, news_items: list[NewsItem]) -> str:
    """Format signals for L1 narrative prompt.

    Accepts both FlashSignal (from flash_preprocessor) and TriageResult
    (from flash_triage). Uses getattr for backward compatibility — TriageResult
    has classification instead of event_type, scores dict instead of flat
    confidence, and headline instead of source_headline.
    """
    lines = ["## Preprocessed Signals"]
    for s in signals:
        event_grade = getattr(s, "event_grade", "E")
        event_type = getattr(s, "event_type", None) or getattr(s, "classification", "unknown")
        direction = getattr(s, "direction", "neutral")
        confidence = getattr(s, "confidence", None)
        if confidence is None:
            scores = getattr(s, "scores", {})
            confidence = scores.get("market_impact", 5) / 10.0
        source = getattr(s, "source_headline", None) or getattr(s, "headline", "")
        lines.append(
            f"- [{event_grade}] {event_type} | {direction} "
            f"(conf={confidence:.2f}) | {source[:120]}"
        )
    if news_items:
        lines.append("\n## Raw Headlines")
        for item in news_items[:20]:
            lines.append(f"- [{item.source_name}] {item.title}")
    return "\n".join(lines)


def _parse_layer1_response(content: str) -> Layer1Result:
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
    return Layer1Result(
        event_grade=data.get("event_grade", "E"),
        surprise_level=data.get("surprise_level", "low"),
        market_size=data.get("market_size", "small"),
        matrix_quadrant=data.get("matrix_quadrant", "observe_skip"),
        price_in_score=float(data.get("price_in_score", 0.5)),
        cascade_rank=int(data.get("cascade_rank", 1)),
        cascade_hub=bool(data.get("cascade_hub", False)),
        sentiment_direction=data.get("sentiment_direction", "neutral"),
        sentiment_intensity=float(data.get("sentiment_intensity", 0.0)),
        sentiment_vs_attention=data.get("sentiment_vs_attention", "neither"),
        expert_signals=data.get("expert_signals", []),
        institutional_surprise=data.get("institutional_surprise", ""),
        key_characters=data.get("key_characters", []),
        tail_risk_flags=data.get("tail_risk_flags", []),
        raw_analysis=content,
    )
