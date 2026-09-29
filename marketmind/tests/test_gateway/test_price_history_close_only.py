"""Close-only bars (O=H=L=C with no volume) are flagged by price_history (offline)."""
import logging

import pytest

from marketmind.gateway import price_history as ph
from marketmind.gateway.price_history import Bar, PriceHistory


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
        with caplog.at_level(logging.WARNING, logger="marketmind.gateway.price_history"):
            hist = await ph.get_price_history("PL=F")
    finally:
        ph.clear_cache()
    assert [b.close_only for b in hist.daily] == [False, True, True, False]
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "PL=F" in msg and "2026-09-23, 2026-09-24" in msg
