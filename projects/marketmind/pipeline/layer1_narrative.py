"""Layer 1: Narrative analysis — event grading, 2x2 matrix, price-in, cascade, sentiment."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

logger = logging.getLogger("marketmind.pipeline.layer1")

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.pipeline.flash_preprocessor import FlashSignal
from marketmind.pipeline.scout import NewsItem
from marketmind.shadows.shadow_agent import defang_text


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

    @classmethod
    def empty_default(cls) -> "Layer1Result":
        """Return a default Layer1Result representing no-signal / error state."""
        return cls(
            event_grade="E", surprise_level="low", market_size="small",
            matrix_quadrant="observe_skip", price_in_score=0.5, cascade_rank=1,
            cascade_hub=False, sentiment_direction="neutral", sentiment_intensity=0.0,
            sentiment_vs_attention="neither", expert_signals=[],
            institutional_surprise="", key_characters=[], tail_risk_flags=[]
        )


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


@monitor(source="l1_narrative", impact=ImpactScope.MAIN_PIPELINE)
async def analyze_layer1(signals: list[FlashSignal], news_items: list[NewsItem],
                         calibration_context: str = "") -> Layer1Result:
    """Run Layer 1 narrative analysis on preprocessed signals.

    If calibration_context is provided (from past prediction accuracy),
    it is prepended to the system prompt as a calibration hint.
    """
    if not signals:
        return Layer1Result.empty_default()
    signal_text = _format_signals(signals, news_items)
    user_prompt = f"Analyze these market signals for narrative structure:\n\n{signal_text}"
    sys_prompt = LAYER1_SYSTEM_PROMPT
    if calibration_context:
        sys_prompt = calibration_context + "\n\n" + LAYER1_SYSTEM_PROMPT
    try:
        result = await chat_pro(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=32768,
        )
        content = result["content"]
        return _parse_layer1_response(content)
    except Exception as e:
        logger.warning("Layer 1 analysis failed: %s", e)
        return Layer1Result.empty_default()


def _format_signals(signals: list[FlashSignal], news_items: list[NewsItem],
                    insider_items: list[NewsItem] | None = None,
                    social_items: list[NewsItem] | None = None) -> str:
    """Format signals and news for L1 narrative analysis.

    CRITICAL-2 fix: insider_signal and social_mention items bypass Flash preprocessing
    and are appended as structured context data with appropriate caveats.
    """
    lines = ["## Preprocessed Signals"]
    for s in signals:
        lines.append(f"- [{s.event_grade}] {s.event_type} | {s.direction} (conf={s.confidence}) | {defang_text(s.source_headline)}")
    if news_items:
        lines.append("\n## Raw Headlines")
        for item in news_items[:20]:
            lines.append(f"- [{item.source_name}] {defang_text(item.title)}")
    # Insider signals: legally-mandated public disclosures, bypass Flash preprocessing
    if insider_items:
        lines.append("\n## Insider Signal Data (Public Disclosures)")
        lines.append("NOTE: These are legally-mandated SEC/Congressional filings — treat as context enrichment, not real-time trading signals.")
        for item in insider_items[:15]:
            lines.append(f"- [{item.source_name}] {defang_text(item.title)} | {defang_text(item.summary[:200])}")
    # Social media mentions: retail sentiment, subject to manipulation — contrarian indicator
    if social_items:
        lines.append("\n## Social Media Mentions (Retail Sentiment)")
        lines.append("NOTE: Social media sentiment is a CONTRARIAN INDICATOR. Extreme retail bullishness often precedes pullbacks; extreme panic can signal bottoms. Treat as positioning/crowding context, not directional signal.")
        for item in social_items[:10]:
            lines.append(f"- [{item.source_name}] {defang_text(item.title)} | {defang_text(item.summary[:200])}")
    return "\n".join(lines)


def _safe_float(val, default=0.0):
    """Parse float from possibly-prefixed string like 'EST:0.7' or '~0.5'."""
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return default
    import re
    m = re.search(r'[-]?\d+\.?\d*', str(val))
    return float(m.group()) if m else default


def _parse_layer1_response(content: str) -> Layer1Result:
    content = strip_markdown_fences(content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    # If JSON parse failed, extract fields from free-form text via regex
    if data is None:
        import re
        logger.warning("Layer1 response has no parseable JSON — %d chars, extracting from text", len(content))

        def _re_field(pattern, text, default=None):
            """Return group(1) if regex matches, else default."""
            m = re.search(pattern, text)
            return m.group(1) if m else default

        # ── Grade: try "event_grade: X", then "grade: X" ──
        grade = "D"
        m = re.search(r'event.grade[:\s]*["\']?([A-Ea-e])', content)
        if m:
            grade = m.group(1).upper()
        else:
            m = re.search(r'\bgrade[:\s]*["\']?([A-Ea-e])\b', content, re.IGNORECASE)
            if m:
                grade = m.group(1).upper()

        # ── Quadrant: try direct extraction, then keyword heuristic ──
        quadrant = "observe_skip"
        m = re.search(r'(?:matrix_)?quadrant[:\s]*["\']?([a-z_]+\s*(?:\w+\s*)*)', content, re.IGNORECASE)
        if m:
            raw_q = m.group(1).strip().lower().replace(" ", "_")
            # Normalize: LLM may output "core opportunity" (with space)
            if "core" in raw_q and "opportunity" in raw_q:
                quadrant = "core_opportunity"
            elif "trend" in raw_q and "opportunity" in raw_q:
                quadrant = "trend_opportunity"
            elif "arbitrage" in raw_q:
                quadrant = "arbitrage"
            elif "observe" in raw_q or "skip" in raw_q:
                quadrant = "observe_skip"
        if quadrant == "observe_skip":
            # Heuristic fallback from keyword intensity
            has_surprise = bool(re.search(r'surprise|shock|unexpected|breaking|crash|surge', content, re.IGNORECASE))
            has_big = bool(re.search(r'broad|systemic|global|sector.wide|contagion|spillover', content, re.IGNORECASE))
            if has_surprise and has_big:
                quadrant = "core_opportunity"
            elif not has_surprise and has_big:
                quadrant = "trend_opportunity"
            elif has_surprise and not has_big:
                quadrant = "arbitrage"

        # ── Direction ──
        direction = "neutral"
        if re.search(r'bullish|看多|做多|long\b', content):
            direction = "bullish"
        elif re.search(r'bearish|看空|做空|short\b', content):
            direction = "bearish"

        # ── Surprise level ──
        surprise_level = _re_field(r'surprise_level[:\s]*["\']?(high|low)', content, "low")

        # ── Market size ──
        market_size = _re_field(r'market_size[:\s]*["\']?(big|small)', content, "small")

        # ── Numeric fields from free-form text ──
        price_in_score = _safe_float(
            _re_field(r'price_in_score[:\s]*([-]?\d+\.?\d*)', content), 0.5
        )
        sentiment_intensity = _safe_float(
            _re_field(r'sentiment_intensity[:\s]*([-]?\d+\.?\d*)', content), 0.0
        )
        cascade_rank_raw = _re_field(r'cascade_rank[:\s]*(\d+)', content)
        cascade_rank = int(cascade_rank_raw) if cascade_rank_raw is not None else 1

        # ── Cascade hub ──
        cascade_hub_raw = _re_field(r'cascade_hub[:\s]*(true|false|yes|no)', content)
        cascade_hub = cascade_hub_raw.lower() in ("true", "yes") if cascade_hub_raw else False

        # ── Sentiment vs attention ──
        sentiment_vs_attention = _re_field(
            r'sentiment_vs_attention[:\s]*["\']?(high_sentiment|high_attention|both|neither)',
            content, "neither"
        )

        data = {
            "event_grade": grade,
            "surprise_level": surprise_level,
            "market_size": market_size,
            "matrix_quadrant": quadrant,
            "price_in_score": price_in_score,
            "cascade_rank": cascade_rank,
            "cascade_hub": cascade_hub,
            "sentiment_direction": direction,
            "sentiment_intensity": sentiment_intensity,
            "sentiment_vs_attention": sentiment_vs_attention,
            "raw_analysis": content,
        }
    # Always preserve raw analysis text
    if "raw_analysis" not in data:
        data["raw_analysis"] = content
    return Layer1Result(
        event_grade=data.get("event_grade", "E"),
        surprise_level=data.get("surprise_level", "low"),
        market_size=data.get("market_size", "small"),
        matrix_quadrant=data.get("matrix_quadrant", "observe_skip"),
        price_in_score=_safe_float(data.get("price_in_score"), 0.5),
        cascade_rank=int(_safe_float(data.get("cascade_rank"), 1)),
        cascade_hub=bool(data.get("cascade_hub", False)),
        sentiment_direction=data.get("sentiment_direction", "neutral"),
        sentiment_intensity=_safe_float(data.get("sentiment_intensity"), 0.0),
        sentiment_vs_attention=data.get("sentiment_vs_attention", "neither"),
        expert_signals=data.get("expert_signals", []),
        institutional_surprise=data.get("institutional_surprise", ""),
        key_characters=data.get("key_characters", []),
        tail_risk_flags=data.get("tail_risk_flags", []),
        raw_analysis=content,
    )
