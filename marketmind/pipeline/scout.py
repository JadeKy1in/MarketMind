"""Multi-source news collection with 3-tier degradation strategy."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

from marketmind.config.settings import MarketMindConfig
from marketmind.config.source_authority import Source, SourceTier, SourceStatus, get_working_sources, SOURCES

# ── Z1 content analysis extracted to pipeline/scout_content.py ──────────
from marketmind.pipeline.scout_content import (
    compute_content_hash,
    compute_salience_multiplier,
    compute_priority,
    load_prune_content_hash_cache,
    save_content_hash_cache,
    _CACHE_PATH,
)

# ── Monitoring report extracted to pipeline/scout_report.py ─────────────
from marketmind.pipeline.scout_report import record_z0_metrics, print_scout_report

logger = logging.getLogger("marketmind.pipeline.scout")

# ── Default field values (extracted as named constants) ─────────────────────
DEFAULT_SOURCE_RELIABILITY = 0.5
DEFAULT_SALIENCE_MULTIPLIER = 1.0
DEFAULT_PRIORITY_SCORE = 0.0

# ── Dedup threshold ─────────────────────────────────────────────────────────
TITLE_SIMILARITY_THRESHOLD = 0.80


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
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Z1: content-aware fields for priority rebalance + two-layer dedup
    content_hash: str | None = None
    source_reliability: float = DEFAULT_SOURCE_RELIABILITY
    salience_multiplier: float = DEFAULT_SALIENCE_MULTIPLIER
    priority_score: float = DEFAULT_PRIORITY_SCORE
    # Social media routing: content_type distinguishes news from social for Flash bypass
    content_type: str = "news_article"  # "news_article" | "social_mention" | "sec_filing"

    @classmethod
    def from_entry(cls, entry: dict, source: Source) -> "NewsItem":
        title = entry.get("title", "Untitled").strip()
        url = entry.get("link", "")
        summary_raw = entry.get("summary", entry.get("description", ""))
        summary = _strip_html(summary_raw)[:500]
        published = entry.get("published", entry.get("updated", datetime.now(timezone.utc).isoformat()))
        item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
        try:
            reliability = float(source.reliability)
        except (TypeError, ValueError):
            reliability = DEFAULT_SOURCE_RELIABILITY
        return cls(
            id=item_id,
            title=title,
            url=url,
            source_name=source.name,
            source_tier=int(source.tier),
            published_at=published,
            summary=summary,
            source_reliability=reliability,
        )


def _strip_html(text: str) -> str:
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
            headers = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
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
                    source_reliability=0.90,
                ))
    except Exception as e:
        logger.warning("SEC EDGAR API fetch failed: %s", e)
    return items

# ── Phase G Layer 4: Insider sources → pipeline/insider_sources.py
from marketmind.pipeline.insider_sources import (
    fetch_congress_trades,
    fetch_form4_insider,
    fetch_13f_holdings,
    detect_insider_clusters,
)

# ── Social media sources → pipeline/social_sources.py
from marketmind.pipeline.social_sources import fetch_apewisdom, fetch_bluesky_posts

async def _fetch_api_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from a JSON API source (NewsAPI, GNews, etc.). Injects API key into URL."""
    items: list[NewsItem] = []

    # Bluesky Social: delegate to social_sources module (special parsing)
    if source.name == "Bluesky Social":
        return await fetch_bluesky_posts(source, config)

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
            published = art.get("publishedAt", datetime.now(timezone.utc).isoformat())
            item_id = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]
            try:
                reliability = float(source.reliability)
            except (TypeError, ValueError):
                reliability = DEFAULT_SOURCE_RELIABILITY
            items.append(NewsItem(
                id=item_id, title=title, url=link,
                source_name=source.name, source_tier=int(source.tier),
                published_at=published, summary=desc[:500],
                source_reliability=reliability,
            ))
    return items


async def fetch_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch a single source. Track A (RSS/API) → Track B (HTML) fallback."""
    items: list[NewsItem] = []
    try:
        # Phase G Layer 4: Insider / Smart Money sources (pipeline/insider_sources.py)
        if source.feed_type == "congress_api":
            items = await fetch_congress_trades()
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.feed_type == "sec_form4":
            items = await fetch_form4_insider()
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.feed_type == "sec_13f":
            items = await fetch_13f_holdings()
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.feed_type == "sec_api":
            items = await _fetch_sec_edgar()
            if items:
                source.status = SourceStatus.WORKING
                source.consecutive_failures = 0
            return items
        if source.name == "ApeWisdom":
            items = await fetch_apewisdom()
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
                        "User-Agent": "Mozilla/5.0 (compatible; MarketMind/0.1; Financial Research Bot)",
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
    source.last_checked = datetime.now(timezone.utc).isoformat()
    return items


def _load_manual_data(items: list) -> None:
    """Load user-provided data from data/manual/ (Congress trades, Bluesky posts)."""
    import json as _json, os as _os
    from datetime import datetime as _dt, timezone as _tz
    manual_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data", "manual")
    if not _os.path.isdir(manual_dir):
        return

    # Congress trades: data/manual/congress_trades.json
    congress_path = _os.path.join(manual_dir, "congress_trades.json")
    if _os.path.exists(congress_path):
        try:
            with open(congress_path, encoding="utf-8") as f:
                trades = _json.load(f)
            for t in trades:
                ticker = (t.get("ticker") or "").upper()
                rep = t.get("representative", t.get("name", "Unknown"))
                if not ticker:
                    continue
                items.append(NewsItem(
                    id=hashlib.sha256(f"manual_congress:{rep}:{ticker}:{t.get('transaction_date','')}".encode()).hexdigest()[:16],
                    title=f"[Congress] {rep} ({t.get('type','?').upper()} ${ticker})",
                    url="", source_name="Congress Trades", source_tier=int(SourceTier.BEST_EFFORT),
                    published_at=t.get("transaction_date", _dt.now(_tz.utc).isoformat()),
                    summary=f"{rep} reported {t.get('type','?')} of ${ticker}. Amount: {t.get('amount','unknown')}. Manual input — STOCK Act disclosure.",
                    source_reliability=0.20, content_type="insider_signal",
                ))
            logger.info("Loaded %d Congress trades from manual file", len(trades))
        except Exception as e:
            logger.warning("Failed to load Congress manual file: %s", e)

    # Bluesky posts: data/manual/bluesky_posts.json
    bluesky_path = _os.path.join(manual_dir, "bluesky_posts.json")
    if _os.path.exists(bluesky_path):
        try:
            with open(bluesky_path, encoding="utf-8") as f:
                posts = _json.load(f)
            for p in posts[:10]:
                text = p.get("text", "")[:500]
                if not text:
                    continue
                items.append(NewsItem(
                    id=hashlib.sha256(f"manual_bluesky:{text[:80]}".encode()).hexdigest()[:16],
                    title=text[:100] + ("..." if len(text) > 100 else ""),
                    url="", source_name="Bluesky Social", source_tier=int(SourceTier.BEST_EFFORT),
                    published_at=p.get("timestamp", _dt.now(_tz.utc).isoformat()),
                    summary=text, source_reliability=0.20, content_type="social_mention",
                ))
            logger.info("Loaded %d Bluesky posts from manual file", len(posts[:10]))
        except Exception as e:
            logger.warning("Failed to load Bluesky manual file: %s", e)


@monitor(source="scout", impact=ImpactScope.INFRASTRUCTURE)
async def fetch_all_sources(config: MarketMindConfig, use_cross_run_cache: bool = True) -> list[NewsItem]:
    """Fetch from all working sources, deduplicate, return sorted by priority_score descending.

    Z1: Two-layer dedup (title_similarity + content_hash cross-run), content-aware
    priority scoring (reliability + freshness + tier_bonus) * salience_multiplier.

    Args:
        config: MarketMindConfig instance.
        use_cross_run_cache: If False, skip loading/saving the cross-run content hash
            cache. Cross-run dedup is disabled (deduplicate receives None). Use this
            in tests with VCR cassette replay where the same articles are replayed
            repeatedly and would always match cached hashes from a prior run.
    """
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

    # Z1: Load content hash cache for cross-run dedup (skipped when use_cross_run_cache=False)
    content_hash_cache: dict | None = None
    if use_cross_run_cache:
        try:
            content_hash_cache = load_prune_content_hash_cache(_CACHE_PATH)
        except Exception:
            content_hash_cache = None

    # Z1: Pre-compute content_hash on all items (needed for cache dedup)
    for item in all_items:
        try:
            if item.content_hash is None:
                item.content_hash = compute_content_hash(item.title, item.summary)
        except Exception:
            logger.warning("content_hash computation failed for item", exc_info=True)

    deduped = deduplicate(all_items, content_hash_cache)

    # Z0 instrumentation: record baseline metrics
    record_z0_metrics(sources, source_counts, source_issues, rss_count, api_count, rss_health, len(all_items), len(deduped))

    # Print monitoring report
    print_scout_report(sources, source_counts, source_issues, len(deduped))

    # Manual data files: load user-provided Congress/Bluesky data before priority scoring
    _load_manual_data(deduped)

    # Z1: Compute salience (base) then apply insider cluster boost (multiply, not replace)
    for item in deduped:
        try:
            item.salience_multiplier = compute_salience_multiplier(item.title, item.summary)
        except Exception:
            logger.warning("salience_multiplier computation failed for item", exc_info=True)

    # Phase G Layer 4: Insider cluster detection multiplies salience by 1.5x for cluster items
    detect_insider_clusters(deduped)

    # Z1: Compute priority using boosted salience, sort by priority descending
    now_utc = datetime.now(timezone.utc)
    for item in deduped:
        try:
            item.priority_score = compute_priority(item, now_utc)
        except Exception:
            logger.warning("priority_score computation failed for item", exc_info=True)
        # Update cache with surviving item (only if cross-run cache is active)
        if use_cross_run_cache and content_hash_cache is not None:
            try:
                if item.content_hash:
                    content_hash_cache[item.content_hash] = now_utc.isoformat()
            except Exception:
                logger.warning("content_hash cache update failed", exc_info=True)

    # Sort by priority_score descending (preserved invariant I13: only output sort changes,
    # deduplicate() internal tier-sort is unchanged)
    try:
        deduped.sort(key=lambda x: getattr(x, "priority_score", 0.0), reverse=True)
    except Exception:
        logger.warning("deduplicated items sort failed", exc_info=True)

    # Z1: Persist updated cache (pruned of >72h entries) — only if cross-run cache is active
    if use_cross_run_cache and content_hash_cache is not None:
        try:
            save_content_hash_cache(_CACHE_PATH, content_hash_cache)
        except Exception:
            logger.warning("content_hash cache save failed", exc_info=True)

    return deduped


def deduplicate(items: list[NewsItem], content_hash_cache: dict | None = None) -> list[NewsItem]:
    """Remove duplicates: URL exact match, title similarity > 0.80, content_hash cross-run.

    Layer 1 (same-run): URL dedup + title_similarity (preserved from pre-Z1).
    Layer 2 (cross-run): content_hash cache lookup for 72h re-publication filter.
    Internal sort by source_tier ascending is preserved (Z1 audit I2).
    """
    seen_urls: set[str] = set()
    result: list[NewsItem] = []
    for item in sorted(items, key=lambda x: x.source_tier):
        if item.url and item.url in seen_urls:
            continue
        is_dup = False
        for existing in result:
            if _title_similarity(item.title, existing.title) > TITLE_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        # Z1: Cross-run dedup via content_hash cache
        if not is_dup and content_hash_cache is not None:
            try:
                ch = item.content_hash
                if ch is None:
                    ch = compute_content_hash(item.title, item.summary)
                    item.content_hash = ch
                if ch and ch in content_hash_cache:
                    is_dup = True
            except Exception:
                logger.warning("content_hash dedup check failed", exc_info=True)  # Hash failure → don't dedup (conservative)
        if not is_dup:
            seen_urls.add(item.url)
            result.append(item)
    return result
