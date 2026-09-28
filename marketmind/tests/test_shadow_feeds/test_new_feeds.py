"""Offline tests for the fed_liquidity, fx_rates and crypto_derivs shadow feeds.

Payloads are trimmed copies of the live responses recorded 2026-09-28.
"""
import httpx
import pytest

import marketmind.shadow_feeds as sf
from marketmind.shadow_feeds import crypto_derivs, fed_liquidity, fx_rates

_real_gather = sf.gather


def _mock(monkeypatch, module, handler, calls=None):
    def _h(req):
        if calls is not None:
            calls.append(req)
        return handler(req)
    monkeypatch.setattr(module, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_h)))


# ── fed liquidity ───────────────────────────────────────────────────────────

def _op(day, kind, amt, cpty=None, rate=None):
    o = {"operationDate": day, "operationType": kind, "auctionStatus": "Results",
         "totalAmtAccepted": amt,
         "details": [{"securityType": "Treasury", "amtAccepted": amt,
                      **({"percentAwardRate": rate} if rate is not None else {})}]}
    if cpty is not None:
        o["participatingCpty"] = cpty
    return o


RP = {"repo": {"operations": [
    _op("2026-09-25", "Repo", 0), _op("2026-09-25", "Reverse Repo", 576000000, 3, 3.75),
    _op("2026-09-25", "Repo", 0),
    _op("2026-09-24", "Repo", 0), _op("2026-09-24", "Reverse Repo", 630000000, 3, 3.75),
    _op("2026-09-24", "Repo", 1000000),
    _op("2026-09-16", "Repo", 0), _op("2026-09-16", "Reverse Repo", 5375000000, 4, 3.5),
    _op("2026-09-16", "Repo", 254000000),
    _op("2026-09-14", "Repo", 0), _op("2026-09-14", "Reverse Repo", 1420000000, 4, 3.5),
    _op("2026-09-14", "Repo", 0)]}}


def _soma_row(day, total, bills, nb, mbs):
    return {"asOfDate": day, "total": total, "bills": bills, "notesbonds": nb, "mbs": mbs,
            "cmbs": "0", "tips": "0", "frn": "", "tipsInflationCompensation": "99e9",
            "agencies": "0"}


SOMA = {"soma": {"summary": [
    _soma_row("2026-06-24", "6344345567445.70", "485973926700", "3597010598200", "1953996337974.40"),
    _soma_row("2026-08-26", "6355853153593.90", "541994926700", "3601804749000", "1906167222266.40"),
    _soma_row("2026-09-02", "6362218153593.90", "548359926700", "3600776303200", "1906167222266.40"),
    _soma_row("2026-09-16", "6364278356116.00", "550481926700", "3600776303200", "1906108916224.00"),
    _soma_row("2026-09-23", "6365055221192.60", "554372926700", "3600776303200", "1902994781300.60"),
]}}


def test_daily_operations_sums_per_day_and_type():
    rrp = fed_liquidity.daily_operations(RP, "Reverse Repo")
    assert [r["date"] for r in rrp] == ["2026-09-14", "2026-09-16", "2026-09-24", "2026-09-25"]
    assert rrp[-1]["accepted"] == 576000000 and rrp[-1]["rate"] == 3.75 and rrp[-1]["cpty"] == 3
    repo = fed_liquidity.daily_operations(RP, "Repo")
    assert repo[1] == {"date": "2026-09-16", "accepted": 254000000.0, "ops": 2,
                       "rate": None, "cpty": None}


@pytest.mark.asyncio
async def test_fed_liquidity_lines(monkeypatch):
    calls = []
    _mock(monkeypatch, fed_liquidity,
          lambda req: httpx.Response(200, json=RP if "/rp/" in req.url.path else SOMA), calls)
    lines = await fed_liquidity.fetch("2026-09-28")
    assert {c.url.path for c in calls} == {"/api/rp/all/all/results/lastTwoWeeks.json",
                                           "/api/soma/summary.json"}
    text = "\n".join(lines)
    assert "ON RRP" in lines[0] and "2026-09-25: $0.58B" in lines[0]
    assert "award 3.75%" in lines[0] and "2-week change -$0.84B" in lines[0]
    assert "Standing repo" in lines[1] and "total $0.26B" in lines[1]
    assert "peak $0.25B on 2026-09-16" in lines[1]
    # 1w vs 09-16, 4w vs 08-26, 13w vs 06-24
    assert "SOMA (Fed balance-sheet securities) 2026-09-23: $6,365.1B" in text
    assert "1w +$0.8B (+0.01%)" in text and "4w +$9.2B (+0.14%)" in text
    assert "13w +$20.7B" in text
    assert "bills +$12.4B" in text and "MBS -$3.2B" in text
    assert "growing = adding liquidity" in text
    assert len(lines) <= 12


@pytest.mark.asyncio
async def test_fed_liquidity_partial_and_total_failure(monkeypatch):
    _mock(monkeypatch, fed_liquidity, lambda req: httpx.Response(
        200, json=SOMA) if "soma" in req.url.path else httpx.Response(503))
    lines = await fed_liquidity.fetch("2026-09-28")
    assert lines[0].startswith("- NY Fed repo / reverse-repo operations: unavailable (HTTPStatusError)")
    assert any("SOMA" in l for l in lines[1:])

    _mock(monkeypatch, fed_liquidity, lambda req: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await fed_liquidity.fetch("2026-09-28")


# ── FX & rates ──────────────────────────────────────────────────────────────

ECB_CSV = """KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS
EXR.D.JPY.EUR.SP00.A,D,JPY,EUR,SP00,A,2026-08-25,185.7,A
EXR.D.JPY.EUR.SP00.A,D,JPY,EUR,SP00,A,2026-08-26,185.62,A
EXR.D.JPY.EUR.SP00.A,D,JPY,EUR,SP00,A,2026-09-25,179.7,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-08-25,1.1662,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-08-26,1.1669,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-09-24,1.1367,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-09-25,1.1403,A
EXR.D.GBP.EUR.SP00.A,D,GBP,EUR,SP00,A,2026-09-25,0.8605,A
EXR.D.CHF.EUR.SP00.A,D,CHF,EUR,SP00,A,2026-09-25,bad,A
"""

JGB_CUR = ("Interest Rate (September 2026),,,,,,,,,,,,,,,(Unit : %)\n"
           "Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y\n"
           "2026/9/1,1.527,1.802,1.952,2.14,2.28,2.411,2.559,2.718,2.848,2.987,3.544,3.859,4.143,4.131,4.145\n"
           "2026/9/25,1.652,1.948,2.098,2.287,2.423,2.536,2.654,2.811,2.94,3.071,3.597,3.883,4.143,4.112,4.105\n"
           ",,,,,,,,,,,,,,,\n").encode("cp932") + \
          b'"  \x81\xa6If you cannot download the latest csv data, please clear the cache.",,,\n'
JGB_HIST = ("Interest Rate,,,,,,,,,,,,,,,(Unit : %)\n"
            "Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y\n"
            "1974/9/24,10.327,9.362,8.83,8.515,8.348,8.29,8.24,8.121,8.127,-,-,-,-,-,-\n"
            "2026/8/25,1.45,1.69,1.84,2.03,2.17,2.31,2.44,2.61,2.75,2.89,3.45,3.76,4.05,4.03,4.04\n"
            "2026/8/26,1.461,1.697,1.846,2.037,2.182,2.315,2.452,2.617,2.755,2.892,3.458,3.764,4.052,4.039,4.043\n"
            ).encode("cp932")


def test_parse_ecb_skips_bad_values_and_sorts():
    s = fx_rates.parse_ecb_csv(ECB_CSV)
    assert s["USD"][-1] == ("2026-09-25", 1.1403) and "CHF" not in s
    assert [d for d, _ in s["USD"]] == sorted(d for d, _ in s["USD"])


@pytest.mark.asyncio
async def test_ecb_lines(monkeypatch):
    calls = []
    _mock(monkeypatch, fx_rates, lambda req: httpx.Response(200, text=ECB_CSV), calls)
    lines = await fx_rates.fetch_ecb("2026-09-28")
    assert calls[0].url.host == "data-api.ecb.europa.eu"
    assert calls[0].url.params["format"] == "csvdata"
    assert lines[0] == ("- EUR/USD 1.1403 USD per EUR (2026-09-25), 1m -2.28% "
                        "(vs 1.1669 on 2026-08-26)")
    assert lines[1].startswith("- EUR/JPY 179.70 JPY per EUR (2026-09-25), 1m -3.19%")
    assert lines[2] == "- EUR/GBP 0.8605 GBP per EUR (2026-09-25)"     # no month-old point
    assert "EUR/CNY: no ECB observation" in lines[3]
    assert "USD/JPY 157.59" in lines[-1] and "GBP/USD 1.3252" in lines[-1]


@pytest.mark.asyncio
async def test_ecb_empty_raises(monkeypatch):
    _mock(monkeypatch, fx_rates, lambda req: httpx.Response(200, text="KEY,CURRENCY\n"))
    with pytest.raises(ValueError):
        await fx_rates.fetch_ecb("2026-09-28")


def test_parse_jgb_handles_dash_and_shift_jis_footer():
    rows = dict(fx_rates.parse_jgb_csv(JGB_HIST))
    assert rows["1974-09-24"]["2Y"] == 9.362 and "10Y" not in rows["1974-09-24"]
    cur = fx_rates.parse_jgb_csv(JGB_CUR)
    assert [d for d, _ in cur] == ["2026-09-01", "2026-09-25"]


@pytest.mark.asyncio
async def test_jgb_lines_merge_history_and_spread(monkeypatch):
    _mock(monkeypatch, fx_rates, lambda req: httpx.Response(
        200, content=JGB_HIST if "historical" in req.url.path else JGB_CUR))

    async def _us():
        return ("2026-09-24", 5.18)
    monkeypatch.setattr(fx_rates, "_us10y", _us)
    lines = await fx_rates.fetch_jgb("2026-09-28")
    assert lines[0] == "- JGB yields (MOF, 2026-09-25): 2Y 1.948%, 10Y 3.071%, 30Y 4.112%"
    assert lines[1].startswith("- JGB 1m change (vs 2026-08-26): 2Y +25.1bp, 10Y +17.9bp, 30Y +7.3bp; 2s30s curve 216bp")
    assert lines[2] == ("- US10Y - JGB10Y: 5.18% (2026-09-24, FRED DGS10) - 3.071% (2026-09-25) "
                        "= 211bp")


@pytest.mark.asyncio
async def test_jgb_without_history_or_fred(monkeypatch):
    _mock(monkeypatch, fx_rates, lambda req: httpx.Response(404) if "historical" in req.url.path
          else httpx.Response(200, content=JGB_CUR))

    async def _none():
        return None
    monkeypatch.setattr(fx_rates, "_us10y", _none)
    lines = await fx_rates.fetch_jgb("2026-09-28")
    assert lines[0].startswith("- JGB yields (MOF, 2026-09-25)")
    assert not any("1m change" in l for l in lines)
    assert lines[-1] == "- US10Y - JGB10Y: US 10Y unavailable (FRED DGS10)"


@pytest.mark.asyncio
async def test_us10y_reads_fred_client(monkeypatch):
    from marketmind.gateway import fred_client

    async def _fred(key):
        assert key == "DGS10"
        return {"value": 4.12, "date": "2026-09-24"}
    monkeypatch.setattr(fred_client, "get_fred_series", _fred)
    assert await fx_rates._us10y() == ("2026-09-24", 4.12)

    async def _err(key):
        return {"error": "source_unavailable"}
    monkeypatch.setattr(fred_client, "get_fred_series", _err)
    assert await fx_rates._us10y() is None


# ── crypto derivatives ──────────────────────────────────────────────────────

def _funding(inst, rate):
    return {"code": "0", "msg": "", "data": [{
        "instId": inst, "instType": "SWAP", "fundingRate": rate,
        "fundingTime": "1790611200000", "prevFundingTime": "1790582400000",
        "nextFundingTime": "1790640000000", "settFundingRate": "-0.0000076067766736",
        "settState": "settled", "ts": "1790602944127"}]}


OI = {"code": "0", "msg": "", "data": [{"instId": "BTC-USDT-SWAP", "instType": "SWAP",
      "oi": "2906566.84", "oiCcy": "29065.6684", "oiUsd": "2434932771.707", "ts": "1790602980957"}]}


@pytest.mark.asyncio
async def test_crypto_funding_lines(monkeypatch):
    def handler(req):
        inst = req.url.params["instId"]
        if req.url.path.endswith("open-interest"):
            return httpx.Response(200, json=OI) if inst.startswith("BTC") else httpx.Response(500)
        if inst.startswith("SOL"):
            return httpx.Response(200, json={"code": "51001", "msg": "Instrument ID does not exist",
                                             "data": []})
        return httpx.Response(200, json=_funding(inst, "0.0000894495146509"))
    _mock(monkeypatch, crypto_derivs, handler)
    lines = await crypto_derivs.fetch("2026-09-28")
    assert len(lines) == 3
    assert lines[0] == ("- BTC perp (OKX BTC-USDT-SWAP): funding +0.0089% per 8h "
                        "(~+9.8% annualised; longs pay shorts), next settlement 2026-09-28 16:00 UTC; "
                        "last settled -0.0008%; open interest $2.43B (29,066 BTC, 2026-09-28)")
    assert "ETH perp" in lines[1] and "open interest" not in lines[1]   # OI failure is optional
    assert lines[2] == "- SOL perp (OKX): unavailable (ValueError)"


@pytest.mark.asyncio
async def test_crypto_all_fail_raises(monkeypatch):
    _mock(monkeypatch, crypto_derivs, lambda req: httpx.Response(403, text="blocked"))
    with pytest.raises(httpx.HTTPStatusError):
        await crypto_derivs.fetch("2026-09-28")


def test_negative_funding_and_default_interval():
    line = crypto_derivs.funding_line("ETH", {"fundingRate": "-0.0002",
                                              "fundingTime": "1790611200000"}, None)
    assert "-0.0200% per 8h (~-21.9% annualised; shorts pay longs)" in line


# ── registration ────────────────────────────────────────────────────────────

def test_feeds_are_discovered_for_their_shadows():
    from marketmind.shadows.v3 import roster
    names = {e.name for e in roster.ROSTER}
    feeds = {f.name: f for f in sf.discover()}
    expect = {"fed_liquidity": {"yield_whisperer", "cycle_reader", "bank_examiner"},
              "ecb_fx": {"currency_dealer", "carry_watch", "euro_watch"},
              "jgb_yields": {"currency_dealer", "carry_watch", "euro_watch"},
              "crypto_derivs": {"chain_oracle", "defi_scout"}}
    for name, shadows in expect.items():
        assert set(feeds[name].shadows) == shadows
        assert shadows <= names


@pytest.mark.asyncio
async def test_gather_with_new_feeds_offline(monkeypatch):
    async def _lines(today):
        return ["- x"]
    feeds = [sf.Feed(f.name, f.title, f.shadows, _lines) for f in sf.discover()
             if f.name in ("fed_liquidity", "crypto_derivs")]
    out = await _real_gather(["bank_examiner", "trial_defi_scout_ab12", "vega_trader"],
                             "2026-09-28", feeds=feeds)
    assert set(out) == {"bank_examiner", "trial_defi_scout_ab12"}
