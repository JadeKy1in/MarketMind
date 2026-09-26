"""Test ALL sources for FULL content availability — not just headlines.

Reports: article count, title availability, summary/description length,
and whether each source provides enough text for Flash preprocessor analysis.
"""
from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx, feedparser

# ── ALL sources to test (currently in source_authority + newly proposed) ────

ALL_SOURCES = [
    # === Existing sources (already in source_authority.py) ===
    {"name": "FRED (Research Blog)", "url": "https://news.research.stlouisfed.org/feed/", "type": "rss", "region": "US"},
    {"name": "SEC EDGAR", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom&count=20", "type": "rss", "region": "US"},
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "type": "rss", "region": "US"},
    {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories", "type": "rss", "region": "US"},
    {"name": "Investing.com", "url": "https://www.investing.com/rss/news.rss", "type": "rss", "region": "US"},
    {"name": "xcancel (FT)", "url": "https://xcancel.com/FinancialTimes/rss", "type": "rss", "region": "US"},
    # === Newly integrated (Round 1) ===
    {"name": "China Daily Bizchina", "url": "http://www.chinadaily.com.cn/rss/bizchina_rss.xml", "type": "rss", "region": "CN"},
    {"name": "CGTN Business", "url": "https://www.cgtn.com/subscribe/rss/section/business.xml", "type": "rss", "region": "CN"},
    {"name": "ECB Press Releases", "url": "https://www.ecb.europa.eu/rss/press.html", "type": "rss", "region": "EU"},
    {"name": "EC Press Corner", "url": "https://ec.europa.eu/commission/presscorner/api/rss", "type": "rss", "region": "EU"},
    {"name": "Financial Times", "url": "https://www.ft.com/world?format=rss", "type": "rss", "region": "EU"},
    {"name": "Turkey TCMB", "url": "https://tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Press+Releases", "type": "rss", "region": "EM"},
    # === Fixed sources (Round 2) — Direct URLs ===
    {"name": "Xinhua English", "url": "http://www.xinhuanet.com/english/rss/worldrss.xml", "type": "rss", "region": "CN"},
    {"name": "SCMP Business", "url": "https://www.scmp.com/rss/4/feed", "type": "rss", "region": "CN"},
    {"name": "EUobserver", "url": "https://euobserver.com/feed/", "type": "rss", "region": "EU"},
    {"name": "Brazil BCB Copom", "url": "https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/copomstatements", "type": "rss", "region": "EM"},
    # === Fixed sources (Round 2) — Google News proxies ===
    {"name": "Caixin (via Google News)", "url": "https://news.google.com/rss/search?q=Caixin+Global+China+economy+financial+news&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "CN"},
    {"name": "PBOC (via Google News)", "url": "https://news.google.com/rss/search?q=PBOC+People+Bank+China+monetary+policy+interest+rate&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "CN"},
    {"name": "China Economy (via Google News)", "url": "https://news.google.com/rss/search?q=China+economic+data+GDP+CPI+PMI+trade&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "CN"},
    {"name": "Euronews (via Google News)", "url": "https://news.google.com/rss/search?q=Euronews+EU+business+economy+eurozone&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EU"},
    {"name": "Eurostat (via Google News)", "url": "https://news.google.com/rss/search?q=Eurostat+EU+eurozone+GDP+inflation+CPI+economic+data&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EU"},
    {"name": "India RBI (via Google News)", "url": "https://news.google.com/rss/search?q=Reserve+Bank+India+RBI+repo+rate+monetary+policy+MPC&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EM"},
    {"name": "S.Africa SARB (via Google News)", "url": "https://news.google.com/rss/search?q=South+Africa+Reserve+Bank+SARB+monetary+policy+repo+rate&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EM"},
    {"name": "World Bank (via Google News)", "url": "https://news.google.com/rss/search?q=World+Bank+development+emerging+markets+economy&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EM"},
    {"name": "IMF (via Google News)", "url": "https://news.google.com/rss/search?q=IMF+International+Monetary+Fund+global+economy+WEO+World+Economic+Outlook&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EM"},
    {"name": "OPEC Oil (via Google News)", "url": "https://news.google.com/rss/search?q=OPEC+oil+production+crude+Saudi+monthly+report&hl=en-US&gl=US&ceid=US:en", "type": "rss", "region": "EM"},
    # === API sources (tested separately) ===
    {"name": "NewsAPI", "url": None, "type": "api", "region": "US"},
    {"name": "GNews", "url": None, "type": "api", "region": "US"},
    {"name": "Bluesky", "url": None, "type": "bluesky", "region": "US"},
    {"name": "BLS API", "url": None, "type": "bls_api", "region": "US"},
]


async def test_source(s):
    """Test a source and return content completeness stats."""
    result = {"name": s["name"], "region": s["region"], "type": s["type"],
              "status": "untested", "articles": 0, "with_title": 0,
              "with_summary": 0, "with_link": 0, "avg_summary_len": 0,
              "max_summary_len": 0, "error": "", "sample_title": "", "sample_summary": ""}

    if s["type"] != "rss" or not s.get("url"):
        result["status"] = "SKIPPED"
        result["error"] = f"Non-RSS source ({s['type']})"
        return result

    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
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
                result["status"] = "EMPTY"
                result["error"] = f"0 entries ({len(resp.text)} bytes)"
                return result

            # Analyze content completeness
            summary_lengths = []
            for e in entries:
                title = (e.get("title") or "").strip()
                summary = (e.get("summary") or e.get("description") or "").strip()
                link = (e.get("link") or "").strip()

                if title:
                    result["with_title"] += 1
                if summary:
                    result["with_summary"] += 1
                    # Strip HTML tags for length measurement
                    import re
                    clean = re.sub(r"<[^>]+>", "", summary).strip()
                    summary_lengths.append(len(clean))
                if link:
                    result["with_link"] += 1

            if summary_lengths:
                result["avg_summary_len"] = sum(summary_lengths) // len(summary_lengths)
                result["max_summary_len"] = max(summary_lengths)

            # Sample first article
            first = entries[0]
            result["sample_title"] = (first.get("title") or "")[:120]
            raw_summary = (first.get("summary") or first.get("description") or "")[:200]
            import re
            result["sample_summary"] = re.sub(r"<[^>]+>", "", raw_summary).strip()[:200]

            # Determine content quality
            if result["with_summary"] >= result["articles"] * 0.5 and result["avg_summary_len"] >= 100:
                result["status"] = "FULL_CONTENT"
            elif result["with_summary"] >= result["articles"] * 0.3:
                result["status"] = "PARTIAL_CONTENT"
            else:
                result["status"] = "HEADLINES_ONLY"

    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)[:100]

    return result


async def main():
    print(f"Testing {len(ALL_SOURCES)} sources for FULL content availability...\n")
    print(f"{'Source':<35s} {'Region':<5s} {'Status':<18s} {'#':>4s} {'Title':>5s} {'Summ':>5s} {'AvgLen':>6s} {'MaxLen':>6s}")
    print("-" * 105)

    tasks = [test_source(s) for s in ALL_SOURCES]
    results = await asyncio.gather(*tasks)

    full = []; partial = []; headlines = []; empty = []; failed = []; skipped = []

    for r in results:
        marker = ""
        if r["status"] == "FULL_CONTENT":
            marker = "[OK]"
            full.append(r)
        elif r["status"] == "PARTIAL_CONTENT":
            marker = "[~] "
            partial.append(r)
        elif r["status"] == "HEADLINES_ONLY":
            marker = "[!] "
            headlines.append(r)
        elif r["status"] == "EMPTY":
            marker = "[--]"
            empty.append(r)
        elif r["status"] == "FAILED":
            marker = "[XX]"
            failed.append(r)
        else:
            marker = "[--]"
            skipped.append(r)

        print(f"{marker} {r['name']:<32s} {r['region']:<5s} {r['status']:<18s} "
              f"{r['articles']:4d} {r['with_title']:5d} {r['with_summary']:5d} "
              f"{r['avg_summary_len']:6d} {r['max_summary_len']:6d}")

    # Region summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(full)} full | {len(partial)} partial | {len(headlines)} headlines-only | "
          f"{len(empty)} empty | {len(failed)} failed | {len(skipped)} skipped")
    print(f"{'='*70}")

    for region in ["US", "CN", "EU", "EM"]:
        region_results = [r for r in results if r["region"] == region]
        usable = [r for r in region_results if r["status"] in ("FULL_CONTENT", "PARTIAL_CONTENT")]
        total_articles = sum(r["articles"] for r in usable)
        print(f"  {region}: {len(usable)}/{len(region_results)} usable, {total_articles} articles with content")

    # Show samples of content
    print(f"\n{'='*70}")
    print(f"  CONTENT SAMPLES (first article from each source)")
    print(f"{'='*70}")
    for r in results:
        if r["sample_title"]:
            print(f"\n  [{r['region']}] {r['name']}")
            print(f"    Title: {r['sample_title']}")
            if r["sample_summary"]:
                print(f"    Summary: {r['sample_summary'][:200]}")

    # Sources that should be DELETED
    print(f"\n{'='*70}")
    print(f"  RECOMMENDED FOR DELETION (no content / empty / failed)")
    print(f"{'='*70}")
    to_delete = empty + failed + headlines
    if to_delete:
        for r in to_delete:
            print(f"  [{r['region']}] {r['name']} — {r['status']}: {r['error']}")
    else:
        print("  None — all sources provide usable content.")

    # Final usable list
    print(f"\n{'='*70}")
    print(f"  FINAL USABLE SOURCE LIST")
    print(f"{'='*70}")
    usable = full + partial
    for r in sorted(usable, key=lambda x: (x["region"], -x["articles"])):
        print(f"  [{r['region']}] {r['name']:<40s} {r['articles']:4d} arts  avg_summary={r['avg_summary_len']}chars")


if __name__ == "__main__":
    asyncio.run(main())
