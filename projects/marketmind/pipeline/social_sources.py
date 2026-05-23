"""Social media fetching: Bluesky (active) + ApeWisdom (discontinued).

ApeWisdom API shut down 2026-05 — returns HTML instead of JSON. Reddit WSB RSS
provides retail sentiment coverage. Bluesky via AT Protocol requires
BLUESKY_USERNAME + BLUESKY_APP_PASSWORD in environment.

Extracted from pipeline/scout.py for modular architecture compliance
(scout.py hard ceiling: 500 lines).
"""
from __future__ import annotations
import hashlib
import logging

logger = logging.getLogger("marketmind.pipeline.social_sources")

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from marketmind.config.source_authority import Source
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import NewsItem


# One-time warning flag for dead sources (module-level, persists for process lifetime)
_apewisdom_dead_warned: bool = False


async def fetch_apewisdom() -> list:
    """Fetch trending tickers from ApeWisdom — API DISCONTINUED.

    The ApeWisdom API (apewisdom.io/api/v1/filter/trending) now returns HTML
    instead of JSON — the API has been shut down. Reddit WSB RSS (configured in
    source_authority.py) provides retail sentiment coverage via Reddit's own
    free, no-auth RSS feed.

    Swiss Finance Institute (2026): finfluencer picks = -2.3% returns;
    fading them = +6.8% alpha. Retail sentiment is a CONTRARIAN INDICATOR.

    Returns empty list with a one-time warning log.
    """
    global _apewisdom_dead_warned
    if not _apewisdom_dead_warned:
        _apewisdom_dead_warned = True
        logger.warning(
            "ApeWisdom API has been discontinued (now returns HTML instead of JSON). "
            "Reddit WSB RSS provides retail sentiment coverage. Returning empty list."
        )
    return []


# Bluesky session cache (module-level, lives for process lifetime)
_bluesky_session: dict | None = None

async def _get_bluesky_token() -> str | None:
    """Obtain a Bluesky access token via createSession. Cached for process lifetime."""
    global _bluesky_session
    import os as _os
    if _bluesky_session is not None:
        return _bluesky_session.get("accessJwt")
    username = _os.environ.get("BLUESKY_USERNAME", "")
    app_password = _os.environ.get("BLUESKY_APP_PASSWORD", "")
    if not username or not app_password:
        logger.warning("Bluesky credentials not set (BLUESKY_USERNAME + BLUESKY_APP_PASSWORD)")
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": username, "password": app_password},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            _bluesky_session = resp.json()
            logger.info("Bluesky session created for @%s", username)
            return _bluesky_session.get("accessJwt")
    except Exception as e:
        logger.warning("Bluesky authentication failed: %s", e)
        return None


async def fetch_bluesky_posts(source, config) -> list:
    """Fetch Bluesky posts via authenticated AT Protocol search.

    Requires BLUESKY_USERNAME + BLUESKY_APP_PASSWORD in environment.
    Uses app.bsky.feed.searchPosts with Bearer token from createSession.

    Args:
        source: Source dataclass with .url containing {QUERY} placeholder.
        config: MarketMindConfig for proxy settings.

    Returns:
        list of NewsItem objects with content_type="social_mention".
    """
    # Lazy import to avoid circular dependency with scout.py
    from marketmind.pipeline.scout import NewsItem

    items: list[NewsItem] = []
    token = await _get_bluesky_token()
    if not token:
        return items

    query = "finance OR stocks OR market OR $AAPL OR $MSFT OR $NVDA OR $TSLA"
    client_kwargs = {"timeout": 30.0, "follow_redirects": True}
    if config.proxy_url:
        client_kwargs["proxy"] = config.proxy_url
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                "https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                params={"q": query, "limit": 10},
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "Mozilla/5.0 (compatible; MarketMind/0.1)",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            posts = data.get("posts", [])
            for post_data in posts[:10]:
                post = post_data
                record = post.get("record", {})
                text = (record.get("text") or "").strip()
                author = post.get("author", {})
                handle = author.get("handle", "unknown")
                title = (text[:100] + "..." if len(text) > 100 else text) if text else "(Bluesky post)"
                indexed_at = post.get("indexedAt", datetime.now(timezone.utc).isoformat())
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
    except Exception as e:
        logger.debug("Bluesky fetch skipped: %s", e)
    return items
