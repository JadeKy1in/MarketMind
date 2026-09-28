"""Offline tests for the 2026-09-28 data-source fixes (scout + registry)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.config.source_authority import (
    RSSHUB_MIRRORS, SOURCES, Source, SourceStatus, SourceTier, rss_candidate_urls,
)
from marketmind.pipeline import scout
from marketmind.pipeline.scout import fetch_source, source_issue

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Headline one</title><link>https://example.com/1</link></item>
</channel></rss>"""


def _by_name() -> dict[str, Source]:
    return {s.name: s for s in SOURCES}


def _resp(status: int, text: str = RSS) -> MagicMock:
    r = MagicMock(status_code=status, text=text)
    if status >= 400:
        r.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            str(status), request=MagicMock(), response=MagicMock(status_code=status)))
    else:
        r.raise_for_status = MagicMock()
    return r


def _client(get: AsyncMock) -> AsyncMock:
    client = AsyncMock()
    client.get = get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _config() -> MagicMock:
    return MagicMock(proxy_url="", newsapi_key="", gnews_key="")


# ── Registry ────────────────────────────────────────────────────────────────

def test_yahoo_uses_fresh_headline_feed_and_xinhua_is_gone():
    by = _by_name()
    assert by["Yahoo Finance"].url.startswith("https://feeds.finance.yahoo.com/rss/2.0/headline")
    assert "rssindex" not in by["Yahoo Finance"].url
    assert "Xinhua Finance" not in by


def test_rsshub_sources_get_mirror_candidates_in_order():
    src = _by_name()["Yicai Brief (via RSSHub)"]
    urls = rss_candidate_urls(src)
    assert urls[0] == src.url
    assert [u.rsplit("/yicai/brief", 1)[0] for u in urls] == list(RSSHUB_MIRRORS)
    bbc = _by_name()["BBC Business"]
    assert rss_candidate_urls(bbc) == [bbc.url]


def test_zero_is_normal_marked_on_quiet_day_sources():
    by = _by_name()
    for name in ("Wikipedia Attention Spikes", "GDELT Events (15-min)", "IMF PortWatch Chokepoints",
                 "CFTC Commitments of Traders", "Cboe VIX History"):
        assert by[name].zero_is_normal, name
    assert not by["BBC Business"].zero_is_normal


# ── RSS fetch: mirror fallback and 406 retry ────────────────────────────────

@pytest.mark.asyncio
async def test_rsshub_timeout_falls_back_to_next_mirror():
    src = Source("Yicai Brief (via RSSHub)", SourceTier.FRAGILE,
                 f"{RSSHUB_MIRRORS[0]}/yicai/brief", "rss", 0.65)
    get = AsyncMock(side_effect=[httpx.ReadTimeout("slow"), _resp(502), _resp(200)])
    with patch("httpx.AsyncClient", return_value=_client(get)):
        items = await fetch_source(src, _config())
    assert len(items) == 1
    assert src.status == SourceStatus.WORKING
    tried = [c.args[0] for c in get.call_args_list]
    assert tried == [m + "/yicai/brief" for m in RSSHUB_MIRRORS[:3]]


@pytest.mark.asyncio
async def test_all_mirrors_failing_degrades_with_reason():
    src = Source("Caixin", SourceTier.FRAGILE, f"{RSSHUB_MIRRORS[0]}/caixin/latest", "rss", 0.7)
    get = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    with patch("httpx.AsyncClient", return_value=_client(get)):
        assert await fetch_source(src, _config()) == []
    assert get.await_count == len(RSSHUB_MIRRORS)
    assert src.status == SourceStatus.DEGRADED
    assert "ReadTimeout" in src.last_error


@pytest.mark.asyncio
async def test_406_is_retried_once_with_alternate_headers():
    src = Source("Euronews Economy", SourceTier.RELIABLE, "https://www.euronews.com/rss", "rss", 0.75)
    get = AsyncMock(side_effect=[_resp(406), _resp(200)])
    with patch("httpx.AsyncClient", return_value=_client(get)):
        items = await fetch_source(src, _config())
    assert len(items) == 1
    h1, h2 = (c.kwargs["headers"]["User-Agent"] for c in get.call_args_list)
    assert h1 != h2


# ── Sources that used to swallow failures ──────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("feed_type,fn", [
    ("sec_form4", "fetch_form4_insider"),
    ("sec_13f", "fetch_13f_holdings"),
    ("congress_api", "fetch_congress_trades"),
    ("sec_api", "_fetch_sec_edgar"),
])
async def test_insider_failure_is_recorded_not_untested(feed_type, fn):
    src = Source("X", SourceTier.BEST_EFFORT, "", feed_type, 0.2)
    with patch.object(scout, fn, AsyncMock(side_effect=RuntimeError("HTTP 503"))):
        assert await fetch_source(src, _config()) == []
    assert src.status == SourceStatus.DEGRADED
    assert "HTTP 503" in src.last_error
    assert "DEGRADED (RuntimeError: HTTP 503)" in source_issue(src, 0)


@pytest.mark.asyncio
async def test_sec_form4_non_200_raises():
    from marketmind.pipeline.insider_sources import fetch_form4_insider
    with patch("httpx.AsyncClient", return_value=_client(AsyncMock(return_value=_resp(403)))):
        with pytest.raises(RuntimeError, match="403"):
            await fetch_form4_insider()


@pytest.mark.asyncio
async def test_newsapi_without_key_is_failed_not_untested():
    src = Source("NewsAPI", SourceTier.RELIABLE, "https://newsapi.org/x?apiKey={API_KEY}", "api", 0.9)
    assert await fetch_source(src, _config()) == []
    assert src.status == SourceStatus.DEGRADED
    assert "key not configured" in src.last_error


@pytest.mark.asyncio
async def test_quiet_day_empty_result_is_working_not_broken():
    src = Source("Congress Trades", SourceTier.BEST_EFFORT, "", "congress_api", 0.2)
    with patch.object(scout, "fetch_congress_trades", AsyncMock(return_value=[])):
        assert await fetch_source(src, _config()) == []
    assert src.status == SourceStatus.WORKING and src.last_error is None


def test_zero_items_flag_respects_zero_is_normal():
    loud = Source("Feed", SourceTier.RELIABLE, "https://x", "rss", status=SourceStatus.WORKING)
    quiet = Source("GDELT", SourceTier.BEST_EFFORT, "https://x", "gdelt_events",
                   status=SourceStatus.WORKING, zero_is_normal=True)
    assert "URL may be broken" in source_issue(loud, 0)
    assert source_issue(quiet, 0) is None
    assert source_issue(loud, 3) is None
