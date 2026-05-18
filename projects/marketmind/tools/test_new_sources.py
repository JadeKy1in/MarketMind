"""Pre-integration source validator — test all proposed new sources before adding to SOURCES.

Usage: python tools/test_new_sources.py

Tests every proposed source from the China/EU/EM gap research.
Only sources that return real data are marked as candidates for integration.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
import feedparser

# ── All proposed new sources from gap research ──────────────────────────────

PROPOSED_SOURCES: list[dict] = [
    # === 🇨🇳 China ===
    {"name": "Caixin Global (RSSHub)", "url": "https://rsshub.app/caixinglobal/latest", "type": "rss", "region": "CN"},
    {"name": "Caixin Finance (RSSHub)", "url": "https://rsshub.app/caixin/finance/bank", "type": "rss", "region": "CN"},
    {"name": "China Daily Bizchina", "url": "http://www.chinadaily.com.cn/rss/bizchina_rss.xml", "type": "rss", "region": "CN"},
    {"name": "SCMP RSS", "url": "https://www.scmp.com/rss", "type": "rss", "region": "CN"},
    {"name": "PBOC RSS (RSSHub)", "url": "https://rsshub.app/pbc/goutongjiaoliu", "type": "rss", "region": "CN"},
    {"name": "ECNS Business", "url": "http://www.ecns.cn/rss/rss_business.xml", "type": "rss", "region": "CN"},
    {"name": "Yicai Global (RSSHub)", "url": "https://rsshub.app/yicai/latest", "type": "rss", "region": "CN"},
    {"name": "China Economic Net", "url": "http://en.ce.cn/main/News/rss.shtml", "type": "rss", "region": "CN"},
    {"name": "Xinhua Finance (RSSHub)", "url": "https://rsshub.app/xinhua/finance", "type": "rss", "region": "CN"},
    {"name": "CGTN Business", "url": "https://www.cgtn.com/subscribe/rss/section/business.xml", "type": "rss", "region": "CN"},
    {"name": "Caixin Original RSS", "url": "https://gateway.caixin.com/api/data/global/feedlyRss.xml", "type": "rss", "region": "CN"},

    # === 🇪🇺 EU ===
    {"name": "ECB Press Releases", "url": "https://www.ecb.europa.eu/rss/press.html", "type": "rss", "region": "EU"},
    {"name": "EC Press Corner", "url": "https://ec.europa.eu/commission/presscorner/api/rss", "type": "rss", "region": "EU"},
    {"name": "DG Competition Antitrust", "url": "https://competition-policy.ec.europa.eu/antitrust/rss_en", "type": "rss", "region": "EU"},
    {"name": "Euronews Business", "url": "https://www.euronews.com/business/feed", "type": "rss", "region": "EU"},
    {"name": "Financial Times RSS", "url": "https://www.ft.com/world?format=rss", "type": "rss", "region": "EU"},
    {"name": "EUobserver Business", "url": "https://euobserver.com/rss/business", "type": "rss", "region": "EU"},
    {"name": "Eurostat RSS", "url": "https://ec.europa.eu/eurostat/news/news-releases/rss", "type": "rss", "region": "EU"},

    # === 🌏 Emerging Markets ===
    {"name": "Brazil BCB RSS", "url": "https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/", "type": "rss", "region": "EM"},
    {"name": "India RBI RSS", "url": "https://www.rbi.org.in/Scripts/Rss.aspx?Id=200", "type": "rss", "region": "EM"},
    {"name": "Turkey TCMB RSS", "url": "https://tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Press+Releases", "type": "rss", "region": "EM"},
    {"name": "South Africa SARB RSS", "url": "https://www.resbank.co.za/en/home/quick-links/rss-feeds", "type": "rss", "region": "EM"},
    {"name": "IMF News RSS", "url": "https://www.imf.org/en/News/RSS", "type": "rss", "region": "EM"},
    {"name": "World Bank News RSS", "url": "https://www.worldbank.org/en/news/rss", "type": "rss", "region": "EM"},
    {"name": "Trading Economics RSS", "url": "https://tradingeconomics.com/rss", "type": "rss", "region": "EM"},
    {"name": "OPEC Monthly Report", "url": "https://www.opec.org/opec_web/en/", "type": "web", "region": "EM"},
]


async def test_source(s: dict) -> dict:
    """Test a single source. Return result dict."""
    result = {"name": s["name"], "region": s["region"], "status": "untested", "articles": 0, "error": ""}
    try:
        if s["type"] == "rss":
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(
                    s["url"],
                    headers={"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)"}
                )
                if resp.status_code >= 400:
                    result["status"] = "FAILED"
                    result["error"] = f"HTTP {resp.status_code}"
                    return result
                feed = feedparser.parse(resp.text)
                entries = feed.entries
                result["articles"] = len(entries)
                if len(entries) == 0:
                    if resp.status_code == 200 and len(resp.text) > 100:
                        result["status"] = "EMPTY"
                        result["error"] = "Feed parsed but 0 entries (not RSS?)"
                    else:
                        result["status"] = "EMPTY"
                        result["error"] = f"Empty response ({len(resp.text)} bytes)"
                else:
                    result["status"] = "WORKING"
        elif s["type"] == "web":
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(
                    s["url"],
                    headers={"User-Agent": "Mozilla/5.0 (compatible; MarketMind/0.1)"}
                )
                if resp.status_code < 400:
                    result["status"] = "REACHABLE"
                    result["articles"] = 1
                else:
                    result["status"] = "FAILED"
                    result["error"] = f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        result["status"] = "FAILED"
        result["error"] = "Connection refused / DNS failed"
    except httpx.TimeoutException:
        result["status"] = "FAILED"
        result["error"] = "Timeout (20s)"
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)[:150]
    return result


async def main():
    print(f"Testing {len(PROPOSED_SOURCES)} proposed sources...\n")

    tasks = [test_source(s) for s in PROPOSED_SOURCES]
    results = await asyncio.gather(*tasks)

    working = [r for r in results if r["status"] == "WORKING"]
    reachable = [r for r in results if r["status"] == "REACHABLE"]
    empty = [r for r in results if r["status"] == "EMPTY"]
    failed = [r for r in results if r["status"] == "FAILED"]

    print(f"\n{'='*70}")
    print(f"  Results: {len(working)} working | {len(reachable)} reachable | "
          f"{len(empty)} empty | {len(failed)} failed")
    print(f"{'='*70}\n")

    if working:
        print("[✅] INTEGRATION CANDIDATES (return real articles):")
        for r in working:
            print(f"  [{r['region']}] {r['name']:40s} {r['articles']:3d} articles")
        print()

    if reachable:
        print("[🌐] REACHABLE (web page, needs scraper):")
        for r in reachable:
            print(f"  [{r['region']}] {r['name']}")
        print()

    if empty:
        print("[⚠️] EMPTY (no articles returned):")
        for r in empty:
            print(f"  [{r['region']}] {r['name']:40s} {r['error']}")
        print()

    if failed:
        print("[❌] FAILED (cannot connect):")
        for r in failed:
            print(f"  [{r['region']}] {r['name']:40s} {r['error']}")

    # Summary by region
    print(f"\n{'='*70}")
    print("  By Region:")
    for region in ["CN", "EU", "EM"]:
        region_results = [r for r in results if r["region"] == region]
        w = sum(1 for r in region_results if r["status"] in ("WORKING", "REACHABLE"))
        total_articles = sum(r["articles"] for r in region_results if r["status"] == "WORKING")
        print(f"  {region}: {w}/{len(region_results)} working, {total_articles} articles")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
