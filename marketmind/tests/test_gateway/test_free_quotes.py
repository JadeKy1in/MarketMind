"""Stooq / baostock / FinMind / EODHD sources and close-only repair (offline, mocked HTTP)."""
import logging

import httpx
import pytest

from marketmind.gateway import free_quotes as fq
from marketmind.gateway import global_quotes as gq
from marketmind.gateway import price_history as ph
from marketmind.gateway.price_history import Bar, PriceHistory

# captured before the conftest stubs replace them
_real_stooq = fq.from_stooq
_real_baostock = fq.from_baostock
_real_finmind = fq.from_finmind
_real_eodhd = fq.from_eodhd

SECRET = "SeCrEtKeY123"

# recorded 2026-10-02 from this machine (key-less request): HTTP 200, text/html
STOOQ_CHALLENGE = (
    '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" '
    'content="noindex,nofollow"></head><body><noscript>This site requires JavaScript to '
    'verify your browser. Please enable JavaScript and reload.</noscript><script>...</script>'
    '</body></html>')
STOOQ_CSV = ("Date,Open,High,Low,Close,Volume\n"
             "2026-09-24,46.10,46.90,45.80,46.50,1200\n"
             "2026-09-25,46.50,47.20,46.00,47.00,1500\n"
             "2026-09-28,bad,1,1,1,1\n")
# recorded 2026-10-02: api.finmindtrade.com TaiwanStockPrice 2330 (trimmed)
FINMIND_OK = {"msg": "success", "status": 200, "data": [
    {"date": "2026-09-21", "stock_id": "2330", "Trading_Volume": 16086510,
     "Trading_money": 39772729100, "open": 2445.0, "max": 2485.0, "min": 2445.0,
     "close": 2480.0, "spread": 20.0, "Trading_turnover": 69432},
    {"date": "2026-09-22", "stock_id": "2330", "Trading_Volume": 22009927,
     "Trading_money": 54678491997, "open": 2505.0, "max": 2510.0, "min": 2460.0,
     "close": 2460.0, "spread": -20.0, "Trading_turnover": 107604}]}


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(fq, "_stooq_disabled", None)
    monkeypatch.setattr(fq, "_bs_disabled", None)
    monkeypatch.setattr(fq, "_fm_disabled", None)
    monkeypatch.setattr(fq, "_eodhd_disabled", None)
    monkeypatch.setattr(fq, "_skipped", set())
    monkeypatch.setattr(fq, "_eodhd_exhausted_logged", set())
    monkeypatch.setattr(fq, "STOOQ_MIN_INTERVAL_S", 0.0)
    for var in ("STOOQ_API_KEY", "EODHD_API_KEY", "FINMIND_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    ph.clear_cache()
    yield
    ph.clear_cache()


def _mock(monkeypatch, handler):
    """Route free_quotes HTTP through `handler`; returns the list of requests seen."""
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)
    monkeypatch.setattr(fq, "_client", lambda headers=None: httpx.AsyncClient(
        transport=httpx.MockTransport(wrapped), headers=headers or fq.HEADERS))
    return seen


# ── Stooq ───────────────────────────────────────────────────────────────────

def test_stooq_symbol_mapping():
    assert fq.stooq_symbol("7203.T") == "7203.jp"
    assert fq.stooq_symbol("0700.HK") == "700.hk"
    assert fq.stooq_symbol("09866.HK") == "9866.hk"
    assert fq.stooq_symbol("SAP.DE") == "sap.de"
    assert fq.stooq_symbol("HSBA.L") == "hsba.uk"
    assert fq.stooq_symbol("SI=F") == "si.f" and fq.stooq_symbol("PL=F") == "pl.f"
    assert fq.stooq_symbol("EURUSD=X") == "eurusd" and fq.stooq_symbol("JPY=X") == "usdjpy"
    assert fq.stooq_symbol("^N225") == "^nkx" and fq.stooq_symbol("^FTSE") == "^ukx"
    for t in ("AAPL", "BTC-USD", "ZF=F", "MC.PA", "600519.SS", "^XYZ", ""):
        assert fq.stooq_symbol(t) is None


def test_stooq_body_is_validated_not_the_status():
    assert fq.classify_stooq_body(STOOQ_CSV) == "csv"
    assert fq.classify_stooq_body("﻿" + STOOQ_CSV) == "csv"
    assert fq.classify_stooq_body(STOOQ_CHALLENGE) == "challenge"
    assert fq.classify_stooq_body("Exceeded the daily hits limit") == "quota"
    assert fq.classify_stooq_body("Get your apikey: https://stooq.com/...") == "apikey"
    assert fq.classify_stooq_body("No data") == "nodata"
    assert fq.classify_stooq_body("") == "nodata"
    assert fq.classify_stooq_body("Something else") == "unknown"


def test_parse_stooq_csv_skips_bad_rows_and_fx_without_volume():
    bars = fq.parse_stooq_csv(STOOQ_CSV)
    assert [b.date for b in bars] == ["2026-09-24", "2026-09-25"]
    assert (bars[1].open, bars[1].high, bars[1].low, bars[1].close, bars[1].volume) == \
        (46.5, 47.2, 46.0, 47.0, 1500)
    fx = fq.parse_stooq_csv("Date,Open,High,Low,Close\n2026-09-25,1.17,1.18,1.16,1.175\n")
    assert fx[0].volume == 0.0 and fx[0].high == 1.18
    # inconsistent row (high below close) is rejected, not repaired
    assert fq.parse_stooq_csv("Date,Open,High,Low,Close,Volume\n2026-09-25,5,4,3,4.5,1\n") == []


@pytest.mark.asyncio
async def test_stooq_ok_and_key_never_logged(monkeypatch, caplog):
    monkeypatch.setenv("STOOQ_API_KEY", SECRET)
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=STOOQ_CSV))
    with caplog.at_level(logging.DEBUG):
        hist = await _real_stooq("SI=F")
    assert hist.source == "stooq" and hist.daily[-1].close == 47.0 and hist.weekly
    q = seen[0].url.params
    assert q["s"] == "si.f" and q["i"] == "d" and q["apikey"] == SECRET
    # httpx logged the request URL at INFO; the filter masked the key
    assert any("HTTP Request" in r.getMessage() for r in caplog.records)
    assert SECRET not in caplog.text and "apikey=***" in caplog.text


@pytest.mark.asyncio
async def test_stooq_challenge_page_disables_for_the_run(monkeypatch, caplog):
    monkeypatch.setenv("STOOQ_API_KEY", SECRET)
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=STOOQ_CHALLENGE))
    with caplog.at_level(logging.WARNING, logger="marketmind.gateway.free_quotes"):
        assert await _real_stooq("7203.T") is None
        assert await _real_stooq("SAP.DE") is None
    assert len(seen) == 1 and "browser" in fq._stooq_disabled
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_stooq_quota_disables_but_no_data_does_not(monkeypatch):
    monkeypatch.setenv("STOOQ_API_KEY", SECRET)
    replies = {"7203.jp": "No data", "sap.de": "Exceeded the daily hits limit"}
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=replies[r.url.params["s"]]))
    assert await _real_stooq("7203.T") is None
    assert fq._stooq_disabled is None                  # an unknown symbol is not fatal
    assert await _real_stooq("SAP.DE") is None
    assert fq._stooq_disabled == "daily request limit reached"
    assert await _real_stooq("7203.T") is None and len(seen) == 2


@pytest.mark.asyncio
async def test_stooq_without_key_is_skipped_with_one_debug_log(monkeypatch, caplog):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=STOOQ_CSV))
    with caplog.at_level(logging.DEBUG, logger="marketmind.gateway.free_quotes"):
        assert await _real_stooq("7203.T") is None
        assert await _real_stooq("SAP.DE") is None
    assert seen == []
    msgs = [r for r in caplog.records if "STOOQ_API_KEY" in r.getMessage()]
    assert len(msgs) == 1 and msgs[0].levelno == logging.DEBUG


def test_redact_masks_every_secret_param():
    url = f"https://x/y?s=a&apikey={SECRET}&api_token={SECRET}&token={SECRET}&fmt=json"
    out = fq.redact(url)
    assert SECRET not in out and out.count("***") == 3 and "fmt=json" in out


# ── baostock ────────────────────────────────────────────────────────────────

def test_baostock_code_and_parse_drops_suspended_days():
    assert fq.baostock_code("600519.SS") == "sh.600519"
    assert fq.baostock_code("000001.SZ") == "sz.000001"
    assert fq.baostock_code("0700.HK") is None and fq.baostock_code("AAPL") is None
    # recorded 2026-10-02 (baostock 0.9.4, sh.600519, adjustflag=2) + a suspended row
    rows = [["2026-09-22", "1252.15", "1265.88", "1248.10", "1253.80", "2457294", "1"],
            ["2026-09-23", "1255.03", "1271.50", "1250.89", "1251.24", "3098122", "1"],
            ["2026-09-24", "1251.24", "1251.24", "1251.24", "1251.24", "0", "0"],
            ["2026-09-25", "", "", "", "", "", "1"]]
    bars = fq.parse_baostock(rows)
    assert [b.date for b in bars] == ["2026-09-22", "2026-09-23"]
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == \
        (1252.15, 1265.88, 1248.10, 1253.80)


@pytest.mark.asyncio
async def test_from_baostock_runs_in_worker_and_fails_soft(monkeypatch):
    calls = []

    def fake_sync(code, start, end):
        calls.append(code)
        return [["2026-09-22", "10", "11", "9.5", "10.5", "100", "1"]]
    monkeypatch.setattr(fq, "_baostock_sync", fake_sync)
    hist = await _real_baostock("600519.SS")
    assert hist.source == "baostock" and calls == ["sh.600519"]
    assert await _real_baostock("SAP.DE") is None and calls == ["sh.600519"]

    def boom(code, start, end):
        raise RuntimeError("login failed: 10001 network")
    monkeypatch.setattr(fq, "_baostock_sync", boom)
    assert await _real_baostock("600519.SS") is None


# ── FinMind ─────────────────────────────────────────────────────────────────

def test_finmind_parse_uses_max_min():
    bars = fq.parse_finmind(FINMIND_OK)
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close, bars[0].volume) == \
        (2445.0, 2485.0, 2445.0, 2480.0, 16086510)
    assert fq.finmind_id("2330.TW") == "2330" and fq.finmind_id("6488.TWO") == "6488"
    assert fq.finmind_id("0700.HK") is None


@pytest.mark.asyncio
async def test_finmind_token_goes_in_header_and_errors_fail_soft(monkeypatch, caplog):
    monkeypatch.setenv("FINMIND_TOKEN", SECRET)
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=FINMIND_OK))
    with caplog.at_level(logging.DEBUG):
        hist = await _real_finmind("2330.TW")
    assert hist.source == "finmind" and hist.daily[-1].close == 2460.0
    assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(seen[0].url) and SECRET not in caplog.text
    # recorded 2026-10-02: invalid token answer echoes a token tail; only msg is logged
    _mock(monkeypatch, lambda r: httpx.Response(200, json={
        "msg": "Token is illegal.", "status": 400, "token_tail": "...Y123"}))
    with caplog.at_level(logging.WARNING):
        assert await _real_finmind("2330.TW") is None
    assert "Y123" not in caplog.text and fq._fm_disabled is None
    _mock(monkeypatch, lambda r: httpx.Response(200, json={
        "msg": "Requests reach the upper limit.", "status": 402}))
    assert await _real_finmind("2330.TW") is None and fq._fm_disabled == "request limit"


@pytest.mark.asyncio
async def test_finmind_works_without_token(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=FINMIND_OK))
    assert (await _real_finmind("2330.TW")).source == "finmind"
    assert "Authorization" not in seen[0].headers


# ── EODHD ───────────────────────────────────────────────────────────────────

def test_eodhd_symbol_mapping():
    assert fq.eodhd_symbol("AAPL") == "AAPL.US" and fq.eodhd_symbol("BRK-B") == "BRK-B.US"
    assert fq.eodhd_symbol("BRK.B") == "BRK-B.US"
    assert fq.eodhd_symbol("7203.T") == "7203.TSE" and fq.eodhd_symbol("SAP.DE") == "SAP.XETRA"
    assert fq.eodhd_symbol("0700.HK") == "0700.HK" and fq.eodhd_symbol("09866.HK") == "9866.HK"
    assert fq.eodhd_symbol("HSBA.L") == "HSBA.LSE" and fq.eodhd_symbol("600519.SS") == "600519.SHG"
    assert fq.eodhd_symbol("EURUSD=X") == "EURUSD.FOREX" and fq.eodhd_symbol("JPY=X") == "USDJPY.FOREX"
    assert fq.eodhd_symbol("BTC-USD") == "BTC-USD.CC" and fq.eodhd_symbol("^GSPC") == "GSPC.INDX"
    for t in ("CL=F", "2222.SR", "^XYZ", ""):
        assert fq.eodhd_symbol(t) is None


def test_eodhd_parse_scales_to_adjusted_close():
    bars = fq.parse_eodhd([
        {"date": "2026-09-24", "open": 100, "high": 110, "low": 90, "close": 100,
         "adjusted_close": 50, "volume": 7},
        {"date": "2026-09-25", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
        {"date": "2026-09-26", "open": None}])
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (50, 55, 45, 50)
    assert bars[1].close == 10 and len(bars) == 2


def test_eodhd_budget_never_exceeds_limit_and_prunes_old_days():
    d = fq._budget_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-09-30.01").write_text("")
    assert all(fq.take_eodhd_slot("2026-10-02") for _ in range(fq.EODHD_DAILY_LIMIT))
    assert fq.take_eodhd_slot("2026-10-02") is False
    assert fq.eodhd_calls_used("2026-10-02") == fq.EODHD_DAILY_LIMIT == 20
    assert not (d / "2026-09-30.01").exists()
    assert fq.take_eodhd_slot("2026-10-03") is True           # a new UTC day resets
    assert fq.eodhd_calls_used("2026-10-03") == 1


@pytest.mark.asyncio
async def test_eodhd_stops_at_budget_and_never_logs_key(monkeypatch, caplog):
    monkeypatch.setenv("EODHD_API_KEY", SECRET)
    rows = [{"date": "2026-09-25", "open": 1, "high": 2, "low": 0.5, "close": 1.5,
             "adjusted_close": 1.5, "volume": 3}]
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=rows))
    with caplog.at_level(logging.DEBUG):
        for _ in range(fq.EODHD_DAILY_LIMIT + 5):
            await _real_eodhd("AAPL")
    assert len(seen) == fq.EODHD_DAILY_LIMIT
    assert seen[0].url.path == "/api/eod/AAPL.US" and seen[0].url.params["api_token"] == SECRET
    assert SECRET not in caplog.text
    assert sum("budget" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_eodhd_auth_error_disables_and_no_key_takes_no_slot(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(401, text="Unauthenticated"))
    assert await _real_eodhd("AAPL") is None
    assert seen == [] and fq.eodhd_calls_used() == 0          # no key: no request, no slot
    monkeypatch.setenv("EODHD_API_KEY", SECRET)
    assert await _real_eodhd("AAPL") is None
    assert await _real_eodhd("MSFT") is None
    assert len(seen) == 1 and fq._eodhd_disabled == "HTTP 401"
    assert await _real_eodhd("CL=F") is None and await _real_eodhd("2222.SR") is None


# ── routing ─────────────────────────────────────────────────────────────────

def _src(order, name, ok=False):
    async def f(ticker, years=5):
        order.append(name)
        if not ok:
            return None
        daily = [Bar("2026-09-25", 1.0, 1.2, 0.9, 1.1, 10.0)]
        return PriceHistory(ticker=ticker, source=name, daily=daily, weekly=ph.to_weekly(daily))
    return f


def _install(monkeypatch, order, winner):
    async def no_yahoo(t, y):
        order.append("yahoo")
        return None
    monkeypatch.setattr(ph, "_from_yfinance", no_yahoo)
    for name in ("eastmoney", "tencent", "twelvedata"):
        monkeypatch.setattr(gq, f"from_{name}", _src(order, name, name == winner))
    for name in ("baostock", "stooq", "finmind", "eodhd"):
        monkeypatch.setattr(fq, f"from_{name}", _src(order, name, name == winner))


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, winner, expected", [
    ("600519.SS", "baostock", ["yahoo", "tencent", "baostock"]),
    ("7203.T", "stooq", ["yahoo", "tencent", "baostock", "eastmoney", "stooq"]),
    ("2330.TW", "finmind", ["yahoo", "tencent", "baostock", "eastmoney", "stooq", "finmind"]),
    ("SAP.DE", "eodhd", ["yahoo", "tencent", "baostock", "eastmoney", "stooq", "finmind",
                         "twelvedata", "eodhd"]),
])
async def test_routing_order(monkeypatch, ticker, winner, expected):
    order = []
    _install(monkeypatch, order, winner)
    hist = await ph.get_price_history(ticker)
    assert hist.source == winner and order == expected


@pytest.mark.asyncio
async def test_us_reaches_eodhd_only_after_nasdaq_and_twelvedata(monkeypatch):
    order = []
    _install(monkeypatch, order, "eodhd")

    async def no_nasdaq(t, y):
        order.append("nasdaq")
        return None
    monkeypatch.setattr(ph, "_from_nasdaq", no_nasdaq)
    hist = await ph.get_price_history("AAPL")
    assert hist.source == "eodhd" and order == ["yahoo", "nasdaq", "twelvedata", "eodhd"]


# ── close-only repair ───────────────────────────────────────────────────────

def _co(d, c):
    return Bar(d, c, c, c, c, 0.0)


def test_repair_fills_and_scales_only_matching_closes():
    daily = [_co("2026-09-23", 100.0), _co("2026-09-24", 100.0), _co("2026-09-25", 100.0),
             _co("2026-09-28", 100.0), _co("2026-09-29", 100.0),
             Bar("2026-09-30", 99, 101, 98, 100, 5)]
    ref = [Bar("2026-09-23", 99.0, 102.0, 98.0, 100.4, 50),     # +0.4%: within 0.5%
           Bar("2026-09-24", 99.0, 102.0, 98.0, 101.0, 50),     # +1.0%: rejected
           _co("2026-09-25", 100.0),                            # reference is close-only too
           Bar("2026-09-28", 99.0, 99.5, 98.0, 100.0, 50),      # inconsistent (high < close)
           Bar("2026-09-30", 1, 2, 0.5, 1.5, 1)]                # our bar is already full
    fixed = ph.repair_close_only(daily, ref)
    assert fixed == ["2026-09-23"]
    b = daily[0]
    k = 100.0 / 100.4
    assert b.close == 100.0 and b.volume == 50 and not ph.is_close_only(b)
    assert (b.open, b.high, b.low) == pytest.approx((99.0 * k, 102.0 * k, 98.0 * k))
    assert b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)
    assert all(ph.is_close_only(x) for x in daily[1:5])          # left flagged
    assert daily[5].open == 99


def test_repair_tolerance_boundary():
    assert ph.REPAIR_CLOSE_TOLERANCE == 0.005
    ref = [Bar("2026-09-23", 99.0, 102.0, 98.0, 100.5, 1)]       # exactly 0.5%
    assert ph.repair_close_only([_co("2026-09-23", 100.0)], ref) == ["2026-09-23"]
    ref = [Bar("2026-09-23", 99.0, 102.0, 98.0, 100.51, 1)]
    assert ph.repair_close_only([_co("2026-09-23", 100.0)], ref) == []


@pytest.mark.asyncio
async def test_get_price_history_repairs_recent_close_only_bars(monkeypatch, caplog):
    daily = [Bar("2026-09-22", 1791.1, 1822.6, 1788.0, 1822.6, 36.0),
             _co("2026-09-23", 1745.7), _co("2026-09-24", 1749.1),
             Bar("2026-09-28", 1736.6, 1741.2, 1716.0, 1721.4, 1881.0)]

    async def fake_yf(ticker, years):
        return PriceHistory(ticker=ticker, source="yfinance", daily=daily,
                            weekly=ph.to_weekly(daily))
    calls = []

    async def fake_stooq(ticker, years=5):
        calls.append((ticker, years))
        ref = [Bar("2026-09-23", 1750.0, 1760.0, 1730.0, 1746.0, 900),
               Bar("2026-09-24", 1740.0, 1770.0, 1735.0, 1790.0, 800)]   # 2.3% off: no
        return PriceHistory(ticker=ticker, source="stooq", daily=ref, weekly=ph.to_weekly(ref))
    monkeypatch.setattr(ph, "_from_yfinance", fake_yf)
    monkeypatch.setattr(fq, "from_stooq", fake_stooq)
    with caplog.at_level(logging.INFO, logger="marketmind.gateway.price_history"):
        hist = await ph.get_price_history("PL=F")
    assert calls == [("PL=F", 2)]
    assert hist.source == "yfinance+stooq"
    assert [b.close_only for b in hist.daily] == [False, False, True, False]
    assert hist.daily[1].close == 1745.7 and hist.daily[1].high > hist.daily[1].low
    msgs = [r.getMessage() for r in caplog.records]
    assert any("repaired from stooq: 2026-09-23" in m for m in msgs)
    warn = [m for m in msgs if "close-only bar(s), range unknown" in m]
    assert len(warn) == 1 and "2026-09-24" in warn[0] and "2026-09-23" not in warn[0]
    assert hist.weekly[-2].high == max(b.high for b in hist.daily[:3])


@pytest.mark.asyncio
async def test_repair_skips_the_primary_source_and_old_bars(monkeypatch):
    calls = []

    async def fake_stooq(ticker, years=5):
        calls.append("stooq")
        return None
    monkeypatch.setattr(fq, "from_stooq", fake_stooq)
    # only bars older than the lookback are close-only: no repair request at all
    old = [_co("2020-01-02", 5.0)] + [Bar(f"d{i:04d}", 1, 2, 0.5, 1.5, 1)
                                      for i in range(ph.REPAIR_LOOKBACK_BARS)]
    hist = PriceHistory(ticker="SI=F", source="yfinance", daily=old)
    await ph._repair_recent_close_only(hist)
    assert calls == [] and hist.source == "yfinance"
    # a Stooq series is never repaired from Stooq again
    hist = PriceHistory(ticker="SI=F", source="stooq", daily=[_co("2026-09-23", 5.0)])
    await ph._repair_recent_close_only(hist)
    assert calls == [] and hist.source == "stooq"


@pytest.mark.asyncio
async def test_repair_reference_order_by_market(monkeypatch):
    order = []
    for name in ("stooq", "baostock", "finmind"):
        monkeypatch.setattr(fq, f"from_{name}", _src(order, name, ok=(name == "finmind")))
    monkeypatch.setattr(gq, "from_tencent", _src(order, "tencent"))
    ref = await fq.repair_reference("2330.TW", exclude="yfinance")
    assert ref.source == "finmind" and order == ["stooq", "baostock", "finmind"]
    order.clear()
    monkeypatch.setattr(fq, "from_finmind", _src(order, "finmind"))
    monkeypatch.setattr(fq, "from_eodhd", _src(order, "eodhd", ok=True))
    assert await fq.repair_reference("0700.HK", exclude="tencent") is None
    assert order == ["stooq", "baostock", "finmind"]                 # never EODHD
