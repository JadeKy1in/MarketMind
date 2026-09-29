"""gateway.crypto_signals: Coin Metrics / alternative.me / TFTC parsing, per-day cache,
rate-limit handling and the derived MVRV statistics. Offline (httpx.MockTransport)."""
import json

import httpx
import pytest

from marketmind.gateway import crypto_signals as cs

CM_PAGE_1 = {"data": [
    {"asset": "btc", "time": "2026-09-26T00:00:00.000000000Z", "CapMVRVCur": "1.5", "CapMrktCurUSD": "1500"},
    {"asset": "btc", "time": "2026-09-27T00:00:00.000000000Z", "CapMVRVCur": "bad", "CapMrktCurUSD": "1"},
], "next_page_url": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?next_page_token=x"}
CM_PAGE_2 = {"data": [
    {"asset": "btc", "time": "2026-09-28T00:00:00.000000000Z", "CapMVRVCur": "2.0", "CapMrktCurUSD": "2000"}]}
FNG = {"name": "Fear and Greed Index", "metadata": {"error": None}, "data": [
    {"value": "73", "value_classification": "Greed", "timestamp": "1790640000"},       # 2026-09-29
    {"value": "20", "value_classification": "Extreme Fear", "timestamp": "1790035200"},  # 2026-09-22
]}
ETF = {"license": "https://creativecommons.org/licenses/by/4.0/", "updatedThrough": "2026-09-28",
       "days": [{"date": "2026-09-25", "netFlowUsd": 134465169.1, "totalNetAssetsUsd": 1.08e11},
                {"date": "2026-09-28", "netFlowUsd": -31070566.4, "totalNetAssetsUsd": None},
                {"date": "2026-09-29", "netFlowUsd": None}]}


@pytest.fixture
def mock_http(monkeypatch, tmp_path):
    """Route requests to `handler`; cache under tmp_path; no rate-limit waits."""
    calls = []
    state = {"handler": None}

    def _h(request):
        calls.append(request)
        return state["handler"](request)
    monkeypatch.setattr(cs, "_TRANSPORT", httpx.MockTransport(_h))
    monkeypatch.setattr(cs, "CM_MIN_INTERVAL_S", 0.0)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return state, calls


@pytest.mark.asyncio
async def test_coinmetrics_pages_and_skips_bad_rows(mock_http):
    state, calls = mock_http
    state["handler"] = lambda r: httpx.Response(200, json=CM_PAGE_2 if "next_page_token" in str(r.url)
                                                else CM_PAGE_1)
    s = await cs.mvrv_history("BTC", today="2026-09-29")
    assert [p.date for p in s.points] == ["2026-09-26", "2026-09-28"] and s.origin == "live"
    assert s.points[-1].realized_cap == pytest.approx(1000.0)
    first = calls[0].url.params
    assert first["assets"] == "btc" and first["metrics"] == "CapMVRVCur,CapMrktCurUSD"
    assert first["paging_from"] == "start" and len(calls) == 2


@pytest.mark.asyncio
async def test_coinmetrics_429_retried_once_and_403_raises(mock_http, monkeypatch):
    state, calls = mock_http
    slept = []

    async def _sleep(s):
        slept.append(s)
    monkeypatch.setattr(cs.asyncio, "sleep", _sleep)
    seq = iter([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=CM_PAGE_2)])
    state["handler"] = lambda r: next(seq)
    s = await cs.mvrv_history("eth", today="2026-09-29")
    assert len(s.points) == 1 and 2.0 in slept
    state["handler"] = lambda r: httpx.Response(403, json={"error": {
        "type": "forbidden", "message": "Requested metric 'CapRealUSD' is not available"}})
    with pytest.raises(cs.CryptoDataUnavailable, match="CapRealUSD"):
        await cs.mvrv_history("btc", today="2026-09-29")


@pytest.mark.asyncio
async def test_cache_once_per_day_and_labelled_stale_fallback(mock_http, tmp_path):
    state, calls = mock_http
    state["handler"] = lambda r: httpx.Response(200, json=FNG)
    a = await cs.fear_greed_history(today="2026-09-29")
    b = await cs.fear_greed_history(today="2026-09-29")
    assert a.origin == "live" and b.origin == "cache" and len(calls) == 1
    assert json.loads((tmp_path / "crypto_signals" / "fear_greed.json").read_text())["fetched_on"] == "2026-09-29"
    state["handler"] = lambda r: httpx.Response(503)
    c = await cs.fear_greed_history(today="2026-09-30")
    assert c.origin == "stale-cache" and c.fetched_on == "2026-09-29" and c.points == a.points
    (tmp_path / "crypto_signals" / "fear_greed.json").unlink()
    with pytest.raises(cs.CryptoDataUnavailable):
        await cs.fear_greed_history(today="2026-09-30")


@pytest.mark.asyncio
async def test_fear_greed_and_etf_parsing(mock_http):
    state, _ = mock_http
    state["handler"] = lambda r: httpx.Response(200, json=ETF if "tftc" in r.url.host else FNG)
    f = await cs.fear_greed_history(today="2026-09-29")
    assert [(p.date, p.value, p.label) for p in f.points] == [
        ("2026-09-22", 20, "Extreme Fear"), ("2026-09-29", 73, "Greed")]
    e = await cs.etf_flow_history(today="2026-09-29")
    assert [d.date for d in e.points] == ["2026-09-25", "2026-09-28"]      # null flow skipped
    assert e.points[-1].net_flow_usd < 0 and e.points[-1].total_net_assets_usd is None
    assert e.meta["updated_through"] == "2026-09-28" and "CC BY 4.0" in e.meta["attribution"]
    with pytest.raises(ValueError):
        cs.parse_fng({"metadata": {"error": "boom"}, "data": []})


def test_expanding_statistics_have_no_look_ahead():
    assert cs.expanding_percentiles([3, 1, 2, 5]) == [100.0, 50.0, pytest.approx(200 / 3), 100.0]
    pts = [cs.MvrvPoint(f"2026-01-{i + 1:02d}", 1.0 + i / 10, 100.0 + i) for i in range(6)]
    z = cs.expanding_mvrv_z(pts, min_days=3)
    assert z[:2] == [None, None]
    z_trunc = cs.expanding_mvrv_z(pts[:4], min_days=3)
    assert z[:4] == z_trunc                                   # later days never change earlier z
    last = pts[-1]
    mcs = [p.market_cap for p in pts]
    mean = sum(mcs) / 6
    sd = (sum((m - mean) ** 2 for m in mcs) / 6) ** 0.5
    assert z[-1] == pytest.approx((last.market_cap - last.realized_cap) / sd)
    assert cs.point_on_or_before(pts, "2026-01-03").date == "2026-01-03"
    assert cs.point_on_or_before(pts, "2025-12-31") is None
