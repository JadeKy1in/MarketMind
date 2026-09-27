"""Offline tests for the Alpaca source in gateway/price_history.py."""
import asyncio

import httpx
import pytest

from marketmind.gateway import price_history as ph


def _bar(d: str, c: float) -> dict:
    return {"t": f"{d}T04:00:00Z", "o": c - 1, "h": c + 1, "l": c - 2, "c": c, "v": 1000, "n": 5, "vw": c}


@pytest.fixture
def alpaca(monkeypatch):
    ph.clear_cache()
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    calls: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, json={"bars": {}, "next_page_token": None})}

    def _handler(req):
        calls.append(req)
        return state["handler"](req)

    monkeypatch.setattr(ph, "_alpaca_client", lambda headers: httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), headers=headers, timeout=ph._ALPACA_TIMEOUT))

    async def _none(*args, **kwargs):
        return None
    for name in ("_from_yfinance", "_from_nasdaq", "_from_binance", "_from_bybit"):
        monkeypatch.setattr(ph, name, _none)
    yield state, calls
    ph.clear_cache()


def test_alpaca_first_with_adjusted_sip_bars(alpaca):
    state, calls = alpaca
    state["handler"] = lambda req: httpx.Response(200, json={
        "bars": {"BRK.B": [_bar("2026-09-24", 500.0), _bar("2026-09-25", 505.5)]},
        "next_page_token": None})
    hist = asyncio.run(ph.get_price_history("BRK-B", years=1))
    assert hist.source == "alpaca"
    assert [b.date for b in hist.daily] == ["2026-09-24", "2026-09-25"]
    assert hist.daily[-1].close == 505.5 and hist.weekly
    q = calls[0].url.params
    assert q["symbols"] == "BRK.B" and q["adjustment"] == "all" and q["feed"] == "sip"
    assert q["end"].endswith("Z")                       # bounded away from the last 15 min
    assert calls[0].headers["APCA-API-KEY-ID"] == "test-id"


def test_pages_are_followed_and_deduped(alpaca):
    state, calls = alpaca

    def handler(req):
        if "page_token" not in req.url.params:
            return httpx.Response(200, json={"bars": {"SPY": [_bar("2026-09-23", 1), _bar("2026-09-24", 2)]},
                                             "next_page_token": "p2"})
        return httpx.Response(200, json={"bars": {"SPY": [_bar("2026-09-24", 2), _bar("2026-09-25", 3)]},
                                         "next_page_token": None})
    state["handler"] = handler
    hist = asyncio.run(ph.get_price_history("SPY", years=1))
    assert [b.close for b in hist.daily] == [1, 2, 3]
    assert len(calls) == 2 and calls[1].url.params["page_token"] == "p2"


@pytest.mark.parametrize("response", [
    httpx.Response(403, json={"message": "forbidden"}),
    httpx.Response(200, json={"bars": {}, "next_page_token": None}),
    httpx.Response(200, json={"bars": {"SPY": [{"t": "bad"}]}, "next_page_token": None}),
])
def test_bad_responses_fall_through(alpaca, response):
    state, _ = alpaca
    state["handler"] = lambda req: response
    assert asyncio.run(ph.get_price_history("SPY", years=1)) is None


def test_timeout_falls_through(alpaca):
    state, _ = alpaca

    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)
    state["handler"] = boom
    assert asyncio.run(ph.get_price_history("SPY", years=1)) is None


def test_no_credentials_or_unsupported_ticker_makes_no_call(alpaca, monkeypatch):
    _, calls = alpaca
    for t in ("BTC-USD", "^GSPC", "600519.SS", "GC=F"):
        asyncio.run(ph.get_price_history(t, years=1))
    monkeypatch.delenv("ALPACA_API_KEY_ID")
    ph.clear_cache()
    asyncio.run(ph.get_price_history("SPY", years=1))
    assert calls == []


def test_falls_back_to_yfinance_when_alpaca_fails(alpaca, monkeypatch):
    state, _ = alpaca
    state["handler"] = lambda req: httpx.Response(500)
    sentinel = ph.PriceHistory(ticker="SPY", source="yfinance")

    async def _yf(ticker, years):
        return sentinel
    monkeypatch.setattr(ph, "_from_yfinance", _yf)
    assert asyncio.run(ph.get_price_history("SPY", years=1)) is sentinel
