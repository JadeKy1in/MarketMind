"""Offline tests for the Bybit crypto fallback in gateway/price_history.py."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from marketmind.gateway import price_history as ph

_DAY_MS = 86_400_000


def _today_ms() -> int:
    now = datetime.now(timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)


def _kline(ms: int, close: float) -> list[str]:
    return [str(ms), str(close - 1), str(close + 2), str(close - 2), str(close), "12.5", "999.9"]


def _ok(rows):
    return {"retCode": 0, "retMsg": "OK",
            "result": {"category": "spot", "symbol": "BTCUSDT", "list": rows},
            "retExtInfo": {}, "time": 0}


def _series_handler(n_days: int):
    """Serve a synthetic daily series of n_days ending today, honouring start/end/limit."""
    today = _today_ms()
    all_ms = [today - i * _DAY_MS for i in range(n_days)]  # newest first

    def handler(req: httpx.Request):
        p = req.url.params
        start = int(p.get("start", 0))
        end = int(p.get("end", today + _DAY_MS))
        limit = int(p.get("limit", 200))
        window = [ms for ms in all_ms if start <= ms <= end]
        # Real Bybit: start without end -> oldest `limit` bars from start onward.
        window = window[-limit:] if ("start" in p and "end" not in p) else window[:limit]
        rows = [_kline(ms, 100.0 + (ms - all_ms[-1]) / _DAY_MS) for ms in window]
        return httpx.Response(200, json=_ok(rows))
    return handler


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    ph.clear_cache()
    calls: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, json=_ok([]))}

    def _handler(req):
        calls.append(req)
        return state["handler"](req)

    monkeypatch.setattr(ph, "_bybit_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), timeout=ph._BYBIT_TIMEOUT))

    async def _none(*args, **kwargs):
        return None
    monkeypatch.setattr(ph, "_from_yfinance", _none)
    monkeypatch.setattr(ph, "_from_binance", _none)
    monkeypatch.setattr(ph, "_from_nasdaq", _none)
    yield state, calls
    ph.clear_cache()


def test_symbol_mapping():
    assert ph._bybit_symbol("BTC-USD") == "BTCUSDT"
    assert ph._bybit_symbol("eth-usd") == "ETHUSDT"
    assert ph._bybit_symbol("SOL-USD") == "SOLUSDT"
    for skip in ("AAPL", "BRK-B", "^GSPC", "EURUSD=X", "-USD", "", "BTC-USDT"):
        assert ph._bybit_symbol(skip) is None


def test_parse_sorts_dedupes_and_skips_bad_rows():
    d1 = int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp() * 1000)
    d2 = d1 + _DAY_MS
    rows = [_kline(d2, 200.0), _kline(d1, 100.0), _kline(d2, 201.0),
            ["bad"], ["x", "1", "1", "1", "1", "1"], None]
    bars = ph._parse_bybit(rows)
    assert [b.date for b in bars] == ["2026-09-25", "2026-09-26"]
    assert bars[0].close == 100.0 and bars[0].high == 102.0 and bars[0].volume == 12.5
    assert bars[1].close == 201.0  # later duplicate wins, no double count
    assert ph._parse_bybit([]) == [] and ph._parse_bybit(None) == []


def test_fallback_after_binance_fails(_isolate):
    state, calls = _isolate
    state["handler"] = _series_handler(30)
    hist = asyncio.run(ph.get_price_history("BTC-USD", years=1))
    assert hist is not None and hist.source == "bybit"
    assert len(hist.daily) == 30
    assert hist.daily == sorted(hist.daily, key=lambda b: b.date)
    # Current UTC day's bar is kept, same as the Binance path.
    assert hist.daily[-1].date == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert hist.weekly and hist.weekly[-1].close == hist.daily[-1].close
    req = calls[0]
    assert req.url.host == "api.bybit.com" and req.url.path == "/v5/market/kline"
    p = req.url.params
    assert (p["category"], p["symbol"], p["interval"], p["limit"]) == ("spot", "BTCUSDT", "D", "1000")
    assert "start" in p and int(p["end"]) >= _today_ms()


def test_pages_back_for_five_years(_isolate):
    state, calls = _isolate
    state["handler"] = _series_handler(2500)  # more than 5y available
    hist = asyncio.run(ph.get_price_history("ETH-USD", years=5))
    assert hist is not None and hist.source == "bybit"
    assert len(calls) == 2
    assert "end" in calls[1].url.params
    dates = [b.date for b in hist.daily]
    assert len(dates) == len(set(dates))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(365.25 * 5))).strftime("%Y-%m-%d")
    assert dates[0] >= cutoff
    assert dates[-1] == datetime.now(timezone.utc).strftime("%Y-%m-%d")  # newest kept
    assert 1820 <= len(dates) <= 1828


def test_short_history_single_page(_isolate):
    state, calls = _isolate
    state["handler"] = _series_handler(400)  # young listing
    hist = asyncio.run(ph.get_price_history("SOL-USD", years=5))
    assert hist is not None and len(hist.daily) == 400
    assert len(calls) == 1


def test_trims_to_years(_isolate):
    state, _ = _isolate
    today = _today_ms()
    rows = [_kline(today - _DAY_MS, 10.0), _kline(today - 800 * _DAY_MS, 5.0)]
    state["handler"] = lambda req: httpx.Response(200, json=_ok(rows))
    hist = asyncio.run(ph.get_price_history("BTC-USD", years=1))
    assert [b.close for b in hist.daily] == [10.0]


@pytest.mark.parametrize("response", [
    lambda req: httpx.Response(500, text="err"),
    lambda req: httpx.Response(403, text="forbidden"),
    lambda req: httpx.Response(200, text="<html>blocked</html>"),
    lambda req: httpx.Response(200, json={"retCode": 10001, "retMsg": "Not supported symbols",
                                          "result": {}}),
    lambda req: httpx.Response(200, json=["not", "a", "dict"]),
    lambda req: httpx.Response(200, json={"retCode": 0, "result": {"list": "oops"}}),
    lambda req: httpx.Response(200, json=_ok([])),
])
def test_bad_responses_return_none(_isolate, response):
    state, calls = _isolate
    state["handler"] = response
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)) is None
    assert len(calls) == 1  # no retries


def test_timeout_returns_none(_isolate):
    state, calls = _isolate

    def _boom(req):
        raise httpx.ReadTimeout("timed out", request=req)
    state["handler"] = _boom
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)) is None
    assert len(calls) == 1


def test_binance_success_skips_bybit(_isolate, monkeypatch):
    _, calls = _isolate
    bar = ph.Bar("2026-09-25", 1, 1, 1, 1, 1)

    async def _binance_ok(ticker, years):
        return ph.PriceHistory(ticker, "binance", [bar], [bar])
    monkeypatch.setattr(ph, "_from_binance", _binance_ok)
    hist = asyncio.run(ph.get_price_history("BTC-USD", years=1))
    assert hist.source == "binance"
    assert calls == []


def test_fallback_order_binance_bybit(_isolate, monkeypatch):
    state, _ = _isolate
    state["handler"] = _series_handler(5)
    order: list[str] = []

    async def _yf(ticker, years):
        order.append("yfinance")
    async def _bn(ticker, years):
        order.append("binance")
    real_bybit = ph._from_bybit

    async def _bb(ticker, years):
        order.append("bybit")
        return await real_bybit(ticker, years)
    monkeypatch.setattr(ph, "_from_yfinance", _yf)
    monkeypatch.setattr(ph, "_from_binance", _bn)
    monkeypatch.setattr(ph, "_from_bybit", _bb)
    hist = asyncio.run(ph.get_price_history("BTC-USD", years=1))
    assert hist.source == "bybit"
    assert order == ["binance", "bybit"]


def test_non_crypto_never_sent_to_bybit(_isolate):
    _, calls = _isolate
    for t in ("AAPL", "BRK-B", "^GSPC", "600519.SS", "GC=F"):
        assert asyncio.run(ph.get_price_history(t, years=1)) is None
    assert calls == []
