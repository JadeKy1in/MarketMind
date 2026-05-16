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
            headers = {"User-Agent": "MarketMind/0.1 (contact via GitHub)"}
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


async def _fetch_api_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from a JSON API source (NewsAPI, GNews, etc.). Injects API key into URL."""
    items: list[NewsItem] = []
    # Determine which API key to use
    api_key = None
    if source.name == "NewsAPI":
        api_key = config.newsapi_key
    elif source.name == "GNews":
        api_key = config.gnews_key
    if not api_key:
        return items

    url = source.url.replace("{API_KEY}", api_key)
    client_kwargs = {"timeout": 30.0, "follow_redirects": True}
    if config.proxy_url:
        client_kwargs["proxy"] = config.proxy_url
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(url, headers={"User-Agent": "MarketMind/0.1"})
        resp.raise_for_status()
        data = resp.json()
        # NewsAPI format: {"articles": [{...}]}
        # GNews format: {"articles": [{...}]}
        articles = data.get("articles", [])
        for art in articles[:20]:
            title = (art.get("title") or "Untitled").strip()
            link = art.get("url", "")
            desc = (art.get("description") or "").strip()
            published = art.get("publishedAt", datetime.now().isoformat())
            item_id = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]
            items.append(NewsItem(
                id=item_id, title=title, url=link,
                source_name=source.name, source_tier=int(source.tier),
                published_at=published, summary=desc[:500],
            ))
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
        if source.feed_type == "api" and source.url:
            items = await _fetch_api_source(source, config)
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.feed_type == "rss" and source.url:
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
                # Tiered article cap: PRIMARY=20, RELIABLE=10, FRAGILE/BEST_EFFORT=5
                max_per = 20 if source.tier == SourceTier.PRIMARY else (10 if source.tier == SourceTier.RELIABLE else 5)
                for entry in feed.entries[:max_per]:
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
    untested = [s for s in SOURCES if s.status == SourceStatus.UNTESTED]
    sources = list({s.name: s for s in (sources + untested)}.values())
    all_items: list[NewsItem] = []
    source_counts: dict[str, int] = {}
    source_issues: list[str] = []

    for source in sources:
        before = len(all_items)
        items = await fetch_source(source, config)
        all_items.extend(items)
        source_counts[source.name] = len(all_items) - before
        if source.status in (SourceStatus.DEGRADED, SourceStatus.DEAD):
            source_issues.append(f"{source.name}: {source.status.value}")
        elif source_counts[source.name] == 0 and source.status == SourceStatus.WORKING:
            source_issues.append(f"{source.name}: 0 articles (URL may be broken)")

    # Z0 instrumentation: count API vs RSS articles before dedup
    rss_count = sum(c for name, c in source_counts.items() if name not in ("NewsAPI", "GNews"))
    api_count = sum(c for name, c in source_counts.items() if name in ("NewsAPI", "GNews"))
    rss_health = sum(1 for s in sources if s.status == SourceStatus.WORKING) / max(len(sources), 1)

    deduped = deduplicate(all_items)

    # Z0 instrumentation: record baseline metrics
    _record_z0_metrics(sources, source_counts, source_issues, rss_count, api_count, rss_health, len(all_items), len(deduped))

    # Print monitoring report
    _print_scout_report(sources, source_counts, source_issues, len(deduped))

    return deduped


def _record_z0_metrics(sources, counts, issues, rss_count, api_count, rss_health, pre_dedup, post_dedup) -> None:
    """Z0 baseline: append per-run metrics to .claude/metrics/baseline.jsonl (accumulates across days)."""
    import json as _json, os as _os
    from datetime import datetime, timezone
    try:
        metrics_root = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".claude", "metrics")
        _os.makedirs(metrics_root, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_count": len(sources),
            "rss_article_count": rss_count,
            "api_article_count": api_count,
            "rss_health_score": round(rss_health, 3),
            "pre_dedup_total": pre_dedup,
            "post_dedup_total": post_dedup,
            "issues": issues[:10],
        }
        fpath = _os.path.join(metrics_root, "baseline.jsonl")
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _print_scout_report(sources: list, counts: dict[str, int], issues: list[str], total: int) -> None:
    """Print daily source monitoring report after news collection."""
    from marketmind.config.source_authority import SourceTier, SourceStatus
    tier_names = {SourceTier.PRIMARY: '核心', SourceTier.RELIABLE: '可靠',
                  SourceTier.FRAGILE: '脆弱', SourceTier.BEST_EFFORT: '尽力'}

    working = sum(1 for s in sources if s.status == SourceStatus.WORKING and counts.get(s.name, 0) > 0)
    empty = sum(1 for s in sources if counts.get(s.name, 0) == 0)
    degraded = sum(1 for s in sources if s.status == SourceStatus.DEGRADED)

    print(f"\n{'='*60}")
    print(f"  每日新闻源监测报告")
    print(f"  总文章: {total} | 活跃源: {working} | 空源: {empty} | 降级: {degraded}")
    print(f"  {'='*60}")

    for s in sources:
        c = counts.get(s.name, 0)
        tier = tier_names.get(s.tier, '?')
        if s.status == SourceStatus.DEAD:
            flag = '[DEAD]'
        elif s.status == SourceStatus.DEGRADED:
            flag = '[DEGRADED]'
        elif c == 0:
            flag = '[EMPTY]'
        else:
            flag = ''
        print(f"  [{tier}] {s.name}: {c}篇 {flag}".strip())

    if issues:
        print(f"\n  [警告] 以下源需要关注:")
        for issue in issues[:10]:
            print(f"    - {issue}")
        if len(issues) > 10:
            print(f"    - ... 还有 {len(issues) - 10} 个问题")

    print(f"  {'='*60}\n")


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicates by URL exact match and title similarity > 0.85."""
    seen_urls: set[str] = set()
    result: list[NewsItem] = []
    for item in sorted(items, key=lambda x: x.source_tier):
        if item.url and item.url in seen_urls:
            continue
        is_dup = False
        for existing in result:
            if _title_similarity(item.title, existing.title) > 0.80:
                is_dup = True
                break
        if not is_dup:
            seen_urls.add(item.url)
            result.append(item)
    return result
