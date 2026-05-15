"""Multi-source news collection with 3-tier degradation strategy."""
from __future__ import annotations
import hashlib
import logging

logger = logging.getLogger("marketmind.pipeline.scout")
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import feedparser
import httpx

from marketmind.config.settings import MarketMindConfig
from marketmind.config.source_authority import Source, SourceTier, SourceStatus, get_working_sources, SOURCES


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


async def _fetch_sec_edgar() -> list[NewsItem]:
    """Fetch recent 8-K filings from SEC EDGAR (free, no key, requires valid User-Agent)."""
    items = []
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # SEC requires: OrganizationName email@domain.com
            headers = {"User-Agent": "MarketMind InvestmentResearch marketmind@github.io"}
            # Use the EDGAR submission feed (Atom XML) — more reliable than the REST API
            resp = await client.get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                headers=headers,
                params={"action": "getcurrent", "type": "8-K", "output": "atom",
                        "count": "20", "start": "0"},
            )
            if resp.status_code != 200:
                logger.warning("SEC EDGAR returned %d: %s", resp.status_code, resp.text[:200])
                return items
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:20]:
                title = entry.get("title", "8-K Filing").strip()
                url = entry.get("link", "")
                summary_raw = entry.get("summary", entry.get("description", ""))
                summary = _strip_html(summary_raw)[:500]
                published = entry.get("published", entry.get("updated", ""))
                item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
                items.append(NewsItem(
                    id=item_id,
                    title=title,
                    url=url,
                    source_name="SEC EDGAR 8-K",
                    source_tier=1,
                    published_at=published,
                    summary=summary,
                ))
    except Exception as e:
        logger.warning("SEC EDGAR API fetch failed: %s", e)
    return items


async def fetch_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch a single source. Track A (RSS/API) → Track B (HTML) fallback."""
    items: list[NewsItem] = []
    try:
        if source.feed_type == "sec_api":
            items = await _fetch_sec_edgar()
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.feed_type in ("rss", "api") and source.url:
            client_kwargs = {"timeout": 30.0, "follow_redirects": True}
            if config.proxy_url:
                client_kwargs["proxy"] = config.proxy_url
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(
                    source.url,
                    headers={
                        "User-Agent": "MarketMind/0.1 (Financial Research Bot; +https://github.com/marketmind)",
                        "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    }
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:20]:
                    try:
                        items.append(NewsItem.from_entry(entry, source))
                    except Exception as e:
                        logger.warning("Scout source fetch degraded: %s — %s", source.name, e)
                        continue
            source.status = SourceStatus.WORKING
            source.consecutive_failures = 0
        elif source.feed_type == "html":
            source.status = SourceStatus.DEGRADED  # HTML scraping not yet implemented
    except Exception as e:
        logger.warning("Scout source fetch failed for '%s': %s", source.name, e)
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
    # Always include UNTESTED sources alongside working/degraded ones
    untested = [s for s in SOURCES if s.status == SourceStatus.UNTESTED]
    sources = list({s.name: s for s in (sources + untested)}.values())  # deduplicate by name
    all_items: list[NewsItem] = []
    fetch_errors: list[str] = []
    for source in sources:
        items = await fetch_source(source, config)
        all_items.extend(items)
        if source.status in (SourceStatus.DEGRADED, SourceStatus.DEAD):
            fetch_errors.append(f"{source.name}: {source.status.value}")
    if fetch_errors:
        logger.warning("Source fetch issues (%d/%d sources): %s",
                       len(fetch_errors), len(sources), "; ".join(fetch_errors[:5]))
        if len(fetch_errors) > 5:
            logger.warning("  (+ %d more)", len(fetch_errors) - 5)
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
