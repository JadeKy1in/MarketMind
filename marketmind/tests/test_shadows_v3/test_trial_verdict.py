"""Variant-trial verdict (docs/S7_DESIGN.md §二 判定): exit-date aligned daily P&L,
one-sided HAC t, Holm across the trials decided in the same review. Offline."""
from __future__ import annotations

import numpy as np
import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import metrics as M
from marketmind.shadows.v3 import trials

PARENT = "momentum:weekly:trend_rider"
OTHER = "momentum:sector:rotation_engine"
START = "2026-09-01"
END = trials.add_trading_days(START, trials.TRIAL_BARS)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return LedgerStore(tmp_path / "ledger.db"), tmp_path


def _days(n, start="2026-08-31"):
    out, d = [], start
    for _ in range(n):
        d = trials.add_trading_days(d, 1)
        out.append(d)
    return out


def _add(store, source_type, source_id, run_day, exit_day, pnl, hold=1, status="settled"):
    e = LedgerEntry(source_type, source_id, "SPY", "long", hold, 0.6, 1000.0, "x",
                    meta={"run_date": run_day})
    if status == "settled":
        e.status, e.entry_date, e.exit_date = "settled", run_day, exit_day
        e.pnl_usd, e.net_return = pnl, pnl / 1000.0
    store.add(e, created_at=f"{run_day}T10:00:00+00:00")


def _trial(tid, parent):
    return trials.Trial(tid, "beta", parent, "n", START, END)


def test_constants_follow_the_owner_decision():
    assert trials.TRIAL_BARS == 40 and trials.MIN_PAIRS == 30 and trials.ALPHA == 0.05
    assert trials.MAX_RUNNING == 5
    assert END == "2026-10-27"


def test_daily_differences_align_by_exit_date(env):
    store, _ = env
    d = _days(45)
    # parent: 3-day holds decided on d0, d1 -> exits d3, d4; variant: 1-day holds -> d1, d2
    _add(store, "shadow", PARENT, d[0], d[3], 100.0, hold=3)
    _add(store, "shadow", PARENT, d[1], d[4], -50.0, hold=3)
    _add(store, "shadow", PARENT, d[2], d[5], 20.0, hold=5)
    _add(store, "temp_shadow", "trial:t1", d[0], d[1], 30.0)
    _add(store, "temp_shadow", "trial:t1", d[1], d[2], 40.0)
    _add(store, "temp_shadow", "trial:t1", d[44], d[44], 999.0)        # decided after the window
    _add(store, "main", "main", d[0], d[7], 1.0)                        # extends the calendar
    out = trials.daily_differences(store, _trial("t1", PARENT))
    assert out["done"] and out["days"] == d[1:6]
    # (variant - parent) / $10,000 notional per exit day
    assert out["diffs"] == pytest.approx([0.003, 0.004, -0.01, 0.005, -0.002])
    assert out["parent_hold"] == 3 and out["lag"] == 2               # median hold 3 -> lag 2


def test_lag_is_at_least_one(env):
    store, _ = env
    d = _days(3)
    _add(store, "shadow", PARENT, d[0], d[0], 1.0, hold=1)
    assert trials.daily_differences(store, _trial("t1", PARENT))["lag"] == 1


def _fill(store, tid, parent, parent_pnl, variant_pnl, hold=1):
    for i, day in enumerate(_days(trials.TRIAL_BARS)):
        _add(store, "shadow", parent, day, day, parent_pnl(i), hold=hold)
        _add(store, "temp_shadow", f"trial:{tid}", day, day, variant_pnl(i), hold=hold)


def test_verdict_uses_hac_on_the_difference(env):
    store, _ = env
    trials.save([_trial("t1", PARENT)])
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 20, 40)
    _fill(store, "t1", PARENT, lambda i: noise[i], lambda i: noise[i] + 10 + 5 * ((-1) ** i),
          hold=5)
    t = trials.evaluate(store, today="2026-11-01")[0]
    r = t.result
    diffs = [(10 + 5 * ((-1) ** i)) / 10_000 for i in range(40)]
    ref = M.hac_t_test(diffs, 4)
    assert r["lag"] == 4 and r["p_value"] == pytest.approx(ref["p_value"])
    assert r["t_stat"] == pytest.approx(ref["t"]) and r["aligned_by"] == "exit_date"
    assert t.status == "passed" and r["p_value"] < 0.05


def test_no_difference_fails_and_short_series_is_insufficient(env):
    store, _ = env
    trials.save([_trial("t1", PARENT), _trial("t2", OTHER)])
    rng = np.random.default_rng(1)
    a, b = rng.normal(0, 20, 40), rng.normal(0, 20, 40)
    _fill(store, "t1", PARENT, lambda i: a[i], lambda i: b[i])
    for day in _days(20):                                  # t2: only 20 exit days
        _add(store, "shadow", OTHER, day, day, 1.0)
        _add(store, "temp_shadow", "trial:t2", day, day, 50.0)
    out = {t.trial_id: t for t in trials.evaluate(store, today="2026-11-01")}
    assert out["t1"].status == "failed" and out["t1"].result["p_value"] > 0.05
    assert out["t2"].status == "insufficient" and out["t2"].result["pairs"] == 20
    assert out["t1"].result["holm_family"] == 1              # t2 was not tested


def test_holm_across_trials_decided_in_the_same_review(env, monkeypatch):
    """p = 0.03 passes alone; two such trials in one review: Holm p = 0.06 -> both fail."""
    store, _ = env

    def fake(d, lag):
        return {"n": len(d), "lag": lag, "mean": 1.0, "se": 1.0, "t": 2.0, "p_value": 0.03}
    monkeypatch.setattr(M, "hac_t_test", fake)
    _fill(store, "t1", PARENT, lambda i: 0.0, lambda i: 10.0 + i)
    _fill(store, "t2", OTHER, lambda i: 0.0, lambda i: 10.0 + i)

    trials.save([_trial("t1", PARENT)])
    alone = trials.evaluate(store, today="2026-11-01")[0]
    assert alone.status == "passed" and alone.result["p_holm"] == pytest.approx(0.03)

    trials.save([_trial("t1", PARENT), _trial("t2", OTHER)])
    both = trials.evaluate(store, today="2026-11-01")
    assert [t.status for t in both] == ["failed", "failed"]
    assert all(t.result["p_holm"] == pytest.approx(0.06) and t.result["holm_family"] == 2
               for t in both)


def test_trial_still_waiting_is_not_in_the_family(env, monkeypatch):
    store, _ = env

    def fake(d, lag):
        return {"n": len(d), "lag": lag, "mean": 1.0, "se": 1.0, "t": 2.0, "p_value": 0.03}
    monkeypatch.setattr(M, "hac_t_test", fake)
    _fill(store, "t1", PARENT, lambda i: 0.0, lambda i: 10.0 + i)
    _add(store, "temp_shadow", "trial:t2", START, None, 0.0, status="pending")
    trials.save([_trial("t1", PARENT), _trial("t2", OTHER)])
    decided = trials.evaluate(store, today="2026-11-01")
    assert [t.trial_id for t in decided] == ["t1"] and decided[0].result["holm_family"] == 1
    assert decided[0].status == "passed"
