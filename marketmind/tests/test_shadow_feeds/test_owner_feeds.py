"""Volatility / sentiment / company-event feeds, offline over recorded payloads
(samples/ were recorded from the live endpoints on 2026-09-28)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import marketmind.shadow_feeds as sf
from marketmind.holdings import inspect as hi
from marketmind.holdings import store as hs
from marketmind.shadow_feeds import company_events as ce
from marketmind.shadow_feeds import sentiment, volatility

SAMPLES = Path(__file__).parent / "samples"


def _text(name):
    return (SAMPLES / name).read_text("utf-8")


def _mock(module, monkeypatch, handler):
    monkeypatch.setattr(module, "_TRANSPORT", httpx.MockTransport(handler))


# ── volatility ──────────────────────────────────────────────────────────────

def _cboe(request):
    sym = request.url.path.rsplit("/", 1)[-1].replace("_History.csv", "")
    return httpx.Response(200, text=_text(f"cboe_{sym}.csv"))


@pytest.mark.asyncio
async def test_volatility_lines(monkeypatch):
    _mock(volatility, monkeypatch, _cboe)
    lines = await volatility.fetch("2026-09-28")
    text = "\n".join(lines)
    assert lines[0] == "- VIX 14.87 (Cboe close 2026-09-25, -0.80 vs 2026-09-24)"
    assert "VIX9D/VIX 0.858 on 2026-09-25" in text          # 12.76 / 14.87
    assert "VIX/VIX3M 0.829 on 2026-09-25 (<1: contango" in text   # 14.87 / 17.93
    assert "VIX 20-day percentile" in text and "SKEW 144.91 (Cboe close 2026-09-25" in text
    assert len(lines) <= 12


def test_volatility_backwardation_and_bad_csv():
    h = {"VIX": [("2026-09-24", 30.0), ("2026-09-25", 40.0)],
         "VIX9D": [("2026-09-25", 50.0)], "VIX3M": [("2026-09-25", 32.0)],
         "SKEW": [("2026-09-25", 120.0)]}
    text = "\n".join(volatility.build_lines(h))
    assert "VIX/VIX3M 1.250" in text and "backwardation" in text
    assert "VIX 2-day percentile 100%" in text
    with pytest.raises(ValueError):
        volatility.parse_history("<html>blocked</html>")


@pytest.mark.asyncio
async def test_volatility_http_error_raises(monkeypatch):
    _mock(volatility, monkeypatch, lambda r: httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        await volatility.fetch("2026-09-28")


# ── sentiment ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fear_greed_lines_and_browser_headers(monkeypatch):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json=json.loads(_text("cnn_fear_greed.json")))
    _mock(sentiment, monkeypatch, handler)
    lines = await sentiment.fetch("2026-09-28")
    text = "\n".join(lines)
    assert "Chrome" in seen["ua"]
    assert lines[0] == "- Fear & Greed 36.9/100 (fear), as of 2026-09-28 13:38 UTC"
    assert "previous close 37.0; 1 week ago 34.2; 1 month ago 53.7" in lines[1]
    assert "S&P 500 7743.41 vs 125-day avg 7426.00 (+4.3%)" in text
    assert "Junk bond demand: 60.2 greed" in text and "1.23 pp" in text
    assert "unofficial" in sentiment.FEEDS[0].title
    assert len(lines) <= 12


def test_fear_greed_without_components():
    d = {"fear_and_greed": {"score": 80, "rating": "extreme greed",
                            "timestamp": "2026-09-28T13:38:48+00:00"}}
    assert sentiment.build_lines(d) == ["- Fear & Greed 80.0/100 (extreme greed), as of 2026-09-28 13:38 UTC"]


# ── company events ──────────────────────────────────────────────────────────

@pytest.fixture
def finnhub(monkeypatch):
    monkeypatch.setenv("FINNHUB_KEY", "test-key")
    monkeypatch.setattr(ce, "MIN_SPACING_S", 0)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.params["token"] == "test-key"
        if request.url.path.endswith("/calendar/earnings"):
            return httpx.Response(200, json=json.loads(_text("finnhub_earnings.json")))
        sym = request.url.params["symbol"]
        if sym == "TSLA":
            return httpx.Response(200, json=json.loads(_text("finnhub_insider_TSLA.json")))
        if sym == "PLTR":
            return httpx.Response(200, json={"data": [
                {"name": "A", "change": 1000, "transactionPrice": 20.0, "transactionCode": "P",
                 "transactionDate": "2026-09-10", "isDerivative": False},
                {"name": "B", "change": -100, "transactionPrice": 20.0, "transactionCode": "S",
                 "transactionDate": "2026-07-01", "isDerivative": False}]})   # outside window
        if sym == "SMCI":
            return httpx.Response(500)
        return httpx.Response(200, json={"data": [], "symbol": sym})
    _mock(ce, monkeypatch, handler)
    return calls


def test_watched_stocks_skip_etfs_crypto_futures_foreign():
    w = ce.watched_stocks()
    assert {"TSLA", "NVDA", "JPM", "NKE", "CELH"} <= set(w)
    assert not {"SPY", "QQQ", "XLF", "KRE", "IWM"} & set(w)
    assert not any("." in t or "=" in t or t.endswith("-USD") or t[0].isdigit() for t in w)
    assert len(w) == len(set(w))
    assert w[:3] == ["TSLA", "AAPL", "NVDA"]      # round-robin: bear_tracker, news_hound, silicon_oracle


@pytest.mark.asyncio
async def test_earnings_feed_filters_to_watchlist(finnhub):
    lines = await ce.fetch_earnings("2026-09-28")
    assert lines == ["- 2026-09-28 NKE (time n/a): Q1 2027, EPS est 0.44, revenue est $11.45B"]
    assert len(finnhub) == 1 and finnhub[0].url.params["to"] == "2026-10-12"


def test_earnings_lines_when_nothing_scheduled():
    assert "none of the 3 watched US stocks report" in \
        ce.earnings_lines({}, ["A", "B", "C"], "2026-09-28", "2026-10-12")[0]


@pytest.mark.asyncio
async def test_insider_feed_nets_open_market_trades(finnhub, monkeypatch):
    monkeypatch.setattr(ce, "INSIDER_MAX_TICKERS", 4)
    monkeypatch.setattr(ce, "watched_stocks", lambda: ["TSLA", "PLTR", "SMCI", "AAPL", "NVDA"])
    lines = await ce.fetch_insiders("2026-09-28")
    # TSLA: one non-derivative S of 2606 sh @ 360.134; the M rows are option exercises
    assert lines[0] == "- TSLA: net sell $939K (0 buys $0, 1 sells $939K; 1 insider)"
    assert lines[1] == "- PLTR: net buy $20K (1 buys $20K, 0 sells $0; 1 insider)"
    assert lines[-1].startswith("- 2 of 4 checked US stocks") and "1 more not checked" in lines[-1]
    assert "lookup failed for SMCI" in lines[-1]
    assert len(finnhub) == 4


@pytest.mark.asyncio
async def test_insider_feed_raises_when_all_fail(monkeypatch):
    monkeypatch.setenv("FINNHUB_KEY", "k")
    monkeypatch.setattr(ce, "MIN_SPACING_S", 0)
    monkeypatch.setattr(ce, "watched_stocks", lambda: ["AAPL", "MSFT"])
    _mock(ce, monkeypatch, lambda r: httpx.Response(429))
    with pytest.raises(RuntimeError):
        await ce.fetch_insiders("2026-09-28")


@pytest.mark.asyncio
async def test_missing_key_shows_unavailable_line(monkeypatch):
    monkeypatch.setattr(ce, "finnhub_key", lambda: (_ for _ in ()).throw(RuntimeError("FINNHUB_KEY not set")))
    out = await sf._run(ce.FEEDS[0], "2026-09-28")
    assert out == [f"- {ce.FEEDS[0].title}: data unavailable today (RuntimeError)"]


def test_feeds_are_discovered_and_serve_owner_named_shadows():
    by = {f.name: f for f in sf.discover()}
    assert set(by["cboe_vol_term"].shadows) == {"vega_trader", "vol_surfer", "crash_hunter", "cycle_reader"}
    assert set(by["cnn_fear_greed"].shadows) == {"fade_master", "vol_surfer", "crash_hunter"}
    assert set(by["finnhub_earnings"].shadows) == set(by["finnhub_insiders"].shadows) == {
        "bear_tracker", "news_hound", "silicon_oracle", "trial_reviewer", "wallet_watcher",
        "bank_examiner", "factory_floor", "squeeze_watch"}
    from marketmind.shadows.v3 import roster
    names = {e.name for e in roster.ROSTER}
    assert all(set(f.shadows) <= names for f in by.values())


# ── holdings earnings note ──────────────────────────────────────────────────

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_holdings_reason_notes_earnings_without_changing_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    holdings = [hs.Holding("NKE", 1, 100.0, "2026-09-01"), hs.Holding("GONE", 1, 10.0, "2026-09-01")]

    async def history(t):
        return None
    seen = {}

    async def earnings(tickers, start, days):
        seen.update(tickers=tickers, start=start, days=days)
        return {"NKE": [{"symbol": "NKE", "date": "2026-10-01", "hour": "amc"}]}
    reports = await hi.inspect_holdings(holdings, history_fn=history, now=NOW, earnings_fn=earnings)
    by = {r.ticker: r for r in reports}
    assert seen == {"tickers": ["NKE", "GONE"], "start": "2026-09-28", "days": 7}
    assert by["NKE"].verdict == hi.UNAVAILABLE
    assert "7 天内有财报（2026-10-01 盘后" in by["NKE"].reason
    assert "财报" not in by["GONE"].reason

    async def broken(tickers, start, days):
        raise httpx.ConnectError("down")
    reports = await hi.inspect_holdings(holdings, history_fn=history, now=NOW, earnings_fn=broken)
    assert [r.verdict for r in reports] == [hi.UNAVAILABLE, hi.UNAVAILABLE]
    assert all("财报" not in r.reason for r in reports)


@pytest.mark.asyncio
async def test_holdings_finnhub_helper_uses_company_events(finnhub):
    found = await hi.finnhub_earnings(["nke", "AAPL"], "2026-09-28", 7)
    assert list(found) == ["NKE"] and finnhub[0].url.params["to"] == "2026-10-05"
