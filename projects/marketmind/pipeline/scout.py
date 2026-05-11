"""Multi-source news collection with 3-tier degradation strategy."""
from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import feedparser
import httpx

from projects.marketmind.config.settings import MarketMindConfig
from projects.marketmind.config.source_authority import Source, SourceTier, SourceStatus, get_working_sources


@dataclass
class NewsItem:
    id: str
    title: str
    url: str
    source_name: str
    source_tier: int
    published_at: str
    summary: str
    raw_text: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_entry(cls, entry: dict, source: Source) -> "NewsItem":
        title = entry.get("title", "Untitled").strip()
        url = entry.get("link", "")
        summary_raw = entry.get("summary", entry.get("description", ""))
        summary = _strip_html(summary_raw)[:500]
        published = entry.get("published", entry.get("updated", datetime.now().isoformat()))
        item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
        return cls(
            id=item_id,
            title=title,
            url=url,
            source_name=source.name,
            source_tier=int(source.tier),
            published_at=published,
            summary=summary,
        )


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _title_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity for deduplication."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / min(len(words_a), len(words_b))


async def fetch_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch a single source. Track A (RSS/API) → Track B (HTML) fallback."""
    items: list[NewsItem] = []
    try:
        if source.feed_type in ("rss", "api") and source.url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    source.url,
                    headers={"User-Agent": "MarketMind/0.1 (Financial Research Bot; +https://github.com/marketmind)"}
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:20]:
                    try:
                        items.append(NewsItem.from_entry(entry, source))
                    except Exception:
                        continue
            source.status = SourceStatus.WORKING
            source.consecutive_failures = 0
        elif source.feed_type == "html":
            source.status = SourceStatus.DEGRADED  # HTML scraping not yet implemented
    except Exception:
        source.consecutive_failures += 1
        if source.consecutive_failures >= 3:
            source.status = SourceStatus.DEAD
        else:
            source.status = SourceStatus.DEGRADED
    source.last_checked = datetime.now().isoformat()
    return items


async def fetch_all_sources(config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from all working sources, deduplicate, return sorted by tier."""
    sources = get_working_sources()
    if not sources:
        sources = [s for s in __import__("projects.marketmind.config.source_authority", fromlist=["SOURCES"]).SOURCES
                   if s.status == SourceStatus.UNTESTED]
    all_items: list[NewsItem] = []
    for source in sources:
        items = await fetch_source(source, config)
        all_items.extend(items)
    return deduplicate(all_items)


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicates by URL exact match and title similarity > 0.85."""
    seen_urls: set[str] = set()
    result: list[NewsItem] = []
    for item in sorted(items, key=lambda x: x.source_tier):
        if item.url and item.url in seen_urls:
            continue
        is_dup = False
        for existing in result:
            if _title_similarity(item.title, existing.title) > 0.85:
                is_dup = True
                break
        if not is_dup:
            seen_urls.add(item.url)
            result.append(item)
    return result
