"""Offline tests for marketmind.universe (docs/S2_DESIGN.md §2)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from marketmind.universe import (
    classify,
    is_tradable,
    load_equity_universe,
    reset_equity_universe,
    set_equity_universe,
)
from marketmind.universe.equities import (
    CACHE_FILENAME,
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
    normalise_symbol,
    parse_nasdaq_listed,
    parse_other_listed,
)

NASDAQ_TXT = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N\n"
    "ABCDW|ABCD Acquisition Corp - Warrant|S|N|N|100|N|N\n"
    "ZXZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N\n"
    "File Creation Time: 0925202621:31|||||||\n"
)
OTHER_TXT = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
    "BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|100|N|BRK.B\n"
    "MKC.V|McCormick & Company, Incorporated Common Stock|N|MKC.V|N|100|N|MKC.V\n"
    "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
    "BFH$A|Bread Financial Preferred Series A|N|BFHpA|N|100|N|BFH-A\n"
    "AAC.U|Ares Acquisition Corporation III Units|N|AAC.U|N|100|N|AAC.U\n"
    "AAC.W|Ares Acquisition Corporation III Redeemable warrants|N|AAC.W|N|100|N|AAC.W\n"
    "AIIA.R|Some Rights|N|AIIA.R|N|100|N|AIIA.R\n"
    "BCAT.V|BlackRock Trust Rights when issued|N|BCAT.V|N|100|N|BCAT.V\n"
    "ABC=|Some Unit|A|ABC=|N|100|N|ABC=\n"
    "CTEST.S|NYSE Test Six Common Stock|N|CTEST.S|N|100|Y|CTEST.S\n"
    "File Creation Time: 0925202621:31||||||\n"
)
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _fetcher(calls: list[str] | None = None, fail: bool = False):
    def fetch(url: str) -> str:
        if calls is not None:
            calls.append(url)
        if fail:
            raise httpx.ConnectError("offline")
        return {NASDAQ_LISTED_URL: NASDAQ_TXT, OTHER_LISTED_URL: OTHER_TXT}[url]
    return fetch


@pytest.fixture(autouse=True)
def _isolate_module_cache():
    reset_equity_universe()
    yield
    reset_equity_universe()


@pytest.fixture
def universe(tmp_path):
    u = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(), now=NOW)
    set_equity_universe(u)
    return u


# ---- parsing and normalisation ----

def test_parse_nasdaq_drops_footer_and_test_issues():
    recs = {r.symbol: r for r in parse_nasdaq_listed(NASDAQ_TXT)}
    assert set(recs) == {"AAPL", "QQQ", "ABCDW"}
    assert recs["QQQ"].is_etf and not recs["AAPL"].is_etf
    assert recs["AAPL"].exchange == "NASDAQ"
    assert recs["AAPL"].name == "Apple Inc. - Common Stock"


def test_parse_other_normalises_and_excludes():
    recs = {r.symbol: r for r in parse_other_listed(OTHER_TXT)}
    assert set(recs) == {"BRK-B", "MKC-V", "SPY"}
    assert recs["SPY"].is_etf and recs["SPY"].exchange == "NYSE Arca"
    assert recs["BRK-B"].exchange == "NYSE"


def test_parse_rejects_missing_footer():
    truncated = NASDAQ_TXT.rsplit("File Creation Time", 1)[0]
    with pytest.raises(ValueError, match="footer"):
        parse_nasdaq_listed(truncated)


def test_parse_rejects_unexpected_header():
    with pytest.raises(ValueError, match="column"):
        parse_other_listed("Foo|Bar\nA|B\nFile Creation Time: x|\n")


@pytest.mark.parametrize("raw,name,expected", [
    ("BRK.B", "", "BRK-B"),
    ("BF.A", "", "BF-A"),
    ("aapl", "", "AAPL"),
    ("BFH$A", "", None),     # preferred
    ("ABR$", "", None),      # preferred without series
    ("XYZ=", "", None),      # unit
    ("XYZ^", "", None),      # right
    ("XYZ#", "", None),      # when-issued
    ("AAC.U", "", None),
    ("AAC.W", "", None),
    ("AAC.WS", "", None),
    ("AIIA.R", "", None),
    ("BCAT.V", "Trust Rights when issued", None),
])
def test_normalise_symbol(raw, name, expected):
    assert normalise_symbol(raw, name) == expected


# ---- cache freshness and fallback ----

def test_download_writes_cache_then_fresh_cache_skips_network(tmp_path):
    calls: list[str] = []
    u = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(calls), now=NOW)
    assert u is not None and not u.from_cache
    assert u.counts() == {"total": 6, "stocks": 4, "etfs": 2}
    payload = json.loads((tmp_path / CACHE_FILENAME).read_text(encoding="utf-8"))
    assert payload["fetched_at"].startswith("2026-09-27")

    calls.clear()
    u2 = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(calls),
                              now=NOW + timedelta(days=6))
    assert calls == []
    assert u2.from_cache and not u2.stale and "BRK-B" in u2


def test_stale_cache_triggers_refresh(tmp_path):
    load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(), now=NOW)
    calls: list[str] = []
    later = NOW + timedelta(days=8)
    u = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(calls), now=later)
    assert calls == [NASDAQ_LISTED_URL, OTHER_LISTED_URL]
    assert not u.from_cache and u.fetched_at == later


def test_download_failure_falls_back_to_cache_and_logs_date(tmp_path, caplog):
    load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(), now=NOW)
    with caplog.at_level(logging.WARNING, logger="marketmind.universe.equities"):
        u = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(fail=True),
                                 now=NOW + timedelta(days=30))
    assert u is not None and u.from_cache and u.stale
    assert "SPY" in u
    assert "2026-09-27" in caplog.text


def test_unavailable_when_no_cache_and_download_fails(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="marketmind.universe.equities"):
        assert load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(fail=True), now=NOW) is None
    assert "unavailable" in caplog.text


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / CACHE_FILENAME).write_text("{not json", encoding="utf-8")
    assert load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(fail=True), now=NOW) is None
    u = load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(), now=NOW)
    assert u is not None and "AAPL" in u


# ---- classification ----

@pytest.mark.parametrize("ticker,layer,asset_type", [
    ("AAPL", "tradable", "stock"),
    ("aapl ", "tradable", "stock"),
    ("QQQ", "tradable", "etf"),
    ("SPY", "tradable", "etf"),
    ("BRK.B", "tradable", "stock"),
    ("BRK-B", "tradable", "stock"),
    ("MKC.V", "tradable", "stock"),        # class letter, not the TSX-V suffix
    ("BTC-USD", "tradable", "crypto"),
    ("UNI7083-USD", "tradable", "crypto"),  # yfinance disambiguated id
    ("ZRX-USD", "unknown", "crypto"),       # unverified on Robinhood's page
    ("XMR-USD", "unknown", "crypto"),       # market data only on Robinhood
    ("/ES", "tradable", "future"),
    ("/ESZ26", "tradable", "future"),
    ("GC=F", "tradable", "future"),
    ("ZC=F", "linkage", "future"),
    ("EVENT:fed-cut-oct-2026", "tradable", "event_contract"),
    ("600900.SS", "linkage", "unknown"),
    ("0700.HK", "linkage", "unknown"),
    ("7203.T", "linkage", "unknown"),
    ("SAP.DE", "linkage", "unknown"),
    ("^GSPC", "linkage", "index"),
    ("EURUSD=X", "linkage", "unknown"),
    ("NOTREAL", "unknown", "unknown"),
    ("", "unknown", "unknown"),
])
def test_classify(universe, ticker, layer, asset_type):
    c = classify(ticker)
    assert (c.layer, c.asset_type) == (layer, asset_type)


def test_classification_fields(universe):
    c = classify("brk.b")
    assert c.ticker == "BRK-B" and c.source == "nasdaqtrader" and c.settleable
    f = classify("/NQ")
    assert f.layer == "tradable" and not f.settleable
    assert not classify("EVENT:x").settleable
    assert classify("ETH-USD").settleable


def test_is_tradable_with_universe(universe):
    assert is_tradable("AAPL") is True
    assert is_tradable("BTC-USD") is True
    assert is_tradable("/CL") is True
    assert is_tradable("600900.SS") is False
    assert is_tradable("^VIX") is False
    assert is_tradable("NOTREAL") is False


def test_is_tradable_when_universe_unavailable():
    set_equity_universe(None)
    assert is_tradable("AAPL") is None
    assert classify("AAPL").source == "equity_universe_unavailable"
    # Crypto, futures and foreign/index tickers do not need the equity universe.
    assert is_tradable("BTC-USD") is True
    assert is_tradable("/ES") is True
    assert is_tradable("0700.HK") is False
    assert is_tradable("^GSPC") is False


def test_lazy_load_happens_once(monkeypatch, tmp_path):
    import marketmind.universe.classifier as cls_mod
    calls = []

    def fake_load():
        calls.append(1)
        return load_equity_universe(cache_dir=tmp_path, fetcher=_fetcher(), now=NOW)

    monkeypatch.setattr(cls_mod, "load_equity_universe", fake_load)
    assert is_tradable("AAPL") is True
    assert is_tradable("SPY") is True
    assert len(calls) == 1


def test_import_has_no_network_side_effect():
    # Fresh interpreter: any HTTP call during import would exit with code 3.
    code = "; ".join([
        "import httpx, sys",
        "httpx.get = lambda *a, **k: sys.exit(3)",
        "import marketmind.universe",
        "import marketmind.universe.classifier as c",
        "assert c._universe is c._UNLOADED",
    ])
    root = Path(__file__).resolve().parents[3]
    proc = subprocess.run([sys.executable, "-c", code], cwd=root, timeout=60,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("MARKETMIND_LIVE_TESTS"),
                    reason="live NASDAQ Trader download; set MARKETMIND_LIVE_TESTS=1")
def test_live_nasdaq_trader_download(tmp_path):
    u = load_equity_universe(cache_dir=tmp_path)
    assert u is not None and not u.from_cache
    c = u.counts()
    assert c["stocks"] > 3000 and c["etfs"] > 1000
    assert "AAPL" in u and "BRK-B" in u and "SPY" in u
