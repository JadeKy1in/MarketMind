"""Event Detector — market event scanning and prioritization."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class DetectedEvent:
    event_id: str
    event_type: str          # "cb_shock" | "geopolitical" | "vol_shock" | "personnel"
    description: str
    affected_assets: list[str]
    impact_score: float      # 0-1 normalized impact
    detected_at: str         # ISO 8601
    vix_level: float | None = None
    max_zscore: float | None = None
    news_volume: int | None = None


class EventDetector:
    """Scans news and market data for trigger events, returning detected events
    sorted by impact score."""

    # Domain keyword families for Gate 2 keyword-triggered temp shadows.
    # 3+ mentions of any family during a session triggers temp shadow creation.
    KEYWORD_FAMILIES: dict[str, list[str]] = {
        "semiconductors": ["semiconductor", "chip", "nvidia", "tsmc", "amd",
                           "intel", "foundry", "gpu", "asic", "hbm"],
        "gold": ["gold", "xau", "precious metal", "bullion", "goldman",
                 "central bank gold"],
        "crypto": ["bitcoin", "crypto", "ethereum", "btc", "defi",
                   "stablecoin", "blockchain", "solana", "digital asset"],
        "energy": ["crude oil", "wti", "brent", "natural gas", "opec",
                   "oil price", "energy sector", "refinery"],
        "bonds": ["treasury", "bond", "yield curve", "duration", "fixed income",
                  "sovereign debt", "credit spread", "jgb", "bund"],
        "fx": ["dollar", "yen", "euro", "forex", "currency", "dxy",
               "exchange rate", "carry trade", "cny", "gbp"],
        "macro": ["fed", "ecb", "boj", "inflation", "gdp", "recession",
                  "cpi", "pce", "unemployment", "nonfarm", "pmi"],
        "tech": ["ai", "artificial intelligence", "machine learning", "llm",
                 "datacenter", "cloud", "software", "saas", "automation"],
        "real_estate": ["housing", "mortgage", "reit", "commercial real estate",
                        "property", "home price", "construction"],
        "healthcare": ["biotech", "pharma", "fda", "clinical trial", "drug",
                       "healthcare", "medicare", "patent"],
    }

    def __init__(self):
        self._keyword_counter: dict[str, int] = {}
        self._triggered_domains: set[str] = set()

    def detect_keyword_triggers(self, user_text: str) -> list[str]:
        """Session-level keyword frequency counter for Gate 2.
        When a keyword family crosses threshold (3+ mentions), returns the domain name.
        Each domain triggers at most once per session."""
        text_lower = user_text.lower()
        newly_triggered: list[str] = []

        for domain, keywords in self.KEYWORD_FAMILIES.items():
            if domain in self._triggered_domains:
                continue
            hits = sum(1 for kw in keywords if kw in text_lower)
            if hits > 0:
                self._keyword_counter[domain] = self._keyword_counter.get(domain, 0) + hits
                if self._keyword_counter[domain] >= 3:
                    self._triggered_domains.add(domain)
                    newly_triggered.append(domain)

        return newly_triggered

    def reset_keyword_state(self) -> None:
        """Reset keyword counters for a new session."""
        self._keyword_counter.clear()
        self._triggered_domains.clear()

    async def scan_events(self, news_items: list[dict]) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        events.extend(self.detect_cb_shock(news_items))
        events.extend(self.detect_geopolitical(news_items))
        events.extend(self.detect_vol_shock(None))
        events.extend(self.detect_personnel_change(news_items))
        events.sort(key=lambda e: e.impact_score, reverse=True)
        return events

    def detect_cb_shock(self, news_items: list[dict]) -> list[DetectedEvent]:
        cb_keywords = [
            r'(?:Fed|Federal Reserve|ECB|BOJ|BOE|PBOC|RBA|RBNZ|BOC|SNB)\s',
            r'(?:rate|hike|cut|ease|tighten|basis point|bp)\s',
            r'(?:surprise|unexpected|vs\s+\d+(?:\.\d+)?%\s+expected)',
        ]
        return self._detect_by_keywords(
            news_items, "cb_shock", cb_keywords, base_impact=0.6
        )

    def detect_geopolitical(self, news_items: list[dict]) -> list[DetectedEvent]:
        geo_keywords = [
            r'(?:war|conflict|sanctions|tensions?|missile|invasion|military|coup)',
            r'(?:geopolitical|crisis|escalation|attack|embargo)',
            r'(?:VIX\s+(?:surge|spike|jump|soar)s?)',
        ]
        return self._detect_by_keywords(
            news_items, "geopolitical", geo_keywords, base_impact=0.5
        )

    def detect_vol_shock(self, market_data: dict[str, float] | None = None) -> list[DetectedEvent]:
        if market_data is None:
            return []
        events: list[DetectedEvent] = []
        for ticker, zscore in market_data.items():
            abs_z = abs(zscore)
            if abs_z >= 5.0:
                event_id = hashlib.sha256(
                    f"vol_shock:{ticker}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(abs_z / 10.0, 1.0)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type="vol_shock",
                    description=f"{ticker} volatility shock: {abs_z:.1f} sigma move",
                    affected_assets=[ticker],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    max_zscore=abs_z,
                ))
        return events

    def detect_personnel_change(self, news_items: list[dict]) -> list[DetectedEvent]:
        personnel_keywords = [
            r'(?:Treasury Secretary|Fed Chair|SEC Chair|CFTC|OCC|FDIC)\b',
            r'(?:resign|fired|replaced|appointed|nominated|confirmed)\b',
        ]
        return self._detect_by_keywords(
            news_items, "personnel", personnel_keywords, base_impact=0.4
        )

    def _detect_by_keywords(self, news_items: list, event_type: str,
                             keywords: list[str], base_impact: float) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        seen_headlines: set[str] = set()
        for item in news_items:
            headline = (
                str(getattr(item, "headline", "")) or
                str(getattr(item, "title", "")) or
                str(item.get("headline", "")) if hasattr(item, "get") else ""
            )
            if not headline or headline in seen_headlines:
                continue
            matched = sum(1 for kw in keywords if re.search(kw, headline, re.IGNORECASE))
            if matched >= 2:
                seen_headlines.add(headline)
                event_id = hashlib.sha256(
                    f"{event_type}:{headline}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(base_impact + matched * 0.1, 1.0)
                tickers = re.findall(r'\b[A-Z]{1,5}\b', headline)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type=event_type,
                    description=headline[:200],
                    affected_assets=tickers[:5],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    news_volume=1,
                ))
        return events

    def prioritize_events(self, events: list[DetectedEvent],
                           max_shadows: int = 5) -> list[DetectedEvent]:
        sorted_events = sorted(events, key=lambda e: e.impact_score, reverse=True)
        return sorted_events[:max_shadows]
