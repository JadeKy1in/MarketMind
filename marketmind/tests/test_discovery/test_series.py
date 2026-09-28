"""Discovery series registry and fetchers with mocked HTTP (offline)."""
import asyncio
import json
from datetime import date

import httpx
import pytest

from marketmind.discovery import series as sr
from marketmind.discovery.series import FetchContext

TODAY = date(2026, 9, 28)


def _ctx(handler):
    return FetchContext(TODAY, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _run(coro):
    return asyncio.run(coro)


def test_registry_entries_are_well_formed():
    reg = sr.default_registry()
    ids = [s.id for s in reg]
    assert len(ids) == len(set(ids)) >= 25
    for s in reg:
        assert ":" in s.id and s.title and s.unit and s.source
        assert s.frequency in ("daily", "weekly", "monthly")
        assert s.proxies and all(d in (1, -1) and t for t, d in s.proxies)
        assert s.keywords and s.prior
    assert {"fred:WRESBAL", "fred:SOFR_IORB", "nyfed:SOMA_TOTAL", "treasury:BTC_10Y",
            "mof:JGB10Y", "ecb:EURUSD", "cboe:VIX_VIX3M", "okx:BTC_FUNDING",
            "defillama:STABLECOIN_SUPPLY", "eia:WCESTUS1"} <= set(ids)


def test_fred_history_uses_params_and_parses(monkeypatch):
    monkeypatch.setenv("FRED_KEY", "secret123")
    seen = []

    def handler(req):
        seen.append(req.url)
        sid = req.url.params["series_id"]
        obs = {"SOFR": [("2026-09-24", "4.30"), ("2026-09-25", "4.35"), ("2026-09-26", ".")],
               "IORB": [("2026-09-24", "4.40"), ("2026-09-25", "4.40")]}[sid]
        return httpx.Response(200, json={"observations": [{"date": d, "value": v} for d, v in obs]})
    ctx = _ctx(handler)
    out = _run(sr._sofr_minus_iorb(ctx))
    assert out == [("2026-09-24", -10.0), ("2026-09-25", -5.0)]
    assert {u.params["observation_start"] for u in seen} == {"2024-07-20"}
    # memo: a second use of SOFR does not refetch
    _run(sr.fred_history(ctx, "SOFR"))
    assert len(seen) == 2


def test_fred_errors_never_leak_the_key(monkeypatch):
    monkeypatch.setenv("FRED_KEY", "secret123")
    ctx = _ctx(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(RuntimeError) as ei:
        _run(sr.fred_history(ctx, "WRESBAL"))
    assert "secret123" not in str(ei.value) and "WRESBAL" in str(ei.value)


def test_fred_without_key_raises(monkeypatch):
    monkeypatch.delenv("FRED_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("marketmind.gateway.fred_client._get_fred_key", lambda: "")
    with pytest.raises(RuntimeError, match="FRED key not configured"):
        _run(sr.fred_history(_ctx(lambda r: httpx.Response(200, json={})), "WRESBAL"))


def test_soma_buckets_in_billions():
    payload = {"soma": {"summary": [
        {"asOfDate": "2026-09-16", "total": "6000000000000", "bills": "200000000000", "mbs": "2000000000000"},
        {"asOfDate": "2026-09-23", "total": "6010000000000", "bills": "210000000000", "mbs": "1990000000000",
         "cmbs": "5000000000"}]}}
    ctx = _ctx(lambda req: httpx.Response(200, json=payload))
    assert _run(sr._soma("total")(ctx)) == [("2026-09-16", 6000.0), ("2026-09-23", 6010.0)]
    assert _run(sr._soma("mbs")(ctx))[-1] == ("2026-09-23", 1995.0)


def test_bid_to_cover_filters_term_and_excludes_tips_frn():
    rows = [
        {"auction_date": "2026-09-10", "security_type": "Note", "security_term": "9-Year 11-Month",
         "original_security_term": "10-Year", "bid_to_cover_ratio": "2.51"},
        {"auction_date": "2026-08-12", "security_type": "Note", "security_term": "10-Year",
         "original_security_term": "10-Year", "bid_to_cover_ratio": "2.40"},
        {"auction_date": "2026-07-20", "security_type": "Note", "security_term": "10-Year",
         "original_security_term": "10-Year", "inflation_index_security": "Yes", "bid_to_cover_ratio": "2.3"},
        {"auction_date": "2026-09-30", "security_type": "Note", "security_term": "10-Year",
         "original_security_term": "10-Year", "bid_to_cover_ratio": "null"},
    ]
    ctx = _ctx(lambda req: httpx.Response(200, json={"data": rows}))
    assert _run(sr._bid_to_cover("10-Year")(ctx)) == [("2026-08-12", 2.40), ("2026-09-10", 2.51)]


def test_okx_funding_daily_mean_and_complete_days_only():
    day_ms = 86_400_000
    t0 = 1790467200000   # 2026-09-27 00:00 UTC
    page = [{"fundingTime": str(t0 + day_ms), "fundingRate": "0.0003"},          # today (dropped)
            {"fundingTime": str(t0 + 16 * 3_600_000), "fundingRate": "0.0002", "realizedRate": "0.0002"},
            {"fundingTime": str(t0 + 8 * 3_600_000), "fundingRate": "0.0001"},
            {"fundingTime": str(t0 - day_ms), "fundingRate": "-0.0001"}]
    calls = []

    def handler(req):
        calls.append(dict(req.url.params))
        return httpx.Response(200, json={"code": "0", "data": page if len(calls) == 1 else []})
    out = _run(sr._okx_funding("BTC")(_ctx(handler)))
    assert out == [("2026-09-26", pytest.approx(-0.01)), ("2026-09-27", pytest.approx(0.015))]
    assert calls[1]["after"] == str(t0 - day_ms)


def test_okx_error_code_raises():
    ctx = _ctx(lambda req: httpx.Response(200, json={"code": "51001", "msg": "x", "data": []}))
    with pytest.raises(ValueError, match="OKX error"):
        _run(sr._okx_oi("BTC")(ctx))


def test_eia_parse_and_key_redaction(monkeypatch):
    payload = {"response": {"data": [{"period": "2026-09-18", "value": 426398},
                                     {"period": "2026-09-11", "value": 430000}]}}
    assert sr.parse_eia_series(payload) == [("2026-09-11", 430000.0), ("2026-09-18", 426398.0)]
    monkeypatch.setattr("marketmind.gateway.macro_data._get_eia_key", lambda: "eiasecret")
    ctx = _ctx(lambda req: httpx.Response(403, text="nope"))
    with pytest.raises(RuntimeError) as ei:
        _run(sr._eia("PET.WCESTUS1.W")(ctx))
    assert "eiasecret" not in str(ei.value)


def test_ecb_and_jgb_share_one_fetch():
    ecb_csv = ("KEY,FREQ,CURRENCY,TIME_PERIOD,OBS_VALUE\n"
               "x,D,USD,2026-09-24,1.15\nx,D,JPY,2026-09-24,170.1\nx,D,USD,2026-09-25,1.16\n")
    jgb_hist = "Date,1Y,2Y,10Y,30Y\n2026/8/31,0.5,0.8,1.6,3.0\n"
    jgb_cur = "Date,1Y,2Y,10Y,30Y\n2026/9/25,0.5,0.9,1.7,-\n"
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if "ecb" in req.url.host:
            return httpx.Response(200, text=ecb_csv)
        body = jgb_hist if "historical" in req.url.path else jgb_cur
        return httpx.Response(200, content=body.encode("cp932"))
    ctx = _ctx(handler)
    assert _run(sr._ecb("USD")(ctx)) == [("2026-09-24", 1.15), ("2026-09-25", 1.16)]
    assert _run(sr._ecb("JPY")(ctx)) == [("2026-09-24", 170.1)]
    assert _run(sr._jgb("10Y")(ctx)) == [("2026-08-31", 1.6), ("2026-09-25", 1.7)]
    assert _run(sr._jgb("30Y")(ctx)) == [("2026-08-31", 3.0)]
    assert len(calls) == 3


def test_cboe_ratio_joins_on_date(monkeypatch):
    async def fake(symbols):
        return {"VIX": [("2026-09-24", 20.0), ("2026-09-25", 22.0)],
                "VIX3M": [("2026-09-25", 20.0)], "VIX9D": [], "SKEW": [("2026-09-25", 140.0)]}
    monkeypatch.setattr("marketmind.shadow_feeds.volatility.fetch_histories", fake)
    ctx = _ctx(lambda r: httpx.Response(404))
    assert _run(sr._cboe_ratio("VIX", "VIX3M")(ctx)) == [("2026-09-25", pytest.approx(1.1))]
    assert _run(sr._cboe_skew(ctx)) == [("2026-09-25", 140.0)]


@pytest.mark.slow
def test_live_registry_smoke(tmp_path, monkeypatch):
    """Real network: every series either fetches or is listed as unavailable."""
    from marketmind.discovery.runner import run_discovery
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    rep = asyncio.run(run_discovery([]))
    assert rep["counts"]["ok"] + rep["counts"]["unavailable"] == rep["counts"]["series"]
