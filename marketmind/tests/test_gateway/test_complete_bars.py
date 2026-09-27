"""Partial (running-session) bars are dropped before L3 and quote snapshots use them."""
from datetime import datetime, timezone

from marketmind.gateway.price_history import (
    Bar, PriceHistory, complete_bars, completed_history, to_weekly,
)


def _bars(*dates):
    return [Bar(d, 1.0, 1.0, 1.0, 1.0, 1.0) for d in dates]


DATES = ("2026-09-24", "2026-09-25")


def test_crypto_drops_today_utc():
    now = datetime(2026, 9, 25, 23, 0, tzinfo=timezone.utc)
    assert [b.date for b in complete_bars("BTC-USD", _bars(*DATES), now)] == ["2026-09-24"]


def test_us_bar_complete_only_after_new_york_close():
    before = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)   # 15:00 ET
    after = datetime(2026, 9, 25, 20, 5, tzinfo=timezone.utc)    # 16:05 ET
    assert [b.date for b in complete_bars("SPY", _bars(*DATES), before)] == ["2026-09-24"]
    assert [b.date for b in complete_bars("SPY", _bars(*DATES), after)] == list(DATES)
    # Beijing morning = previous New York evening: yesterday's bar is complete
    bj = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
    assert [b.date for b in complete_bars("SPY", _bars(*DATES), bj)] == list(DATES)


def test_completed_history_rebuilds_weekly_only_when_needed():
    daily = _bars(*DATES)
    hist = PriceHistory("ETH-USD", "bybit", daily=daily, weekly=to_weekly(daily))
    later = datetime(2026, 9, 27, tzinfo=timezone.utc)
    assert completed_history(hist, later) is hist
    trimmed = completed_history(hist, datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    assert [b.date for b in trimmed.daily] == ["2026-09-24"]
    assert trimmed.weekly[-1].date == "2026-09-24" and trimmed.source == "bybit"
