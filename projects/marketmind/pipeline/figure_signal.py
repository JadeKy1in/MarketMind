"""FigureSignalExtractor — detect and classify market-moving figure activity.

Scans news items for mentions of key persons, classifies signal type,
computes AWA scores, and emits FigureSignal objects for the main pipeline.

Design spec: market-figure-intelligence-module.md §8
  - Flash LLM ONLY for market-relevance classification — not for AWA scoring (§8.3)
  - AWA scoring delegated to awa_scorer.py (§8.3)
  - FigureSignal objects passed to BOTH main pipeline and shadow ecosystem (§8.1)
  - Shadows receive RAW content only (person_name + text + timestamp) — no AWA scores (§8.1)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.config.key_persons import KeyPerson

from marketmind.config.key_persons import KEY_PERSONS
from marketmind.pipeline.awa_scorer import AWAScorer

logger = logging.getLogger("marketmind.pipeline.figure_signal")

# ── Category labels ────────────────────────────────────────────────────────────

CATEGORY_LABELS: dict[str, str] = {
    "I": "policymaker",
    "II": "political",
    "III": "executive",
    "IV": "activist",
    "V": "fund_manager",
    "VI": "celebrity",
}

# ── Directional keyword patterns ───────────────────────────────────────────────

BULLISH_PATTERNS: list[str] = [
    r"\bbuy\b", r"\bpurchase\b", r"\blong\b", r"\bbullish\b",
    r"\bupgrade\b", r"\bbeat\b", r"\braise\s+guidance\b",
    r"\baccumulate\b", r"\bincrease\s+position\b", r"\boverweight\b",
    r"\bpositive\b", r"\boutperform\b", r"\bstrong\s+buy\b",
    r"\bacquire\b", r"\bexpansion\b", r"\bgrowth\b",
    r"\badded\s+to\b", r"\binitiated\b", r"\bboost\b",
]

BEARISH_PATTERNS: list[str] = [
    r"\bsell\b", r"\bshort\b", r"\bbearish\b", r"\bdowngrade\b",
    r"\bmiss\b", r"\bcut\s+guidance\b", r"\breduce\b",
    r"\bdump\b", r"\bunderweight\b", r"\bnegative\b",
    r"\bunderperform\b", r"\bweak\b", r"\bliquidate\b",
    r"\bexit\b", r"\bwarning\b",
    r"\btrim\b", r"\bslashed\b", r"\bwarns\b",
]

WARN_PATTERNS: list[str] = [
    r"\bwarn(?:ing|s)?\b", r"\brisk\b", r"\bcaution\b",
    r"\bconcern\b", r"\bthreat\b", r"\bdanger\b",
    r"\bovervalued\b", r"\bbubble\b", r"\bunsustainable\b",
]

# ── Event type detection patterns ──────────────────────────────────────────────

TRADE_PATTERNS: list[str] = [
    r"\bbought\b", r"\bsold\b", r"\bpurchased\b", r"\bacquired\b",
    r"\bdisclosed\b", r"\bform\s*4\b", r"\btransaction\b",
    r"\bposition\b", r"\bshares\b", r"\bstake\b",
]

FILING_PATTERNS: list[str] = [
    r"\b13[fF]\b", r"\bform\s*[34]\b", r"\bfiling\b", r"\bedgar\b",
    r"\bdisclosure\b", r"\bholding\b", r"\breported\b",
    r"\bquarterly\s*report\b", r"\bannual\s*report\b",
]

SPEECH_PATTERNS: list[str] = [
    r"\bspeech\b", r"\bremarks\b", r"\bstatement\b", r"\btestimony\b",
    r"\bpress\s*conference\b", r"\bhearing\b", r"\baddress\b",
    r"\bminutes\b", r"\bfomc\b", r"\bdecision\b",
    r"\bconference\b", r"\bkeynote\b", r"\binterview\b",
]

SOCIAL_PATTERNS: list[str] = [
    r"\btweet(?:ed|s)?\b", r"\bpost(?:ed|s)?\b", r"\btruth\s*social\b",
    r"\bx\s*(?:formerly|平台|post)", r"\bsocial\s*media\b",
    r"\breddit\b", r"\byoutube\b", r"\bvideo\b",
]

# ── Flash LLM system prompt for market-relevance classification ────────────────

MARKET_RELEVANCE_SYSTEM_PROMPT = (
    "You are a financial relevance classifier. Determine if a mention of a key "
    "market figure in a news article is relevant to financial markets.\n\n"
    "Return ONLY a JSON object: {\"relevant\": true/false, \"reason\": \"brief explanation\"}\n\n"
    "Guidelines:\n"
    "- RELEVANT: comments on monetary policy, interest rates, trade, tariffs, "
    "regulations, specific stocks/sectors, economic outlook, corporate strategy, "
    "earnings, M&A, capital allocation, market trends\n"
    "- NOT RELEVANT: personal life, non-financial politics, entertainment gossip, "
    "charity events, sports, unrelated social commentary\n"
    "- DO NOT return markdown, code fences, or additional text."
)

# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class FigureSignal:
    """A signal emitted by a market-moving figure.

    Fields match the canonical spec (market-figure-intelligence-module.md §8.2).
    AWA scoring is computed by awa_scorer.py, not inline.
    """
    person_name: str
    category: str           # "I" = policymaker, "II" = political, "III" = executive,
                            # "IV" = activist, "V" = fund_manager, "VI" = celebrity
    signal_direction: str   # "directional" | "contrarian" | "confirmatory"
    event_type: str         # "speech" | "trade" | "filing" | "social_post"
    ticker: str | None = None
    direction: str | None = None  # "long" | "short" | "warn"
    awa_score: float = 0.0
    confidence: float = 0.0
    summary: str = ""
    source_url: str = ""
    timestamp: str = ""

    def to_raw(self) -> dict:
        """Export raw content for shadow ecosystem (no AWA scores).

        Per §8.1 isolation compliance: shadows receive person_name + text +
        timestamp only. AWA scores and signal direction are stripped to
        prevent anchoring bias in shadow analysis.
        """
        return {
            "person_name": self.person_name,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "source_url": self.source_url,
        }


# ── Extractor ──────────────────────────────────────────────────────────────────


class FigureSignalExtractor:
    """Detect key person mentions in news and classify signals.

    Uses Flash LLM for topic classification (market-related vs noise).
    Pure Python for text matching and signal direction inference.

    Design constraints (§1.3):
      1. Capability x Willingness x Market Acknowledgment = signal validity
      2. Real-money actions > verbal statements (cost hierarchy L4 > L0)
      3. Categories I-IV = directional; V-VI = confirmatory/contrarian
      4. All signals verified via event study before historical accuracy counts
      5. Congressional trade / SEC filing sources use public data only
    """

    def __init__(self) -> None:
        from marketmind.config.key_persons import KEY_PERSONS as _key_persons

        self.key_persons: list[KeyPerson] = _key_persons  # type: ignore[name-defined]
        self._name_index: dict[str, list[KeyPerson]] = self._build_index()  # type: ignore[name-defined]
        self._awa_scorer = AWAScorer()

    # ── Index construction ─────────────────────────────────────────────────

    def _build_index(self) -> dict[str, list]:
        """Build keyword-to-person lookup for fast matching.

        Indexes both explicit keywords and person names (lowercased).
        A single keyword may map to multiple persons (e.g., "powell" matches
        both Jerome Powell and potential future additions).
        """
        index: dict[str, list] = {}
        for person in self.key_persons:
            # Index by explicit keywords
            for keyword in person.keywords:
                key = keyword.lower()
                if key not in index:
                    index[key] = []
                if person not in index[key]:
                    index[key].append(person)
            # Also index by person name (lowercased, as fallback)
            name_key = person.name.lower()
            if name_key not in index:
                index[name_key] = []
            if person not in index[name_key]:
                index[name_key].append(person)
        return index

    # ── Main extraction entry point ────────────────────────────────────────

    async def extract(self, news_items: list[dict]) -> list[FigureSignal]:
        """Scan news items for key person mentions. Returns FigureSignal list.

        Process (six-layer filter, §9.1):
          L0: Source filtering (handled upstream by scout)
          L1: Keyword matching → candidate persons
          L2: Flash LLM classification → market-relevant?  ← THIS METHOD
          L3: AWA scoring → score threshold (delegated to awa_scorer)
          L4-L6: downstream (event study, historical consistency, text quality)

        Only invokes Flash LLM for news items that match a keyword (lazy LLM).
        """
        signals: list[FigureSignal] = []

        for item in news_items:
            # Normalize item to text + metadata (handles dict and NewsItem)
            text, source_url, timestamp = self._normalize_item(item)
            if not text:
                continue

            text_lower = text.lower()

            # Step 1: Keyword matching (L1 — pure Python, no LLM)
            matched_persons: list[KeyPerson] = []  # type: ignore[name-defined]
            seen: set[str] = set()
            for keyword, persons in self._name_index.items():
                if keyword in text_lower:
                    for p in persons:
                        if p.name not in seen:
                            seen.add(p.name)
                            matched_persons.append(p)

            if not matched_persons:
                continue

            # Step 2: Flash LLM relevance classification (L2)
            # Deduplicate persons before LLM calls
            for person in matched_persons:
                is_relevant = await self._classify_relevance(text, person)
                if not is_relevant:
                    continue

                # Step 3: Infer signal attributes (pure Python)
                event_type = self._infer_event_type(text)
                direction = self._infer_direction(person, text)
                ticker = self._extract_ticker(text)

                # Step 4: Compute AWA score (delegated to awa_scorer)
                awa_result = self._awa_scorer.score(person, event_type, text)
                awa_score = awa_result["final_score"]

                # Confidence: higher when direction is clear
                confidence = 0.75 if direction else 0.50

                # Flash-generated summary (concise)
                summary = self._generate_summary(person, text, event_type)

                signal = FigureSignal(
                    person_name=person.name,
                    category=person.category if hasattr(person, "category") and person.category else "",
                    signal_direction=person.signal_direction,
                    event_type=event_type,
                    ticker=ticker,
                    direction=direction,
                    awa_score=awa_score,
                    confidence=confidence,
                    summary=summary,
                    source_url=source_url,
                    timestamp=timestamp,
                )
                signals.append(signal)

                # Fire-and-forget WebSocket broadcast (follows add_log_entry pattern)
                try:
                    from marketmind.api.websocket import broadcast_person_signal
                    asyncio.create_task(broadcast_person_signal(signal))
                except Exception:
                    pass  # Graceful degradation — signal storage is primary

        return signals

    # ── Flash LLM relevance classification ─────────────────────────────────

    async def _classify_relevance(self, text: str, person: "KeyPerson") -> bool:
        """Flash LLM: is this mention market-relevant?

        Prompt is ~100 tokens — minimal cost. Only called for keyword-matched
        items (lazy LLM pattern: avoid burning tokens on obvious noise).

        Falls back to heuristic (True) on LLM failure to avoid missing signals.
        """
        from marketmind.gateway.async_client import chat_flash

        # Truncate text to keep prompt small
        truncated = text[:600] if len(text) > 600 else text

        user_prompt = (
            f"Person: {person.name}\n"
            f"Text: \"{truncated}\"\n\n"
            f"Is this mention relevant to financial markets?"
        )

        try:
            response = await chat_flash(
                system_prompt=MARKET_RELEVANCE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=128,
            )
            content: str = response.get("content", "")
            # Parse JSON — strip possible markdown code fences
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*\n?", "", content)
                content = re.sub(r"\n?```\s*$", "", content)
            result = json.loads(content)
            return bool(result.get("relevant", False))
        except Exception:
            logger.warning(
                f"Flash classification failed for {person.name}, "
                f"falling back to heuristic (assume relevant)"
            )
            # Fallback: assume relevant if keyword matched (conservative)
            return True

    # ── Direction inference (pure Python, no LLM) ──────────────────────────

    def _infer_direction(self, person: "KeyPerson", text: str) -> str | None:
        """Infer trading direction from text context using keyword heuristics.

        Bullish/bearish keywords are counted. Warning keywords trigger "warn".
        For contrarian figures (Elon Musk, finfluencers), the direction is
        INVERTED — their bullish statements are bearish signals and vice versa.

        Returns:
            "long" | "short" | "warn" | None
        """
        text_lower = text.lower()

        bullish_count = sum(1 for pat in BULLISH_PATTERNS if re.search(pat, text_lower))
        bearish_count = sum(1 for pat in BEARISH_PATTERNS if re.search(pat, text_lower))

        if bullish_count > bearish_count:
            if person.signal_direction == "contrarian":
                return "short"
            return "long"
        elif bearish_count > bullish_count:
            if person.signal_direction == "contrarian":
                return "long"
            return "short"

        # No clear bullish/bearish signal — check for warning language
        warn_count = sum(1 for pat in WARN_PATTERNS if re.search(pat, text_lower))
        if warn_count >= 2:
            return "warn"

        return None

    # ── Event type inference ───────────────────────────────────────────────

    def _infer_event_type(self, text: str) -> str:
        """Infer event type from text context.

        Priority: trade > filing > speech > social_post (descending cost).
        Higher-cost signals are more reliable (§3.3 signal cost hierarchy).
        """
        text_lower = text.lower()

        # L4: Actual trades (highest cost)
        if any(re.search(p, text_lower) for p in TRADE_PATTERNS):
            return "trade"
        # L3: SEC/regulatory filings
        if any(re.search(p, text_lower) for p in FILING_PATTERNS):
            return "filing"
        # L2: Official speeches/remarks
        if any(re.search(p, text_lower) for p in SPEECH_PATTERNS):
            return "speech"
        # L1: Social media posts
        if any(re.search(p, text_lower) for p in SOCIAL_PATTERNS):
            return "social_post"

        # Default: speech (most common for policymakers)
        return "speech"

    # ── Ticker extraction ──────────────────────────────────────────────────

    def _extract_ticker(self, text: str) -> str | None:
        """Extract stock ticker from text.

        Matches: $TICKER format, (TICKER) parenthetical format.
        Returns the first match or None.
        """
        # $TICKER format
        dollar_matches = re.findall(r"\$([A-Z]{1,5})\b", text)
        if dollar_matches:
            return dollar_matches[0]

        # (TICKER) parenthetical — common in news: "Apple (AAPL)"
        paren_matches = re.findall(r"\(([A-Z]{1,5})\)", text)
        # Filter common false positives that happen to be all-caps
        noise = {"THE", "CEO", "ETF", "IPO", "NYSE", "NASDAQ", "SPAC", "AI",
                 "GDP", "CPI", "FOMC", "ECB", "BOJ", "YTD", "USD", "EUR", "JPY"}
        for m in paren_matches:
            if m not in noise:
                return m

        return None

    # ── Summary generation ─────────────────────────────────────────────────

    def _generate_summary(
        self, person: "KeyPerson", text: str, event_type: str
    ) -> str:
        """Generate a concise one-line summary for Gate 2 display."""
        name = person.name
        # Truncate to ~150 chars for readability
        snippet = text[:150].replace("\n", " ").strip()
        if len(text) > 150:
            snippet += "..."
        return f"[{event_type}] {name}: {snippet}"

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_item(item: dict | object) -> tuple[str, str, str]:
        """Normalize a news item (dict or NewsItem object) to (text, url, timestamp)."""
        if isinstance(item, dict):
            text_parts = []
            for field in ("title", "headline", "content", "summary", "description"):
                val = item.get(field, "")
                if val:
                    text_parts.append(str(val))
            text = " ".join(text_parts)
            source_url = str(item.get("url", item.get("source_url", "")))
            timestamp = str(item.get("published_at", item.get("timestamp", "")))
        else:
            # Object with attributes (e.g., NewsItem)
            text_parts = []
            for attr in ("headline", "title", "content", "summary"):
                val = getattr(item, attr, "")
                if val:
                    text_parts.append(str(val))
            text = " ".join(text_parts)
            source_url = str(getattr(item, "url", ""))
            timestamp = str(getattr(item, "published_at", ""))
        return text, source_url, timestamp
