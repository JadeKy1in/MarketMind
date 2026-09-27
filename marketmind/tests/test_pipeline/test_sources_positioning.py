"""Offline tests for pipeline/sources_positioning.py (httpx.MockTransport, no network)."""
import json
from types import SimpleNamespace

import httpx
import pytest

from marketmind.config.source_authority import Source, SourceTier
from marketmind.pipeline import sources_positioning as sp


def _src(name="Test Source", reliability=0.9):
    return Source(name, SourceTier.PRIMARY, "https://example.test", "x", reliability, 1.0)


CFG = SimpleNamespace(proxy_url="")


def _patch(monkeypatch, handler):
    """Route every client created by the module through ``handler``; record requests."""
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(sp, "_make_client",
                        lambda config: httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return seen


# ── Pure calculations ───────────────────────────────────────────────────────

def test_percentile_rank_midrank():
    assert sp.percentile_rank([1, 2, 3, 4], 4) == pytest.approx(87.5)
    assert sp.percentile_rank([1, 2, 3, 4], 1) == pytest.approx(12.5)
    assert sp.percentile_rank([5, 5, 5], 5) == pytest.approx(50.0)
    assert sp.percentile_rank([], 1) is None


def test_compact_formatting():
    assert sp._k(212345) == "+212.3k"
    assert sp._k(-950) == "-950"
    assert sp._k(12000, signed=False) == "12.0k"
    assert sp._usd(4.81e9) == "$4.81B"
    assert sp._annualised(0.0001, 8) == pytest.approx(10.95)
    assert sp._annualised(0.0000125, 1) == pytest.approx(10.95)


# ── CFTC ────────────────────────────────────────────────────────────────────

def test_cot_stats_change_and_percentile():
    series = [(f"2026-01-{d:02d}", float(n), 0.0, 0.0) for d, n in enumerate(range(10, 40), start=1)]
    st = sp.cot_stats(series)
    assert st["net"] == 39 and st["change"] == 1
    assert st["percentile"] == pytest.approx(100 * 29.5 / 30)
    short = sp.cot_stats(series[:5])
    assert short["percentile"] is None  # below CFTC_MIN_HISTORY


def test_cot_series_filters_code_and_sorts():
    rows = [
        {"cftc_contract_market_code": "067651", "report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000",
         "noncomm_positions_long_all": "300", "noncomm_positions_short_all": "100"},
        {"cftc_contract_market_code": "067651", "report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000",
         "noncomm_positions_long_all": "250", "noncomm_positions_short_all": "100"},
        {"cftc_contract_market_code": "999999", "report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000",
         "noncomm_positions_long_all": "1", "noncomm_positions_short_all": "1"},
    ]
    s = sp.cot_series(rows, "067651", "noncomm_positions_long_all", "noncomm_positions_short_all")
    assert [x[0] for x in s] == ["2026-09-15", "2026-09-22"]
    assert [x[1] for x in s] == [150, 200]


def _dated_rows(code, nets, long_key, short_key):
    """Weekly rows ending 2026-09-22, oldest first in ``nets``."""
    from datetime import date, timedelta
    end = date(2026, 9, 22)
    out = []
    for i, net in enumerate(reversed(nets)):
        d = end - timedelta(weeks=i)
        out.append({"cftc_contract_market_code": code, "report_date_as_yyyy_mm_dd": f"{d}T00:00:00.000",
                    long_key: str(200000 + net), short_key: "200000"})
    return out


@pytest.mark.asyncio
async def test_fetch_cftc_cot_groups_and_titles(monkeypatch):
    nets = list(range(0, 40000, 1000))  # 40 weeks, rising -> latest is the max
    legacy = _dated_rows("067651", nets, "noncomm_positions_long_all", "noncomm_positions_short_all")
    tff = _dated_rows("13874A", [-n for n in nets], "lev_money_positions_long", "lev_money_positions_short")

    def handler(request):
        body = legacy if "6dca-aqww" in request.url.path else tff
        return httpx.Response(200, json=body)

    seen = _patch(monkeypatch, handler)
    items = await sp.fetch_cftc_cot(_src("CFTC COT"), CFG)
    assert len(seen) == 2
    assert "cftc_contract_market_code in(" in seen[0].url.params["$where"]
    assert len(items) == 2  # energy + financials only (other contracts absent)
    energy, fin = items
    assert energy.title.startswith("CFTC COT (week to 2026-09-22) energy, non-commercial net: WTI crude +39.0k (+1.0k w/w")
    assert "3y pct 99%" in energy.title  # 39.5/40 mid-rank -> 98.75 -> '99%'
    assert "leveraged funds" in fin.title and "S&P 500 e-mini -39.0k (-1.0k w/w" in fin.title
    assert energy.published_at == "2026-09-22"
    assert energy.source_name == "CFTC COT"
    assert len(energy.summary) <= 500


@pytest.mark.asyncio
async def test_fetch_cftc_cot_raises_on_http_error(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(503, text="down"))
    with pytest.raises(httpx.HTTPStatusError):
        await sp.fetch_cftc_cot(_src(), CFG)


@pytest.mark.asyncio
async def test_fetch_cftc_cot_raises_when_empty(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError):
        await sp.fetch_cftc_cot(_src(), CFG)


# ── EIA ─────────────────────────────────────────────────────────────────────

EIA_CSV = "\n".join([
    '"STUB_1","9/18/26","9/11/26","Difference","Percent Change","9/19/25","Difference","Percent Change"',
    '"Crude Oil","710.950","708.386","2.564","0.400","820.712","-109.762","-13.400"',
    '"Commercial (Excluding SPR)","426.398","423.429","2.969","0.700","414.754","11.644","2.800"',
    '"Strategic Petroleum Reserve (SPR)","284.552","284.957","-0.405","-0.100","405.958","-121.406","-29.900"',
    '"Total Motor Gasoline","206.046","207.732","-1.686","-0.800","216.569","-10.524","-4.900"',
    '"Distillate Fuel Oil","107.431","107.859","-0.428","-0.400","122.999","-15.568","-12.700"',
    '"Total Stocks (Including SPR)","1,535.908","1,536.205","-0.297","0.000","1,600.0","-64.1","-4.0"',
    '"STUB_1","STUB_2","9/18/26","9/11/26","Difference","9/19/25","Difference","x"',
    '"Crude Oil Supply ","(17)   Crude Oil Input to Refineries","16,811","17,330","-519","16,900","-89","x"',
])


def test_parse_eia_table1():
    p = sp.parse_eia_table1(EIA_CSV)
    assert p["week"] == "2026-09-18" and p["week_prev"] == "2026-09-11"
    crude = p["stocks"]["Commercial (Excluding SPR)"]
    assert crude["value"] == pytest.approx(426.398) and crude["wow"] == pytest.approx(2.969)
    assert crude["yoy"] == pytest.approx(11.644)
    assert p["refinery_input"] == {"value": 16811.0, "wow": -519.0}


def test_parse_eia_table1_bad_header():
    with pytest.raises(ValueError):
        sp.parse_eia_table1("foo,bar\n1,2")


@pytest.mark.asyncio
async def test_fetch_eia_petroleum(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(200, content=("﻿" + EIA_CSV).encode("utf-8")))
    [item] = await sp.fetch_eia_petroleum(_src("EIA"), CFG)
    assert item.title == ("EIA weekly petroleum (week to 2026-09-18): commercial crude 426.4M bbl (+3.0M w/w), "
                          "gasoline 206.0M bbl (-1.7M w/w), distillate 107.4M bbl (-0.4M w/w)")
    assert "SPR 284.6M bbl (-0.4M w/w)" in item.summary
    assert "refinery crude input 16,811 kb/d (-519 w/w)" in item.summary


NGS = {
    "release_date": "2026-Sep-24 00:00:00",
    "series": [
        {"name": "total lower 48 states", "data": [["2026-09-18", 3351], ["2026-09-11", 3298]],
         "calculated": {"5yr-avg": 3256, "net_change": 53, "implied_flow": 53,
                        "pct-change_yrago": -4.2, "pct-chg_5yr-avg": 2.9}},
        {"name": "east region", "data": [["2026-09-18", 815]],
         "calculated": {"net_change": 20, "pct-chg_5yr-avg": 5.2}},
    ],
}


@pytest.mark.asyncio
async def test_fetch_eia_natgas_with_bom(monkeypatch):
    body = ("﻿" + json.dumps(NGS)).encode("utf-8")
    _patch(monkeypatch, lambda r: httpx.Response(200, content=body))
    [item] = await sp.fetch_eia_natgas_storage(_src("EIA NG"), CFG)
    assert item.title == ("EIA natgas storage (week to 2026-09-18): Lower 48 3,351 Bcf, +53 Bcf w/w, "
                          "+2.9% vs 5-yr avg (3,256), -4.2% y/y")
    assert "east 815 (+20, +5.2% vs 5y)" in item.summary
    assert item.published_at == "2026-09-18"


def test_eia_natgas_missing_series_raises():
    with pytest.raises(ValueError):
        sp.eia_natgas_to_newsitem({"series": []}, _src())


# ── Cboe ────────────────────────────────────────────────────────────────────

def _vix_csv(closes):
    from datetime import date, timedelta
    start = date(2025, 1, 1)
    lines = ["DATE,OPEN,HIGH,LOW,CLOSE"]
    for i, c in enumerate(closes):
        d = start + timedelta(days=i)
        lines.append(f"{d:%m/%d/%Y},{c},{c},{c},{c}")
    return "\n".join(lines)


def test_vix_stats():
    closes = [10.0 + i * 0.1 for i in range(300)] + [12.0]
    hist = sp.parse_vix_history(_vix_csv(closes))
    item = sp.vix_to_newsitem(hist, _src("VIX"))
    last = hist[-1][0]
    assert item.published_at == last
    d1 = 12.0 - closes[-2]
    d5 = 12.0 - closes[-6]
    assert f"12.00 ({d1:+.2f} d/d, {d5:+.2f} over 5 sessions)" in item.title
    window = [c for _, c in hist[-252:]]
    assert f"1y percentile {sp.percentile_rank(window, 12.0):.0f}%" in item.title


@pytest.mark.asyncio
async def test_fetch_cboe_vix_http_error(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        await sp.fetch_cboe_vix(_src(), CFG)


def _spx_payload():
    opts = []
    # 30-DTE expiry (2026-10-26 from 2026-09-26): strikes with a delta ladder.
    for i in range(12):
        k = 7000 + i * 100
        opts.append({"option": f"SPXW261026C0{k}000", "volume": 10, "open_interest": 100,
                     "delta": round(0.9 - i * 0.075, 3), "iv": 0.10})
        opts.append({"option": f"SPXW261026P0{k}000", "volume": 20, "open_interest": 150,
                     "delta": round(-0.1 - i * 0.075, 3), "iv": 0.14})
    opts.append({"option": "SPX261016C00200000", "volume": 5, "open_interest": 50, "delta": 1.0, "iv": 5.0})
    opts.append({"option": "garbage", "volume": 1e9, "open_interest": 1e9})
    return {"timestamp": "2026-09-26 22:25:13",
            "data": {"current_price": 7743.41, "iv30": 11.6, "last_trade_time": "2026-09-25T16:14:59",
                     "options": opts}}


def test_spx_chain_stats():
    st = sp.spx_chain_stats(_spx_payload())
    assert st["asof"] == "2026-09-25"
    assert st["call_volume"] == 125 and st["put_volume"] == 240
    assert st["pc_volume"] == pytest.approx(240 / 125)
    assert st["pc_oi"] == pytest.approx(1800 / 1250)
    assert st["skew"]["dte"] == 30 and st["skew"]["rr"] == pytest.approx(4.0)


def test_spx_chain_empty_raises():
    with pytest.raises(ValueError):
        sp.spx_chain_stats({"data": {"options": []}})


@pytest.mark.asyncio
async def test_fetch_cboe_spx_options(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(200, json=_spx_payload()))
    [item] = await sp.fetch_cboe_spx_options(_src("SPX"), CFG)
    assert item.title == ("Cboe SPX options 2026-09-25: put/call volume 1.92, put/call OI 1.44, "
                          "25d put-call skew +4.0 vol pts (30d)")
    assert "SPX IV30 11.60%" in item.summary


# ── Crypto ──────────────────────────────────────────────────────────────────

def test_dvol_stats():
    day = 86_400_000
    candles = [[i * day, 0, 0, 0, 40.0 + i] for i in range(20)]
    st = sp.dvol_stats(candles)
    assert st["level"] == 59 and st["d1"] == 1 and st["d7"] == 7
    assert st["percentile"] == pytest.approx(100 * 19.5 / 20)
    with pytest.raises(ValueError):
        sp.dvol_stats(candles[:3])


@pytest.mark.asyncio
async def test_fetch_deribit_dvol(monkeypatch):
    day = 86_400_000

    def handler(request):
        base = 30.0 if request.url.params["currency"] == "BTC" else 50.0
        data = [[1789000000000 + i * day, 0, 0, 0, base + i * 0.5] for i in range(30)]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"data": data, "continuation": None}})

    seen = _patch(monkeypatch, handler)
    [item] = await sp.fetch_deribit_dvol(_src("Deribit"), CFG)
    assert [r.url.params["currency"] for r in seen] == ["BTC", "ETH"]
    assert item.title.startswith("Deribit DVOL implied vol: BTC 44.5 (+0.5 d/d, +3.5 w/w, 1y pct 98%); ETH 64.5")


@pytest.mark.asyncio
async def test_fetch_bybit_derivs(monkeypatch):
    tickers = {"retCode": 0, "result": {"list": [
        {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingIntervalHour": "8",
         "openInterest": "50000", "openInterestValue": "4000000000", "price24hPcnt": "0.01"},
        {"symbol": "ETHUSDT", "fundingRate": "-0.00004", "fundingIntervalHour": "4",
         "openInterest": "800000", "openInterestValue": "2000000000", "price24hPcnt": "-0.02"},
    ]}}

    def handler(request):
        if request.url.path.endswith("/tickers"):
            return httpx.Response(200, json=tickers)
        sym = request.url.params["symbol"]
        if sym == "SOLUSDT":
            return httpx.Response(200, json={"retCode": 0, "result": {"list": []}})
        hist = [{"openInterest": "110"}] + [{"openInterest": "100"}] * 24
        return httpx.Response(200, json={"retCode": 0, "result": {"list": hist}})

    _patch(monkeypatch, handler)
    [item] = await sp.fetch_bybit_derivs(_src("Bybit"), CFG)
    assert item.title == ("Bybit perps: BTC funding +21.9% ann., OI $4.00B (+10.0% 24h); "
                          "ETH funding -8.8% ann., OI $2.00B (+10.0% 24h)")


@pytest.mark.asyncio
async def test_fetch_bybit_retcode_error_raises(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(200, json={"retCode": 10001, "retMsg": "bad"}))
    with pytest.raises(ValueError):
        await sp.fetch_bybit_derivs(_src(), CFG)


@pytest.mark.asyncio
async def test_fetch_hyperliquid_derivs(monkeypatch):
    payload = [{"universe": [{"name": "BTC"}, {"name": "ATOM"}, {"name": "ETH"}]},
               [{"funding": "0.0000125", "openInterest": "1000", "markPx": "80000", "prevDayPx": "79000",
                 "premium": "-0.0002"},
                {"funding": "0.0", "openInterest": "1", "markPx": "1"},
                {"funding": "-0.00001", "openInterest": "10000", "markPx": "2500", "prevDayPx": "2500"}]]
    seen = _patch(monkeypatch, lambda r: httpx.Response(200, json=payload))
    [item] = await sp.fetch_hyperliquid_derivs(_src("HL"), CFG)
    assert seen[0].method == "POST" and json.loads(seen[0].content) == {"type": "metaAndAssetCtxs"}
    assert item.title == "Hyperliquid perps: BTC funding +11.0% ann., OI $80M; ETH funding -8.8% ann., OI $25M"


@pytest.mark.asyncio
async def test_fetch_hyperliquid_http_error(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await sp.fetch_hyperliquid_derivs(_src(), CFG)


def test_fetcher_map_complete():
    assert set(sp.POSITIONING_FETCHERS) == {
        "cftc_cot", "eia_petroleum", "eia_natgas", "cboe_vix", "cboe_spx_options",
        "deribit_dvol", "bybit_derivs", "hyperliquid_derivs"}


def test_make_client_uses_proxy_and_timeout(monkeypatch):
    captured = {}

    class Dummy:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(sp.httpx, "AsyncClient", Dummy)
    sp._make_client(SimpleNamespace(proxy_url="http://127.0.0.1:7890"))
    assert captured["timeout"] == 30.0 and captured["proxy"] == "http://127.0.0.1:7890"
