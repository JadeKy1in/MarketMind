"""Playground data fetcher — WP API + RSS dual channel.

Independent of main pipeline Scout. Fetches from WordPress REST API
(full article JSON) and traditional RSS/Atom feeds.

Three-tier fetch logic:
  CORE         — fetched every run
  SUPPLEMENTAL — fetched when core yield < threshold (15 articles)
  RETIRED      — never fetched (kept for audit)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET

import httpx

from marketmind.playground.playground_sources import (
    PlaygroundSource, SourceChannel, UsageTier,
    get_core_sources, get_supplemental_sources, get_source,
)

logger = logging.getLogger("marketmind.playground.fetcher")

DEFAULT_TIMEOUT = httpx.Timeout(30.0)
SUPPLEMENTAL_TRIGGER_THRESHOLD = 15  # fire supplemental when core < 15 articles
USER_AGENT = "MarketMind-Playground/1.0"


# ══════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════

async def fetch_core_sources(agent_ids: list[str]) -> list[dict]:
    """Fetch all CORE-tier sources for active agents.

    Returns list of result dicts: {source_name, source_tier, source_reliability,
    channel, items: [{title, url, summary, full_content?, published_at, ...}], error}
    """
    sources = get_core_sources(agent_ids)
    if not sources:
        logger.info("Playground fetcher: no CORE sources for %s", agent_ids)
        return []
    return await _fetch_all(sources, label="CORE")


async def fetch_supplemental_if_needed(
    agent_ids: list[str],
    core_results: list[dict],
) -> list[dict]:
    """Fetch SUPPLEMENTAL sources only if core yield is below threshold."""
    core_total = sum(len(r.get("items", [])) for r in core_results)
    if core_total >= SUPPLEMENTAL_TRIGGER_THRESHOLD:
        logger.info(
            "Playground fetcher: core yield %d >= %d, skipping supplemental",
            core_total, SUPPLEMENTAL_TRIGGER_THRESHOLD,
        )
        return []

    sources = get_supplemental_sources(agent_ids)
    if not sources:
        return []

    logger.info(
        "Playground fetcher: core yield %d < %d, fetching %d supplemental sources",
        core_total, SUPPLEMENTAL_TRIGGER_THRESHOLD, len(sources),
    )
    return await _fetch_all(sources, label="SUPPLEMENTAL")


async def fetch_for_agents(agent_ids: list[str]) -> list[dict]:
    """Full fetch: CORE + conditional SUPPLEMENTAL."""
    core = await fetch_core_sources(agent_ids)
    supp = await fetch_supplemental_if_needed(agent_ids, core)
    return core + supp


def flatten_results(results: list[dict]) -> list[dict]:
    """Flatten all fetch results into a single list of item dicts."""
    items: list[dict] = []
    for result in results:
        items.extend(result.get("items", []))
    return items


# ══════════════════════════════════════════════════════════════════════════
# Internal: dispatch + fetch
# ══════════════════════════════════════════════════════════════════════════

async def _fetch_all(sources: list[PlaygroundSource], label: str) -> list[dict]:
    """Fetch multiple sources concurrently."""
    logger.info("Playground fetcher [%s]: fetching %d sources", label, len(sources))
    tasks = [_fetch_source(s) for s in sources]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict] = []
    for i, result in enumerate(raw):
        src = sources[i]
        if isinstance(result, Exception):
            results.append(_error_result(src, str(result)))
        else:
            results.append(result)

    total = sum(len(r.get("items", [])) for r in results)
    errors = sum(1 for r in results if r.get("error"))
    logger.info("Playground fetcher [%s]: %d items, %d/%d errors",
                label, total, errors, len(results))
    return results


async def _fetch_source(source: PlaygroundSource) -> dict:
    """Fetch a single source, dispatching by channel."""
    if source.channel == SourceChannel.WP_API:
        return await _fetch_wp_api(source)
    else:
        return await _fetch_rss(source)


# ══════════════════════════════════════════════════════════════════════════
# Channel: WP API
# ══════════════════════════════════════════════════════════════════════════

async def _fetch_wp_api(source: PlaygroundSource) -> dict:
    """Fetch articles from WordPress REST API.

    Returns full article content in 'full_content' field, plus a truncated
    'summary' for LLM prompt efficiency.
    """
    result = _empty_result(source)
    url = source.wp_api_url or source.url

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.debug("WP API fetch failed for %s: %s", source.name, exc)
        result["error"] = str(exc)
        return result

    if not isinstance(data, list):
        logger.debug("WP API: unexpected response format from %s", source.name)
        return result

    items: list[dict] = []
    for post in data:
        title = _wp_render(post, "title")
        if not title:
            continue

        link = post.get("link", "")
        published = post.get("date", "") or post.get("modified", "")
        excerpt = _wp_render(post, "excerpt")
        content = _wp_render(post, "content")

        # Clean for LLM consumption
        summary = (_clean_text(excerpt)[:400] if excerpt
                   else _clean_text(content)[:400])
        full_content = _clean_text(content) if content else summary

        items.append({
            "title": title[:300],
            "url": link or "",
            "summary": summary,
            "full_content": full_content[:8000],
            "published_at": published,
            "source_name": source.name,
            "source_tier": int(source.tier),
            "source_reliability": source.reliability,
        })

    result["items"] = items
    return result


def _wp_render(post: dict, field: str) -> str:
    """Extract rendered text from a WP API post field."""
    f = post.get(field, {})
    if isinstance(f, dict):
        return f.get("rendered", "")
    if isinstance(f, str):
        return f
    return ""


# ══════════════════════════════════════════════════════════════════════════
# Channel: RSS
# ══════════════════════════════════════════════════════════════════════════

async def _fetch_rss(source: PlaygroundSource) -> dict:
    """Fetch and parse an RSS/Atom feed."""
    result = _empty_result(source)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                source.url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            response.raise_for_status()
            content = response.text
    except Exception as exc:
        logger.debug("RSS fetch failed for %s: %s", source.name, exc)
        result["error"] = str(exc)
        return result

    try:
        result["items"] = _parse_rss_feed(content, source)
    except Exception as exc:
        logger.debug("RSS parse failed for %s: %s", source.name, exc)
        result["error"] = f"Parse error: {exc}"

    return result


def _parse_rss_feed(content: str, source: PlaygroundSource) -> list[dict]:
    """Parse RSS 2.0 or Atom feed into item dicts."""
    content = re.sub(r'<\?xml-stylesheet[^?]*\?>', '', content)
    root = ET.fromstring(content)

    items: list[dict] = []
    channel = root.find("channel")

    if channel is not None:
        for elem in channel.findall("item"):
            item = _parse_rss_item(elem, source)
            if item:
                items.append(item)
    else:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for elem in root.findall("atom:entry", ns) or root.findall("entry"):
            item = _parse_atom_entry(elem, source, ns)
            if item:
                items.append(item)

    return items


def _parse_rss_item(elem: ET.Element, source: PlaygroundSource) -> dict | None:
    title = _elem_text(elem, "title")
    link = _elem_text(elem, "link")
    if not title:
        return None

    summary = _clean_text(
        _elem_text(elem, "description")
        or _elem_text(elem, "{http://purl.org/rss/1.0/modules/content/}encoded")
        or ""
    )
    pub_date = _elem_text(elem, "pubDate") or ""

    return {
        "title": title[:300],
        "url": link or "",
        "summary": summary[:400],
        "full_content": summary[:8000],
        "published_at": pub_date,
        "source_name": source.name,
        "source_tier": int(source.tier),
        "source_reliability": source.reliability,
    }


def _parse_atom_entry(elem: ET.Element, source: PlaygroundSource,
                      ns: dict) -> dict | None:
    title = _elem_text(elem, "title") or _elem_text(elem, "atom:title", ns)
    if not title:
        return None

    link_elem = elem.find("link") or elem.find("atom:link", ns)
    link = link_elem.get("href", "") if link_elem is not None else ""

    summary = _clean_text(
        _elem_text(elem, "summary") or _elem_text(elem, "atom:summary", ns)
        or _elem_text(elem, "content") or _elem_text(elem, "atom:content", ns)
        or ""
    )
    published = (
        _elem_text(elem, "published") or _elem_text(elem, "atom:published", ns)
        or _elem_text(elem, "updated") or _elem_text(elem, "atom:updated", ns)
        or ""
    )

    return {
        "title": title[:300],
        "url": link,
        "summary": summary[:400],
        "full_content": summary[:8000],
        "published_at": published,
        "source_name": source.name,
        "source_tier": int(source.tier),
        "source_reliability": source.reliability,
    }


def _elem_text(elem: ET.Element, tag: str, ns: dict | None = None) -> str:
    child = elem.find(tag, ns) if ns else elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _clean_text(text: str) -> str:
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def _empty_result(source: PlaygroundSource) -> dict:
    return {
        "source_name": source.name,
        "source_tier": int(source.tier),
        "source_reliability": source.reliability,
        "channel": source.channel.value,
        "usage_tier": source.usage_tier.value,
        "items": [],
        "error": "",
    }


def _error_result(source: PlaygroundSource, error: str) -> dict:
    r = _empty_result(source)
    r["error"] = error
    return r
