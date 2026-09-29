"""Monthly long-horizon rules (docs/TREND_DESIGN.md §10) on synthetic bars (offline)."""
from dataclasses import replace

import pytest

from marketmind.trend.backtest import result_from_sim, run_portfolio
from marketmind.trend.monthly import (
    ALWAYS, CHECK_MID_MONTH, M1, M2, SLOTS, MonthlyConfig, RULE_SMA, RULE_TSMOM,
    check_indices, decide, simulate_monthly, whipsaws,
)
from marketmind.trend.state import CASH, EXIT, TREND
from marketmind.tests.test_trend.test_rules_state import make_bars

NO_START = replace(M1, eval_from=None)


def monthly_path(levels, per_month=21, start="2020-01-01", crypto=False):
    """Daily bars whose closes step through `levels`, roughly one level per month."""
    closes = []
    for lv in levels:
        closes += [float(lv)] * per_month
    return make_bars(closes, start=start, crypto=crypto, spread=0.0)


def test_month_end_checks_are_last_bar_of_each_month():
    bars = make_bars([100.0] * 70, start="2021-01-01")           # weekdays only
    ends = [bars[i].date for i in check_indices(bars)]
    assert ends[:3] == ["2021-01-29", "2021-02-26", "2021-03-31"]
    last = check_indices(bars)[-1]
    assert bars[last + 1].date[:7] != bars[last].date[:7]      # never the final bar


def test_mid_month_checks_are_last_bar_on_or_before_the_15th():
    bars = make_bars([100.0] * 70, start="2021-01-01")
    mids = [bars[i].date for i in check_indices(bars, CHECK_MID_MONTH)]
    assert mids[:3] == ["2021-01-15", "2021-02-15", "2021-03-15"]
    crypto = make_bars([100.0] * 70, start="2021-01-01", crypto=True)
    assert [crypto[i].date for i in check_indices(crypto)][:2] == ["2021-01-31", "2021-02-28"]


def test_decide_sma_and_tsmom():
    assert decide([1.0] * 9, M1) is None                          # needs 10 closes
    hold, s = decide([10.0] * 9 + [12.0], M1)
    assert hold and s == pytest.approx(12 / 10.2 - 1)
    assert decide([10.0] * 9 + [9.0], M1)[0] is False
    assert decide([1.0] * 12, M2) is None                         # needs 13 closes
    closes = [100.0] + [100.0] * 11 + [104.0]                     # +4% over 12 months
    assert decide(closes, M2, hurdle_annual=0.03)[0] is True
    assert decide(closes, M2, hurdle_annual=0.05)[0] is False
    nine = MonthlyConfig(RULE_TSMOM, 9)
    assert decide([100.0] * 9 + [103.0], nine, 0.05)[0] is False  # hurdle (1.05)^0.75-1 ≈ 3.7%
    assert decide([100.0] * 9 + [104.0], nine, 0.05)[0] is True


def test_entry_and_exit_fill_at_next_open_on_check_days_only():
    bars = monthly_path([100] * 10 + [120, 130, 140] + [60] * 4)
    sim = simulate_monthly("SPY", bars, NO_START)
    checks = check_indices(bars)
    assert sim.trades, "rising monthly closes above the SMA must enter"
    tr = sim.trades[0]
    assert tr.signal_idx in checks and tr.fill_idx == tr.signal_idx + 1
    assert tr.fill_price == bars[tr.fill_idx].open
    assert tr.exit_signal_idx in checks and tr.exit_idx == tr.exit_signal_idx + 1
    assert tr.exit_price == bars[tr.exit_idx].open
    assert sim.states[tr.signal_idx] == TREND and sim.states[tr.exit_signal_idx] == EXIT
    assert all(sim.states[i] == TREND for i in range(tr.fill_idx, tr.exit_signal_idx))
    assert sim.states[tr.exit_idx] == CASH
    assert tr.initial_stop == 0.0


def test_no_look_ahead_truncated_history_gives_the_same_decisions():
    levels = [100, 101, 99, 102, 98, 103, 105, 104, 108, 110, 107, 115, 90, 95, 120, 125, 80, 85]
    bars = monthly_path(levels)
    full = simulate_monthly("SPY", bars, NO_START)
    for cut in check_indices(bars)[10:]:
        part = simulate_monthly("SPY", bars[:cut + 2], NO_START)   # up to the fill bar
        want = [(t.signal_idx, t.exit_signal_idx if t.exit_signal_idx is not None and
                 t.exit_signal_idx <= cut else None)
                for t in full.trades if t.signal_idx <= cut]
        got = [(t.signal_idx, t.exit_signal_idx) for t in part.trades]
        assert got == want


def test_eval_from_skips_earlier_checks_but_keeps_their_closes():
    bars = monthly_path([100 + i for i in range(24)], start="2004-01-01")
    sim = simulate_monthly("SPY", bars, replace(M1, eval_from="2005-06-01"))
    assert sim.first_ready is not None and bars[sim.first_ready].date >= "2005-06-01"
    assert sim.trades[0].signal_idx == sim.first_ready             # already trending: enter at once


def test_tsmom_uses_the_point_in_time_hurdle():
    bars = monthly_path([100] * 13 + [104] * 3)
    lo = simulate_monthly("SPY", bars, replace(M2, eval_from=None), hurdle=0.02)
    hi = simulate_monthly("SPY", bars, replace(M2, eval_from=None), hurdle=0.10)
    assert lo.trades and not hi.trades
    by_date = simulate_monthly("SPY", bars, replace(M2, eval_from=None),
                               hurdle=lambda d: 0.10 if d < "2021-02-01" else 0.02)
    assert by_date.trades and by_date.trades[0].hurdle == 0.02


def test_whipsaw_counts_round_trips_shorter_than_two_months():
    bars = monthly_path([100] * 10 + [110, 90, 90, 115, 118, 80])
    sim = simulate_monthly("SPY", bars, NO_START)
    assert len(sim.trades) == 2
    assert whipsaws(sim) == 1                    # 110 -> 90: out at the next check
    held_two = [t for t in sim.trades if t.closed][-1]
    assert held_two.exit_signal_idx > held_two.signal_idx


def test_always_rule_buys_once_and_never_sells():
    bars = monthly_path([100, 80, 60, 40, 30, 20, 30, 40, 50, 60, 20, 10])
    sim = simulate_monthly("SPY", bars, replace(ALWAYS, eval_from=None))
    assert len(sim.trades) == 1 and not sim.trades[0].closed


def test_backtest_and_slot_portfolio_reuse():
    spy = monthly_path([100] * 10 + [110, 120, 130, 140, 150, 160], start="2021-01-01")
    btc = monthly_path([100] * 10 + [130, 160, 200, 260, 300, 350], start="2021-01-01",
                       per_month=30, crypto=True)
    sims = {"SPY": simulate_monthly("SPY", spy, NO_START),
            "BTC-USD": simulate_monthly("BTC-USD", btc, NO_START)}
    res = {t: result_from_sim(s) for t, s in sims.items()}
    assert res["SPY"].metrics["signals"] == 1 and 0 < res["SPY"].metrics["time_in_market"] <= 1
    port = run_portfolio(res, SLOTS)
    assert len(port.taken) == 2
    first = port.taken[0]
    assert first["weight"] == pytest.approx(1 / 6, rel=1e-6)       # one slot of equity
    assert not port.skipped


def test_labels():
    assert M1.label == "M1 SMA10" and M2.label == "M2 TSMOM12"
    assert replace(M1, check=CHECK_MID_MONTH).label == "M1 SMA10 mid-month"
    assert MonthlyConfig(RULE_SMA, 8).min_checks == 8 and M2.min_checks == 13


def test_preregistered_verdict_and_grid():
    from marketmind.trend.monthly_report import grid, passed, verdict
    bench = {"mdd": -0.50, "cagr": 0.10}
    good = {"entries_py": 5.0, "tim": 0.55, "mdd": -0.20, "cagr": 0.08,
            "h1": {"cagr": 0.02}, "h2": {"cagr": 0.05}}
    assert passed(verdict(good, bench))
    for key, bad in (("entries_py", 10.5), ("tim", 0.61), ("mdd", -0.26), ("cagr", 0.069),
                     ("h1", {"cagr": -0.01})):
        v = verdict({**good, key: bad}, bench)
        assert not passed(v) and sum(not ok for _, ok, _ in v) == 1
    labels = [c.label for c in grid()]
    assert len(labels) == 12 and "M1 SMA10" in labels and "M2 TSMOM15 mid-month" in labels
