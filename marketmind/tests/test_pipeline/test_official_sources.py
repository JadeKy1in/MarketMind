"""Offline tests for the 2026-09-27 source registry changes and official-data fetchers."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.config.source_authority import (
    SOURCES, Source, SourceStatus, SourceTier, get_working_sources,
)
from marketmind.pipeline.official_data_sources import (
    auction_to_newsitem, fetch_nyfed_reference_rates, fetch_treasury_auctions,
    nyfed_rates_to_newsitem,
)
from marketmind.pipeline.scout import NewsItem, _fetch_sec_edgar, fetch_source

NEW_SOURCES = {
    "Federal Reserve Press": "rss",
    "Federal Reserve Speeches": "rss",
    "US Treasury Press": "rss",
    "OFAC Recent Actions": "rss",
    "USTR Press": "rss",
    "Federal Register (Trade & Sanctions)": "rss",
    "SEC EDGAR 8-K": "sec_api",
    "US Treasury Auctions": "fiscaldata_auctions",
    "NY Fed Reference Rates": "nyfed_rates",
    "Decrypt": "rss",
    "Caixin Latest (via RSSHub)": "rss",
    "Yicai Brief (via RSSHub)": "rss",
}


def _by_name() -> dict[str, Source]:
    return {s.name: s for s in SOURCES}


def _mock_client(resp: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = resp
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _json_resp(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            f"{status}", request=MagicMock(), response=MagicMock()))
    return resp


# ── Registry ────────────────────────────────────────────────────────────────

def test_source_names_unique():
    names = [s.name for s in SOURCES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("name,feed_type", sorted(NEW_SOURCES.items()))
def test_new_sources_registered_and_fetched(name, feed_type):
    src = _by_name()[name]
    assert src.feed_type == feed_type
    assert src.url and src.url.startswith("https://")
    assert not src.requires_auth
    # UNTESTED sources are included by fetch_all_sources alongside WORKING/DEGRADED ones.
    assert src.status in (SourceStatus.UNTESTED, SourceStatus.WORKING, SourceStatus.DEGRADED)


def test_sec_8k_registry_entry_matches_handler():
    src = _by_name()["SEC EDGAR 8-K"]
    assert src.feed_type == "sec_api"
    assert src.tier == SourceTier.PRIMARY


def test_status_corrections():
    by = _by_name()
    # Congress: capitoltrades scraper replaced by House Clerk PTR filings (verified 2026-09-27).
    assert by["Congress Trades"].status == SourceStatus.WORKING
    assert "disclosures-clerk.house.gov" in by["Congress Trades"].url
    assert by["Euronews Economy"].status == SourceStatus.DEGRADED
    assert by["Euronews Economy"].is_available
    # Xinhua feed frozen since 2018: documented but not fetched.
    assert by["Xinhua Finance"].status == SourceStatus.DEAD
    assert by["Xinhua Finance"] not in get_working_sources()


# ── Scout dispatch ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_source_dispatches_sec_api():
    src = Source("SEC EDGAR 8-K", SourceTier.PRIMARY, "https://www.sec.gov/x", "sec_api", 0.9)
    item = NewsItem("id1", "8-K - ACME", "https://sec.gov/a", "SEC EDGAR 8-K", 1, "2026-09-27", "s")
    with patch("marketmind.pipeline.scout._fetch_sec_edgar", AsyncMock(return_value=[item])) as m:
        items = await fetch_source(src, MagicMock())
    m.assert_awaited_once()
    assert items == [item]
    assert src.status == SourceStatus.WORKING


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::DeprecationWarning:feedparser")
async def test_fetch_sec_edgar_sends_sec_user_agent_and_parses_atom():
    atom = """<?xml version="1.0" encoding="ISO-8859-1" ?>
    <feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>
    <entry><title>8-K - ACME CORP (0000000001) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1/a.htm"/>
    <summary type="html">Item 2.02 Results of Operations</summary>
    <updated>2026-09-25T17:00:00-04:00</updated></entry></feed>"""
    resp = MagicMock(status_code=200, text=atom)
    client = _mock_client(resp)
    with patch("httpx.AsyncClient", return_value=client):
        items = await _fetch_sec_edgar()
    assert len(items) == 1
    assert items[0].source_name == "SEC EDGAR 8-K"
    assert items[0].title.startswith("8-K - ACME")
    ua = client.get.call_args.kwargs["headers"]["User-Agent"]
    assert "@" in ua  # SEC requires "Org contact@email" style User-Agent


@pytest.mark.asyncio
async def test_fetch_source_official_api_non_200_degrades():
    src = Source("US Treasury Auctions", SourceTier.PRIMARY, "https://api.x", "fiscaldata_auctions", 0.95)
    client = _mock_client(_json_resp({}, status=503))
    with patch("httpx.AsyncClient", return_value=client):
        items = await fetch_source(src, MagicMock(proxy_url=""))
    assert items == []
    assert src.status == SourceStatus.DEGRADED
    assert src.consecutive_failures == 1


# ── FiscalData auctions ─────────────────────────────────────────────────────

_AUCTION_DONE = {
    "cusip": "91282CAA1", "security_type": "Note", "security_term": "7-Year",
    "auction_date": "2026-09-24", "high_yield": "4.0850", "high_investment_rate": "null",
    "bid_to_cover_ratio": "2.420000", "offering_amt": "44000000000", "reopening": "No",
    "indirect_bidder_accepted": "30000000000", "direct_bidder_accepted": "null",
}
_AUCTION_BILL = {
    "cusip": "912797AA1", "security_type": "Bill", "security_term": "13-Week",
    "auction_date": "2026-09-21", "high_yield": "null", "high_investment_rate": "3.900",
    "bid_to_cover_ratio": "2.9", "offering_amt": "80000000000", "reopening": "Yes",
}
_AUCTION_UPCOMING = {
    "cusip": "912797WJ2", "security_type": "Bill", "security_term": "52-Week",
    "auction_date": "2026-09-29", "high_yield": "null", "bid_to_cover_ratio": "null",
}
_AUCTION_SRC = Source("US Treasury Auctions", SourceTier.PRIMARY, "https://api.x", "fiscaldata_auctions", 0.95)


def test_auction_to_newsitem_completed_note():
    item = auction_to_newsitem(_AUCTION_DONE, _AUCTION_SRC)
    assert item.title == ("US Treasury 7-Year Note auction: high yield 4.085%, "
                          "bid-to-cover 2.42 (2026-09-24)")
    assert "$44B offered" in item.summary
    assert "indirect accepted $30.0B" in item.summary
    assert "; direct accepted" not in item.summary
    assert item.published_at == "2026-09-24"
    assert "91282CAA1" in item.url
    assert item.source_tier == 1 and item.source_reliability == 0.95
    assert len(item.id) == 16


def test_auction_to_newsitem_bill_uses_investment_rate():
    item = auction_to_newsitem(_AUCTION_BILL, _AUCTION_SRC)
    assert "13-Week Bill auction (reopening): high investment rate 3.9%" in item.title


def test_auction_to_newsitem_skips_upcoming():
    assert auction_to_newsitem(_AUCTION_UPCOMING, _AUCTION_SRC) is None


@pytest.mark.asyncio
async def test_fetch_treasury_auctions_filters_and_orders():
    payload = {"data": [_AUCTION_UPCOMING, _AUCTION_DONE, _AUCTION_BILL]}
    client = _mock_client(_json_resp(payload))
    with patch("httpx.AsyncClient", return_value=client):
        items = await fetch_treasury_auctions(_AUCTION_SRC, MagicMock(proxy_url=""))
    assert [i.published_at for i in items] == ["2026-09-24", "2026-09-21"]
    assert client.get.call_args.kwargs["params"]["sort"] == "-auction_date"


# ── NY Fed reference rates ──────────────────────────────────────────────────

_NYFED = {"refRates": [
    {"effectiveDate": "2026-09-25", "type": "SOFRAI", "index": 1.26},
    {"effectiveDate": "2026-09-24", "type": "EFFR", "percentRate": 3.88, "percentPercentile1": 3.85,
     "percentPercentile99": 3.94, "targetRateFrom": 3.75, "targetRateTo": 4.0, "volumeInBillions": 105},
    {"effectiveDate": "2026-09-24", "type": "SOFR", "percentRate": 3.88, "percentPercentile1": 3.81,
     "percentPercentile99": 3.96, "volumeInBillions": 2990},
]}
_NYFED_SRC = Source("NY Fed Reference Rates", SourceTier.PRIMARY, "https://x", "nyfed_rates", 0.95)


def test_nyfed_rates_single_summary_item():
    item = nyfed_rates_to_newsitem(_NYFED["refRates"], _NYFED_SRC)
    assert item.title == "NY Fed reference rates 2026-09-24: SOFR 3.88%, EFFR 3.88%"
    assert "FOMC target range 3.75-4.0%" in item.summary
    assert "volume $2990B" in item.summary
    assert item.url.endswith("?date=2026-09-24")


def test_nyfed_rates_empty_returns_none():
    assert nyfed_rates_to_newsitem([{"type": "SOFRAI", "index": 1.2}], _NYFED_SRC) is None


@pytest.mark.asyncio
async def test_fetch_source_nyfed_rates_marks_working():
    src = Source("NY Fed Reference Rates", SourceTier.PRIMARY, "https://x", "nyfed_rates", 0.95)
    client = _mock_client(_json_resp(_NYFED))
    with patch("httpx.AsyncClient", return_value=client):
        items = await fetch_source(src, MagicMock(proxy_url=""))
    assert len(items) == 1
    assert src.status == SourceStatus.WORKING


# ── RSS title hygiene ───────────────────────────────────────────────────────

def test_from_entry_strips_html_from_title():
    src = Source("Yicai Brief (via RSSHub)", SourceTier.FRAGILE, "https://x")
    item = NewsItem.from_entry({"title": "<b>Headline |</b> body text", "link": "https://y/1"}, src)
    assert item.title == "Headline | body text"
