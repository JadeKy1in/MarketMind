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


def _trades(n: int, net: float, direction="long", hold_same_day=True) -> list[LedgerEntry]:
    out = []
    for i in range(n):
        d = DAYS[i]
        out.append(LedgerEntry("shadow", "S", "UP", direction if isinstance(direction, str)
                               else direction[i], 1, 0.6, 100.0, "x", status="settled",
                               entry_date=d, exit_date=d if hold_same_day else DAYS[i + 1],
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


def test_known_distribution_pass_and_fail():
    """Pool UP (+1% per window) and FLAT (0%): each draw's gross mean is 1% x Binomial(n, 1/2) / n."""
    bars = {"UP": _flat_bars(0.01), "FLAT": _flat_bars(0.0)}
    n = 100
    good = R.mc_baseline("S", _trades(n, 0.009), ["UP", "FLAT"], bars, "2026-06-01")
    assert good["status"] == "pass" and good["valid_draws"] == C.MC_DRAWS
    assert good["sim_mean"] == pytest.approx(0.005 - COST, abs=2e-4)
    assert good["sim_sd"] == pytest.approx(0.005 / np.sqrt(n), rel=0.1)
    assert good["p_value"] == pytest.approx(1 / (C.MC_DRAWS + 1))
    q95 = 0.005 - COST + 1.645 * 0.0005
    assert good["sim_quantile"] == pytest.approx(q95, abs=2.5e-4)
    # a shadow at the random mean fails; just under the 95th percentile fails too
    assert R.mc_baseline("S", _trades(n, 0.004), ["UP", "FLAT"], bars, "2026-06-01")["status"] == "fail"
    near = R.mc_baseline("S", _trades(n, q95 - 3e-4), ["UP", "FLAT"], bars, "2026-06-01")
    assert near["status"] == "fail" and 0.05 < near["p_value"] < 0.5


def test_long_short_ratio_is_preserved_exactly():
    """Only UP in the pool: every draw's mean is (longs - shorts) / n x 1% - cost."""
    dirs = ["long"] * 70 + ["short"] * 30
    out = R.mc_baseline("S", _trades(100, 0.02, direction=dirs), ["UP"], {"UP": _flat_bars(0.01)},
                        "2026-06-01")
    assert out["sim_mean"] == pytest.approx(0.4 * 0.01 - COST)
    assert out["sim_sd"] == pytest.approx(0.0, abs=1e-12)
    assert out["status"] == "pass"


def test_same_dates_and_holding_periods():
    """A 2-bar trade is priced open(entry day) -> close(exit day), not a one-bar window."""
    bars = [Bar(d, 100.0 + i, 0, 0, 100.0 + i + 0.5, 0) for i, d in enumerate(DAYS)]
    t = _trades(1, 0.0, hold_same_day=False)
    out = R.mc_baseline("S", t * 1, ["X"], {"X": bars}, "2026-06-01", draws=C.MC_MIN_VALID)
    assert out["sim_mean"] == pytest.approx((101.5 / 100.0 - 1) - COST)


def test_deterministic_seed_per_shadow_and_date():
    rng = np.random.default_rng(0)
    bars = {t: [Bar(d, 100.0, 0, 0, 100.0 * (1 + 0.01 * rng.standard_normal()), 0) for d in DAYS]
            for t in ("A", "B", "C")}
    tr = _trades(60, 0.001)
    one = R.mc_baseline("S", tr, ["A", "B", "C"], bars, "2026-06-01")
    assert one == R.mc_baseline("S", tr, ["A", "B", "C"], bars, "2026-06-01")
    other = R.mc_baseline("S", tr, ["A", "B", "C"], bars, "2026-06-02")
    assert other["seed"] != one["seed"] and other["sim_mean"] != one["sim_mean"]
    assert R.seed_for("S", "2026-06-01") != R.seed_for("T", "2026-06-01")


def test_not_evaluable_cases_fail_closed():
    tr = _trades(20, 0.05)
    assert R.mc_baseline("S", [], ["UP"], {"UP": _flat_bars(0.0)}, "2026-06-01")["status"] == "not_evaluable"
    # every pool ticker without bars
    out = R.mc_baseline("S", tr, ["UP", "X"], {}, "2026-06-01")
    assert out["status"] == "not_evaluable" and out["missing_tickers"] == ["UP", "X"]
    # more than half of the pool without bars
    out = R.mc_baseline("S", tr, ["UP", "X", "Y"], {"UP": _flat_bars(0.0)}, "2026-06-01")
    assert out["status"] == "not_evaluable" and "pool tickers" in out["reason"]
    # half the pool missing is tolerated: the missing ticker is dropped and reported
    out = R.mc_baseline("S", tr, ["UP", "X"], {"UP": _flat_bars(0.0)}, "2026-06-01")
    assert out["status"] == "pass" and out["pool_usable"] == 1 and out["missing_tickers"] == ["X"]


def test_gappy_ticker_excludes_draws_and_reports_the_effective_count():
    """GAP has no bars on the first k trade days: a draw is valid only if none of those
    k trades picked GAP, probability 2^-k."""
    tr = _trades(20, 0.05)
    full, gappy = _flat_bars(0.0), _flat_bars(0.0)
    few = R.mc_baseline("S", tr, ["OK", "GAP"], {"OK": full, "GAP": gappy[2:]}, "2026-06-01")
    assert few["status"] == "pass" and 180 < few["valid_draws"] < 330      # ~250 of 1000
    assert few["gap_cells"] == 2
    none = R.mc_baseline("S", tr, ["OK", "GAP"], {"OK": full, "GAP": gappy[4:]}, "2026-06-01")
    assert none["status"] == "not_evaluable" and none["valid_draws"] < C.MC_MIN_VALID  # ~62
    assert "valid draws" in none["reason"]


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
