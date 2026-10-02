"""Global scope (docs/S3_DESIGN.md §7): market model, fallback quotes, foreign settlement."""
from datetime import datetime, timezone

import pytest

from marketmind.gateway import global_quotes as gq
from marketmind.gateway.price_history import Bar, complete_bars
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.settlement import (
    bars_after_creation, cost_bps, market_benchmark, settle_all,
)
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.markets import CASH, is_shadow_tradable, market_for


@pytest.mark.parametrize("ticker, code, bench", [
    ("AAPL", "US", "SPY"), ("BRK-B", "US", "SPY"), ("BTC-USD", "CRYPTO", "BTC-USD"),
    ("0700.HK", "HK", "2800.HK"), ("600519.SS", "CN", "510300.SS"), ("000001.SZ", "CN", "510300.SS"),
    ("7203.T", "JP", "1306.T"), ("SAP.DE", "DE", "^GDAXI"), ("HSBA.L", "UK", "^FTSE"),
    ("CL=F", "FUTURE", "DBC"), ("ZN=F", "RATES_FUTURE", CASH), ("EURUSD=X", "FX", CASH),
    ("^N225", "INDEX", CASH),
])
def test_market_for(ticker, code, bench):
    m = market_for(ticker)
    assert (m.code, m.benchmark) == (code, bench)


def test_shadow_tradable_excludes_bare_indices():
    assert is_shadow_tradable("0700.HK") and is_shadow_tradable("CL=F")
    assert not is_shadow_tradable("^N225") and not is_shadow_tradable("")


def test_symbol_mapping():
    assert gq.eastmoney_secid("0700.HK") == "116.00700"
    assert gq.eastmoney_secid("600519.SS") == "1.600519"
    assert gq.eastmoney_secid("000001.SZ") == "0.000001"
    assert gq.eastmoney_secid("CL=F") == "102.CL00Y"
    assert gq.eastmoney_secid("JPY=X") == "119.USDJPY"
    assert gq.eastmoney_secid("USDCNH=X") == "133.USDCNH"
    assert gq.eastmoney_secid("^N225") == "100.N225"
    assert gq.eastmoney_secid("7203.T") is None and gq.eastmoney_secid("AAPL") is None
    assert gq.tencent_code("700.HK") == "hk00700" and gq.tencent_code("600519.SS") == "sh600519"
    assert gq.tencent_code("SAP.DE") is None


def test_eastmoney_field_order_is_open_close_high_low():
    bars = gq.parse_eastmoney({"data": {"klines": [
        "2026-09-23,442.8,451.6,452.0,440.0,100", "2026-09-22,424.6,430.0,434.8,423.0,50",
        "bad,row"]}})
    assert [b.date for b in bars] == ["2026-09-22", "2026-09-23"]
    b = bars[1]
    assert (b.open, b.close, b.high, b.low, b.volume) == (442.8, 451.6, 452.0, 440.0, 100)
    assert gq.parse_eastmoney({"rc": 102, "data": None}) == []


def test_tencent_parses_qfq_and_plain_days():
    rows = [["2026-09-25", "433.8", "436.6", "437.2", "431.2", "9113746.0"]]
    for key in ("qfqday", "day"):
        bars = gq.parse_tencent({"data": {"hk00700": {key: rows}}}, "hk00700")
        assert (bars[0].open, bars[0].close, bars[0].high, bars[0].low) == (433.8, 436.6, 437.2, 431.2)


def _bars(*dates):
    return [Bar(d, 1.0, 1.0, 1.0, 1.0, 1.0) for d in dates]


def test_complete_bars_uses_local_close():
    d = _bars("2026-09-24", "2026-09-25")
    tokyo_after = datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc)    # 16:00 JST
    tokyo_during = datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc)   # 14:00 JST
    assert len(complete_bars("7203.T", d, tokyo_after)) == 2
    assert len(complete_bars("7203.T", d, tokyo_during)) == 1
    assert len(complete_bars("EURUSD=X", d, datetime(2026, 9, 25, 23, tzinfo=timezone.utc))) == 1


def _entry(ticker, created, **kw):
    base = dict(source_type="shadow", source_id="t", ticker=ticker, direction="long",
                hold_bars=2, confidence=0.6, position_usd=500, falsifier="wrong if down",
                created_at=created)
    base.update(kw)
    return LedgerEntry(**base)


def test_first_bar_follows_the_exchange_clock():
    bars = _bars("2026-09-24", "2026-09-25", "2026-09-28")
    # 2026-09-24T22:00Z = 09-25 07:00 in Tokyo, before the 09:00 open -> fills on 09-25
    assert bars_after_creation(_entry("7203.T", "2026-09-24T22:00:00Z"), bars)[0].date == "2026-09-25"
    # same instant for a US stock is 09-24 18:00 ET, after the close -> fills on 09-25 too
    assert bars_after_creation(_entry("AAPL", "2026-09-24T22:00:00Z"), bars)[0].date == "2026-09-25"
    # 2026-09-25T02:00Z = 11:00 Tokyo, market open -> next session 09-28
    assert bars_after_creation(_entry("7203.T", "2026-09-25T02:00:00Z"), bars)[0].date == "2026-09-28"


def test_costs_and_benchmarks_by_market():
    assert cost_bps("stock", "7203.T") == 10.0 and cost_bps("stock", "AAPL") == 5.0
    assert cost_bps("crypto", "BTC-USD") == 100.0 and cost_bps("unknown", "CL=F") == 2.0
    assert cost_bps("crypto", "SOL-USD") == 125.0 and cost_bps("stock", "ETH-USD") == 100.0
    assert market_benchmark(_entry("0700.HK", "2026-09-24T00:00:00Z")) == "2800.HK"
    assert market_benchmark(_entry("EURUSD=X", "2026-09-24T00:00:00Z")) == CASH


@pytest.mark.asyncio
async def test_fx_settles_against_cash_benchmark(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(_entry("EURUSD=X", "2026-09-21T12:00:00Z", asset_type="unknown"))
    bars = [Bar(f"2026-09-{d}", 1.10, 1.11, 1.09, 1.10 + i * 0.01, 1) for i, d in
            enumerate(("21", "22", "23", "24"))]
    await settle_all(store, StaticPriceSource({"EURUSD=X": bars}), today="2026-09-30")
    e = store.get(eid)
    assert e.status == "settled" and e.market_benchmark == CASH and e.market_return == 0.0
    assert e.cost_return == pytest.approx(0.0004)
    assert e.excess_market == e.net_return and e.settle_note == ""


# ── Twelve Data ─────────────────────────────────────────────────────────────

_real_from_twelvedata = gq.from_twelvedata   # captured before conftest stubs it


def test_twelvedata_symbol_mapping():
    assert gq.twelvedata_symbol("EURUSD=X") == ("EUR/USD", None)
    assert gq.twelvedata_symbol("JPY=X") == ("USD/JPY", None)
    assert gq.twelvedata_symbol("BTC-USD") == ("BTC/USD", None)
    assert gq.twelvedata_symbol("AAPL") == ("AAPL", None)
    assert gq.twelvedata_symbol("BRK-B") == ("BRK.B", None)
    assert gq.twelvedata_symbol("7203.T") == ("7203", "XJPX")
    assert gq.twelvedata_symbol("SAP.DE") == ("SAP", "XETR")
    for t in ("CL=F", "^N225", "0700.HK", "600519.SS", ""):
        assert gq.twelvedata_symbol(t) is None


def test_twelvedata_parse_newest_first_and_fx_without_volume():
    bars = gq.parse_twelvedata({"status": "ok", "values": [
        {"datetime": "2026-09-25", "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15"},
        {"datetime": "2026-09-24", "open": "1", "high": "1", "low": "1", "close": "1",
         "volume": "500"},
        {"datetime": "2026-09-23", "open": "x"}]})
    assert [b.date for b in bars] == ["2026-09-24", "2026-09-25"]
    assert (bars[1].open, bars[1].high, bars[1].low, bars[1].close, bars[1].volume) == \
        (1.1, 1.2, 1.0, 1.15, 0.0)
    assert bars[0].volume == 500


@pytest.fixture
def _td(monkeypatch):
    """Fake Twelve Data endpoint: records every request, answers from `replies`."""
    import httpx
    calls, replies = [], {}

    async def _fake_get(client, params, key):
        calls.append((dict(params), key))
        return httpx.Response(200, json=replies.get(params["symbol"], {}))
    monkeypatch.setattr(gq, "_td_get", _fake_get)
    monkeypatch.setattr(gq, "_td_plan_blocked", set())
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key")
    return calls, replies


@pytest.mark.asyncio
async def test_twelvedata_fetch_ok(_td):
    calls, replies = _td
    replies["EUR/USD"] = {"status": "ok", "values": [
        {"datetime": "2026-09-25", "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15"}]}
    hist = await _real_from_twelvedata("EURUSD=X")
    assert hist.source == "twelvedata" and hist.daily[0].close == 1.15
    params, key = calls[0]
    assert key == "test-key" and "apikey" not in params and "mic_code" not in params


@pytest.mark.asyncio
async def test_twelvedata_plan_block_skips_market(_td):
    calls, replies = _td
    replies["SAP"] = {"code": 404, "status": "error",
                      "message": "This symbol is available starting with the Grow plan."}
    assert await _real_from_twelvedata("SAP.DE") is None
    assert calls[0][0]["mic_code"] == "XETR"
    assert await _real_from_twelvedata("SIE.DE") is None
    assert len(calls) == 1                      # DE market skipped after the plan error
    replies["AAPL"] = {"status": "error", "code": 429, "message": "run out of API credits"}
    assert await _real_from_twelvedata("AAPL") is None
    assert "US" not in gq._td_plan_blocked      # rate limit is not a plan block


@pytest.mark.asyncio
async def test_twelvedata_without_key_makes_no_request(_td, monkeypatch):
    calls, _ = _td
    monkeypatch.delenv("TWELVEDATA_API_KEY")
    assert await _real_from_twelvedata("AAPL") is None
    assert await _real_from_twelvedata("CL=F") is None
    assert calls == []


@pytest.mark.asyncio
async def test_twelvedata_comes_after_other_fallbacks(monkeypatch):
    from marketmind.gateway import free_quotes as fq
    from marketmind.gateway import price_history as ph
    order = []

    def _src(name, ok=False):
        async def f(ticker, years=5):
            order.append(name)
            return ph.PriceHistory(ticker=ticker, source=name) if ok else None
        return f
    ph.clear_cache()
    monkeypatch.setattr(ph, "_from_yfinance", lambda t, y: _src("yahoo")(t, y))
    monkeypatch.setattr(gq, "from_eastmoney", _src("eastmoney"))
    monkeypatch.setattr(gq, "from_tencent", _src("tencent"))
    for name in ("baostock", "stooq", "finmind", "eodhd"):
        monkeypatch.setattr(fq, f"from_{name}", _src(name))
    monkeypatch.setattr(gq, "from_twelvedata", _src("twelvedata", ok=True))
    hist = await ph.get_price_history("SAP.DE")
    assert hist.source == "twelvedata"
    assert order == ["yahoo", "tencent", "baostock", "eastmoney", "stooq", "finmind",
                     "twelvedata"]
    ph.clear_cache()


# ── Unknown suffixes and index timezones (red-team fix 2026-09-29) ──────────

@pytest.mark.parametrize("ticker, code, tz, bench", [
    ("D05.SI", "SG", "Asia/Singapore", "^STI"),
    ("247540.KQ", "KR", "Asia/Seoul", "^KQ11"),
    ("VOLV-B.ST", "SE", "Europe/Stockholm", "^OMX"),
    ("EQNR.OL", "NO", "Europe/Oslo", "OSEBX.OL"),
    ("BMW.F", "DE", "Europe/Berlin", "^GDAXI"),
    ("BBCA.JK", "ID", "Asia/Jakarta", "^JKSE"),
])
def test_added_exchange_suffixes(ticker, code, tz, bench):
    m = market_for(ticker)
    assert (m.code, m.tz, m.benchmark, m.asset_class) == (code, tz, bench, "equity")
    assert m.cost_bps == market_for("SAP.DE").cost_bps          # existing non-US default
    assert is_shadow_tradable(ticker)


@pytest.mark.parametrize("ticker", ["2222.SR", "XYZ.QQ", "ABC.NE"])
def test_unknown_suffix_is_not_us_and_not_settleable(ticker):
    from marketmind.markets import UNKNOWN, is_settleable
    m = market_for(ticker)
    assert m is UNKNOWN and m.benchmark == CASH and m.code != "US"
    assert not is_shadow_tradable(ticker) and not is_settleable(ticker)
    assert is_settleable("AAPL") and is_settleable("0700.HK")


def test_dotted_us_share_class_stays_us():
    assert market_for("BRK.B").code == "US" and market_for("BF.A").code == "US"


@pytest.mark.parametrize("ticker, tz", [
    ("^MXX", "America/Mexico_City"), ("^N225", "Asia/Tokyo"), ("^GDAXI", "Europe/Berlin"),
    ("^HSI", "Asia/Hong_Kong"), ("^TASI.SR", "Asia/Riyadh"), ("^GSPC", "America/New_York"),
])
def test_indices_use_their_home_exchange_timezone(ticker, tz):
    m = market_for(ticker)
    assert (m.code, m.tz, m.benchmark, m.asset_class) == ("INDEX", tz, CASH, "index")
    assert not is_shadow_tradable(ticker)


def test_index_bar_completes_at_its_home_close():
    d = _bars("2026-09-24", "2026-09-25")
    # 15:30 Mexico City (21:30 UTC): ^MXX closed at 15:00 local; a New York index would
    # also be closed, so check 14:00 local (20:00 UTC) - still open in Mexico City.
    assert len(complete_bars("^MXX", d, datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc))) == 1
    assert len(complete_bars("^MXX", d, datetime(2026, 9, 25, 21, 30, tzinfo=timezone.utc))) == 2
    # ^N225 closes 15:30 Tokyo = 06:30 UTC, long before New York opens
    assert len(complete_bars("^N225", d, datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc))) == 2


def test_dollar_index_is_a_new_york_index_until_1700():
    m = market_for("DX-Y.NYB")
    assert m.asset_class == "index" and m.tz == "America/New_York" and m.close.hour == 17
    assert not is_shadow_tradable("DX-Y.NYB")
