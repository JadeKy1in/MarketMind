"""Tests for code-computed Layer 3 technicals (pipeline/l3_indicators.py)."""
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory, to_weekly
from marketmind.pipeline.l3_indicators import atr, compute_snapshot, describe, sma


def make_history(closes: list[float], ticker: str = "TEST", spread: float = 0.01) -> PriceHistory:
    start = date(2021, 1, 4)
    bars = []
    d = start
    for c in closes:
        while d.weekday() >= 5:  # skip weekends
            d += timedelta(days=1)
        bars.append(Bar(d.isoformat(), c, c * (1 + spread), c * (1 - spread), c, 1_000_000))
        d += timedelta(days=1)
    return PriceHistory(ticker=ticker, source="synthetic", daily=bars, weekly=to_weekly(bars))


def uptrend(n: int = 1300, start: float = 50.0, step: float = 0.1) -> list[float]:
    # steady rise with a small saw-tooth so lows keep rising
    return [start + step * i + (0.3 if i % 5 == 0 else 0.0) for i in range(n)]


def test_sma_and_atr_basics():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 5) is None
    bars = make_history([10, 11, 12], spread=0.0).daily
    assert atr(bars) == pytest.approx(1.0)


def test_steady_uptrend_at_highs_is_green_breakout():
    snap = compute_snapshot(make_history(uptrend()))
    assert snap is not None
    assert snap.above_200wma and snap.structure_intact
    assert snap.near_key_resistance is False          # above 52w resistance = breakout
    assert snap.light == "green"
    # levels are code-computed and internally consistent
    assert snap.stop_loss < snap.support_low < snap.close
    assert snap.entry_low < snap.close < snap.entry_high
    assert snap.target_price > snap.close
    # no swing high overhead -> target is the 6 ATR cap; risk capped at 2 ATR
    assert snap.target_price == pytest.approx(snap.close + 6 * snap.atr14, abs=0.01)
    assert snap.close - snap.stop_loss <= 2 * snap.atr14 + 0.01
    assert snap.reward_risk_ratio == pytest.approx(3.0, abs=0.01)
    assert snap.recommendation == "enter"


def test_target_is_nearest_significant_swing_high():
    closes = uptrend()
    a_peak = closes[-60]
    # rally to a peak 60 sessions ago, a sharp drop, then recovery to 1.5% under it
    drop = [a_peak - 0.8 * (i + 1) for i in range(10)]
    back = [drop[-1] + (a_peak * 0.985 - drop[-1]) * (i + 1) / 49 for i in range(49)]
    snap = compute_snapshot(make_history(closes[:-59] + drop + back))
    assert snap.target_price == pytest.approx(a_peak, abs=0.01)


def test_minor_swing_without_drop_is_not_a_target():
    # a local high followed by only a tiny dip is not "significant"
    snap = compute_snapshot(make_history(uptrend()))
    assert snap.target_price == pytest.approx(snap.close + 6 * snap.atr14, abs=0.01)


def test_far_support_stop_is_capped_at_two_atr():
    closes = uptrend()
    # a deep 20-day low far below the close (8% flush, then recovery)
    closes[-15] = closes[-15] * 0.92
    snap = compute_snapshot(make_history(closes))
    assert snap.support_low - snap.atr14 < snap.close - 2 * snap.atr14
    assert snap.stop_loss == pytest.approx(snap.close - 2 * snap.atr14, abs=0.01)


def test_downtrend_is_never_a_buy():
    closes = list(reversed(uptrend()))
    snap = compute_snapshot(make_history(closes))
    assert not snap.above_200wma and not snap.structure_intact
    # far below resistance passes rule 3 only -> yellow per design wording, action "wait"
    assert snap.light == "yellow"
    assert snap.recommendation == "wait"


def test_all_three_fail_is_red():
    # downtrend that bounced to just under its old closing high: every rule fails
    closes = list(reversed(uptrend()))
    peak = max(closes[-252:-10])
    closes[-1] = peak * 0.99
    snap = compute_snapshot(make_history(closes))
    assert snap.near_key_resistance            # ~1% under the old closing high
    assert not snap.structure_intact
    assert not snap.above_200wma               # ~75 vs a 200WMA near 100
    assert snap.light == "red" and snap.recommendation == "avoid"


def test_short_history_fails_200wma_and_is_not_green():
    snap = compute_snapshot(make_history(uptrend(n=300)))
    assert snap.wma200 is None
    assert snap.above_200wma is False
    assert snap.light != "green"
    assert any("weekly bars" in n for n in snap.notes)


def test_too_little_data_returns_none():
    assert compute_snapshot(make_history(uptrend(n=30))) is None


def test_pullback_just_below_resistance_is_near():
    closes = uptrend()
    peak = closes[-40]
    # 30 sessions of drift ending 2% below the old peak
    tail = [peak * (1 - 0.02 * (i + 1) / 30) for i in range(30)]
    snap = compute_snapshot(make_history(closes[:-30] + tail))
    assert snap.key_resistance is not None
    assert 0 < snap.resistance_distance_pct <= 3.0
    assert snap.near_key_resistance is True
    assert snap.light != "green"


@pytest.mark.parametrize("closes", [
    uptrend(),
    list(reversed(uptrend())),
    uptrend()[:-30] + [uptrend()[-31] * (1 - 0.001 * i) for i in range(30)],
    [100 + (i % 7) * 0.8 for i in range(1300)],          # choppy range
])
def test_stop_always_below_entry_zone(closes):
    snap = compute_snapshot(make_history(closes, spread=0.02))
    assert snap.stop_loss < snap.entry_low <= snap.close <= snap.entry_high


def test_describe_is_traceable():
    text = describe(compute_snapshot(make_history(uptrend())))
    assert "GREEN" in text and "200WMA" in text and "stop" in text
