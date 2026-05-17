"""Multi-source news collection with 3-tier degradation strategy."""
from __future__ import annotations
import hashlib
import logging

logger = logging.getLogger("marketmind.pipeline.scout")
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from marketmind.config.settings import MarketMindConfig
from marketmind.config.source_authority import Source, SourceTier, SourceStatus, get_working_sources


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
    source_reliability: float = 0.5
    content_type: str = "news"
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_entry(cls, entry: dict, source: Source) -> "NewsItem":
        title = _truncate(entry.get("title", "Untitled").strip(), MAX_HEADLINE_LENGTH)
        url = entry.get("link", "")
        summary_raw = entry.get("summary", entry.get("description", ""))
        summary = _truncate(_strip_html(summary_raw), MAX_SUMMARY_LENGTH)
        published = entry.get("published", entry.get("updated", datetime.now(timezone.utc).isoformat()))
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


MAX_HEADLINE_LENGTH = 300
MAX_SUMMARY_LENGTH = 1000


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters, preserving whole characters."""
    if not text:
        return text
    return text[:max_len]


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


# Session-level cache for NewsAPI/GNews (1 call per session)
_newsapi_cache: list[NewsItem] | None = None
_newsapi_cache_time: float = 0.0
_gnews_cache: list[NewsItem] | None = None
_gnews_cache_time: float = 0.0

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines?country=us&category=business&apiKey="
GNEWS_URL = "https://gnews.io/api/v4/top-headlines?category=business&lang=en&country=us&max=20&apikey="


async def _fetch_newsapi(config: MarketMindConfig) -> list[NewsItem]:
    """Fetch top business headlines from NewsAPI (JSON API, not RSS feed)."""
    global _newsapi_cache, _newsapi_cache_time
    # Rate limit: 1 call per session (24h cache)
    if _newsapi_cache is not None and (time.time() - _newsapi_cache_time) < 86400:
        return _newsapi_cache

    api_key = config.newsapi_key
    if not api_key:
        logger.warning("NEWSAPI_KEY not configured, skipping NewsAPI fetch")
        return []

    items: list[NewsItem] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{NEWSAPI_URL}{api_key}",
                headers={"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                logger.warning("NewsAPI returned non-ok status: %s", data.get("status", "unknown"))
                _newsapi_cache = items
                _newsapi_cache_time = time.time()
                return items

            for article in data.get("articles", [])[:20]:
                title = _truncate((article.get("title") or "Untitled").strip(), MAX_HEADLINE_LENGTH)
                url = article.get("url") or ""
                if not title and not url:
                    continue
                summary_raw = article.get("description") or ""
                summary = _truncate(_strip_html(summary_raw), MAX_SUMMARY_LENGTH)
                published = article.get("publishedAt") or datetime.now(timezone.utc).isoformat()
                item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
                items.append(NewsItem(
                    id=item_id,
                    title=title,
                    url=url,
                    source_name="NewsAPI",
                    source_tier=2,
                    published_at=published,
                    summary=summary,
                    source_reliability=0.90,
                    content_type="news",
                ))
    except Exception as e:
        logger.warning("NewsAPI fetch failed: %s", e)

    _newsapi_cache = items
    _newsapi_cache_time = time.time()
    return items


async def _fetch_gnews(config: MarketMindConfig) -> list[NewsItem]:
    """Fetch top business headlines from GNews API (JSON API, not RSS feed)."""
    global _gnews_cache, _gnews_cache_time
    # Rate limit: 1 call per session (24h cache)
    if _gnews_cache is not None and (time.time() - _gnews_cache_time) < 86400:
        return _gnews_cache

    api_key = config.gnews_key
    if not api_key:
        logger.warning("GNEWS_API_KEY not configured, skipping GNews fetch")
        return []

    items: list[NewsItem] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GNEWS_URL}{api_key}",
                headers={"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
            )
            resp.raise_for_status()
            data = resp.json()
            for article in data.get("articles", [])[:20]:
                title = _truncate((article.get("title") or "Untitled").strip(), MAX_HEADLINE_LENGTH)
                url = article.get("url") or ""
                if not title and not url:
                    continue
                summary_raw = article.get("description") or ""
                summary = _truncate(_strip_html(summary_raw), MAX_SUMMARY_LENGTH)
                published = article.get("publishedAt") or datetime.now(timezone.utc).isoformat()
                item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
                items.append(NewsItem(
                    id=item_id,
                    title=title,
                    url=url,
                    source_name="GNews",
                    source_tier=2,
                    published_at=published,
                    summary=summary,
                    source_reliability=0.85,
                    content_type="news",
                ))
    except Exception as e:
        logger.warning("GNews fetch failed: %s", e)

    _gnews_cache = items
    _gnews_cache_time = time.time()
    return items


async def fetch_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch a single source. Track A (RSS/API) → Track B (HTML) fallback."""
    items: list[NewsItem] = []
    try:
        if source.name == "NewsAPI":
            items = await _fetch_newsapi(config)
            source.status = SourceStatus.WORKING
        elif source.name == "GNews":
            items = await _fetch_gnews(config)
            source.status = SourceStatus.WORKING
        elif source.feed_type == "rss" and source.url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    source.url,
                    headers={"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
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
        elif source.feed_type == "bls_api":
            from marketmind.pipeline.bls_fetcher import fetch_bls_indicators
            indicators = await fetch_bls_indicators()
            if indicators:
                for ind in indicators:
                    title = f"BLS {ind['indicator']}: {ind['value']}% ({ind['date']})"
                    item_id = hashlib.sha256(title.encode()).hexdigest()[:16]
                    items.append(NewsItem(
                        id=item_id,
                        title=title,
                        url=source.url or "",
                        source_name=source.name,
                        source_tier=int(source.tier),
                        published_at=datetime.now(timezone.utc).isoformat(),
                        summary=f"{ind['indicator']} at {ind['value']}{ind['unit']} as of {ind['date']}",
                        source_reliability=source.reliability,
                        content_type="macro_indicator",
                    ))
            source.status = SourceStatus.WORKING
            source.consecutive_failures = 0
        elif source.feed_type == "bluesky":
            from marketmind.pipeline.social_sources import fetch_bluesky_posts
            items = await fetch_bluesky_posts(source, config)
            source.status = SourceStatus.WORKING
            source.consecutive_failures = 0
    except Exception as e:
        logger.warning("Scout source fetch failed for '%s': %s", source.name, e)
        source.consecutive_failures += 1
        if source.consecutive_failures >= 3:
            source.status = SourceStatus.DEAD
        else:
            source.status = SourceStatus.DEGRADED
    source.last_checked = datetime.now(timezone.utc).isoformat()
    return items


async def fetch_all_sources(config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from all working sources, deduplicate, return sorted by tier."""
    sources = get_working_sources()
    if not sources:
        sources = [s for s in __import__("marketmind.config.source_authority", fromlist=["SOURCES"]).SOURCES
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
