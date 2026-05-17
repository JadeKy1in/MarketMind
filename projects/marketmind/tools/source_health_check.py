"""Test all information sources — report which return real data and which fail."""
from __future__ import annotations
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
import feedparser

from marketmind.config.source_authority import SOURCES, Source, SourceTier, SourceStatus

TIER_NAMES = {1: "PRIMARY", 2: "RELIABLE", 3: "FRAGILE", 4: "BEST_EFFORT"}

HEADERS = {
    "User-Agent": "MarketMind/0.1 (contact@marketmind.dev)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}
SEC_HEADERS = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}


async def test_rss(source: Source) -> tuple[int, str]:
    """Test RSS source. Returns (article_count, error_msg)."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(source.url, headers=HEADERS)
            if resp.status_code != 200:
                return 0, f"HTTP {resp.status_code}"
            feed = feedparser.parse(resp.text)
            if feed.bozo and not feed.entries:
                return 0, f"Parse error: {feed.bozo_exception}"
            return len(feed.entries), ""
    except httpx.TimeoutException:
        return 0, "Timeout"
    except Exception as e:
        msg = str(e)[:100]
        return 0, msg


async def test_api(source: Source) -> tuple[int, str]:
    """Test API source (NewsAPI, GNews, Bluesky, etc.)."""
    from marketmind.config.settings import MarketMindConfig
    config = MarketMindConfig()

    # Check API key availability
    if source.name == "NewsAPI" and not config.newsapi_key:
        return 0, "No NEWSAPI_KEY configured"
    if source.name == "GNews" and not config.gnews_key:
        return 0, "No GNEWS_KEY configured"
    if source.name in ("Bluesky", "Bluesky Social"):
        # Try OAuth with env credentials (same as production code)
        import os as _os
        username = _os.environ.get("BLUESKY_USERNAME", "")
        app_password = _os.environ.get("BLUESKY_APP_PASSWORD", "")
        if not username or not app_password:
            return 0, "Requires OAuth (BLUESKY_USERNAME + BLUESKY_APP_PASSWORD)"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Create session
                auth_resp = await client.post(
                    "https://bsky.social/xrpc/com.atproto.server.createSession",
                    json={"identifier": username, "password": app_password},
                    headers={"Content-Type": "application/json"},
                )
                if auth_resp.status_code != 200:
                    return 0, f"Auth failed: HTTP {auth_resp.status_code}"
                token = auth_resp.json().get("accessJwt", "")
                # Search posts
                resp = await client.get(
                    "https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                    params={"q": "finance OR stocks OR market", "limit": 5},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    return 0, f"HTTP {resp.status_code}"
                data = resp.json()
                posts = data.get("posts", [])
                return len(posts), ""
        except Exception as e:
            return 0, str(e)[:100]

    # For NewsAPI/GNews — skip actual API call (would consume quota), just check key exists
    if source.name in ("NewsAPI", "GNews"):
        return -1, "SKIPPED (API call would consume quota)"

    return 0, f"Unknown API source: {source.name}"


async def test_congress_api(source: Source) -> tuple[int, str]:
    """Test Congress trades S3 JSON endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                source.url,
                headers={"User-Agent": "MarketMind/0.1"},
            )
            if resp.status_code != 200:
                return 0, f"HTTP {resp.status_code}"
            data = resp.json()
            if not isinstance(data, list):
                return 0, "Unexpected response format"
            # Filter last 30 days
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            recent = 0
            for tx in data:
                try:
                    d = tx.get("transaction_date", "")
                    if d:
                        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
                        if dt >= cutoff:
                            recent += 1
                except Exception:
                    pass
            return recent, f"({len(data)} total in database)"
    except Exception as e:
        return 0, str(e)[:100]


async def test_sec_edgar(source: Source) -> tuple[int, str]:
    """Test SEC EDGAR Atom feed (Form 4, 13F, 8-K)."""
    feed_type_map = {
        "sec_api": ("8-K", "SEC EDGAR 8-K"),
        "sec_form4": ("4", "SEC Form 4"),
        "sec_13f": ("13F-HR", "SEC 13F"),
    }
    ftype = feed_type_map.get(source.feed_type, ("8-K", "Unknown"))
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = SEC_HEADERS
            resp = await client.get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                headers=headers,
                params={"action": "getcurrent", "type": ftype[0], "output": "atom",
                        "count": "20", "start": "0"},
            )
            if resp.status_code != 200:
                return 0, f"HTTP {resp.status_code}"
            feed = feedparser.parse(resp.text)
            return len(feed.entries), ""
    except Exception as e:
        return 0, str(e)[:100]


async def test_apewisdom() -> tuple[int, str]:
    """Test ApeWisdom trending API."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://apewisdom.io/api/v1/filter/trending",
                headers={"User-Agent": "MarketMind/0.1"},
            )
            if resp.status_code != 200:
                return 0, f"HTTP {resp.status_code}"
            data = resp.json()
            results = data.get("results", [])
            return len(results), ""
    except Exception as e:
        return 0, str(e)[:100]


async def main():
    print("=" * 72)
    print("  MarketMind Source Health Check")
    print(f"  {len(SOURCES)} sources total")
    print("=" * 72)
    print()

    results = []
    total_articles = 0
    working = 0
    empty = 0
    failed = 0
    skipped = 0

    for i, source in enumerate(SOURCES, 1):
        tier = TIER_NAMES.get(int(source.tier), "?")
        print(f"[{i:2d}/{len(SOURCES)}] {source.name} ({tier}, {source.feed_type}) ... ", end="", flush=True)

        count = 0
        error = ""

        if source.status == SourceStatus.DEAD:
            count = 0
            error = "Pre-marked DEAD"
        elif source.name == "CFTC COT":
            count = -1
            error = "SKIPPED (handled by macro_data.py)"
        elif source.feed_type == "bls_api":
            count = -1
            error = "SKIPPED (BLS API — implementation TBD)"
        elif source.feed_type == "rss":
            count, error = await test_rss(source)
        elif source.feed_type in ("sec_api", "sec_form4", "sec_13f"):
            count, error = await test_sec_edgar(source)
        elif source.feed_type == "congress_api":
            count, error = await test_congress_api(source)
        elif source.name == "ApeWisdom":
            count, error = await test_apewisdom()
        elif source.feed_type in ("api", "bluesky"):
            count, error = await test_api(source)
        else:
            count = 0
            error = f"Unknown feed_type: {source.feed_type}"

        if count > 0:
            print(f"OK ({count} articles)")
            working += 1
            total_articles += count
        elif count == -1:
            print("SKIPPED")
            skipped += 1
        elif error and "Pre-marked" in error:
            print("DEAD (pre-marked)")
            failed += 1
        elif count == 0 and not error:
            print("EMPTY (0 articles)")
            empty += 1
        else:
            print(f"FAIL: {error[:80]}")
            failed += 1

        results.append((source.name, tier, count, error))

        # Rate limit: SEC EDGAR needs 2s between requests; others 0.5s
        delay = 2.0 if source.feed_type in ("sec_api", "sec_form4", "sec_13f") else 0.5
        await asyncio.sleep(delay)

    print()
    print("=" * 72)
    print(f"  Results: {working} working | {empty} empty | {failed} failed | {skipped} skipped")
    print(f"  Total articles: {total_articles}")
    print("=" * 72)
    print()

    # Working sources
    print("[OK] WORKING SOURCES:")
    for name, tier, count, _ in results:
        if count > 0:
            print(f"  [{tier:12s}] {name:<35s} {count:4d} articles")

    print()
    print("[!!] FAILED:")
    for name, tier, count, error in results:
        if count == 0 and error and "Pre-marked" in error:
            print(f"  [{tier:12s}] {name:<35s} DEAD (pre-marked)")
        elif count == -1:
            print(f"  [{tier:12s}] {name:<35s} SKIPPED (quota check)")
        elif count == 0 and not error:
            print(f"  [{tier:12s}] {name:<35s} 0 articles (URL broken?)")
        elif count == 0 and error:
            print(f"  [{tier:12s}] {name:<35s} {error[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
