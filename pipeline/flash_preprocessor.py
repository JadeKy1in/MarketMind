"""Flash preprocessor: batch signal extraction, classification, denoising."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("marketmind.pipeline.flash")
from dataclasses import dataclass, field

from marketmind.gateway.async_client import chat_batch_flash, chat_flash
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.pipeline.scout import NewsItem


@dataclass
class FlashSignal:
    signal_id: str
    event_type: str
    event_grade: str  # A-E
    direction: str    # bullish | bearish | neutral
    confidence: float
    affected_assets: list[str]
    key_facts: list[str]
    noise_flag: bool
    cascade_potential: str  # high | medium | low
    source_headline: str = ""
    source_url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "FlashSignal":
        return cls(
            signal_id=d.get("signal_id", ""),
            event_type=d.get("event_type", "macro_data"),
            event_grade=d.get("event_grade", "E"),
            direction=d.get("direction", "neutral"),
            confidence=float(d.get("confidence", 0.5)),
            affected_assets=d.get("affected_assets", []),
            key_facts=d.get("key_facts", []),
            noise_flag=d.get("noise_flag", False),
            cascade_potential=d.get("cascade_potential", "low"),
        )


FLASH_SYSTEM_PROMPT = """You are a financial news preprocessor. Your task is to extract investable signals from news headlines.

For each article, output a structured signal:
{
  "signal_id": "SIG-{date}-{seq}",
  "event_type": "monetary_policy|corporate_action|regulation|geopolitical|macro_data",
  "event_grade": "A|B|C|D|E",
  "direction": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "affected_assets": ["ticker1", "ticker2"],
  "key_facts": ["fact1 with data source", "fact2"],
  "noise_flag": true|false,
  "cascade_potential": "high|medium|low"
}

Grades: A=monetary policy, B=corporate actions, C=regulation, D=geopolitical, E=macro data.
Direction: bullish (likely to push prices up), bearish (likely to push prices down), neutral.
Noise flag: true if the headline is likely noise, clickbait, or already widely priced in.

Return ONLY valid JSON array. No markdown, no explanation.

IMPORTANT: Never fabricate data. If a number is unavailable, omit it rather than guessing."""


def _build_headline_text(items: list[NewsItem]) -> str:
    lines = []
    for i, item in enumerate(items):
        lines.append(f"[{i}] [{item.source_name}] {item.title} | {item.summary[:200]}")
    return "\n".join(lines)


async def preprocess_batch(items: list[NewsItem], batch_size: int = 15) -> list[FlashSignal]:
    """Process news items through Flash in batches. Returns structured signals."""
    if not items:
        return []
    signals: list[FlashSignal] = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        headline_text = _build_headline_text(batch)
        user_prompt = f"Process these headlines and return only the JSON array of signals:\n{headline_text}"
        try:
            result = await chat_flash(
                system_prompt=FLASH_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            content = result["content"]
            raw_signals = _parse_json_response(content)
            for j, sig_dict in enumerate(raw_signals):
                signal = FlashSignal.from_dict(sig_dict)
                if j < len(batch):
                    signal.source_headline = batch[j].title
                    signal.source_url = batch[j].url
                signals.append(signal)
        except Exception as e:
            logger.warning("Flash preprocessing failed for item: %s", e)
            continue
    return signals


async def preprocess_single(item: NewsItem) -> FlashSignal | None:
    """Process a single high-priority news item."""
    headline_text = f"[{item.source_name}] {item.title} | {item.summary[:200]}"
    user_prompt = f"Process this headline and return a single signal JSON object:\n{headline_text}"
    try:
        result = await chat_flash(
            system_prompt=FLASH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=2048,
        )
        content = result["content"]
        raw_signals = _parse_json_response(content)
        if raw_signals:
            signal = FlashSignal.from_dict(raw_signals[0])
            signal.source_headline = item.title
            signal.source_url = item.url
            return signal
    except Exception as e:
        logger.warning("Flash single preprocessing failed: %s", e)
    return None


def _parse_json_response(content: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown wrapping."""
    content = strip_markdown_fences(content)
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
    return []
