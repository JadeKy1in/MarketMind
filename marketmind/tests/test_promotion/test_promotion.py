"""Promotion ladder (docs/S7_DESIGN.md §一): metric values, every gate, pause/resume, challenge, files."""
from __future__ import annotations

import json
import math
from itertools import combinations

import numpy as np
import pytest
from scipy import stats

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import config as C
from marketmind.promotion import metrics as M
from marketmind.promotion.ladder import (composite_scores, evaluate, matured, probation_gates,
                                         shadow_stats, trial_ids)
from marketmind.promotion.random_mc import static_loader
from marketmind.promotion.runner import run_promotion, trial_count
from marketmind.shadows.v3.roster import PENDING_PROMPT, ROSTER, RosterEntry

DAYS = [str(d) for d in np.arange(np.datetime64("2026-01-05"), np.datetime64("2026-12-31"),
                                  dtype="datetime64[D]") if np.is_busday(d)]


# ── Metrics ─────────────────────────────────────────────────────────────

def test_min_trl_hand_value_and_psr_identity():
    z = stats.norm.ppf(0.95)
    assert M.min_trl(0.5, 0.0, 3.0) == pytest.approx(1 + 1.125 * (z / 0.5) ** 2)
    assert M.min_trl(0.5, 0.0, 3.0) == pytest.approx(13.1754, abs=1e-3)
    assert M.min_trl(0.0, 0.0, 3.0) == math.inf
    # Bailey & Lopez de Prado: PSR evaluated at n = MinTRL equals the confidence level
    for sr, g3, g4 in [(0.5, 0.0, 3.0), (0.2, -1.0, 6.0), (0.1, 0.5, 4.0)]:
        assert M.psr(sr, M.min_trl(sr, g3, g4), g3, g4) == pytest.approx(0.95)


def test_psr_direct_formula():
    sr, n, g3, g4 = 0.1, 100, -0.5, 5.0
    expected = stats.norm.cdf(sr * math.sqrt(n - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    assert M.psr(sr, n, g3, g4) == pytest.approx(expected)
    assert expected == pytest.approx(0.8331, abs=1e-3)


def test_dsr_sidak_form():
    """DSR = PSR(0) ** K with the variance term floored at 1 (fix 2026-09-29)."""
    r = np.random.default_rng(1).normal(0.001, 0.01, 250)
    g3, g4 = M.skew_kurt(r)
    sr = M.sharpe(r)
    z = sr * math.sqrt(249) / math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr * sr, 1.0))
    assert M.dsr(r, 1) == pytest.approx(stats.norm.cdf(z))
    assert M.dsr(r, 30) == pytest.approx(stats.norm.cdf(z) ** 30)
    assert M.dsr(r, 100) < M.dsr(r, 10) < M.dsr(r, 1)
    # a positively skewed outlier cannot push the variance term below the normal value
    x = np.r_[np.zeros(59), 0.5]
    g3, g4 = M.skew_kurt(x)
    assert 1 - g3 * M.sharpe(x) < 1
    assert M.dsr(x, 1) == pytest.approx(stats.norm.cdf(M.sharpe(x) * math.sqrt(59)))


def test_dsr_family_wise_size_and_power():
    """30 candidates with t(5) daily returns: the best zero-skill one passes <= ~5%."""
    rng = np.random.default_rng(3)
    hits = 0
    for _ in range(300):
        r = 0.01 * rng.standard_t(5, (120, 30)) / math.sqrt(5 / 3)
        hits += any(M.dsr(r[:, i], 30) >= 0.95 for i in range(30))
    assert hits / 300 < 0.09


def test_effective_trials_clusters_correlated_candidates():
    rng = np.random.default_rng(4)
    days = DAYS[:120]
    base = rng.standard_normal(120)
    series = {f"c{i}": (days, base + 0.3 * rng.standard_normal(120)) for i in range(4)}
    series |= {f"u{i}": (days, rng.standard_normal(120)) for i in range(3)}
    series["short"] = (days[:10], rng.standard_normal(10))          # too little overlap
    k, clusters = M.effective_trials(series)
    assert k == 5 and ["c0", "c1", "c2", "c3"] in clusters
    assert M.effective_trials({}) == (1, []) and M.effective_trials({"a": series["u0"]})[0] == 1


def test_moments():
    r = np.random.default_rng(2).standard_normal(200_000)
    g3, g4 = M.skew_kurt(r)
    assert abs(g3) < 0.02 and g4 == pytest.approx(3.0, abs=0.05)
    assert M.sharpe([0.01, 0.03]) == pytest.approx(0.02 / np.std([0.01, 0.03], ddof=1))
    assert M.sharpe([0.01, 0.01]) == 0.0


def test_n_eff():
    assert M.n_eff(100, 60, 5) == 12
    assert M.n_eff(10, 60, 1) == 10
    assert M.n_eff(0, 60, 1) == 0


def test_mppm_calmar_omega_drawdown():
    assert M.mppm([0.01] * 5) == pytest.approx(math.log(1.01) * 252)
    r = [0.01, -0.01]
    hand = math.log((1.01 ** -2 + 0.99 ** -2) / 2) / (-2 / 252)
    assert M.mppm(r) == pytest.approx(hand)
    assert M.mppm([-1.0]) == -math.inf
    r = [0.01, -0.02, 0.01, 0.03]            # equity 1, 1.01, 0.99, 1.00, 1.03
    assert M.max_drawdown(r) == pytest.approx(0.02)
    assert M.calmar(r) == pytest.approx(0.0075 * 252 / 0.02)
    assert M.omega(r) == pytest.approx(0.05 / 0.02)
    assert M.calmar([0.01]) == math.inf and M.omega([0.01]) == math.inf
    assert M.omega([0.0]) == 0.0


def test_shrink_and_percentiles():
    assert M.shrink(1.0, 30, 0.5, 30) == pytest.approx(0.75)
    assert M.shrink(1.0, 0, 0.5, 30) == 0.5
    assert M.percentile_ranks([3.0, 1.0, 2.0, 2.0]) == [1.0, 0.25, 0.625, 0.625]
    assert M.percentile_ranks([math.inf, 0.0, float("nan")]) == pytest.approx([1.0, 2 / 3, 1 / 3])


def _pbo_reference(m, s):
    """Loop version of CSCV for cross-checking."""
    t, n = m.shape
    size = t // s
    m = m[t - size * s:]
    blocks = np.split(m, s)
    sr = lambda x: np.array([c.mean() / c.std() if c.std() > 0 else 0 for c in x.T])
    hits = total = 0
    for c in combinations(range(s), s // 2):
        ins = np.vstack([blocks[i] for i in c])
        oos = np.vstack([blocks[i] for i in range(s) if i not in c])
        best = int(np.argmax(sr(ins)))
        w = stats.rankdata(sr(oos))[best] / (n + 1)
        hits += np.log(w / (1 - w)) <= 0
        total += 1
    return hits / total


def test_pbo_matches_reference_and_behaves():
    rng = np.random.default_rng(3)
    small = rng.normal(0, 1, (41, 5))
    assert M.pbo_cscv(small, 8) == pytest.approx(_pbo_reference(small, 8))
    dominant = rng.normal(0, 1, (320, 10))
    dominant[:, 0] += 0.3
    assert M.pbo_cscv(dominant) < 0.1
    noise = [M.pbo_cscv(np.random.default_rng(s).normal(0, 1, (320, 10))) for s in range(20)]
    assert 0.4 < np.mean(noise) < 0.65
    assert M.pbo_cscv(rng.normal(0, 1, (320, 1))) is None
    assert M.pbo_cscv(rng.normal(0, 1, (20, 3))) is None


def test_cusum():
    assert M.cusum_down([-1.0] * 20, 0.0, 1.0) == 10          # S grows 0.5/step, > 5 at step 11
    for seed in (1, 2, 3, 4):
        assert M.cusum_down(np.random.default_rng(seed).normal(0, 1, 250), 0.0, 1.0) is None
    x = np.random.default_rng(5).normal(0, 1, 200)
    x[100:] -= 1.5
    alarm = M.cusum_down(x, 0.0, 1.0)
    assert alarm is not None and 100 <= alarm <= 115
    assert M.cusum_down(x, 0.0, 0.0) is None


def test_stress_test():
    """Worst-decile market days: the shadow must do at least as well as the market."""
    market = np.array([-0.02] + [0.001] * 9)
    ok, d = M.stress_test(np.array([-0.02] + [0.0] * 9), market)
    assert ok and d["worst_days"] == 1 and d["market_mean"] == -0.02
    assert M.stress_test(np.array([-0.005] + [0.0] * 9), market)[0] is True
    assert M.stress_test(np.array([-0.03] + [0.0] * 9), market)[0] is False     # old rule passed
    assert M.stress_test(np.zeros(5), np.full(5, -0.01))[0] is None


def test_stress_rejects_zero_skill_beta_one_longs_half_the_time():
    """Old rule (>= 2 x market mean) passed ~99% of zero-skill beta-1 longs."""
    rng = np.random.default_rng(6)
    passed = 0
    for _ in range(400):
        mk = 0.01 * rng.standard_normal(120)
        passed += M.stress_test(mk + 0.004 * rng.standard_normal(120), mk)[0]
    assert 0.35 < passed / 400 < 0.65
    hedged = sum(M.stress_test(0.3 * mk + 0.004 * rng.standard_normal(120), mk)[0]
                 for mk in (0.01 * rng.standard_normal(120) for _ in range(200)))
    assert hedged / 200 > 0.95


def test_daily_pnl_and_calendar():
    rows = [_row("shadow", "x", DAYS[0], DAYS[2], 0.01, position=1000),
            _row("shadow", "x", DAYS[1], DAYS[2], 0.02, position=500),
            _row("main", "main", DAYS[0], DAYS[4], 0.01)]
    assert M.trading_calendar(rows) == [DAYS[2], DAYS[4]]
    assert M.daily_pnl(rows[:2]) == {DAYS[2]: pytest.approx((10 + 10) / 10_000)}
    assert list(M.daily_series({DAYS[2]: 0.5}, DAYS[1:4])) == [0.0, 0.5, 0.0]


# ── Synthetic ledger ────────────────────────────────────────────────────

def _row(st, sid, created, exit_, net, position=1000.0, hold=1, excess_domain=0.01,
         brier=0.2, market=None) -> LedgerEntry:
    return LedgerEntry(
        source_type=st, source_id=sid, ticker="SPY", direction="long", hold_bars=hold,
        confidence=0.6, position_usd=position, falsifier="x", created_at=f"{created}T12:00:00Z",
        status="settled", entry_date=created, exit_date=exit_, net_return=net,
        pnl_usd=net * position, excess_domain=excess_domain, brier=brier, market_return=market)


def _shadow(sid, days, mean, sd, seed, crash_from=None, **kw) -> list[LedgerEntry]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(days):
        net = mean + sd * rng.standard_normal()
        if crash_from is not None and i + 1 >= crash_from:
            net = -0.03
        rows.append(_row("shadow", sid, DAYS[i], DAYS[i + 1], net,
                         market=0.02 * rng.standard_normal(), **kw))
    return rows


def _bench(sid, days, net):
    return [_row("benchmark", f"random:{sid}", DAYS[i], DAYS[i + 1], net) for i in range(days)]


def _main(days, net):
    return [_row("main", "main", DAYS[i], DAYS[i + 1], net) for i in range(days)]


POOL = ("SPY", "AAA")              # the synthetic shadows trade SPY


def _bars(drift=0.0, sd=0.01, seed=11) -> dict[str, list[Bar]]:
    """Daily bars for the Monte Carlo ticker pool on every day of DAYS."""
    rng = np.random.default_rng(seed)
    out = {}
    for t in POOL:
        px, bars = 100.0, []
        for d in DAYS:
            o = px * (1 + drift / 2 + sd / 2 * rng.standard_normal())
            px = o * (1 + drift / 2 + sd / 2 * rng.standard_normal())
            bars.append(Bar(d, o, max(o, px), min(o, px), px, 1e6))
        out[t] = bars
    return out


BARS = _bars()                    # zero drift: random portfolios earn ~ -cost
TREND_BARS = _bars(drift=0.03)    # +3% a day: random longs beat every shadow here


def _roster(*ids, status="active"):
    return [RosterEntry(s, s, s, "fundamental", "d", POOL, "SPY", status) for s in ids]


def _world(days=130, a_kw=None, b_kw=None, bench=-0.01, main=-0.01):
    rows = _shadow("A", days, 0.02, 0.01, 1, **(a_kw or {}))
    rows += _shadow("B", days, 0.006, 0.01, 2, **(b_kw or {}))
    rows += _bench("A", days, bench) + _bench("B", days, bench) + _main(days, main)
    return rows


def _run(rows, day_idx, state=None, ids=("A", "B"), trials=2, bars=BARS, **kw):
    return evaluate(rows, _roster(*ids), DAYS[day_idx], state, trials,
                    active_ids=set(ids), bars_for=static_loader(bars), **kw)


# ── Probation -> formal ─────────────────────────────────────────────────

def test_probation_progress_then_formal():
    rows = _world()
    st, ev = _run(rows, 58)                                      # decisions on days 0..58
    assert st["shadows"]["A"]["stage"] == "probation"
    assert st["shadows"]["A"]["metrics"]["record_days"] == 59
    assert st["shadows"]["A"]["score"] is None                   # C04: not ranked
    st, ev = _run(rows, 59, st)
    assert st["shadows"]["A"]["stage"] == "formal"
    assert st["shadows"]["A"]["formal_since"] == DAYS[59]
    assert {e["shadow_id"] for e in ev if e["type"] == "promote"} == {"A", "B"}


@pytest.mark.parametrize("gate,rows_fn,bars", [
    ("days", lambda: _world(days=59), BARS),
    ("min_trl", lambda: _shadow("A", 100, 0.01, 0.1, 3) + _bench("A", 100, -0.1)
     + _main(100, -0.1), BARS),
    ("beat_random", lambda: _world(), TREND_BARS),
    ("beat_domain", lambda: _world(a_kw={"excess_domain": -0.01}), BARS),
    ("beat_main", lambda: _world(main=0.05), BARS),
])
def test_each_probation_gate_blocks_alone(gate, rows_fn, bars):
    rows = rows_fn()
    st, ev = _run(rows, 60 if gate != "min_trl" else 100, ids=("A",), bars=bars)
    gates = st["shadows"]["A"]["probation_gates"]
    assert gates[gate] is False
    if gate != "days":            # below the days gate the Monte Carlo is not run at all
        assert all(v for k, v in gates.items() if k != gate), gates
    assert st["shadows"]["A"]["stage"] == "probation" and not ev


def test_beat_random_is_monte_carlo_not_the_ledger_random_shadow():
    rows = _world(bench=0.05)       # the ledger's random shadow did better than A ...
    st, _ = _run(rows, 60, ids=("A",))
    mc = st["shadows"]["A"]["random_mc"]
    assert st["shadows"]["A"]["probation_gates"]["beat_random"] is True    # ... irrelevant now
    assert mc["status"] == "pass" and mc["valid_draws"] == C.MC_DRAWS
    assert mc["p_value"] == pytest.approx(1 / (C.MC_DRAWS + 1))
    # the shadow's own trades moved in time: only its own ticker (SPY) is priced
    assert mc["method"] == "monte_carlo_time_shift" and mc["tickers"] == 1
    assert mc["missing_tickers"] == [] and mc["unpriced_trades"] == 0
    assert mc["trades"] == 60                                     # matured cohorts days 0..59
    # the old ledger comparison is still reported for the dashboard
    assert st["shadows"]["A"]["metrics"]["random_mean_net"] == pytest.approx(0.05)
    st, _ = _run(rows, 60, ids=("A",), bars=TREND_BARS)
    assert st["shadows"]["A"]["random_mc"]["status"] == "fail"


def test_beat_random_fails_closed_and_is_only_run_when_needed():
    rows = _world()
    st, _ = _run(rows, 30, ids=("A",))
    assert st["shadows"]["A"]["random_mc"]["status"] == "not_evaluated"
    st, _ = _run(rows, 60, ids=("A",), bars={})                   # no bars at all
    mc = st["shadows"]["A"]["random_mc"]
    assert mc["status"] == "not_evaluable" and mc["missing_tickers"] == ["SPY"]
    assert st["shadows"]["A"]["stage"] == "probation"
    st, _ = evaluate(rows, _roster("A"), DAYS[60], None, 1, active_ids={"A"})   # no price source
    assert st["shadows"]["A"]["random_mc"]["status"] == "not_evaluable"
    assert st["shadows"]["A"]["probation_gates"]["beat_random"] is False


def test_formal_shadow_keeps_its_promotion_day_monte_carlo():
    rows = _world()
    st, _ = _run(rows, 60, ids=("A",))
    mc = st["shadows"]["A"]["random_mc"]
    calls = []

    def spy(tickers):
        calls.append(tickers)
        return {}
    st2, _ = evaluate(rows, _roster("A"), DAYS[61], st, 2, active_ids={"A"}, bars_for=spy)
    assert calls == [] and st2["shadows"]["A"]["random_mc"] == mc


def test_blocked_roster_shadow_listed():
    rows = _world()
    roster = _roster("A") + _roster("Z", status=PENDING_PROMPT)
    st, _ = evaluate(rows, roster, DAYS[60], None, 1, active_ids={"A"},
                     bars_for=static_loader(BARS))
    assert st["shadows"]["Z"]["stage"] == "blocked"
    assert st["shadows"]["A"]["stage"] == "formal"


# ── Formal -> advisor ───────────────────────────────────────────────────

def _to_formal(rows):
    st, _ = _run(rows, 60)
    assert st["shadows"]["A"]["stage"] == "formal"
    return st


def test_advisor_promotion():
    rows = _world()
    st = _to_formal(rows)
    st, ev = _run(rows, 80, st)
    assert st["shadows"]["A"]["stage"] == "formal"                # 19 matured formal cohorts
    assert st["shadows"]["A"]["advisor_inputs"]["forward_oos_days"] == 19
    st, ev = _run(rows, 81, st)
    a = st["shadows"]["A"]
    assert a["stage"] == "advisor", a["advisor_gates"]
    assert a["tier"] == 1 and st["shadows"]["B"]["tier"] is None
    assert st["shadows"]["B"]["stage"] == "formal"
    assert st["shadows"]["B"]["advisor_gates"]["tier"] is False
    assert [e["to"] for e in ev] == ["advisor"]


@pytest.mark.parametrize("gate,const,value", [
    ("formal_days", "ADVISOR_MIN_FORMAL_DAYS", 22),
    ("tier", "TIER2_TOP_SHARE", 0.0),
    ("stress", "STRESS_MIN_DAYS", 10_000),
    ("forward_oos", "FORWARD_OOS_DAYS", 21),
    ("pbo", "PBO_MAX", 0.0),
    ("dsr", "DSR_MIN", 1.01),
    ("brier", "BRIER_MAX", 0.1),
])
def test_each_advisor_gate_blocks_alone(monkeypatch, gate, const, value):
    rows = _world()
    st = _to_formal(rows)
    monkeypatch.setattr(C, const, value)
    if const == "TIER2_TOP_SHARE":
        monkeypatch.setattr(C, "TIER1_TOP_SHARE", 0.0)
    st, ev = _run(rows, 81, st)
    gates = st["shadows"]["A"]["advisor_gates"]
    assert gates[gate] is False
    assert all(v for k, v in gates.items() if k != gate), gates
    assert st["shadows"]["A"]["stage"] == "formal" and not ev


def test_stress_gate_fails_on_crash_days():
    rows = _world()
    st = _to_formal(rows)
    # after becoming formal: three market crashes (-8%) on which A loses half its position
    window = [e for e in rows if e.source_id == "A" and DAYS[60] < e.exit_date <= DAYS[81]]
    for e in window[:3]:
        e.market_return, e.net_return, e.pnl_usd = -0.08, -0.5, -0.5 * e.position_usd
    st, _ = _run(rows, 81, st)
    assert st["shadows"]["A"]["advisor_gates"]["stress"] is False


# ── Monitoring: pause and resume ────────────────────────────────────────

def test_cusum_pause_then_resume_and_same_day_idempotent():
    rows = _world(a_kw={"crash_from": 83})                        # decisions from day 82 lose
    st = _to_formal(rows)
    st, _ = _run(rows, 81, st)
    assert st["shadows"]["A"]["stage"] == "advisor"
    st, ev = _run(rows, 82, st)                                   # formal period complete
    cus = st["shadows"]["A"]["cusum"]
    assert st["shadows"]["A"]["stage"] == "advisor" and not ev
    assert cus["reference"] == [DAYS[60], DAYS[81]] and cus["ref_days"] == 21
    assert cus["h"] > 4.4                  # above the known-parameter value for ARL 500
    # every crash day is a clipped z of -CUSUM_WINSOR: S grows by 3.5 a day
    crash_days = math.floor(cus["h"] / (C.CUSUM_WINSOR - C.CUSUM_K)) + 1
    pause_day = 82 + crash_days                   # cohort 81 + n matures one day later
    for day in range(83, pause_day):
        st, ev = _run(rows, day, st)
        assert st["shadows"]["A"]["stage"] == "advisor" and not ev, day
        assert st["shadows"]["A"]["cusum"] == cus                 # calibrated once
    st, ev = _run(rows, pause_day, st)
    assert st["shadows"]["A"]["stage"] == "paused"
    assert [e["type"] for e in ev] == ["pause"]
    assert st["shadows"]["A"]["cusum"] is None                     # recalibrated next time
    again, ev2 = _run(rows, pause_day, st)
    assert again == st and ev2 == []
    st, ev = _run(rows, pause_day + 1, st)
    assert st["shadows"]["A"]["stage"] == "formal"
    assert st["shadows"]["A"]["formal_since"] == DAYS[pause_day + 1]
    assert [e["type"] for e in ev] == ["resume"]


def test_robust_cusum_calibration_and_clip():
    rng = np.random.default_rng(8)
    ref = rng.standard_normal(250)
    h = M.calibrate_cusum_h(ref, seed=1)
    assert h == M.calibrate_cusum_h(ref, seed=1)                   # deterministic
    assert 4.0 < h < 8.0                                           # ~4.4 with known parameters
    assert M.calibrate_cusum_h(ref[:21], seed=1) > h               # short reference -> wider
    assert M.calibrate_cusum_h([], seed=1) == math.inf
    c, s = M.robust_center_scale(np.r_[np.zeros(9), 100.0])        # MAD 0 -> sample sd
    assert c == 0.0 and s == pytest.approx(np.std(np.r_[np.zeros(9), 100.0], ddof=1))
    assert M.robust_center_scale([1.0, 2.0, 3.0, 1000.0])[1] == pytest.approx(1.4826 * 1.0)
    # one extreme day counts at most CUSUM_WINSOR standard deviations
    assert M.cusum_down([-1000.0], 0.0, 1.0, 0.5, 3.4, clip=4.0) is not None
    assert M.cusum_down([-1000.0], 0.0, 1.0, 0.5, 3.6, clip=4.0) is None


# ── Matured decision cohorts (fix 2026-09-29) ───────────────────────────

def _cohort_row(created, exit_=None, net=0.01, hold=5, status="settled"):
    e = _row("shadow", "M", created, exit_, net, hold=hold)
    if status != "settled":
        e.status, e.exit_date, e.net_return, e.pnl_usd = status, None, None, None
    return e


def test_matured_cohorts_wait_for_every_record_of_a_decision_day():
    rows = [_cohort_row(DAYS[0], DAYS[2]), _cohort_row(DAYS[0], DAYS[5], net=-0.1),
            _cohort_row(DAYS[1], DAYS[2], net=0.03),             # early target hit ...
            _cohort_row(DAYS[1], status="open"),                  # ... its sibling still open
            _cohort_row(DAYS[2], DAYS[3], net=0.03),
            _cohort_row(DAYS[3], status="void")]
    done, horizon, stale = matured(rows, DAYS, DAYS[6])
    assert horizon == DAYS[0] and stale == 0
    assert sorted(e.net_return for e in done) == [-0.1, 0.01]    # day 1 and 2 not yet
    # the exit date counts "as of today": a row settled with a later exit is still open
    assert matured(rows, DAYS, DAYS[4])[1] is None
    # entry window 5 + longest hold 5 + grace 5 trading days later day 1 is given up on
    done, horizon, stale = matured(rows, DAYS, DAYS[16])
    assert horizon == DAYS[3] and stale == 1
    assert sorted(e.net_return for e in done) == [-0.1, 0.01, 0.03, 0.03]
    assert matured(rows, DAYS, DAYS[15])[1] == DAYS[0]


def test_shadow_stats_use_matured_cohorts_booked_on_the_decision_day():
    rows = [_cohort_row(DAYS[i], DAYS[i + 2], net=0.01, hold=2) for i in range(10)]
    rows.append(_cohort_row(DAYS[10], DAYS[11], net=0.05, hold=2))   # early exit, sibling open
    rows.append(_cohort_row(DAYS[10], status="open", hold=2))
    s = shadow_stats("M", rows, DAYS[:20], DAYS[11])
    assert s["horizon"] == DAYS[9] and s["settled"] == 10 and s["record_days"] == 11
    assert s["mean_net"] == pytest.approx(0.01)                   # the +5% early exit waits
    assert s["window"] == DAYS[:10]
    assert list(s["series"]) == pytest.approx([0.001] * 10)       # $10 on each decision day


def test_dsr_trials_are_candidates_clustered_by_correlation():
    rows = _world()
    for sid in ("temp_event:e1", "missed_path:main"):             # not candidates
        rows += [_row("temp_shadow", sid, DAYS[i], DAYS[i + 1], 0.0) for i in range(80)]
    twin = [_row("temp_shadow", "trial:t1", e.created_at[:10], e.exit_date, e.net_return)
            for e in rows if e.source_id == "A"]                  # a variant that copies A
    rows += twin + [_row("playground", "playground:p", DAYS[i], DAYS[i + 1], 0.001 * (-1) ** i)
                    for i in range(80)]
    assert trial_ids(rows) == ["A", "B", "playground:p", "trial:t1"]
    assert trial_count(rows) == 4
    st = _to_formal(rows)
    st, _ = _run(rows, 70, st, trials=None)
    info = st["dsr_trials"]
    assert info["raw"] == 4 and info["effective"] == 3 and info["clusters"] == [["A", "trial:t1"]]
    assert st["shadows"]["A"]["advisor_inputs"]["trial_count"] == 3


# ── Composite score ─────────────────────────────────────────────────────

def _stats(mppm, calmar, omega, win, n=30, share=0.0):
    return {"mppm": mppm, "calmar": calmar, "omega": omega, "win_rate": win,
            "settled": n, "min_position_share": share}


def test_composite_shrinkage_and_haircut():
    c = composite_scores({"x": _stats(2, 2, 2, 0.6), "y": _stats(1, 1, 1, 0.4)})
    assert c["x"]["raw"] == pytest.approx(1.0) and c["y"]["raw"] == pytest.approx(0.5)
    # k = 30, n = 30 -> halfway toward the mean 0.75
    assert c["x"]["score"] == pytest.approx(0.875) and c["y"]["score"] == pytest.approx(0.625)
    c = composite_scores({"x": _stats(2, 2, 2, 0.6, n=0), "y": _stats(1, 1, 1, 0.4, n=0)})
    assert c["x"]["score"] == pytest.approx(0.75)
    c = composite_scores({"x": _stats(2, 2, 2, 0.6, share=0.61), "y": _stats(1, 1, 1, 0.4, share=0.6)})
    assert c["x"]["haircut"] and not c["y"]["haircut"]
    assert c["x"]["score"] == pytest.approx(0.875 * 0.8) and c["y"]["score"] == pytest.approx(0.625)


# ── Evaluation periods -> challenger ────────────────────────────────────

def test_challenge_after_three_bottom_periods(monkeypatch):
    monkeypatch.setattr(C, "BOTTOM_SHARE", 0.5)          # 2 ranked shadows -> 1 in the bottom
    rows = _world(days=125)
    st, _ = _run(rows, 60)
    challenges = []
    for day in (70, 80, 90, 100, 110, 120):
        st, ev = _run(rows, day, st)
        challenges += [(day, e["shadow_id"]) for e in ev if e["type"] == "challenge"]
    assert challenges == [(120, "B")]
    assert st["period"]["index"] == 3 and st["shadows"]["B"]["bottom_streak"] == 0


def test_no_bottom_group_under_five_ranked():
    rows = _world(days=125)
    st, _ = _run(rows, 60)
    for day in (80, 100, 120):
        st, ev = _run(rows, day, st)
        assert not [e for e in ev if e["type"] == "challenge"]


# ── Runner and files ────────────────────────────────────────────────────

def test_trial_count():
    rows = _shadow("A", 2, 0, 0, 0) + _shadow("B", 2, 0, 0, 0) + _bench("A", 2, 0)
    rows.append(_row("temp_shadow", "trial:1", DAYS[0], DAYS[1], 0.0))
    assert trial_count(rows) == 3 and trial_count([]) == 1


def test_run_promotion_files_and_idempotent(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    for e in _world(days=90):
        store.add(e, created_at=e.created_at)
    roster = _roster("A", "B") + _roster("Z", status=PENDING_PROMPT)
    kw = dict(data_dir=tmp_path, roster=roster, active_ids={"A", "B"},
              price_source=StaticPriceSource(BARS))

    run_promotion(store, today=DAYS[10], **kw)
    adv = json.loads((tmp_path / "advisors.json").read_text(encoding="utf-8"))
    assert adv == {"updated_at": DAYS[10], "advisors": []}

    run_promotion(store, today=DAYS[60], **kw)
    out = run_promotion(store, today=DAYS[81], **kw)
    assert out["advisors"] == ["A"] and out["stages"] == {"advisor": 1, "formal": 1, "blocked": 1}
    assert out["trial_count"] == 2 and out["thresholds"]["PBO_MAX"] == 0.3
    adv = json.loads((tmp_path / "advisors.json").read_text(encoding="utf-8"))
    assert adv == {"updated_at": DAYS[81], "advisors": ["A"]}

    state_before = (tmp_path / "promotion" / "state.json").read_text(encoding="utf-8")
    events_before = (tmp_path / "promotion" / "events.jsonl").read_text(encoding="utf-8")
    again = run_promotion(store, today=DAYS[81], **kw)
    assert again["events"] == []
    assert (tmp_path / "promotion" / "state.json").read_text(encoding="utf-8") == state_before
    assert (tmp_path / "promotion" / "events.jsonl").read_text(encoding="utf-8") == events_before
    types = [json.loads(line)["type"] for line in events_before.splitlines()]
    assert types == ["promote", "promote", "promote"]


def test_run_promotion_real_roster_empty_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    out = run_promotion(LedgerStore(tmp_path / "ledger.db"), today="2026-09-28")
    assert out["stages"]["blocked"] >= 1 and out["advisors"] == []
    state = json.loads((tmp_path / "promotion" / "state.json").read_text(encoding="utf-8"))
    assert state["shadows"]["derivatives:odds:odds_analyst"]["stage"] == "blocked"
    assert len(state["shadows"]) == len(ROSTER)
    assert set(out["probation_progress"].values()) == {0}
