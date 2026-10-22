"""Close-only bars (O=H=L=C with no volume) are flagged by price_history (offline)."""
import logging

import pytest

from marketmind.gateway import price_history as ph
from marketmind.gateway.price_history import Bar, PriceHistory


@pytest.fixture(autouse=True)
def _clean_run_notes():
    ph._close_only_seen.clear()
    ph._alpaca_empty_seen.clear()
    yield
    ph._close_only_seen.clear()
    ph._alpaca_empty_seen.clear()


def test_close_only_needs_equal_ohlc_and_no_volume():
    assert ph.is_close_only(Bar("2026-09-23", 1745.7, 1745.7, 1745.7, 1745.7, 0.0))
    assert ph.is_close_only(Bar("2026-09-23", 5.0, 5.0, 5.0, 5.0, None))     # volume missing
    # a genuinely flat session that traded is a real bar
    assert not ph.is_close_only(Bar("2026-09-23", 5.0, 5.0, 5.0, 5.0, 12.0))
    # no volume but a real range (FX / index sources report volume 0)
    assert not ph.is_close_only(Bar("2026-09-23", 5.0, 5.2, 4.9, 5.1, 0.0))


def test_bar_constructors_keep_working_and_default_to_full_bars():
    b = Bar(*["2026-09-22", 1.0, 2.0, 0.5, 1.5, 10.0])       # trend cache: Bar(*row)
    assert b.close_only is False
    weekly = ph.to_weekly([Bar("2026-09-21", 1, 1, 1, 1, 0, close_only=True),
                           Bar("2026-09-22", 1, 2, 0.5, 1.5, 3)])
    assert len(weekly) == 1 and weekly[0].close_only is False


def test_mark_close_only_sets_and_clears_flags():
    bars = [Bar("2026-09-22", 1791.1, 1822.6, 1788.0, 1822.6, 36.0, close_only=True),
            Bar("2026-09-23", 1745.7, 1745.7, 1745.7, 1745.7, 0.0),
            Bar("2026-09-24", 1749.1, 1749.1, 1749.1, 1749.1, 0.0)]
    assert ph.mark_close_only(bars) == ["2026-09-23", "2026-09-24"]
    assert [b.close_only for b in bars] == [False, True, True]


@pytest.mark.asyncio
async def test_get_price_history_flags_and_warns_with_the_dates(monkeypatch, caplog):
    daily = [Bar("2026-09-22", 1791.1, 1822.6, 1788.0, 1822.6, 36.0),
             Bar("2026-09-23", 1745.7, 1745.7, 1745.7, 1745.7, 0.0),
             Bar("2026-09-24", 1749.1, 1749.1, 1749.1, 1749.1, 0.0),
             Bar("2026-09-28", 1736.6, 1741.2, 1716.0, 1721.4, 1881.0)]

    async def fake_yf(ticker, years):
        return PriceHistory(ticker=ticker, source="yfinance", daily=daily,
                            weekly=ph.to_weekly(daily))

    monkeypatch.setattr(ph, "_from_yfinance", fake_yf)
    ph.clear_cache()
    try:
        with caplog.at_level(logging.DEBUG, logger="marketmind.gateway.price_history"):
            hist = await ph.get_price_history("PL=F")
    finally:
        ph.clear_cache()
    assert [b.close_only for b in hist.daily] == [False, True, True, False]
    detail = [r for r in caplog.records if "PL=F" in r.getMessage()]
    # per-symbol detail is DEBUG (2026-10-22); the run summary carries the WARNING
    assert detail and all(r.levelno == logging.DEBUG for r in detail)
    assert "2026-09-23, 2026-09-24" in detail[0].getMessage()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="marketmind.gateway.price_history"):
        ph.log_run_summary()
        ph.log_run_summary()                                   # notes were reset
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["price history: 1 symbol(s) with 2 close-only bar(s) in total, range unknown "
                    "(most: PL=F 2; per-symbol detail at DEBUG)"]


def test_run_summary_collapses_many_symbols(caplog):
    for i in range(12):
        ph._close_only_seen[f"T{i}"] = i + 1
        ph._alpaca_empty_seen[f"E{i}"] = None
    with caplog.at_level(logging.WARNING, logger="marketmind.gateway.price_history"):
        ph.log_run_summary()
    close_line, alpaca_line = [r.getMessage() for r in caplog.records]
    assert "12 symbol(s) with 78 close-only bar(s)" in close_line
    assert "most: T11 12, T10 11, T9 10, T8 9, T7 8 (+7 more)" in close_line
    assert alpaca_line.startswith("Alpaca bars empty for 12 symbol(s)")
    assert alpaca_line.endswith("E9 (+2 more)")
    assert not ph._close_only_seen and not ph._alpaca_empty_seen
