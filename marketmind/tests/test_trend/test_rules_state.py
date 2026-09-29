"""Trend rules and state machine on synthetic bars (offline)."""
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar
from marketmind.trend.rules import (
    EXIT_SMA, TrendConfig, prior_high, sma, trailing_return, wilder_atr,
)
from marketmind.trend.state import (
    CASH, EVENT_ENTRY, EVENT_EXIT, EXIT, TREND, UNAVAILABLE, WATCH, compute_states,
    hurdle_from_tbill, simulate,
)


def make_bars(closes, start="2020-01-01", crypto=False, spread=0.005):
    d0 = date.fromisoformat(start)
    out, prev, day = [], closes[0], d0
    for c in closes:
        o = prev
        out.append(Bar(day.isoformat(), o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c, 1e6))
        prev = c
        day += timedelta(days=1)
        if not crypto:
            while day.weekday() >= 5:
                day += timedelta(days=1)
    return out


def flat_then_up(n_flat=300, n_up=60, step=0.01):
    closes = [100.0 + (0.5 if i % 2 else -0.5) for i in range(n_flat)]
    for _ in range(n_up):
        closes.append(closes[-1] * (1 + step))
    return closes


# ── indicators ──────────────────────────────────────────────────────────────

def test_sma_and_trailing_return():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    r = trailing_return([100, 110, 121], 1)
    assert r[0] is None and r[1] == pytest.approx(0.1) and r[2] == pytest.approx(0.1)


def test_prior_high_excludes_today():
    v = [1, 5, 2, 3, 9, 4]
    assert prior_high(v, 3) == [None, None, None, 5, 5, 9]


def test_wilder_atr_seed_and_smoothing():
    bars = [Bar(f"2020-01-0{i+1}", 10, 11, 9, 10, 0) for i in range(5)]   # TR = 2 each
    atr = wilder_atr(bars, 3)
    assert atr[:3] == [None, None, None]
    assert atr[3] == pytest.approx(2.0) and atr[4] == pytest.approx(2.0)
    bars.append(Bar("2020-01-06", 10, 15, 10, 14, 0))                      # TR = 5
    assert wilder_atr(bars, 3)[5] == pytest.approx((2.0 * 2 + 5) / 3)


def test_min_bars_by_asset_class():
    cfg = TrendConfig()
    assert cfg.min_bars("SPY") == 260
    assert cfg.min_bars("BTC-USD") == 366
    assert cfg.momentum_bars("ETH-USD") == 365


# ── state machine ───────────────────────────────────────────────────────────

def test_entry_on_breakout_fill_next_open():
    bars = make_bars(flat_then_up())
    sim = simulate("SPY", bars, TrendConfig(), 0.0)
    assert sim.trades, "an uptrend after a flat year must trigger an entry"
    tr = sim.trades[0]
    t = tr.signal_idx
    assert t >= 300                                   # breakout happens in the up leg
    assert sim.states[t] == TREND
    assert tr.fill_idx == t + 1 and tr.fill_price == bars[t + 1].open
    assert bars[t].close > sim.ind.high_prior[t]      # 55-day closing-high breakout
    assert sim.ind.close[t] > sim.ind.sma_filter[t]
    assert tr.initial_stop == pytest.approx(bars[t].close - 3 * sim.ind.atr[t])


def test_hurdle_blocks_entry():
    bars = make_bars(flat_then_up(n_up=20, step=0.005))   # 12m return ~ +10%
    assert simulate("SPY", bars, TrendConfig(), 0.0).trades
    assert not simulate("SPY", bars, TrendConfig(), 0.50).trades   # 50% hurdle


def test_no_lookahead_states_prefix_invariant():
    closes = flat_then_up() + [150.0 * (0.98 ** i) for i in range(40)]
    bars = make_bars(closes)
    full = simulate("SPY", bars, TrendConfig(), 0.0)
    for cut in (320, 340, 361, 380):
        part = simulate("SPY", bars[:cut], TrendConfig(), 0.0)
        assert part.states == full.states[:cut]
        assert part.stops == full.stops[:cut]


def test_chandelier_exit_and_monotone_stop():
    up = flat_then_up()
    closes = up + [up[-1] * (0.97 ** i) for i in range(1, 15)]
    bars = make_bars(closes)
    sim = simulate("SPY", bars, TrendConfig(), 0.0)
    tr = sim.trades[0]
    assert tr.exit_signal_idx is not None
    x = tr.exit_signal_idx
    assert sim.states[x] == EXIT
    assert bars[x].close < sim.stops[x - 1]           # decided on the stop in force that day
    assert tr.exit_idx == x + 1 and tr.exit_price == bars[x + 1].open
    held = [s for s in sim.stops[tr.signal_idx:x] if s is not None]
    assert held == sorted(held)                        # stop only ratchets up


def test_sma_exit_variant():
    up = flat_then_up()
    closes = up + [up[-1] * (0.99 ** i) for i in range(1, 80)]
    cfg = TrendConfig(exit_rule=EXIT_SMA)
    sim = simulate("SPY", make_bars(closes), cfg, 0.0)
    tr = sim.trades[0]
    x = tr.exit_signal_idx
    assert x is not None and "SMA100" in tr.exit_reason
    assert sim.ind.close[x] < sim.ind.sma_exit[x]


def test_watch_when_filters_met_without_breakout():
    up = flat_then_up()
    # after the up leg: a small pullback that stays far above SMA200 without a new high;
    # a tight stop (0.1 ATR) exits on the pullback, leaving the filters met -> WATCH
    closes = up + [up[-1] * 0.99] * 5
    sim = simulate("SPY", make_bars(closes), TrendConfig(atr_mult=0.1), 0.0)
    assert sim.trades and sim.trades[-1].exit_signal_idx is not None
    assert sim.states[-1] == WATCH


# ── daily states ────────────────────────────────────────────────────────────

def test_compute_states_unavailable_reasons():
    bars = make_bars(flat_then_up())
    last = date.fromisoformat(bars[-1].date)
    out = compute_states({"SPY": bars, "QQQ": bars[:100], "IWM": None, "BTC-USD": make_bars(
        flat_then_up(), crypto=True)[:300]}, 0.0, today=last)
    assert out["QQQ"].state == UNAVAILABLE and "insufficient history" in out["QQQ"].reason
    assert out["IWM"].state == UNAVAILABLE and "no price history" in out["IWM"].reason
    assert out["BTC-USD"].state == UNAVAILABLE and "300 < 366" in out["BTC-USD"].reason
    stale = compute_states({"SPY": bars}, 0.0, today=last + timedelta(days=30))
    assert stale["SPY"].state == UNAVAILABLE and "stale" in stale["SPY"].reason


def test_compute_states_numbers_and_entry_event():
    bars = make_bars(flat_then_up())
    sim = simulate("SPY", bars, TrendConfig(), 0.0)
    t = sim.trades[0].signal_idx
    upto = bars[:t + 1]
    st = compute_states({"SPY": upto}, 0.0, today=date.fromisoformat(upto[-1].date),
                        hurdle_source="test")["SPY"]
    assert st.state == TREND and st.event == EVENT_ENTRY
    assert st.as_of == upto[-1].date and st.entry_signal_date == upto[-1].date
    assert st.stop_level == pytest.approx(sim.trades[0].initial_stop, rel=1e-6)
    assert st.sma200 is not None and st.high_55 is not None and st.atr is not None
    assert st.hurdle_source == "test"
    assert st.to_dict()["ticker"] == "SPY"


def test_compute_states_exit_event_and_cash_reason():
    up = flat_then_up()
    closes = up + [up[-1] * (0.97 ** i) for i in range(1, 15)]
    bars = make_bars(closes)
    x = simulate("SPY", bars, TrendConfig(), 0.0).trades[0].exit_signal_idx
    st = compute_states({"SPY": bars[:x + 1]}, 0.0, today=date.fromisoformat(bars[x].date))["SPY"]
    assert st.state == EXIT and st.event == EVENT_EXIT and "chandelier" in st.reason
    down = make_bars([200 - i * 0.3 for i in range(300)])
    st2 = compute_states({"SPY": down}, 0.0, today=date.fromisoformat(down[-1].date))["SPY"]
    assert st2.state == CASH and "12m return" in st2.reason and "SMA200" in st2.reason


def test_hurdle_from_tbill():
    irx = [Bar(f"d{i}", 0, 0, 0, 4.0 if i % 2 else 5.0, 0) for i in range(300)]
    assert hurdle_from_tbill(irx) == pytest.approx(0.045)
    assert hurdle_from_tbill(irx[:50]) is None
