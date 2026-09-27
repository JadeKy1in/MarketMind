"""Offline tests for the Nasdaq fallback in gateway/price_history.py."""
import asyncio
from datetime import date, timedelta

import httpx
import pytest

from marketmind.gateway import price_history as ph


def _row(d: date, close: float) -> dict:
    return {"date": d.strftime("%m/%d/%Y"), "close": f"${close:,.2f}",
            "volume": "1,234,567", "open": f"${close - 1:,.2f}",
            "high": f"${close + 2:,.2f}", "low": f"${close - 2:,.2f}"}


def _payload(rows):
    return {"data": {"symbol": "X", "totalRecords": len(rows),
                     "tradesTable": {"rows": rows}}, "status": {"rCode": 200}}


_NOT_FOUND = {"data": None, "status": {"rCode": 400, "bCodeMessage": [
    {"code": 1001, "errorMessage": "Symbol not exists."}]}}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    ph.clear_cache()
    calls: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, json=_NOT_FOUND)}

    def _handler(req):
        calls.append(req)
        return state["handler"](req)

    monkeypatch.setattr(ph, "_nasdaq_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), headers=ph._NASDAQ_HEADERS,
        timeout=ph._NASDAQ_TIMEOUT))

    async def _no_yf(ticker, years):
        return None
    monkeypatch.setattr(ph, "_from_yfinance", _no_yf)
    yield state, calls
    ph.clear_cache()


def _recent_rows(n=10, start_close=100.0):
    today = date.today()
    days = [today - timedelta(days=i) for i in range(1, 40) if (today - timedelta(days=i)).weekday() < 5][:n]
    return [_row(d, start_close + i) for i, d in enumerate(days)]  # newest first, like Nasdaq


def test_symbol_mapping():
    assert ph._nasdaq_symbol("aapl") == "AAPL"
    assert ph._nasdaq_symbol("BRK-B") == "BRK.B"
    for skip in ("^GSPC", "^TNX", "600519.SS", "0700.HK", "BTC-USD", "GC=F", "EURUSD=X", ""):
        assert ph._nasdaq_symbol(skip) is None


def test_parse_formats_and_sorts():
    rows = [
        {"date": "09/25/2026", "close": "$1,505.48", "volume": "2,994,434",
         "open": "$1,505.25", "high": "$1,510.00", "low": "$1,500.1329"},
        {"date": "09/24/2026", "close": "$1,500.00", "volume": "N/A",
         "open": "$1,499", "high": "$1,501", "low": "$1,498"},
        {"date": "bad", "close": "$1"},
        {"date": "09/23/2026", "close": "N/A", "volume": "1", "open": "1", "high": "1", "low": "1"},
    ]
    bars = ph._parse_nasdaq(_payload(rows))
    assert [b.date for b in bars] == ["2026-09-24", "2026-09-25"]
    assert bars[1].close == 1505.48 and bars[1].low == 1500.1329
    assert bars[1].volume == 2994434.0
    assert bars[0].volume == 0.0
    assert ph._parse_nasdaq(_NOT_FOUND) == []
    assert ph._parse_nasdaq({}) == []


def test_fallback_used_when_yfinance_fails(_isolate):
    state, calls = _isolate
    rows = _recent_rows()
    state["handler"] = lambda req: httpx.Response(200, json=_payload(rows))
    hist = asyncio.run(ph.get_price_history("AAPL", years=1))
    assert hist is not None and hist.source == "nasdaq"
    assert len(hist.daily) == len(rows)
    assert hist.daily == sorted(hist.daily, key=lambda b: b.date)
    assert hist.weekly and hist.weekly[-1].close == hist.daily[-1].close
    req = calls[0]
    assert req.url.path == "/api/quote/AAPL/historical"
    assert req.url.params["assetclass"] == "stocks"
    assert "Mozilla" in req.headers["user-agent"]


def test_etf_assetclass_tried_after_stocks(_isolate):
    state, calls = _isolate
    rows = _recent_rows()
    state["handler"] = lambda req: httpx.Response(
        200, json=_payload(rows) if req.url.params["assetclass"] == "etf" else _NOT_FOUND)
    hist = asyncio.run(ph.get_price_history("SPY", years=1))
    assert hist is not None and hist.source == "nasdaq"
    assert [c.url.params["assetclass"] for c in calls] == ["stocks", "etf"]


def test_trims_to_years(_isolate):
    state, _ = _isolate
    today = date.today()
    rows = [_row(today - timedelta(days=3), 10.0), _row(today - timedelta(days=800), 5.0)]
    state["handler"] = lambda req: httpx.Response(200, json=_payload(rows))
    hist = asyncio.run(ph.get_price_history("MSFT", years=1))
    assert [b.close for b in hist.daily] == [10.0]


@pytest.mark.parametrize("response", [
    lambda req: httpx.Response(500, text="err"),
    lambda req: httpx.Response(200, text="<html>blocked</html>"),
    lambda req: httpx.Response(200, json=_NOT_FOUND),
    lambda req: httpx.Response(200, json=_payload([])),
])
def test_bad_responses_return_none(_isolate, response):
    state, calls = _isolate
    state["handler"] = response
    assert asyncio.run(ph.get_price_history("AAPL", years=1)) is None
    assert len(calls) == 2  # stocks + etf, no further retries


def test_timeout_returns_none(_isolate):
    state, calls = _isolate

    def _boom(req):
        raise httpx.ReadTimeout("timed out", request=req)
    state["handler"] = _boom
    assert asyncio.run(ph.get_price_history("AAPL", years=1)) is None
    assert len(calls) == 1


def test_crypto_and_indices_not_sent_to_nasdaq(_isolate, monkeypatch):
    _, calls = _isolate

    async def _no_binance(ticker):
        return None
    async def _no_bybit(ticker, years):
        return None
    monkeypatch.setattr(ph, "_from_binance", _no_binance)
    monkeypatch.setattr(ph, "_from_bybit", _no_bybit)
    for t in ("BTC-USD", "^GSPC", "600519.SS"):
        assert asyncio.run(ph.get_price_history(t, years=1)) is None
    assert calls == []


def test_yfinance_success_skips_nasdaq(_isolate, monkeypatch):
    _, calls = _isolate
    bar = ph.Bar("2026-09-25", 1, 1, 1, 1, 1)

    async def _yf_ok(ticker, years):
        return ph.PriceHistory(ticker, "yfinance", [bar], [bar])
    monkeypatch.setattr(ph, "_from_yfinance", _yf_ok)
    hist = asyncio.run(ph.get_price_history("AAPL", years=1))
    assert hist.source == "yfinance"
    assert calls == []
