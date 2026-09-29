"""Test playground fetcher — WP API + RSS dual channel, three-tier logic."""
from __future__ import annotations

import httpx
import pytest

from marketmind.playground.playground_sources import (
    PlaygroundSource, SourceTier, UsageTier, SourceChannel,
    get_sources_for_agent, get_core_sources, get_supplemental_sources,
    get_retired_sources, get_all_active_sources,
    PLAYGROUND_SOURCES,
)
from marketmind.playground.playground_fetcher import (
    _parse_rss_feed, _parse_rss_item, _clean_text,
    flatten_results, _wp_render,
)


_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Memory prices climb</title><link>https://www.eetasia.com/1</link>
<description>DRAM contract prices rose.</description></item>
<item><title>Foundry outlook</title><link>https://www.eetasia.com/2</link>
<description>Utilisation recovers.</description></item>
</channel></rss>"""


def _mock_http(monkeypatch, handler) -> list[str]:
    """Route the fetcher's httpx clients to `handler`; returns the requested URLs."""
    from marketmind.playground import playground_fetcher as pf
    seen: list[str] = []
    real = httpx.AsyncClient

    def record(request):
        seen.append(str(request.url))
        return handler(request)

    class _Client(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(record)
            super().__init__(*a, **kw)

    monkeypatch.setattr(pf.httpx, "AsyncClient", _Client)
    return seen


# ── Source registry tests ─────────────────────────────────────────────────

def test_get_sources_for_serenity_reply():
    sources = get_sources_for_agent("serenity_reply")
    assert len(sources) >= 8
    names = {s.name for s in sources}
    assert "EE Times" in names
    assert "Photonics Spectra" in names
    assert "Semiconductor Engineering" in names
    assert "Google News — Semiconductor" in names  # supplemental still declared


def test_get_sources_for_unknown_agent():
    assert get_sources_for_agent("nonexistent") == []


def test_core_sources_excludes_supplemental_and_retired():
    """get_core_sources returns only UsageTier.CORE sources."""
    core = get_core_sources(["serenity_reply"])
    tiers = {s.usage_tier for s in core}
    assert tiers == {UsageTier.CORE}
    names = {s.name for s in core}
    assert "Google News — Semiconductor" not in names  # supplemental
    assert "WCCFTech" not in names  # retired


def test_supplemental_sources():
    supp = get_supplemental_sources(["serenity_reply"])
    tiers = {s.usage_tier for s in supp}
    assert tiers == {UsageTier.SUPPLEMENTAL}
    names = {s.name for s in supp}
    assert "Google News — Semiconductor" in names


def test_retired_sources_exist():
    retired = get_retired_sources()
    names = {s.name for s in retired}
    assert "WCCFTech" in names
    assert "Ars Technica" in names
    assert "The Register" in names
    # All retired sources have a reason
    for s in retired:
        assert s.retire_reason, f"{s.name} has no retire_reason"


def test_get_all_active_sources():
    active = get_all_active_sources(["serenity_reply"])
    tiers = {s.usage_tier for s in active}
    assert UsageTier.RETIRED not in tiers
    assert len(active) > 8


def test_wp_api_sources_have_wp_api_url():
    wp_sources = [s for s in PLAYGROUND_SOURCES if s.channel == SourceChannel.WP_API]
    assert len(wp_sources) >= 6
    for s in wp_sources:
        assert s.wp_api_url, f"{s.name} WP_API source has no wp_api_url"
        assert "wp-json/wp/v2/posts" in s.wp_api_url


def test_all_sources_have_urls():
    for source in PLAYGROUND_SOURCES:
        assert source.url, f"{source.name} has empty URL"


# ── RSS parsing tests ─────────────────────────────────────────────────────

def test_clean_text_strips_html():
    assert _clean_text("<p>Hello <b>World</b></p>") == "Hello World"
    assert _clean_text("<![CDATA[Hello]]>") == "Hello"


def test_parse_rss_feed():
    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Test Article</title>
          <link>https://example.com/1</link>
          <description>Article summary here</description>
          <pubDate>Mon, 26 May 2026 14:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Second Article</title>
          <link>https://example.com/2</link>
          <description>Another summary</description>
        </item>
      </channel>
    </rss>"""
    source = PlaygroundSource(name="Test", url="https://example.com/feed",
                              tier=SourceTier.RELIABLE, reliability=0.8)
    items = _parse_rss_feed(rss_xml, source)
    assert len(items) == 2
    assert items[0]["title"] == "Test Article"
    assert items[0]["source_name"] == "Test"


def test_parse_feed_handles_empty():
    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Empty</title></channel></rss>"""
    source = PlaygroundSource(name="Test", url="https://example.com/feed",
                              tier=SourceTier.RELIABLE, reliability=0.8)
    items = _parse_rss_feed(rss_xml, source)
    assert items == []


def test_parse_item_skips_empty_title():
    import xml.etree.ElementTree as ET
    elem = ET.fromstring("<item><title></title><link>https://x.com</link></item>")
    source = PlaygroundSource(name="Test", url="https://x.com",
                              tier=SourceTier.RELIABLE, reliability=0.8)
    result = _parse_rss_item(elem, source)
    assert result is None


def test_flatten_results():
    results = [
        {"items": [{"title": "A"}, {"title": "B"}]},
        {"items": []},
        {"items": [{"title": "C"}]},
    ]
    items = flatten_results(results)
    assert len(items) == 3


# ── WP API parsing tests ──────────────────────────────────────────────────

def test_wp_render_dict():
    post = {"title": {"rendered": "Hello World"}}
    assert _wp_render(post, "title") == "Hello World"


def test_wp_render_string_fallback():
    post = {"title": "Plain Title"}
    assert _wp_render(post, "title") == "Plain Title"


def test_wp_render_missing():
    assert _wp_render({}, "title") == ""


# ── Integration tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_wp_api_source(monkeypatch):
    """WP API channel against a mocked WordPress reply (no network)."""
    from marketmind.playground.playground_fetcher import _fetch_source
    body = "<p>" + "Chiplet packaging capacity is expanding across the supply chain. " * 4 + "</p>"
    seen = _mock_http(monkeypatch, lambda req: httpx.Response(200, json=[
        {"title": {"rendered": "TSMC expands CoWoS"}, "link": "https://www.eetimes.com/a",
         "date": "2026-09-28T08:00:00", "excerpt": {"rendered": "<p>Short</p>"},
         "content": {"rendered": body}},
        {"title": {"rendered": ""}, "content": {"rendered": "untitled posts are skipped"}},
    ]))

    source = PlaygroundSource(
        name="EE Times",
        url="https://www.eetimes.com",
        wp_api_url="https://www.eetimes.com/wp-json/wp/v2/posts?per_page=5&_embed",
        channel=SourceChannel.WP_API,
        tier=SourceTier.PRIMARY,
        reliability=0.88,
    )
    result = await _fetch_source(source)
    assert seen == ["https://www.eetimes.com/wp-json/wp/v2/posts?per_page=5&_embed"]
    assert result["source_name"] == "EE Times" and not result.get("error")
    assert [i["title"] for i in result["items"]] == ["TSMC expands CoWoS"]
    item = result["items"][0]
    assert item["url"] == "https://www.eetimes.com/a" and item["summary"] == "Short"
    assert len(item["full_content"]) > 100  # WP API returns full article


@pytest.mark.asyncio
async def test_fetch_rss_source(monkeypatch):
    """RSS channel against a mocked feed (no network)."""
    from marketmind.playground.playground_fetcher import _fetch_source
    seen = _mock_http(monkeypatch, lambda req: httpx.Response(200, text=_RSS))

    source = PlaygroundSource(
        name="EE Times Asia",
        url="https://www.eetasia.com/feed/",
        channel=SourceChannel.RSS,
        tier=SourceTier.RELIABLE,
        reliability=0.78,
    )
    result = await _fetch_source(source)
    assert seen == ["https://www.eetasia.com/feed/"]
    assert result["source_name"] == "EE Times Asia" and not result.get("error")
    assert [(i["title"], i["url"]) for i in result["items"]] == [
        ("Memory prices climb", "https://www.eetasia.com/1"),
        ("Foundry outlook", "https://www.eetasia.com/2")]


@pytest.mark.slow  # live RSS fetch; fails offline
@pytest.mark.asyncio
async def test_fetch_core_sources():
    """Integration: fetch CORE sources for serenity_reply."""
    from marketmind.playground.playground_fetcher import fetch_core_sources

    results = await fetch_core_sources(["serenity_reply"])
    assert len(results) >= 8  # 8 CORE sources for serenity_reply
    total_items = sum(len(r.get("items", [])) for r in results)
    assert total_items > 0, "CORE sources should yield articles"


@pytest.mark.asyncio
async def test_supplemental_trigger_threshold(monkeypatch):
    """Supplemental fires when core yield is low, skips when high."""
    from marketmind.playground.playground_fetcher import fetch_supplemental_if_needed

    # Core yield 5 (< 15) → should trigger supplemental
    seen = _mock_http(monkeypatch, lambda req: httpx.Response(200, text=_RSS))
    fake_core = [
        {"items": [{"title": "x"}] * 3},
        {"items": [{"title": "x"}] * 2},
    ]
    supp = await fetch_supplemental_if_needed(["serenity_reply"], fake_core)
    # Google News is fetched (mocked)
    names = {r.get("source_name") for r in supp}
    assert "Google News — Semiconductor" in names
    assert any("news.google.com" in u for u in seen)
    seen.clear()

    # Core yield 50 (>= 15) → should skip supplemental
    fake_core_high = [{"items": [{"title": "x"}] * 50}]
    supp_skip = await fetch_supplemental_if_needed(["serenity_reply"], fake_core_high)
    assert supp_skip == [] and seen == []
