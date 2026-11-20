"""Offline tests: Yahoo "not found" memory in gateway.price_history (2026-11-20).

3529.TW (a TPEx stock; Yahoo spells it .TWO) was asked from Yahoo on every run although
FinMind served it; yfinance logged "possibly delisted" daily.
"""
import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from marketmind.gateway import global_quotes
from marketmind.gateway import price_history as ph


def _hist(ticker, source):
    return ph.PriceHistory(ticker=ticker, source=source,
                           daily=[ph.Bar("2026-11-18", 1, 1, 1, 1, 0)])


@pytest.fixture
def world(monkeypatch):
    """Yahoo answers empty (or with data when state["yahoo_has"]); Tencent stands in
    for the later source that has the ticker."""
    state = {"yahoo_calls": 0, "yahoo_has": False, "day": "2026-11-01"}
    df_full = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
                            "Volume": [1]}, index=pd.to_datetime(["2026-11-18"]))

    def history(**kw):
        state["yahoo_calls"] += 1
        return df_full if state["yahoo_has"] else pd.DataFrame()

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.side_effect = history
    monkeypatch.setattr(ph, "yf", fake_yf)

    async def tencent(ticker, years):
        return _hist(ticker, "finmind")
    monkeypatch.setattr(global_quotes, "from_tencent", tencent)
    monkeypatch.setattr(ph, "_utc_today", lambda: state["day"])
    monkeypatch.setattr(ph, "_repair_recent_close_only", _noop)
    ph.clear_cache()
    yield state
    ph.clear_cache()


async def _noop(hist):
    return None


async def _run_day(state, day):
    state["day"] = day
    ph.clear_cache()                      # a new process each day: memory comes from the file
    return await ph.get_price_history("3529.TW")


def _day(n):
    return (date(2026, 11, 1) + timedelta(days=n)).isoformat()


@pytest.mark.asyncio
async def test_yahoo_skipped_after_three_days_then_retried(world):
    for n in range(ph.YAHOO_MISS_DAYS):
        hist = await _run_day(world, _day(n))
        assert hist is not None and hist.source == "finmind"   # data still served
    assert world["yahoo_calls"] == ph.YAHOO_MISS_DAYS
    path = ph._yahoo_misses_path()
    rec = json.loads(path.read_text(encoding="utf-8"))["3529.TW"]
    assert rec["streak"] == ph.YAHOO_MISS_DAYS and rec["served_by"] == "finmind"

    # skipped while the retry interval runs; the other source still answers
    hist = await _run_day(world, _day(ph.YAHOO_MISS_DAYS + 1))
    assert hist.source == "finmind" and world["yahoo_calls"] == ph.YAHOO_MISS_DAYS

    # retried once the interval has passed
    await _run_day(world, _day(ph.YAHOO_MISS_DAYS - 1 + ph.YAHOO_RETRY_DAYS))
    assert world["yahoo_calls"] == ph.YAHOO_MISS_DAYS + 1


@pytest.mark.asyncio
async def test_same_day_counts_once_and_yahoo_success_clears(world):
    for _ in range(3):
        await _run_day(world, _day(0))
    assert not ph.yahoo_skipped("3529.TW", _day(0))
    assert ph._misses()["3529.TW"]["streak"] == 1
    await _run_day(world, _day(1))
    world["yahoo_has"] = True
    hist = await _run_day(world, _day(2))
    assert hist.source == "yfinance"
    assert "3529.TW" not in ph._misses()


@pytest.mark.asyncio
async def test_network_error_or_no_source_never_counts(world, monkeypatch):
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.side_effect = ConnectionError("reset")
    monkeypatch.setattr(ph, "yf", fake_yf)
    for n in range(4):
        await _run_day(world, _day(n))
    assert "3529.TW" not in ph._misses()

    # Yahoo empty but no other source has the ticker either: not recorded
    monkeypatch.setattr(ph, "yf", MagicMock(**{"Ticker.return_value.history.return_value":
                                               pd.DataFrame()}))

    async def none(*a, **k):
        return None
    from marketmind.gateway import free_quotes as fq
    monkeypatch.setattr(global_quotes, "from_tencent", none)
    for name in ("from_baostock", "from_stooq", "from_finmind", "from_eodhd"):
        monkeypatch.setattr(fq, name, none)
    monkeypatch.setattr(global_quotes, "from_eastmoney", none)
    monkeypatch.setattr(global_quotes, "from_twelvedata", none)
    for n in range(4):
        assert await _run_day(world, _day(n)) is None
    assert "3529.TW" not in ph._misses()
