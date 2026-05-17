"""Archive all information source outputs to local text files.

Usage:
    python tools/archive_sources.py                    # archive to data/archive/
    python tools/archive_sources.py --golden           # archive to tests/fixtures/

Runs the full source collection pipeline once, saves raw output from each
source as individual text files, plus a combined manifest JSON.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # .../projects/marketmind
sys.path.insert(0, str(PROJECT_ROOT.parent))  # .../projects — enables 'from marketmind import ...'


async def collect_all_sources() -> dict:
    """Collect articles from all sources and return structured results."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.config.source_authority import SOURCES, SourceTier, SourceStatus
    from marketmind.pipeline.scout import fetch_source, NewsItem

    config = MarketMindConfig()
    results: dict[str, dict] = {}
    all_items: list[dict] = []

    print(f"Collecting from {len(SOURCES)} sources...\n")

    for source in SOURCES:
        name = source.name
        tier_name = SourceTier(source.tier).name
        print(f"  [{tier_name}] {name} ... ", end="", flush=True)
        try:
            items: list[NewsItem] = await fetch_source(source, config)
            item_dicts = [
                {
                    "id": it.id,
                    "title": it.title,
                    "url": it.url,
                    "source_name": it.source_name,
                    "source_tier": int(it.source_tier),
                    "published_at": it.published_at,
                    "summary": it.summary[:500],
                    "source_reliability": it.source_reliability,
                    "content_type": it.content_type,
                }
                for it in items
            ]
            results[name] = {
                "tier": tier_name,
                "reliability": source.reliability,
                "feed_type": source.feed_type,
                "status": "working" if items else "empty",
                "count": len(items),
                "items": item_dicts,
            }
            all_items.extend(item_dicts)
            print(f"{len(items)} articles")
        except Exception as e:
            results[name] = {
                "tier": tier_name,
                "reliability": source.reliability,
                "feed_type": source.feed_type,
                "status": "failed",
                "count": 0,
                "error": str(e)[:200],
                "items": [],
            }
            print(f"FAILED: {e}")

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "total_sources": len(SOURCES),
        "working_sources": sum(1 for r in results.values() if r["status"] == "working"),
        "empty_sources": sum(1 for r in results.values() if r["status"] == "empty"),
        "failed_sources": sum(1 for r in results.values() if r["status"] == "failed"),
        "total_articles": len(all_items),
        "sources": results,
    }


def save_archive(data: dict, target_dir: Path) -> Path:
    """Save collected data as text files in target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)

    # Write combined manifest JSON
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\n  Manifest: {manifest_path}")

    # Write per-source text files
    txt_dir = target_dir / "by_source"
    txt_dir.mkdir(exist_ok=True)
    for name, src in data["sources"].items():
        items = src.get("items", [])
        if not items:
            continue
        lines = [
            f"# {name} ({src['tier']}, reliability={src['reliability']})",
            f"# Collected: {data['collected_at']}",
            f"# Articles: {len(items)}",
            "",
        ]
        for i, item in enumerate(items, 1):
            lines.append(f"--- [{i}] {item['title']}")
            lines.append(f"URL: {item['url']}")
            lines.append(f"Published: {item['published_at']}")
            lines.append(f"Summary: {item['summary']}")
            lines.append("")
        out_path = txt_dir / f"{name.replace(' ', '_').lower()}.txt"
        out_path.write_text("\n".join(lines), encoding="utf-8")

    # Write combined all-items text
    all_path = target_dir / "all_articles.txt"
    all_lines = [
        f"# MarketMind Source Archive",
        f"# Collected: {data['collected_at']}",
        f"# Working: {data['working_sources']} | Empty: {data['empty_sources']} | Failed: {data['failed_sources']}",
        f"# Total articles: {data['total_articles']}",
        "",
    ]
    for name, src in data["sources"].items():
        items = src.get("items", [])
        all_lines.append(f"## {name} ({src['tier']}) — {len(items)} articles")
        for item in items:
            all_lines.append(f"  [{item['source_tier']}] {item['title']}")
        all_lines.append("")
    all_path.write_text("\n".join(all_lines), encoding="utf-8")

    return manifest_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Archive MarketMind source outputs")
    parser.add_argument(
        "--golden", action="store_true",
        help="Save to tests/fixtures/sources_golden/ (for regression testing)"
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.golden:
        target = PROJECT_ROOT / "tests" / "fixtures" / "sources_golden"
        print(f"=== GOLDEN ARCHIVE → {target} ===\n")
    else:
        target = (
            PROJECT_ROOT / "data" / "archive"
            / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
        )
        print(f"=== ARCHIVE → {target} ===\n")

    data = asyncio.run(collect_all_sources())

    print(f"\nResults: {data['working_sources']} working, "
          f"{data['empty_sources']} empty, {data['failed_sources']} failed, "
          f"{data['total_articles']} total articles")

    manifest = save_archive(data, target)
    print(f"\nDone. Archive saved to {target}")

    # Summary
    print("\n=== Source Summary ===")
    for name, src in data["sources"].items():
        status = src["status"]
        marker = "✅" if status == "working" else ("⚠️" if status == "empty" else "❌")
        print(f"  {marker} {name:25s} {src['count']:3d} articles  [{src['tier']}]")


if __name__ == "__main__":
    main()
