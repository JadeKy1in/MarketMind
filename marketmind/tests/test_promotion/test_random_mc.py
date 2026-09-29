"""Monte Carlo "beats random" gate (docs/S7_DESIGN.md §一, promotion/random_mc.py). Offline."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C
from marketmind.promotion import random_mc as R

DAYS = [str(d) for d in np.arange(np.datetime64("2026-01-05"), np.datetime64("2026-12-31"),
                                  dtype="datetime64[D]") if np.is_busday(d)]
COST = 0.001                      # 2 x 5 bp for US tickers (settlement.cost_bps)


def _flat_bars(ret: float, days=DAYS) -> list[Bar]:
    """Every bar opens at 100 and closes at 100 * (1 + ret): a one-bar window returns `ret`."""
    return [Bar(d, 100.0, 100.0 * (1 + ret), 100.0, 100.0 * (1 + ret), 1.0) for d in days]


def _compound_bars(step: float, days=DAYS) -> list[Bar]:
    """open_i = 100 (1+step)^i, close_i = open_{i+1}: any L-bar window returns (1+step)^L - 1."""
    return [Bar(d, 100.0 * (1 + step) ** i, 0, 0, 100.0 * (1 + step) ** (i + 1), 1.0)
            for i, d in enumerate(days)]


def _pattern_bars(signs, days=DAYS) -> list[Bar]:
    """One-bar windows return +1% or -1% by `signs`."""
    return [Bar(d, 100.0, 0, 0, 100.0 * (1 + 0.01 * g), 1.0) for d, g in zip(days, signs)]


def _trades(n: int, net, direction="long", hold_same_day=True, ticker="UP",
            days=None) -> list[LedgerEntry]:
    out = []
    days = list(days) if days is not None else list(range(n))
    for i, k in enumerate(days):
        d = DAYS[k]
        out.append(LedgerEntry("shadow", "S", ticker, direction if isinstance(direction, str)
                               else direction[i], 1, 0.6, 100.0, "x", status="settled",
                               entry_date=d, exit_date=d if hold_same_day else DAYS[k + 1],
                               net_return=net))
    return out


def test_round_trip_cost_is_the_ledgers():
    from marketmind.ledger.settlement import cost_bps
    assert R.round_trip_cost("AAPL") == pytest.approx(2 * cost_bps("stock", "AAPL") / 1e4)
    assert R.round_trip_cost("BTC-USD") == pytest.approx(0.02)
    assert R.round_trip_cost("SOL-USD") == pytest.approx(0.025)


def test_window_return_and_gaps():
    bars = [Bar("2026-01-05", 100, 0, 0, 101, 0), Bar("2026-01-06", 102, 0, 0, 104, 0),
            Bar("2026-01-12", 104, 0, 0, 110, 0)]
    dates = [b.date for b in bars]
    assert R.window_return(bars, dates, "2026-01-05", "2026-01-06") == pytest.approx(0.04)
    assert R.window_return(bars, dates, "2026-01-05", "2026-01-05") == pytest.approx(0.01)
    # Saturday entry (crypto shadow) -> first bar on or after it, within the gap tolerance
    assert R.window_return(bars, dates, "2026-01-10", "2026-01-12") == pytest.approx(110 / 104 - 1)
    # last bar 5 calendar days before the exit (> MC_MAX_GAP_DAYS): gap -> None
    assert R.window_return(bars, dates, "2026-01-06", "2026-01-11") is None
    assert R.window_return(bars, dates, "2026-01-07", "2026-01-08") is None      # no bar inside
    assert R.window_return(bars, dates, "2026-02-01", "2026-02-02") is None      # after the data


def test_timing_skill_passes_and_anti_timing_fails():
    """The shadow is long exactly on the +1% days (or exactly on the -1% days)."""
    signs = np.where(np.random.default_rng(0).random(len(DAYS)) < 0.5, 1, -1)
    bars = {"UP": _pattern_bars(signs)}
    up = [k for k in range(120) if signs[k] > 0][:50]
    down = [k for k in range(120) if signs[k] < 0][:50]
    good = R.mc_baseline("S", _trades(50, 0.01 - COST, days=up), bars, "2026-06-01")
    assert good["status"] == "pass" and good["valid_draws"] == C.MC_DRAWS
    assert good["p_value"] == pytest.approx(1 / (C.MC_DRAWS + 1))
    assert abs(good["sim_mean"] + COST) < 0.004                  # random timing earns ~0
    bad = R.mc_baseline("S", _trades(50, -0.01 - COST, days=down), bars, "2026-06-01")
    assert bad["status"] == "fail" and bad["p_value"] > 0.9


def test_long_short_mix_ticker_and_length_are_kept_exactly():
    """Every bar +1%: whatever the shift, each draw's mean is (longs - shorts) / n x 1% - cost."""
    dirs = ["long"] * 70 + ["short"] * 30
    out = R.mc_baseline("S", _trades(100, 0.02, direction=dirs), {"UP": _flat_bars(0.01)},
                        "2026-06-01")
    assert out["sim_mean"] == pytest.approx(0.4 * 0.01 - COST)
    assert out["sim_sd"] == pytest.approx(0.0, abs=1e-12)
    assert out["status"] == "pass"
    # a 2-bar trade is priced over 2 bars wherever it is moved
    two = R.mc_baseline("S", _trades(60, 0.0, hold_same_day=False), {"UP": _compound_bars(0.01)},
                        "2026-06-01")
    assert two["sim_mean"] == pytest.approx(1.01 ** 2 - 1 - COST)
    assert two["sim_sd"] == pytest.approx(0.0, abs=1e-9)


def test_zero_skill_concentrated_shadow_keeps_the_nominal_level():
    """One high-volatility ticker, overlapping 10-day holds, random timing: ~5% pass
    (uniform pool draws passed ~26% in the 2026-09-29 simulation)."""
    rng = np.random.default_rng(5)
    passes, reps = 0, 150
    for k in range(reps):
        px, bars = 100.0, []
        for d in DAYS[:140]:
            o = px * np.exp(0.015 * rng.standard_normal())
            px = o * np.exp(0.035 * rng.standard_normal())
            bars.append(Bar(d, o, 0, 0, px, 1.0))
        tr = []
        for i in range(60):
            a, b = i + 1, i + 10
            sign = 1.0 if rng.random() < 0.7 else -1.0
            tr.append(LedgerEntry("shadow", "S", "HOT", "long" if sign > 0 else "short", 10, 0.6,
                                  100.0, "x", status="settled", entry_date=DAYS[a],
                                  exit_date=DAYS[b],
                                  net_return=sign * (bars[b].close / bars[a].open - 1) - COST))
        passes += R.mc_baseline("S", tr, {"HOT": bars}, f"r{k}")["status"] == "pass"
    assert passes / reps < 0.11


def test_deterministic_seed_per_shadow_and_date():
    rng = np.random.default_rng(0)
    bars = {"UP": [Bar(d, 100.0, 0, 0, 100.0 * (1 + 0.01 * rng.standard_normal()), 0)
                   for d in DAYS]}
    tr = _trades(60, 0.001, days=range(0, 120, 2))
    one = R.mc_baseline("S", tr, bars, "2026-06-01")
    assert one == R.mc_baseline("S", tr, bars, "2026-06-01")
    other = R.mc_baseline("S", tr, bars, "2026-06-02")
    assert other["seed"] != one["seed"] and other["sim_mean"] != one["sim_mean"]
    assert R.seed_for("S", "2026-06-01") != R.seed_for("T", "2026-06-01")


def test_not_evaluable_cases_fail_closed():
    tr = _trades(60, 0.05)
    assert R.mc_baseline("S", [], {"UP": _flat_bars(0.0)}, "2026-06-01")["status"] == "not_evaluable"
    out = R.mc_baseline("S", tr, {}, "2026-06-01")                # traded ticker without bars
    assert out["status"] == "not_evaluable" and out["missing_tickers"] == ["UP"]
    assert out["unpriced_trades"] == 60
    # a second ticker without bars: 20% unpriced is tolerated, more is not
    mixed = tr[:48] + _trades(12, 0.05, ticker="X", days=range(48, 60))
    ok = R.mc_baseline("S", mixed, {"UP": _flat_bars(0.0)}, "2026-06-01")
    assert ok["status"] == "pass" and ok["unpriced_trades"] == 12 and ok["missing_tickers"] == ["X"]
    mixed = tr[:47] + _trades(13, 0.05, ticker="X", days=range(47, 60))
    out = R.mc_baseline("S", mixed, {"UP": _flat_bars(0.0)}, "2026-06-01")
    assert out["status"] == "not_evaluable" and "without usable bars" in out["reason"]
    # evaluation window too short for a 5% test
    out = R.mc_baseline("S", _trades(30, 0.05), {"UP": _flat_bars(0.0)}, "2026-06-01")
    assert out["status"] == "not_evaluable" and out["window_days"] == 30


def test_trade_on_a_data_gap_is_unpriced():
    tr = _trades(60, 0.05)
    bars = _flat_bars(0.0)
    out = R.mc_baseline("S", tr, {"UP": bars[:10] + bars[20:]}, "2026-06-01")
    assert out["unpriced_trades"] == 10 and out["status"] == "pass"


class _CountingSource(StaticPriceSource):
    def __init__(self, bars):
        super().__init__(bars)
        self.calls: list[str] = []

    async def daily_bars(self, ticker):
        self.calls.append(ticker)
        if ticker == "BOOM":
            raise RuntimeError("network down")
        return await super().daily_bars(ticker)


def test_source_loader_caches_cuts_at_today_and_survives_errors():
    src = _CountingSource({"UP": _flat_bars(0.01), "FLAT": _flat_bars(0.0)})
    load = R.source_loader(src, today=DAYS[9])
    got = load(["UP", "FLAT", "BOOM", "NONE"])
    assert [b.date for b in got["UP"]][-1] == DAYS[9] and len(got["UP"]) == 10
    assert got["BOOM"] is None and got["NONE"] is None
    load(["UP", "BOOM"])
    assert sorted(src.calls) == ["BOOM", "FLAT", "NONE", "UP"]            # cached, fetched once


@pytest.mark.asyncio
async def test_source_loader_works_inside_a_running_event_loop():
    """The daily pipeline calls run_promotion from an async step."""
    load = R.source_loader(StaticPriceSource({"UP": _flat_bars(0.01)}))
    assert len(load(["UP"])["UP"]) == len(DAYS)
    await asyncio.sleep(0)


def test_source_loader_budget_exhausted_counts_as_missing():
    class Slow(StaticPriceSource):
        async def daily_bars(self, ticker):
            await asyncio.sleep(0.5)
            return await super().daily_bars(ticker)
    load = R.source_loader(Slow({"UP": _flat_bars(0.01)}), budget_s=0.05)
    assert load(["UP"])["UP"] is None
