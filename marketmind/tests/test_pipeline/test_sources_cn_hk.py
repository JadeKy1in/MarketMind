"""Offline tests for the China / Hong Kong company-announcement fetchers (Group D).

Fixtures are small synthetic payloads shaped like the live responses recorded 2026-09-27.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.pipeline import sources_cn_hk as m
from marketmind.pipeline.scout import NewsItem

SRC = SimpleNamespace(name="Test CN/HK", tier=1, reliability=0.9)
CFG = SimpleNamespace(proxy_url="")


def _hk(news_id, ltxt, code="01936", name="RITAMIX", title="ANNOUNCEMENT", rel="25/09/2026 21:56"):
    return {"newsId": news_id, "lTxt": ltxt, "sTxt": ltxt, "title": title, "ext": "pdf", "size": "90KB",
            "webPath": f"/listedco/listconews/sehk/2026/0925/{news_id}.pdf", "market": "SEHK", "multi": 0,
            "stock": [{"sc": code, "sn": name}], "relTime": rel, "t1Code": "10000", "t2Code": "NaN",
            "dod": "N", "dodPath": "NaN"}


def _cn(ann_id, title, code="600095", name="湘财股份", ts=1790265600000):
    return {"id": None, "secCode": code, "secName": name, "orgId": f"gssh0{code}", "announcementId": str(ann_id),
            "announcementTitle": title, "announcementTime": ts,
            "adjunctUrl": f"finalpage/2026-09-25/{ann_id}.PDF", "adjunctSize": 153, "adjunctType": "PDF",
            "columnId": "250401", "pageColumn": "SHZB", "announcementType": "01010503"}


def _resp(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            str(status), request=MagicMock(), response=MagicMock()))
    return resp


def _client(resp):
    client = AsyncMock()
    client.get.return_value = resp
    client.post.return_value = resp
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ── HKEXnews ────────────────────────────────────────────────────────────────

def test_hkex_filter_keeps_high_signal_and_watchlist_drops_noise():
    recs = [
        _hk(1, "Next Day Disclosure Returns - [Share Buyback]"),                       # non-watchlist buyback: drop
        _hk(2, "Next Day Disclosure Returns - [Share Buyback]", code="00700", name="TENCENT"),  # keep
        _hk(3, "Announcements and Notices - [Profit Warning / Inside Information]"),   # keep, prio 0
        _hk(4, "Proxy Forms", code="00700", name="TENCENT"),                           # boilerplate: drop
        _hk(5, "Circulars - [Other]"),                                                 # drop
        _hk(6, "Announcements and Notices - [Inside Information]", code="09988", name="BABA-W"),  # watchlist prio -1
        _hk(7, "Announcements and Notices - [Final Results]"),                         # keep, prio 1
    ]
    out = [r["newsId"] for r in m.select_hkex_records(recs)]
    assert out == [6, 3, 7, 2]


def test_hkex_cap():
    recs = [_hk(i, "Announcements and Notices - [Inside Information]") for i in range(50)]
    out = m.select_hkex_records(recs)
    assert len(out) == m.MAX_HKEX == 20
    assert [r["newsId"] for r in out] == list(range(20))  # feed order (newest first) preserved


def test_hkex_record_to_newsitem():
    rec = _hk(12347511, "Announcements and Notices - [Inside Information]", code="00700", name="TENCENT",
              title="INSIDE INFORMATION\nARBITRATION AWARD")
    item = m.hkex_record_to_newsitem(rec, SRC)
    assert isinstance(item, NewsItem)
    assert item.title == "HKEX: TENCENT (00700.HK) - INSIDE INFORMATION ARBITRATION AWARD"
    assert item.url == "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0925/12347511.pdf"
    assert item.published_at == "2026-09-25T21:56:00+08:00"
    assert "Watchlist: Tencent" in item.summary
    assert item.source_reliability == 0.9
    assert m.hkex_record_to_newsitem({**rec, "webPath": ""}, SRC) is None


@pytest.mark.asyncio
async def test_fetch_hkex_parses_and_uses_one_request():
    payload = {"genDate": 1790471701827, "maxNumOfFile": 7, "newsInfoLst": [
        _hk(1, "Announcements and Notices - [Suspension]"), _hk(2, "Circulars - [Other]")]}
    client = _client(_resp(payload))
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=client):
        items = await m.fetch_hkex_announcements(SRC, CFG)
    assert len(items) == 1 and "HKEX:" in items[0].title
    assert client.get.await_count == 1
    assert client.get.call_args.args[0] == m.HKEX_LATEST_URL


@pytest.mark.asyncio
async def test_fetch_hkex_raises_on_http_error():
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=_client(_resp({}, 503))):
        with pytest.raises(httpx.HTTPStatusError):
            await m.fetch_hkex_announcements(SRC, CFG)


@pytest.mark.asyncio
async def test_fetch_hkex_raises_on_bad_shape():
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=_client(_resp({"x": 1}))):
        with pytest.raises(ValueError):
            await m.fetch_hkex_announcements(SRC, CFG)


def test_proxy_passed_through():
    assert m._client_kwargs(SimpleNamespace(proxy_url="http://127.0.0.1:7890"))["proxy"] == "http://127.0.0.1:7890"
    assert "proxy" not in m._client_kwargs(CFG)
    assert m._client_kwargs(None)["timeout"] == m.HTTP_TIMEOUT


# ── CNINFO ──────────────────────────────────────────────────────────────────

def test_cninfo_select_ranks_dedups_and_drops_attachments():
    recs = [
        _cn(1, "股票交易异常波动公告", ts=1790265600000),                        # prio 3
        _cn(2, "关于收到中国证券监督管理委员会<em>立案</em>告知书的公告", ts=1790006400000),  # prio 0
        _cn(3, "2026年前三季度业绩预告", ts=1790265600000),                      # prio 1
        _cn(3, "2026年前三季度业绩预告", ts=1790265600000),                      # duplicate id
        _cn(4, "本次重大资产重组涉及的拟购买资产审计报告"),                        # attachment: drop
        _cn(5, "关于董事会换届选举的公告", ts=1790265600000),                     # prio 9
    ]
    out = [r["announcementId"] for r in m.select_cninfo_records(recs)]
    assert out == ["2", "3", "1", "5"]


def test_cninfo_cap():
    recs = [_cn(i, "关于股票交易风险提示性公告") for i in range(30)]
    assert len(m.select_cninfo_records(recs)) == m.MAX_CNINFO == 20


def test_cninfo_record_to_newsitem():
    item = m.cninfo_record_to_newsitem(_cn(1225583316, "关于<em>重组</em>进展的公告"), SRC)
    assert item.title == "CNINFO 湘财股份(600095): 关于重组进展的公告"
    assert item.url == "https://static.cninfo.com.cn/finalpage/2026-09-25/1225583316.PDF"
    assert item.published_at == "2026-09-25T00:00:00+08:00"
    assert m.cninfo_record_to_newsitem({**_cn(1, "x"), "adjunctUrl": None}, SRC) is None


def test_build_cninfo_form():
    form = m.build_cninfo_form(categories=("category_a", "category_b"), today=datetime(2026, 9, 27))
    assert form["category"] == "category_a;category_b;"
    assert form["seDate"] == "2026-09-23~2026-09-27"
    assert form["pageSize"] == "30" and form["isHLtitle"] == "false" and form["searchkey"] == ""
    assert m.build_cninfo_form(searchkey="重大资产重组")["searchkey"] == "重大资产重组"


@pytest.mark.asyncio
async def test_fetch_cninfo_risk_posts_categories():
    payload = {"announcements": [_cn(1, "关于公司股票可能被终止上市的风险提示公告")], "totalAnnouncement": 1}
    client = _client(_resp(payload))
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=client):
        items = await m.fetch_cninfo_risk_announcements(SRC, CFG)
    assert len(items) == 1
    assert client.post.await_count == 1
    form = client.post.call_args.kwargs["data"]
    assert "category_yjygjxz_szsh;" in form["category"] and "category_tbclts_szsh;" in form["category"]


@pytest.mark.asyncio
async def test_fetch_cninfo_restructuring_uses_searchkey_and_handles_null():
    client = _client(_resp({"announcements": None, "totalAnnouncement": 0}))
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=client):
        assert await m.fetch_cninfo_restructuring(SRC, CFG) == []
    assert client.post.call_args.kwargs["data"]["searchkey"] == "重大资产重组"


@pytest.mark.asyncio
async def test_fetch_cninfo_raises_on_gateway_timeout():
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=_client(_resp({}, 504))):
        with pytest.raises(httpx.HTTPStatusError):
            await m.fetch_cninfo_risk_announcements(SRC, CFG)


@pytest.mark.asyncio
async def test_fetch_cninfo_raises_on_non_json():
    resp = _resp({})
    resp.json.side_effect = ValueError("Expecting value")
    with patch("marketmind.pipeline.sources_cn_hk.httpx.AsyncClient", return_value=_client(resp)):
        with pytest.raises(ValueError):
            await m.fetch_cninfo_risk_announcements(SRC, CFG)
