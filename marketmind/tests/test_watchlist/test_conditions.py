"""Watch conditions (docs/S10_DESIGN.md §3): schema validation and evaluation, pure code."""
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.watchlist.conditions import (
    describe, evaluate, validate_condition, validate_conditions,
)


def bar(i, c=100.0, h=None, lo=None, v=1000.0):
    return Bar(f"2026-07-{i:02d}" if i <= 31 else f"2026-08-{i - 31:02d}", c, h or c + 1,
               lo or c - 1, c, v)


def series(n, c=100.0):
    return [bar(i + 1, c) for i in range(n)]


# ── validation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cond, norm", [
    ({"type": "close_above", "price": "101.5"}, {"type": "close_above", "price": 101.5}),
    ({"type": "close_below", "price": 99}, {"type": "close_below", "price": 99.0}),
    ({"type": "close_above_ma", "period": 50}, {"type": "close_above_ma", "period": 50}),
    ({"type": "close_below_ma", "period": "200"}, {"type": "close_below_ma", "period": 200}),
    ({"type": "volume_ratio_at_least", "ratio": 1.5}, {"type": "volume_ratio_at_least", "ratio": 1.5}),
    ({"type": "after_date", "date": "2026-10-02"}, {"type": "after_date", "date": "2026-10-02"}),
    ({"type": "breakout_20d", "note": " CPI "}, {"type": "breakout_20d", "note": "CPI"}),
])
def test_each_condition_type_validates_and_normalises(cond, norm):
    assert validate_condition(cond) == norm


@pytest.mark.parametrize("cond", [
    {"type": "price_strength"},                                  # not code-checkable
    {"type": "close_above"},                                     # missing price
    {"type": "close_above", "price": -1},
    {"type": "close_above", "price": True},
    {"type": "close_above", "price": "abc"},
    {"type": "close_above", "price": float("nan")},
    {"type": "close_above_ma", "period": 30},                    # only 20/50/200
    {"type": "close_above_ma", "period": 20.5},
    {"type": "volume_ratio_at_least", "ratio": 0},
    {"type": "volume_ratio_at_least", "ratio": 500},
    {"type": "after_date", "date": "10/02/2026"},
    {"type": "after_date", "date": "2026-10-2"},
    {"type": "close_below", "price": 90, "when": "soon"},        # unknown key
    "close above 100",
    None,
])
def test_anything_else_is_rejected(cond):
    with pytest.raises(ValueError):
        validate_condition(cond)


def test_condition_list_rules():
    assert validate_conditions([], allow_empty=True) == []
    assert validate_conditions(None, allow_empty=True) == []
    with pytest.raises(ValueError):
        validate_conditions([])
    with pytest.raises(ValueError):
        validate_conditions({"type": "breakout_20d"})


# ── evaluation (last bar of the series) ────────────────────────────────────

def test_close_above_and_below_price():
    bars = series(5)[:-1] + [bar(5, 105.0)]
    assert evaluate({"type": "close_above", "price": 104.0}, bars, "long")[0] is True
    assert evaluate({"type": "close_above", "price": 105.0}, bars, "long")[0] is False   # strict
    assert evaluate({"type": "close_below", "price": 106.0}, bars, "long")[0] is True
    assert evaluate({"type": "close_below", "price": 104.0}, bars, "long")[0] is False


def test_moving_average_conditions_and_short_history():
    bars = series(19) + [bar(20, 110.0)]
    above = {"type": "close_above_ma", "period": 20}
    ok, detail = evaluate(above, bars, "long")
    assert ok and "MA20" in detail                   # MA20 = 100.5 < 110
    assert evaluate({"type": "close_below_ma", "period": 20}, bars, "long")[0] is False
    ok, detail = evaluate({"type": "close_above_ma", "period": 50}, bars, "long")
    assert ok is False and "unavailable" in detail
    down = series(19) + [bar(20, 90.0)]
    assert evaluate({"type": "close_below_ma", "period": 20}, down, "short")[0] is True


def test_volume_ratio_uses_prior_twenty_bars():
    bars = series(20) + [bar(21, v=2500.0)]
    assert evaluate({"type": "volume_ratio_at_least", "ratio": 2.5}, bars, "long")[0] is True
    assert evaluate({"type": "volume_ratio_at_least", "ratio": 2.6}, bars, "long")[0] is False
    ok, detail = evaluate({"type": "volume_ratio_at_least", "ratio": 1}, bars[-20:], "long")
    assert ok is False and "unavailable" in detail
    no_vol = [Bar(b.date, b.open, b.high, b.low, b.close, 0.0) for b in bars]
    assert evaluate({"type": "volume_ratio_at_least", "ratio": 1}, no_vol, "long") == (False, "no volume data")


def test_after_date_is_strictly_after():
    bars = series(3)                                   # last bar 2026-07-03
    assert evaluate({"type": "after_date", "date": "2026-07-02"}, bars, "long")[0] is True
    assert evaluate({"type": "after_date", "date": "2026-07-03"}, bars, "long")[0] is False


def test_breakout_20d_long_and_short():
    base = series(20)                                  # highs 101, lows 99
    assert evaluate({"type": "breakout_20d"}, base + [bar(21, 101.5)], "long")[0] is True
    assert evaluate({"type": "breakout_20d"}, base + [bar(21, 101.0)], "long")[0] is False
    assert evaluate({"type": "breakout_20d"}, base + [bar(21, 98.5)], "short")[0] is True
    assert evaluate({"type": "breakout_20d"}, base + [bar(21, 101.5)], "short")[0] is False
    ok, detail = evaluate({"type": "breakout_20d"}, series(20), "long")
    assert ok is False and "unavailable" in detail


def test_no_bars_is_not_met():
    assert evaluate({"type": "close_above", "price": 1.0}, [], "long") == (False, "no bars")


def test_describe_is_chinese_and_direction_aware():
    assert describe({"type": "close_above", "price": 110.0}) == "收盘价上破 110"
    assert describe({"type": "close_above_ma", "period": 50}) == "收盘站上 50 日均线"
    assert describe({"type": "volume_ratio_at_least", "ratio": 2.0}) == "成交量 ≥ 2 倍 20 日均量"
    assert describe({"type": "breakout_20d"}, "long") == "收盘突破前 20 日高点"
    assert describe({"type": "breakout_20d"}, "short") == "收盘跌破前 20 日低点"
