"""Tests for news scout."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from marketmind.pipeline.scout import (
    NewsItem, fetch_source, fetch_all_sources, deduplicate,
    _strip_html, _title_similarity,
)
from marketmind.config.source_authority import Source, SourceTier, SourceStatus


def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>World</b></p>") == "Hello World"
    assert _strip_html("Plain text") == "Plain text"


def test_title_similarity_identical():
    assert _title_similarity("Fed raises rates", "Fed raises rates") == 1.0


def test_title_similarity_completely_different():
    assert _title_similarity("Fed raises rates", "Apple launches iPhone") < 0.5


def test_title_similarity_partial():
    score = _title_similarity(
        "Fed raises interest rates by 25bp",
        "Federal Reserve raises rates by 25 basis points"
    )
    assert 0.3 < score < 1.0


def test_newsitem_from_entry():
    source = Source("TestSource", SourceTier.RELIABLE, "https://test.com/rss")
    entry = {
        "title": "Breaking News",
        "link": "https://test.com/1",
        "summary": "Something happened in markets today.",
        "published": "2026-05-11T10:00:00Z",
    }
    item = NewsItem.from_entry(entry, source)
    assert item.title == "Breaking News"
    assert item.url == "https://test.com/1"
    assert item.source_name == "TestSource"
    assert item.source_tier == 2
    assert len(item.id) == 16


def test_deduplicate_removes_duplicate_urls():
    items = [
        NewsItem("id1", "Same Title", "https://same.com/1", "s1", 1, "2026-01-01", "summary"),
        NewsItem("id2", "Same Title", "https://same.com/1", "s2", 2, "2026-01-01", "summary"),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_deduplicate_removes_similar_titles():
    items = [
        NewsItem("id1", "Fed raises interest rates 25 basis points", "https://a.com/1", "s1", 1, "2026-01-01", "summary"),
        NewsItem("id2", "Fed raises rates 25 basis points today extra words", "https://b.com/2", "s2", 1, "2026-01-01", "summary"),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_deduplicate_keeps_distinct_items():
    items = [
        NewsItem("id1", "Fed raises rates", "https://a.com/1", "s1", 1, "2026-01-01", "summary"),
        NewsItem("id2", "Apple launches new product", "https://b.com/2", "s2", 1, "2026-01-01", "summary"),
        NewsItem("id3", "Oil prices surge", "https://c.com/3", "s3", 1, "2026-01-01", "summary"),
    ]
    result = deduplicate(items)
    assert len(result) == 3


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::DeprecationWarning:feedparser")
async def test_fetch_source_rss_returns_items():
    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
    <item><title>Fed Meeting Today</title><link>https://test.com/1</link><description>Analysis of Fed meeting</description><pubDate>Mon, 11 May 2026 10:00:00 GMT</pubDate></item>
    <item><title>Market Rally Continues</title><link>https://test.com/2</link><description>Stocks up</description><pubDate>Mon, 11 May 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = rss_xml
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    source = Source("TestRSS", SourceTier.RELIABLE, "https://test.com/rss")

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await fetch_source(source, MagicMock())
        assert len(items) >= 1
        assert items[0].source_name == "TestRSS"
        assert source.status == SourceStatus.WORKING
