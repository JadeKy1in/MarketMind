"""Offline tests for the Coinbase Exchange crypto fallback in gateway/price_history.py."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from marketmind.gateway import price_history as ph

_DAY = 86_400
_real_binance = ph._from_binance     # the autouse fixture below replaces it


def _today_s() -> int:
    now = datetime.now(timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())


def _candle(ts: int, close: float) -> list:
    # [time, low, high, open, close, volume]
    return [ts, close - 2, close + 2, close - 1, close, 12.5]


def _iso(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def _series_handler(n_days: int):
    """Serve n_days of candles ending today, honouring start/end and the 300 cap."""
    today = _today_s()
    all_ts = [today - i * _DAY for i in range(n_days)]      # newest first

    def handler(req: httpx.Request):
        p = req.url.params
        start, end = _iso(p["start"]), _iso(p["end"])
        window = [t for t in all_ts if start <= t <= end]
        if len(window) > 300:
            return httpx.Response(400, json={"message": "granularity too small for the requested time range"})
        return httpx.Response(200, json=[_candle(t, 100.0 + (t - all_ts[-1]) / _DAY) for t in window])
    return handler


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    ph.clear_cache()
    calls: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, json=[])}

    def _handler(req):
        calls.append(req)
        return state["handler"](req)

    monkeypatch.setattr(ph, "_coinbase_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), timeout=ph._COINBASE_TIMEOUT))

    async def _none(*args, **kwargs):
        return None
    for name in ("_from_yfinance", "_from_binance", "_from_bybit", "_from_nasdaq"):
        monkeypatch.setattr(ph, name, _none)
    yield state, calls
    ph.clear_cache()


def test_product_mapping():
    assert ph._coinbase_product("btc-usd") == "BTC-USD"
    for skip in ("AAPL", "BRK-B", "^GSPC", "EURUSD=X", "-USD", "", "BTC-USDT"):
        assert ph._coinbase_product(skip) is None


def test_parse_maps_columns_sorts_and_dedupes():
    d1 = int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp())
    rows = [[d1 + _DAY, 190, 210, 195, 200, 3], [d1, 90, 110, 95, 100, 1],
            [d1 + _DAY, 191, 211, 196, 201, 4], ["bad"], None, ["x", 1, 1, 1, 1, 1]]
    bars = ph._parse_coinbase(rows)
    assert [b.date for b in bars] == ["2026-09-25", "2026-09-26"]
    b = bars[0]
    assert (b.open, b.high, b.low, b.close, b.volume) == (95.0, 110.0, 90.0, 100.0, 1.0)
    assert bars[1].close == 201.0
    assert ph._parse_coinbase(None) == []


def test_fallback_after_binance_and_bybit_fail(_isolate):
    state, calls = _isolate
    state["handler"] = _series_handler(30)
    hist = asyncio.run(ph.get_price_history("BTC-USD", years=1))
    assert hist is not None and hist.source == "coinbase"
    assert len(hist.daily) == 30
    # current UTC day's bar is kept, like Binance / Bybit; complete_bars drops it
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert hist.daily[-1].date == today
    assert ph.complete_bars("BTC-USD", hist.daily)[-1].date < today
    req = calls[0]
    assert req.url.host == "api.exchange.coinbase.com"
    assert req.url.path == "/products/BTC-USD/candles"
    assert req.url.params["granularity"] == "86400"
    # stopped paging once a page came back empty (young history)
    assert len(calls) == 2


def test_pages_back_for_five_years_within_300_cap(_isolate):
    state, calls = _isolate
    state["handler"] = _series_handler(2500)
    hist = asyncio.run(ph.get_price_history("ETH-USD", years=5))
    assert hist is not None and hist.source == "coinbase"
    assert len(calls) == 7                          # ceil(1826 / 299)
    for c in calls:
        span = _iso(c.url.params["end"]) - _iso(c.url.params["start"])
        assert span <= 299 * _DAY
    dates = [b.date for b in hist.daily]
    assert len(dates) == len(set(dates)) and dates == sorted(dates)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(365.25 * 5))).strftime("%Y-%m-%d")
    assert dates[0] >= cutoff and 1820 <= len(dates) <= 1828


@pytest.mark.parametrize("response", [
    lambda req: httpx.Response(404, json={"message": "NotFound"}),
    lambda req: httpx.Response(429, json={"message": "Public rate limit exceeded"}),
    lambda req: httpx.Response(200, json={"message": "odd"}),
    lambda req: httpx.Response(200, json=[]),
])
def test_bad_responses_return_none(_isolate, response):
    state, calls = _isolate
    state["handler"] = response
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)) is None
    assert len(calls) == 1


def test_timeout_returns_none(_isolate):
    state, calls = _isolate

    def _boom(req):
        raise httpx.ReadTimeout("timed out", request=req)
    state["handler"] = _boom
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)) is None


def test_order_binance_bybit_coinbase_yf(_isolate, monkeypatch):
    state, _ = _isolate
    state["handler"] = _series_handler(5)
    order: list[str] = []

    async def _yf(ticker, years):
        order.append("yfinance")
    async def _bn(ticker, years):
        order.append("binance")
    async def _bb(ticker, years):
        order.append("bybit")
    real = ph._from_coinbase

    async def _cb(ticker, years):
        order.append("coinbase")
        return await real(ticker, years)
    monkeypatch.setattr(ph, "_from_yfinance", _yf)
    monkeypatch.setattr(ph, "_from_binance", _bn)
    monkeypatch.setattr(ph, "_from_bybit", _bb)
    monkeypatch.setattr(ph, "_from_coinbase", _cb)
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)).source == "coinbase"
    assert order == ["binance", "bybit", "coinbase"]


def test_bybit_success_skips_coinbase(_isolate, monkeypatch):
    _, calls = _isolate
    bar = ph.Bar("2026-09-25", 1, 1, 1, 1, 1)

    async def _bb(ticker, years):
        return ph.PriceHistory(ticker, "bybit", [bar], [bar])
    monkeypatch.setattr(ph, "_from_bybit", _bb)
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)).source == "bybit"
    assert calls == []


def test_non_crypto_never_sent_to_coinbase(_isolate):
    _, calls = _isolate
    for t in ("AAPL", "^GSPC", "600519.SS", "GC=F"):
        assert asyncio.run(ph.get_price_history(t, years=1)) is None
    assert calls == []


def _bars(*dates):
    return [ph.Bar(d, 1, 1, 1, 1, 1) for d in dates]


def test_missing_utc_day():
    assert ph.missing_utc_day(_bars("2026-09-26", "2026-09-27", "2026-09-28")) is None
    assert ph.missing_utc_day(_bars("2026-09-27", "2026-09-29")) == "2026-09-28"
    assert ph.missing_utc_day(_bars("2026-09-30", "2026-10-01")) is None


def test_yfinance_only_when_exchanges_fail(_isolate, monkeypatch):
    async def _yf(ticker, years):
        return ph.PriceHistory(ticker, "yfinance", _bars("2026-09-27", "2026-09-29"))
    monkeypatch.setattr(ph, "_from_yfinance", _yf)
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)).source == "yfinance"


def test_exchange_success_skips_yfinance(_isolate, monkeypatch):
    async def _bn(ticker, years):
        return ph.PriceHistory(ticker, "binance", _bars("2026-09-27", "2026-09-28"))

    async def _boom(*args):
        raise AssertionError("yfinance must not be called")
    monkeypatch.setattr(ph, "_from_binance", _bn)
    monkeypatch.setattr(ph, "_from_yfinance", _boom)
    assert asyncio.run(ph.get_price_history("BTC-USD", years=1)).source == "binance"


def _binance_series(n_days: int, calls: list):
    """Serve n_days of klines ending today; honours startTime and the 1000 limit."""
    today = _today_s() * 1000
    all_ms = [today - i * _DAY * 1000 for i in range(n_days)][::-1]   # oldest first

    def handler(req: httpx.Request):
        calls.append(req)
        start = int(req.url.params["startTime"])
        limit = int(req.url.params["limit"])
        rows = [[ms, "1", "2", "0.5", "1.5", "10"] for ms in all_ms if ms >= start][:limit]
        return httpx.Response(200, json=rows)
    return handler


def test_binance_pages_forward_to_cover_five_years(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ph, "_binance_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_binance_series(2000, calls))))
    hist = asyncio.run(_real_binance("BTC-USD", 5))
    assert hist.source == "binance"
    assert 1820 <= len(hist.daily) <= 1828 and len(calls) == 2    # ~5 years: 1000 + rest
    assert hist.daily[-1].date == datetime.fromtimestamp(_today_s(), timezone.utc).strftime("%Y-%m-%d")
    assert calls[0].url.params["symbol"] == "BTCUSDT"


def test_binance_http_error_returns_none(monkeypatch):
    monkeypatch.setattr(ph, "_binance_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(451, text="blocked"))))
    assert asyncio.run(_real_binance("BTC-USD", 1)) is None
