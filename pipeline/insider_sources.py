"""Phase G Layer 4: Insider / Smart Money data sources.

Congress trades: SOURCE DEAD as of 2026-05 (House Stock Watcher S3 403,
Senate Stock Watcher 503/TLS, CapitolTrades BFF 503). Returns empty list
with one-time warning. SEC Form 4 and 13F via EDGAR Atom feeds remain
active. Insider cluster detection for priority boosting.

All sources are free, use no API keys, and return NewsItem objects
with content_type="insider_signal" for Flash bypass routing.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

import feedparser
import httpx

logger = logging.getLogger("marketmind.pipeline.insider_sources")


# One-time warning flag for dead sources (module-level, persists for process lifetime)
_congress_trades_dead_warned: bool = False


async def fetch_congress_trades() -> list[Any]:
    """Fetch Congressional stock trades — SOURCE DEAD as of 2026-05.

    House Stock Watcher S3 (all regions 403), Senate Stock Watcher API (503/TLS),
    and CapitolTrades BFF (503 CloudFront) are all confirmed DEAD. No free,
    programmatic congressional trade endpoint is currently available.

    Returns empty list with a one-time warning log.
    """
    global _congress_trades_dead_warned
    if not _congress_trades_dead_warned:
        _congress_trades_dead_warned = True
        logger.warning(
            "Congress Trades source is DEAD (House Stock Watcher S3: 403, "
            "Senate Stock Watcher API: 503/TLS, CapitolTrades BFF: 503 CloudFront). "
            "No free congressional trade endpoint available. Returning empty list."
        )
    return []


async def fetch_form4_insider() -> list[Any]:
    """Fetch recent SEC Form 4 filings (insider trades) from SEC EDGAR Atom feed.

    Form 4 must be filed within 2 business days of a transaction by corporate insiders
    (officers, directors, 10%+ owners). Free, no API key — same EDGAR pattern as 8-K.
    """
    from marketmind.config.source_authority import SourceTier
    from marketmind.pipeline.scout import NewsItem, _strip_html

    items: list[NewsItem] = []
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
            resp = await client.get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                headers=headers,
                params={"action": "getcurrent", "type": "4", "output": "atom",
                        "count": "20", "start": "0"},
            )
            if resp.status_code != 200:
                logger.warning("SEC Form 4 returned %d: %s", resp.status_code, resp.text[:200])
                return items
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:20]:
                title = entry.get("title", "Form 4 Filing").strip()
                url = entry.get("link", "")
                summary_raw = entry.get("summary", entry.get("description", ""))
                summary = _strip_html(summary_raw)[:500]
                published = entry.get("published", entry.get("updated", ""))
                item_id = hashlib.sha256(f"form4:{title}{url}".encode()).hexdigest()[:16]
                items.append(NewsItem(
                    id=item_id,
                    title=f"[Form 4] {title}",
                    url=url,
                    source_name="SEC Form 4",
                    source_tier=int(SourceTier.BEST_EFFORT),
                    published_at=published,
                    summary=summary,
                    source_reliability=0.20,
                    content_type="insider_signal",
                ))
    except Exception as e:
        logger.warning("SEC Form 4 fetch failed: %s", e)
    return items


async def fetch_13f_holdings() -> list[Any]:
    """Fetch recent SEC 13F-HR filings (institutional holdings) from SEC EDGAR Atom feed.

    13F is filed quarterly by institutional investors managing >$100M. Filing deadline
    is 45 days after quarter-end. Data is STALE (45-135 day lag) but reveals STRUCTURAL
    positioning shifts that news cannot capture. Free, no API key.
    """
    from marketmind.config.source_authority import SourceTier
    from marketmind.pipeline.scout import NewsItem, _strip_html

    items: list[NewsItem] = []
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
            resp = await client.get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                headers=headers,
                params={"action": "getcurrent", "type": "13F-HR", "output": "atom",
                        "count": "20", "start": "0"},
            )
            if resp.status_code != 200:
                logger.warning("SEC 13F returned %d: %s", resp.status_code, resp.text[:200])
                return items
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:20]:
                title = entry.get("title", "13F Filing").strip()
                url = entry.get("link", "")
                summary_raw = entry.get("summary", entry.get("description", ""))
                summary = _strip_html(summary_raw)[:500]
                published = entry.get("published", entry.get("updated", ""))
                item_id = hashlib.sha256(f"13f:{title}{url}".encode()).hexdigest()[:16]
                items.append(NewsItem(
                    id=item_id,
                    title=f"[13F] {title}",
                    url=url,
                    source_name="SEC 13F",
                    source_tier=int(SourceTier.BEST_EFFORT),
                    published_at=published,
                    summary=summary,
                    source_reliability=0.15,
                    content_type="insider_signal",
                ))
    except Exception as e:
        logger.warning("SEC 13F fetch failed: %s", e)
    return items


def detect_insider_clusters(items: list[Any]) -> list[Any]:
    """Detect insider trading clusters: 3+ unique members, same ticker, 14-day window.

    Cluster items get a 1.5x priority boost via salience_multiplier.
    Modifies items in-place and returns the list for chaining.
    """
    from collections import defaultdict as _dd
    try:
        ticker_groups: dict[str, list] = _dd(list)
        for item in items:
            if getattr(item, "content_type", "") != "insider_signal":
                continue
            title = getattr(item, "title", "")
            import re as _re
            ticker_match = _re.search(r'\$([A-Z]{1,5})', title)
            if not ticker_match:
                continue
            ticker = ticker_match.group(1)
            ticker_groups[ticker].append(item)

        for ticker, group in ticker_groups.items():
            if len(group) < 3:
                continue
            dates = []
            for item in group:
                pub = getattr(item, "published_at", "")
                try:
                    d = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
                    dates.append(d)
                except (ValueError, TypeError):
                    continue
            if len(dates) < 3:
                continue
            window = (max(dates) - min(dates)).days
            if window > 14:
                continue
            member_keys: set[str] = set()
            for item in group:
                title = getattr(item, "title", "")
                member_keys.add(f"{getattr(item, 'source_name', '')}:{title[:30]}")
            if len(member_keys) < 3:
                continue
            for item in group:
                try:
                    current = float(getattr(item, "salience_multiplier", 1.0))
                    item.salience_multiplier = current * 1.5  # type: ignore[attr-defined]
                except (TypeError, ValueError):
                    pass
            logger.info(
                "Insider cluster: %s — %d members, %d-day window (boosted 1.5x)",
                ticker, len(member_keys), window,
            )
        return items
    except Exception as e:
        logger.debug("Insider cluster detection skipped: %s", e)
        return items
