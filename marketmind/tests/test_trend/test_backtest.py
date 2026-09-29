"""Backtest metrics, big-move capture, portfolio sizing and report smoke test (offline)."""
import json
import math
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar
from marketmind.trend import backtest as bt
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import Trade
from marketmind.tests.test_trend.test_rules_state import flat_then_up, make_bars


def test_one_way_cost_matches_settlement():
    assert bt.one_way_cost("SPY") == pytest.approx(0.0005)
    assert bt.one_way_cost("BTC-USD") == pytest.approx(0.01)
    assert bt.one_way_cost("SOL-USD") == pytest.approx(0.0125)


def test_trade_net_return_and_daily_returns():
    bars = [Bar(f"2020-01-0{i+1}", o, o, o, c, 0) for i, (o, c) in
            enumerate([(10, 10), (10, 11), (11, 12), (13, 12), (12, 12)])]
    tr = Trade("SPY", 0, bars[0].date, 10, 9, 0.1, 0.0, fill_idx=1, fill_date=bars[1].date,
               fill_price=10.0, exit_signal_idx=2, exit_idx=3, exit_date=bars[3].date, exit_price=13.0)
    cost = 0.001
    assert bt.trade_net_return(tr, cost) == pytest.approx(13 / 10 * (1 - cost) ** 2 - 1)
    net, gross, held = bt.daily_returns(bars, [tr], cost)
    assert gross[1] == pytest.approx(0.1) and gross[2] == pytest.approx(12 / 11 - 1)
    assert gross[3] == pytest.approx(13 / 12 - 1)          # close -> exit open
    assert held == [False, True, True, False, False]
    total = math.prod(1 + r for r in net) - 1
    assert total == pytest.approx(bt.trade_net_return(tr, cost))


def test_max_drawdown_and_cagr():
    assert bt.max_drawdown([1, 2, 1, 3]) == pytest.approx(-0.5)
    assert bt.cagr(1, 2, "2020-01-01", "2021-01-01") == pytest.approx(2 ** (365.25 / 366) - 1)
    assert bt.cagr(1, 2, "2020-01-01", "2020-01-01") is None


def test_big_moves_greedy_non_overlapping():
    closes = [100] * 5 + [100 + 3 * i for i in range(1, 11)] + [120] * 5 + [100] * 5 + [95, 90] \
        + [90 + 5 * i for i in range(1, 7)]
    moves = bt.big_moves(closes, 0, 0.20, 120)
    assert len(moves) == 2
    (a1, p1), (a2, p2) = moves
    assert closes[a1] == 100 and closes[p1] == 130 and p1 < a2
    assert closes[a2] == 90 and closes[p2] == 120
    assert bt.big_moves(closes, 0, 0.50, 120) == []


def test_move_capture_participation_and_midpoint():
    closes = [100, 110, 121, 133.1, 146.41]
    gross = [0, 0.1, 0.1, 0.1, 0.1]
    held_late = [False, False, True, True, True]
    m = bt.move_capture(closes, [0, 0, 0, 0.1, 0.1], held_late, 0, 4)
    assert m["participated"] and m["capture"] == pytest.approx(0.5)
    assert m["in_at_mid"]                           # midpoint (log) is reached on bar 2
    none = bt.move_capture(closes, [0] * 5, [False] * 5, 0, 4)
    assert not none["participated"] and none["capture"] == 0
    assert bt.move_capture(closes, gross, [True] * 5, 0, 4)["capture"] == pytest.approx(1.0)


def test_tbill_hurdle_point_in_time():
    irx = [Bar("2020-01-01", 0, 0, 0, 2.0, 0), Bar("2020-01-02", 0, 0, 0, 4.0, 0)]
    fn, src = bt.tbill_hurdle_fn(irx, window=2)
    assert fn("2019-12-31") == 0.0
    assert fn("2020-01-01") == pytest.approx(0.02)
    assert fn("2020-01-05") == pytest.approx(0.03)
    assert "IRX" in src
    zero, src0 = bt.tbill_hurdle_fn(None)
    assert zero("2020-01-01") == 0.0 and "unavailable" in src0


def _uptrend_result(ticker, start="2020-01-01"):
    up = flat_then_up()
    bars = make_bars(up + [up[-1] * (0.97 ** i) for i in range(1, 15)], start=start)
    return bt.backtest_instrument(ticker, bars, TrendConfig(), 0.0, "synthetic")


def test_backtest_instrument_metrics():
    r = _uptrend_result("SPY")
    m = r.metrics
    assert m["signals"] == 1 and m["closed"] == 1 and m["hit_rate"] == 1.0
    assert m["cagr"] is not None and m["mdd"] <= 0 and 0 < m["time_in_market"] < 1
    assert m["moves"] >= 1 and m["participation"] == 1.0
    short = bt.backtest_instrument("SPY", make_bars([100.0] * 50), TrendConfig(), 0.0)
    assert "unavailable" in short.metrics


def test_portfolio_risk_sizing_caps_and_slots():
    results = {t: _uptrend_result(t) for t in ("SPY", "QQQ", "IWM")}
    p = bt.run_portfolio(results, bt.PortfolioConfig(max_positions=2))
    assert len(p.taken) == 2 and len(p.skipped) == 1 and p.skipped[0]["why"] == "max positions"
    for pos in p.taken:
        tr = pos["trade"]
        risk = pos["units"] * (tr.fill_price - tr.initial_stop)
        assert risk <= 0.01 * 30_000 * 1.0001 or pos["weight"] <= 0.25 + 1e-9
        assert pos["weight"] <= 0.25 + 1e-9
    assert p.metrics["taken"] == 2 and p.equity[0] == pytest.approx(30_000, rel=0.01)
    assert 0 <= p.metrics["avg_exposure"] <= 1


def test_variants_grid():
    names = [n for n, _ in bt.variants(TrendConfig())]
    assert len(names) == 10 and "breakout 55 / 3xATR" in names


def test_report_builds_from_synthetic_cache(tmp_path):
    from marketmind.trend import report
    for t, crypto in (("SPY", False), ("BTC-USD", True)):
        up = flat_then_up()
        bars = make_bars(up + [up[-1] * (0.97 ** i) for i in range(1, 15)], start="2006-01-02",
                         crypto=crypto)
        (tmp_path / f"{t}.json").write_text(json.dumps({"ticker": t, "source": "synthetic", "bars": [
            [b.date, b.open, b.high, b.low, b.close, b.volume] for b in bars]}), encoding="utf-8")
    text = report.build(cache_dir=tmp_path, as_of="2007-12-31")
    assert "数据不可用" in text                      # the other instruments are labelled, not guessed
    assert "| SPY | synthetic |" in text and "## 9." in text
