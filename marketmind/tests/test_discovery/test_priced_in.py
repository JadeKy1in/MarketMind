"""Discovery "already priced in?" buckets (docs/S10_DESIGN.md §2)."""
from datetime import date, timedelta

import pytest

from marketmind.discovery.priced_in import (
    NOT_PRICED, PARTIAL, PRICED_IN, UNAVAILABLE, PricedInConfig, assess, bucket_for,
)
from marketmind.gateway.price_history import Bar


def _bars(closes, start="2026-08-01", rng=1.0, vols=None):
    """Bars with high-low range `rng` around each close (ATR ~ rng for flat series)."""
    d0 = date.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        v = vols[i] if vols else 1000.0
        out.append(Bar((d0 + timedelta(days=i)).isoformat(), c, c + rng / 2, c - rng / 2, c, v))
    return out


BASE_N = 20          # bars up to and including the base date
SINCE = (date(2026, 8, 1) + timedelta(days=BASE_N - 1)).isoformat()


def _path(after):
    return _bars([100.0] * BASE_N + after)


def test_bucket_rules():
    cfg = PricedInConfig()
    assert bucket_for(2.5, 1, cfg) == (True, PRICED_IN)
    assert bucket_for(-2.0, -1, cfg) == (True, PRICED_IN)
    assert bucket_for(1.0, 1, cfg) == (True, PARTIAL)
    assert bucket_for(0.3, 1, cfg) == (True, NOT_PRICED)
    assert bucket_for(-3.0, 1, cfg) == (False, NOT_PRICED)      # opposite direction
    assert bucket_for(0.0, 1, cfg) == (False, NOT_PRICED)
    assert bucket_for(3.0, 0, cfg) == (False, NOT_PRICED)       # no prior


def test_priced_in_when_moved_two_atr_in_implied_direction():
    r = assess("SPY", _path([101.0, 102.5]), SINCE, 1)
    assert r["base_date"] == SINCE and r["base_close"] == 100.0
    assert r["atr14"] == pytest.approx(1.0)
    assert r["move_atr"] == pytest.approx(2.5)
    assert r["return_pct"] == pytest.approx(2.5)
    assert r["bars_since"] == 2 and r["agree"] is True
    assert r["bucket"] == PRICED_IN


def test_partial_and_not_priced_and_opposite():
    assert assess("SPY", _path([101.0]), SINCE, 1)["bucket"] == PARTIAL
    assert assess("SPY", _path([100.2]), SINCE, 1)["bucket"] == NOT_PRICED
    r = assess("SPY", _path([97.0]), SINCE, 1)
    assert r["agree"] is False and r["bucket"] == NOT_PRICED
    assert assess("SPY", _path([97.0]), SINCE, -1)["bucket"] == PRICED_IN


def test_thresholds_are_configurable():
    cfg = PricedInConfig(priced_atr=5.0, partial_atr=2.0)
    assert assess("SPY", _path([102.5]), SINCE, 1, cfg)["bucket"] == PARTIAL
    assert assess("SPY", _path([101.0]), SINCE, 1, cfg)["bucket"] == NOT_PRICED


def test_release_on_last_bar_is_not_priced_yet():
    r = assess("SPY", _path([]), SINCE, 1)
    assert r["bars_since"] == 0 and r["move_atr"] == 0 and r["bucket"] == NOT_PRICED
    assert r["volume_ratio"] is None


def test_base_uses_last_bar_on_or_before_the_observation_date():
    bars = _path([101.0])
    later = (date.fromisoformat(SINCE) + timedelta(days=5)).isoformat()
    assert assess("SPY", bars, later, 1)["base_date"] == bars[-1].date


def test_volume_ratio_since_release_vs_prior_20_days():
    vols = [1000.0] * BASE_N + [3000.0, 1000.0]
    r = assess("SPY", _bars([100.0] * BASE_N + [101.0, 101.0], vols=vols), SINCE, 1)
    assert r["volume_ratio"] == pytest.approx(2.0)


def test_unavailable_rows_have_reasons():
    assert assess("SPY", None, SINCE, 1)["bucket"] == UNAVAILABLE
    early = assess("SPY", _path([101.0]), "2026-07-01", 1)
    assert early["bucket"] == UNAVAILABLE and "no bar on or before" in early["reason"]
    short = assess("SPY", _bars([100.0] * 5 + [101.0]), "2026-08-05", 1)
    assert short["bucket"] == UNAVAILABLE and "ATR14" in short["reason"]


def test_single_stock_uses_excess_over_sector_etf():
    stock = _path([103.0])                 # +3 ATR raw
    etf = _path([102.5])                   # sector moved +2.5%
    r = assess("XOM", stock, SINCE, 1, sector_bars=etf, sector_etf="XLE")
    assert r["move_atr"] == pytest.approx(3.0)
    assert r["excess_pct"] == pytest.approx(0.5)
    assert r["excess_atr"] == pytest.approx(0.5)
    assert r["bucket"] == PARTIAL          # bucketed on the excess, not the raw move
    missing = assess("XOM", stock, SINCE, 1, sector_bars=None, sector_etf="XLE")
    assert missing["bucket"] == PRICED_IN and "sector ETF XLE unavailable" in missing["reason"]
