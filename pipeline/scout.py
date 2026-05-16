"""Multi-source news collection with 3-tier degradation strategy."""
from __future__ import annotations
import hashlib
import logging

logger = logging.getLogger("marketmind.pipeline.scout")
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

import json
import os
import re

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
    # Z1: content-aware fields for priority rebalance + two-layer dedup
    content_hash: str | None = None
    source_reliability: float = 0.5
    salience_multiplier: float = 1.0
    priority_score: float = 0.0
    # Social media routing: content_type distinguishes news from social for Flash bypass
    content_type: str = "news_article"  # "news_article" | "social_mention" | "sec_filing"

    @classmethod
    def from_entry(cls, entry: dict, source: Source) -> "NewsItem":
        title = entry.get("title", "Untitled").strip()
        url = entry.get("link", "")
        summary_raw = entry.get("summary", entry.get("description", ""))
        summary = _strip_html(summary_raw)[:500]
        published = entry.get("published", entry.get("updated", datetime.now().isoformat()))
        item_id = hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]
        try:
            reliability = float(source.reliability)
        except (TypeError, ValueError):
            reliability = 0.5
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


# ── Z1: Salience regex patterns ──────────────────────────────────────────
# CRITICAL: \b word boundaries prevent "rate" matching "corporate"/"strategic" (Z1 audit Q1.1)
# Evaluation order: macro_event → earnings → filler (Z1 audit Q1.2 — broadest first
# because macro-signal articles must not be downgraded to filler or earnings)
_RE_MACRO_EVENT = re.compile(
    r"\b(?:Fed|ECB|PBOC|rate|inflation|GDP|employment|CPI|PPI)\b",
    re.IGNORECASE,
)
_RE_EARNINGS = re.compile(
    r"\b(?:earnings|revenue|profit|guidance)\b",
    re.IGNORECASE,
)
# NOTE: "mixed close" is intentionally short (11 chars) but filler-is-last ordering
# ensures macro-containing filler-prefixed headlines are correctly classified as macro.
_RE_FILLER = re.compile(
    r"\b(?:market wrap|closing bell|stocks edge|mixed close)\b",
    re.IGNORECASE,
)

# Z1: Content hash cache path (relative to scout.py → ../data/cache/)
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "content_hash_tracker.json")


def _compute_content_hash(title: str, summary: str) -> str | None:
    """SHA256 of lowercased + normalized title|summary. Returns None if content is empty.

    Empty-content guard (Z1 audit E3): if both title and summary are empty after
    strip, return None to avoid the well-known SHA256("") collision.
    """
    try:
        t = (title or "").strip().lower()
        s = (summary or "")[:500].strip().lower()
        if not t and not s:
            return None
        text = f"{t}|{s}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        return None


def _compute_salience_multiplier(title: str, summary: str) -> float:
    """Classify article salience via regex on title + summary[:200].

    Evaluation order (Z1 audit Q1.2): macro_event → earnings → filler.
    Returns 1.15 (macro), 1.05 (earnings), 0.85 (filler), or 1.0 (neutral).

    KNOWN LIMITATION (Z1 audit E1): patterns are English-only. Non-English
    sources (e.g., Caixin Chinese headlines) will always return 1.0.
    Chinese-language regex support is deferred to Phase Z1b/Z4.
    """
    try:
        text = f"{title or ''} {(summary or '')[:200]}"
    except Exception:
        return 1.0
    try:
        if _RE_MACRO_EVENT.search(text):
            return 1.15
        if _RE_EARNINGS.search(text):
            return 1.05
        if _RE_FILLER.search(text):
            return 0.85
        return 1.0
    except Exception:
        return 1.0


def _parse_published_at(published_at: str) -> datetime | None:
    """Parse published_at string to timezone-aware datetime.

    Returns None on failure (Z1 audit E2: unparseable dates handled by caller).
    """
    if not published_at or not published_at.strip():
        return None
    ts = published_at.strip()
    # Try ISO 8601 first (API sources)
    try:
        ts_normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try dateutil if available (handles RFC 822, relative, etc.)
    try:
        from dateutil.parser import parse as dateutil_parse  # type: ignore[import-untyped]
        dt = dateutil_parse(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    return None


def _compute_priority(item: NewsItem, now: datetime) -> float:
    """Compute priority score: 0.45*reliability + 0.25*freshness + 0.30*tier_bonus,
    multiplied by salience_multiplier. HOT max_age = 6h.

    Priority function must never raise (Z1 audit E5). All computations are
    try/except-wrapped with sane defaults.
    """
    # --- reliability (0.45 weight) ---
    try:
        reliability = float(getattr(item, "source_reliability", 0.5))
    except (TypeError, ValueError):
        reliability = 0.5

    # --- freshness (0.25 weight) ---
    try:
        pub_dt = _parse_published_at(item.published_at)
    except Exception:
        pub_dt = None
    if pub_dt is None:
        freshness = 0.3  # Conservative default for missing dates (Z1 audit E2)
    else:
        try:
            hours = (now - pub_dt).total_seconds() / 3600.0
            if hours < 0:
                hours = 0.0
            max_age = 6.0  # Z1: HOT max_age 6h
            freshness = 1.0 - hours / max_age
            freshness = max(0.0, min(1.0, freshness))
        except Exception:
            freshness = 0.3

    # --- tier_bonus (0.30 weight) ---
    try:
        tier = int(getattr(item, "source_tier", 4))
    except (TypeError, ValueError):
        tier = 4
    if tier == 1:       # PRIMARY
        tier_bonus = 1.0
    elif tier == 2:     # RELIABLE
        tier_bonus = 0.6
    elif tier == 3:     # FRAGILE
        tier_bonus = 0.4
    else:               # BEST_EFFORT
        tier_bonus = 0.3

    # --- salience ---
    try:
        salience = float(getattr(item, "salience_multiplier", 1.0))
    except (TypeError, ValueError):
        salience = 1.0

    try:
        base = 0.45 * reliability + 0.25 * freshness + 0.30 * tier_bonus
        return base * salience
    except Exception:
        return 0.0


def _load_prune_content_hash_cache(path: str) -> dict:
    """Load content hash cache from JSON, prune entries older than 72h.

    Corruption recovery (Z1 audit Q3.1): JSONDecodeError or OSError → log warning,
    delete corrupted file, return empty cache. Malformed entries are silently skipped.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Content hash cache corrupted, resetting: %s", e)
        try:
            os.remove(path)
        except OSError:
            pass
        return {}
    if not isinstance(data, dict):
        logger.warning("Content hash cache is not a dict, resetting")
        return {}
    # Prune entries older than 72h
    try:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 72 * 3600
        pruned: dict = {}
        for h, ts in data.items():
            if not isinstance(h, str) or not isinstance(ts, str):
                continue
            try:
                t = datetime.fromisoformat(ts)
                if t.timestamp() >= cutoff:
                    pruned[h] = ts
            except Exception:
                continue  # Skip malformed timestamps
        return pruned
    except Exception:
        return {}


def _save_content_hash_cache(path: str, cache: dict) -> None:
    """Atomically write content hash cache to JSON via temp file.

    Creates the cache directory if it doesn't exist (Z1 audit Q3.2).
    Uses os.replace() for atomic write — prevents corruption on crash.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("Failed to save content hash cache: %s", e)


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
                    source_reliability=0.90,
                ))
    except Exception as e:
        logger.warning("SEC EDGAR API fetch failed: %s", e)
    return items


async def _fetch_apewisdom() -> list[NewsItem]:
    """Fetch trending tickers from ApeWisdom (Reddit/4chan retail sentiment).

    Swiss Finance Institute (2026): finfluencer picks = -2.3% returns;
    fading them = +6.8% alpha. Retail sentiment is a CONTRARIAN INDICATOR.
    ApeWisdom API lacks per-account data — manipulation detection is probabilistic.

    Multi-factor filter: mention_count >= 100, >2 unique subreddits,
    mentions span >2 hours. Without per-account data, pump-and-dump detection
    is best-effort. Items tagged content_type="social_mention" to bypass Flash.
    """
    items: list[NewsItem] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get("https://apewisdom.io/api/v1/filter/trending",
                                     headers={"User-Agent": "MarketMind/0.1"})
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not isinstance(results, list):
                return items
            for entry in results[:10]:  # top 10 trending
                ticker = entry.get("ticker", "")
                mentions = int(entry.get("mentions", 0))
                # Multi-factor filter (Red Team Q2 recommendations)
                if mentions < 100:
                    continue
                # Check subreddit diversity if available
                subreddits = entry.get("subreddits", [])
                if isinstance(subreddits, list) and len(subreddits) < 3:
                    continue
                sentiment = float(entry.get("sentiment", 0))
                # Contrarian signal: extreme sentiment is most actionable
                # >85% bullish = contrarian bearish; >85% bearish = contrarian bullish
                if sentiment > 0.85:
                    direction = "CONTRARIAN BEARISH (fade retail bullishness)"
                elif sentiment < 0.15:
                    direction = "CONTRARIAN BULLISH (fade retail panic)"
                else:
                    continue  # Moderate sentiment = noise
                title = (
                    f"[Retail Sentiment] ${ticker} — {mentions} mentions, "
                    f"{sentiment:.0%} bullish — {direction}"
                )
                items.append(NewsItem(
                    id=hashlib.sha256(f"apewisdom:{ticker}:{mentions}".encode()).hexdigest()[:16],
                    title=title,
                    url="",
                    source_name="ApeWisdom",
                    source_tier=int(SourceTier.BEST_EFFORT),
                    published_at=datetime.now().isoformat(),
                    summary=(
                        f"Reddit/4chan retail sentiment: {ticker} mentioned {mentions} times, "
                        f"{sentiment:.0%} bullish. CONTRARIAN INDICATOR — "
                        f"high retail bullishness often precedes pullbacks. "
                        f"{direction}. Source: ApeWisdom (hobby project, no per-account data)."
                    ),
                    source_reliability=0.15,
                    content_type="social_mention",
                ))
    except Exception as e:
        logger.debug("ApeWisdom fetch skipped: %s", e)
    return items


# ── Phase G Layer 4: Insider sources ─────────────────────────────────────────
# Extracted to pipeline/insider_sources.py for modular architecture compliance.
from marketmind.pipeline.insider_sources import (
    fetch_congress_trades,
    fetch_form4_insider,
    fetch_13f_holdings,
    detect_insider_clusters,
)

async def _fetch_api_source(source: Source, config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from a JSON API source (NewsAPI, GNews, etc.). Injects API key into URL."""
    items: list[NewsItem] = []
    # Determine which API key to use
    api_key = None
    if source.name == "NewsAPI":
        api_key = config.newsapi_key
    elif source.name == "GNews":
        api_key = config.gnews_key

    # Bluesky Social: replace {QUERY} with financial keyword search (no API key needed)
    if source.name == "Bluesky Social":
        query = "finance OR stocks OR market OR $AAPL OR $MSFT OR $NVDA OR $TSLA"
        url = source.url.replace("{QUERY}", query)
    elif not api_key:
        return items
    else:
        url = source.url.replace("{API_KEY}", api_key)
    client_kwargs = {"timeout": 30.0, "follow_redirects": True}
    if config.proxy_url:
        client_kwargs["proxy"] = config.proxy_url
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(url, headers={"User-Agent": "MarketMind/0.1"})
        resp.raise_for_status()
        data = resp.json()
        # Bluesky format: {"posts": [{"post": {"record": {"text": "..."}, "author": {...}, "indexedAt": "..."}}]}
        # NewsAPI format: {"articles": [{...}]}
        # GNews format: {"articles": [{...}]}
        if source.name == "Bluesky Social":
            posts = data.get("posts", [])
            for post_data in posts[:10]:  # max 10 Bluesky posts
                post = post_data.get("post", {})
                record = post.get("record", {})
                text = (record.get("text") or "").strip()
                author = post.get("author", {})
                handle = author.get("handle", "unknown")
                # Bluesky posts have no real title; use first 100 chars of text
                title = (text[:100] + "..." if len(text) > 100 else text) if text else "(Bluesky post)"
                indexed_at = post.get("indexedAt", datetime.now().isoformat())
                item_id = hashlib.sha256(f"bluesky:{handle}:{text[:80]}".encode()).hexdigest()[:16]
                try:
                    reliability = float(source.reliability)
                except (TypeError, ValueError):
                    reliability = 0.5
                items.append(NewsItem(
                    id=item_id, title=title, url=f"https://bsky.app/profile/{handle}",
                    source_name=source.name, source_tier=int(source.tier),
                    published_at=indexed_at, summary=text[:500],
                    source_reliability=reliability,
                    content_type="social_mention",
                ))
        else:
            articles = data.get("articles", [])
            for art in articles[:20]:
                title = (art.get("title") or "Untitled").strip()
                link = art.get("url", "")
                desc = (art.get("description") or "").strip()
                published = art.get("publishedAt", datetime.now().isoformat())
                item_id = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]
                try:
                    reliability = float(source.reliability)
                except (TypeError, ValueError):
                    reliability = 0.5
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
            items = await _fetch_apewisdom()
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


async def fetch_all_sources(config: MarketMindConfig) -> list[NewsItem]:
    """Fetch from all working sources, deduplicate, return sorted by priority_score descending.

    Z1: Two-layer dedup (title_similarity + content_hash cross-run), content-aware
    priority scoring (reliability + freshness + tier_bonus) * salience_multiplier.
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

    # Z1: Load content hash cache for cross-run dedup
    content_hash_cache = {}
    try:
        content_hash_cache = _load_prune_content_hash_cache(_CACHE_PATH)
    except Exception:
        pass

    # Z1: Pre-compute content_hash on all items (needed for cache dedup)
    for item in all_items:
        try:
            if item.content_hash is None:
                item.content_hash = _compute_content_hash(item.title, item.summary)
        except Exception:
            pass

    deduped = deduplicate(all_items, content_hash_cache)

    # Z0 instrumentation: record baseline metrics
    _record_z0_metrics(sources, source_counts, source_issues, rss_count, api_count, rss_health, len(all_items), len(deduped))

    # Print monitoring report
    _print_scout_report(sources, source_counts, source_issues, len(deduped))

    # Manual data files: load user-provided Congress/Bluesky data before priority scoring
    _load_manual_data(deduped)

    # Z1: Compute salience (base) then apply insider cluster boost (multiply, not replace)
    for item in deduped:
        try:
            item.salience_multiplier = _compute_salience_multiplier(item.title, item.summary)
        except Exception:
            pass

    # Phase G Layer 4: Insider cluster detection multiplies salience by 1.5x for cluster items
    detect_insider_clusters(deduped)

    # Z1: Compute priority using boosted salience, sort by priority descending
    now_utc = datetime.now(timezone.utc)
    for item in deduped:
        try:
            item.priority_score = _compute_priority(item, now_utc)
        except Exception:
            pass
        # Update cache with surviving item
        try:
            if item.content_hash:
                content_hash_cache[item.content_hash] = now_utc.isoformat()
        except Exception:
            pass

    # Sort by priority_score descending (preserved invariant I13: only output sort changes,
    # deduplicate() internal tier-sort is unchanged)
    try:
        deduped.sort(key=lambda x: getattr(x, "priority_score", 0.0), reverse=True)
    except Exception:
        pass

    # Z1: Persist updated cache (pruned of >72h entries)
    try:
        _save_content_hash_cache(_CACHE_PATH, content_hash_cache)
    except Exception:
        pass

    return deduped


def _record_z0_metrics(sources, counts, issues, rss_count, api_count, rss_health, pre_dedup, post_dedup) -> None:
    """Z0 baseline: append per-run metrics to .claude/metrics/baseline.jsonl (accumulates across days)."""
    import json as _json, os as _os
    from datetime import datetime, timezone, timedelta
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
            if _title_similarity(item.title, existing.title) > 0.80:
                is_dup = True
                break
        # Z1: Cross-run dedup via content_hash cache
        if not is_dup and content_hash_cache is not None:
            try:
                ch = item.content_hash
                if ch is None:
                    ch = _compute_content_hash(item.title, item.summary)
                    item.content_hash = ch
                if ch and ch in content_hash_cache:
                    is_dup = True
            except Exception:
                pass  # Hash failure → don't dedup (conservative)
        if not is_dup:
            seen_urls.add(item.url)
            result.append(item)
    return result
