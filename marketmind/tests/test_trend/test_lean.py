"""Lean variant (docs/TREND_DESIGN.md §8) on synthetic bars (offline)."""
from datetime import date

import pytest

from marketmind.trend.backtest import backtest_instrument, result_from_sim
from marketmind.trend.lean import (
    NO_GATING, VETO_GROUP, VETO_PEER, VETO_RANK, VETO_SECTOR, LeanConfig, lean_states,
    simulate_lean,
)
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import TREND, UNAVAILABLE, WATCH, simulate
from marketmind.tests.test_trend.test_rules_state import flat_then_up, make_bars

CFG = TrendConfig()


def up(step, n_up=60, n_flat=300):
    return make_bars(flat_then_up(n_flat, n_up, step))


def test_no_gating_equals_single_instrument_simulation():
    data = {"SPY": up(0.01), "GLD": up(0.004), "BTC-USD": make_bars(flat_then_up(400, 80, 0.02),
                                                                        crypto=True)}
    lean = LeanConfig(core=("SPY", "GLD", "BTC-USD"), sectors=(), strongest_only=False,
                      one_per_group=False)
    res = simulate_lean(data, CFG, 0.0, lean)
    for t, bars in data.items():
        a, b = res.sims[t], simulate(t, bars, CFG, 0.0)
        assert [vars(x) for x in a.trades] == [vars(x) for x in b.trades]
        assert a.states == b.states and a.stops == b.stops
    assert NO_GATING.top_n is None and not NO_GATING.one_per_group


def test_only_the_strongest_sector_may_signal():
    data = {"XLK": up(0.012), "XLF": up(0.006)}
    lean = LeanConfig(core=(), sectors=("XLK", "XLF"), groups=())
    res = simulate_lean(data, CFG, 0.0, lean)
    assert res.sims["XLK"].trades and not res.sims["XLF"].trades
    assert any(v["ticker"] == "XLF" and v["why"].startswith(VETO_SECTOR) for v in res.vetoes)
    assert res.last_strongest() == "XLK"
    t = next(v for v in res.vetoes if v["ticker"] == "XLF")["date"]
    i = next(k for k, b in enumerate(data["XLF"]) if b.date == t)
    assert res.sims["XLF"].states[i] == WATCH          # vetoed: flat, no phantom position


def test_one_position_per_group_stronger_member_wins():
    data = {"SPY": up(0.006), "QQQ": up(0.012)}
    lean = LeanConfig(core=("SPY", "QQQ"), sectors=(), groups=(("SPY", "QQQ"),))
    res = simulate_lean(data, CFG, 0.0, lean)
    assert res.sims["QQQ"].trades and not res.sims["SPY"].trades
    whys = {v["why"].split(" (")[0] for v in res.vetoes if v["ticker"] == "SPY"}
    assert VETO_PEER in whys or VETO_GROUP in whys
    assert VETO_GROUP in whys                            # later SPY highs while QQQ is held
    q = res.sims["QQQ"].trades[0]
    for tr in res.sims["SPY"].trades:
        assert tr.signal_date > (q.exit_signal_date or "9999")


def test_group_frees_after_exit_signal():
    # QQQ rallies then crashes (exit); SPY keeps making highs afterwards -> SPY may enter
    q = flat_then_up(300, 60, 0.012)
    q += [q[-1] * (0.97 ** k) for k in range(1, 30)]
    s = flat_then_up(300, 110, 0.006)
    data = {"SPY": make_bars(s), "QQQ": make_bars(q)}
    lean = LeanConfig(core=("SPY", "QQQ"), sectors=(), groups=(("SPY", "QQQ"),))
    res = simulate_lean(data, CFG, 0.0, lean)
    qt = res.sims["QQQ"].trades[0]
    assert qt.exit_signal_date is not None
    assert res.sims["SPY"].trades and res.sims["SPY"].trades[0].signal_date >= qt.exit_signal_date


def test_top_n_rank_filter():
    data = {"GLD": up(0.012), "TLT": up(0.005)}
    lean = LeanConfig(core=("GLD", "TLT"), sectors=(), groups=(), top_n=1)
    res = simulate_lean(data, CFG, 0.0, lean)
    assert res.sims["GLD"].trades and not res.sims["TLT"].trades
    assert any(v["ticker"] == "TLT" and v["why"].startswith(VETO_RANK) for v in res.vetoes)
    both = simulate_lean(data, CFG, 0.0, LeanConfig(core=("GLD", "TLT"), sectors=(), groups=()))
    assert both.sims["TLT"].trades                      # without the filter TLT enters


def test_group_labels():
    lc = LeanConfig()
    assert lc.group_of("SPY") == lc.group_of("XLK") == lc.group_of("SMH") == "SPY+QQQ+SECTOR"
    assert lc.group_of("ETH-USD") == "BTC-USD+ETH-USD"
    assert lc.group_of("GLD") == "GLD"


def test_result_from_sim_matches_backtest_instrument():
    bars = up(0.01)
    a = backtest_instrument("SPY", bars, CFG, 0.0, "x")
    b = result_from_sim(simulate("SPY", bars, CFG, 0.0), "x")
    assert a.metrics == b.metrics


def test_lean_states_today():
    spy, qqq = up(0.006), up(0.012)
    today = date.fromisoformat(qqq[-1].date)
    data = {"SPY": spy, "QQQ": qqq, "XLK": up(0.02), "XLF": up(0.001), "GLD": None,
            "TLT": up(0.01)[:100]}
    out = lean_states(data, 0.0, CFG, today=today)
    st = out["states"]
    assert out["strongest_sector"] == "XLK"
    assert st["GLD"].state == UNAVAILABLE and "no price history" in st["GLD"].reason
    assert st["TLT"].state == UNAVAILABLE and "insufficient" in st["TLT"].reason
    assert "XLF" not in st                              # not strongest, not held
    held = [t for t in ("SPY", "QQQ", "XLK") if st[t].state == TREND]
    assert len(held) == 1                               # one position in the equity group
    assert out["groups"]["XLK"] == "SPY+QQQ+SECTOR"
    assert "BTC-USD" not in st                          # not in the given histories


def test_lean_states_reports_vetoed_signal_today():
    data = {"SPY": up(0.006, n_up=61), "QQQ": up(0.012, n_up=61)}
    lean = LeanConfig(core=("SPY", "QQQ"), sectors=(), groups=(("SPY", "QQQ"),))
    out = lean_states(data, 0.0, CFG, lean, today=date.fromisoformat(data["SPY"][-1].date))
    spy = out["states"]["SPY"]
    assert spy.state == WATCH
    assert spy.reason and "entry signal not taken" in spy.reason


@pytest.mark.parametrize("lc", [LeanConfig(), LeanConfig(top_n=3)])
def test_default_configs_cover_the_pre_registered_universe(lc):
    assert lc.core == ("SPY", "QQQ", "GLD", "TLT", "USO", "BTC-USD", "ETH-USD")
    assert len(lc.sectors) == 10 and "SMH" in lc.sectors
