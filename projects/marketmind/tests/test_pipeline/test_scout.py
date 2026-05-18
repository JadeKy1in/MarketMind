"""Tests for news scout."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from marketmind.pipeline.scout import (
    NewsItem, fetch_source, fetch_all_sources, deduplicate,
    _strip_html, _title_similarity, _fetch_newsapi, _fetch_gnews,
    _fetch_ecb_press_content,
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


# ── NewsAPI / GNews API fetcher tests ──────────────────────────────────────

NEWSAPI_JSON_RESPONSE = {
    "status": "ok",
    "totalResults": 2,
    "articles": [
        {
            "source": {"id": "cnn", "name": "CNN"},
            "author": "Author One",
            "title": "Fed Raises Rates by 25bp",
            "description": "The Federal Reserve raised interest rates today.",
            "url": "https://cnn.com/fed-rates",
            "urlToImage": "https://cnn.com/img.jpg",
            "publishedAt": "2026-05-17T14:00:00Z",
            "content": "Full article content here..."
        },
        {
            "source": {"id": "reuters", "name": "Reuters"},
            "author": "Author Two",
            "title": "Market Rally Continues",
            "description": "Stocks extended gains in afternoon trading.",
            "url": "https://reuters.com/rally",
            "urlToImage": None,
            "publishedAt": "2026-05-17T13:30:00Z",
            "content": "Market details..."
        },
    ]
}

GNEWS_JSON_RESPONSE = {
    "totalArticles": 2,
    "articles": [
        {
            "title": "Oil Prices Surge on Supply Concerns",
            "description": "Crude oil prices jumped today amid supply fears.",
            "content": "Full content...",
            "url": "https://example.com/oil",
            "image": "https://example.com/img.jpg",
            "publishedAt": "2026-05-17T12:00:00Z",
            "source": {"name": "Bloomberg", "url": "https://bloomberg.com"}
        },
        {
            "title": "Tech Earnings Beat Expectations",
            "description": "Major tech firms reported quarterly results above forecasts.",
            "content": "Full content...",
            "url": "https://example.com/tech",
            "image": "https://example.com/img2.jpg",
            "publishedAt": "2026-05-17T11:00:00Z",
            "source": {"name": "CNBC", "url": "https://cnbc.com"}
        },
    ]
}


@pytest.mark.asyncio
async def test_fetch_newsapi_no_api_key_returns_empty():
    """NewsAPI: missing API key → empty list, no crash."""
    config = MagicMock()
    config.newsapi_key = None
    # Reset cache so we don't get stale results
    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None
    items = await _fetch_newsapi(config)
    assert items == []


@pytest.mark.asyncio
async def test_fetch_newsapi_parses_json_response():
    """NewsAPI: valid JSON response → correctly parsed NewsItems."""
    config = MagicMock()
    config.newsapi_key = "test-key-123"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = NEWSAPI_JSON_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # Reset cache
    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await _fetch_newsapi(config)
        assert len(items) == 2
        assert items[0].title == "Fed Raises Rates by 25bp"
        assert items[0].url == "https://cnn.com/fed-rates"
        assert items[0].source_name == "NewsAPI"
        assert items[0].source_tier == 2
        assert items[0].source_reliability == 0.90
        assert items[0].content_type == "news"
        assert items[1].title == "Market Rally Continues"


@pytest.mark.asyncio
async def test_fetch_newsapi_handles_non_ok_status():
    """NewsAPI: non-ok status → empty list, no crash."""
    config = MagicMock()
    config.newsapi_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "error", "message": "API key invalid"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await _fetch_newsapi(config)
        assert items == []


@pytest.mark.asyncio
async def test_fetch_newsapi_handles_http_error():
    """NewsAPI: HTTP error → empty list, no crash."""
    config = MagicMock()
    config.newsapi_key = "test-key"

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await _fetch_newsapi(config)
        assert items == []


@pytest.mark.asyncio
async def test_fetch_gnews_no_api_key_returns_empty():
    """GNews: missing API key → empty list, no crash."""
    config = MagicMock()
    config.gnews_key = None
    import marketmind.pipeline.scout as scout_mod
    scout_mod._gnews_cache = None
    items = await _fetch_gnews(config)
    assert items == []


@pytest.mark.asyncio
async def test_fetch_gnews_parses_json_response():
    """GNews: valid JSON response → correctly parsed NewsItems."""
    config = MagicMock()
    config.gnews_key = "test-key-456"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GNEWS_JSON_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._gnews_cache = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await _fetch_gnews(config)
        assert len(items) == 2
        assert items[0].title == "Oil Prices Surge on Supply Concerns"
        assert items[0].url == "https://example.com/oil"
        assert items[0].source_name == "GNews"
        assert items[0].source_tier == 2
        assert items[0].source_reliability == 0.85
        assert items[0].content_type == "news"
        assert items[1].title == "Tech Earnings Beat Expectations"


@pytest.mark.asyncio
async def test_fetch_gnews_handles_http_error():
    """GNews: HTTP error → empty list, no crash."""
    config = MagicMock()
    config.gnews_key = "test-key"

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Timeout")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._gnews_cache = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await _fetch_gnews(config)
        assert items == []


@pytest.mark.asyncio
async def test_fetch_source_dispatches_to_newsapi():
    """fetch_source with NewsAPI source → calls _fetch_newsapi, sets WORKING."""
    source = Source("NewsAPI", SourceTier.RELIABLE, None, "api", 0.90, 10.0, True)
    config = MagicMock()
    config.newsapi_key = None  # no key → empty, but dispatch still works

    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None

    items = await fetch_source(source, config)
    assert items == []
    assert source.status == SourceStatus.WORKING


@pytest.mark.asyncio
async def test_fetch_source_dispatches_to_gnews():
    """fetch_source with GNews source → calls _fetch_gnews, sets WORKING."""
    source = Source("GNews", SourceTier.RELIABLE, None, "api", 0.85, 10.0, True)
    config = MagicMock()
    config.gnews_key = None  # no key → empty, but dispatch still works

    import marketmind.pipeline.scout as scout_mod
    scout_mod._gnews_cache = None

    items = await fetch_source(source, config)
    assert items == []
    assert source.status == SourceStatus.WORKING


@pytest.mark.asyncio
async def test_newsapi_cache_used_on_second_call():
    """NewsAPI: second call within 24h returns cached result without HTTP call."""
    config = MagicMock()
    config.newsapi_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = NEWSAPI_JSON_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._newsapi_cache = None
    scout_mod._newsapi_cache_time = 0.0

    with patch("httpx.AsyncClient", return_value=mock_client) as mock_async_client:
        items1 = await _fetch_newsapi(config)
        assert len(items1) == 2
        call_count = mock_async_client.call_count

        items2 = await _fetch_newsapi(config)
        assert len(items2) == 2
        # Second call should use cache — no new httpx.AsyncClient constructed
        assert mock_async_client.call_count == call_count


@pytest.mark.asyncio
async def test_gnews_cache_used_on_second_call():
    """GNews: second call within 24h returns cached result without HTTP call."""
    config = MagicMock()
    config.gnews_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GNEWS_JSON_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import marketmind.pipeline.scout as scout_mod
    scout_mod._gnews_cache = None
    scout_mod._gnews_cache_time = 0.0

    with patch("httpx.AsyncClient", return_value=mock_client) as mock_async_client:
        items1 = await _fetch_gnews(config)
        assert len(items1) == 2
        call_count = mock_async_client.call_count

        items2 = await _fetch_gnews(config)
        assert len(items2) == 2
        assert mock_async_client.call_count == call_count


# ── ECB HTML content extraction tests ────────────────────────────────────

VALID_ECB_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>ECB Press Release</title></head>
<body>
<nav><a href="/">Home</a></nav>
<script>console.log('tracking');</script>
<main class="ecb-publications">
  <h1>Monetary policy decisions</h1>
  <p>The Governing Council today decided to lower the three key ECB interest rates by 25 basis points.</p>
  <p>In particular, the decision to lower the deposit facility rate is based on an updated assessment of the inflation outlook.</p>
  <p>The disinflation process is well on track. Inflation has developed broadly as staff previously projected.</p>
</main>
<footer>© ECB 2026</footer>
</body>
</html>"""

ECB_HTML_WITH_ARTICLE = """<!DOCTYPE html>
<html><body>
<article>
<p>Statistical Data for May 2026 show continued economic expansion across the euro area.</p>
<p>GDP growth estimates revised upward by 0.3 percentage points reflecting stronger-than-expected consumer spending.</p>
</article>
</body></html>"""

ECB_HTML_NO_MAIN = """<!DOCTYPE html>
<html><body>
<p>Some loose paragraph without semantic structure.</p>
<p>Another paragraph that falls back to body extraction.</p>
</body></html>"""

ECB_HTML_LONG = """<!DOCTYPE html>
<html><body>
<main><p>""" + (". ".join(["Sentence number %d with meaningful content about monetary policy and economic outlook" % i for i in range(50)]) + ".") + """</p></main>
</body></html>"""


@pytest.mark.asyncio
async def test_ecb_html_extraction_article_tag():
    """ECB HTML with <article> content → extracts paragraph text correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ECB_HTML_WITH_ARTICLE
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/1.html")
        assert "Statistical Data for May 2026" in result
        assert "GDP growth estimates revised upward" in result
        assert "console" not in result.lower()


@pytest.mark.asyncio
async def test_ecb_fallback_on_empty_page():
    """Empty HTML → returns empty string, doesn't crash."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body></body></html>"
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/empty.html")
        assert result == ""


@pytest.mark.asyncio
async def test_ecb_script_tags_stripped():
    """JavaScript in HTML → removed from output."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_ECB_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/2.html")
        assert "The Governing Council today decided" in result
        # script content must be stripped
        assert "console.log" not in result
        assert "tracking" not in result
        # nav content must be stripped
        assert "Home" not in result


@pytest.mark.asyncio
async def test_ecb_length_truncation():
    """Very long press release → truncated at sentence boundary under 1000 chars."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ECB_HTML_LONG
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/long.html")
        assert len(result) <= 1000
        assert len(result) > 50
        # ends with period (sentence boundary)
        assert result.rstrip().endswith(".")


@pytest.mark.asyncio
async def test_ecb_no_main_or_article_falls_back_to_body():
    """HTML without <main> or <article> → falls back to full body extraction."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ECB_HTML_NO_MAIN
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/nomain.html")
        assert "Some loose paragraph" in result
        assert "falls back to body extraction" in result


@pytest.mark.asyncio
async def test_ecb_http_error_returns_empty():
    """HTTP error → returns empty string, graceful degradation."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ecb_press_content("https://ecb.europa.eu/press/error.html")
        assert result == ""
