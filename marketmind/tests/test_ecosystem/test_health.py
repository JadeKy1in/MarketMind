"""Ecosystem health checks on synthetic ledgers (docs/ECOSYSTEM_DESIGN.md)."""
from datetime import date, timedelta

import numpy as np
import pytest

from marketmind.ecosystem import config as C
from marketmind.ecosystem import health as H
from marketmind.ledger.store import LedgerEntry


def rec(sid, day, ticker="SPY", direction="long", stype="shadow", conf=0.55, **kw):
    meta = kw.pop("meta", {})
    return LedgerEntry(source_type=stype, source_id=sid, ticker=ticker, direction=direction,
                       hold_bars=1, confidence=conf, position_usd=100.0, falsifier="x",
                       meta={"run_date": day, **meta}, created_at=f"{day}T15:00:00Z", **kw)


def days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


SIDS = [f"s{i}" for i in range(6)]


def facts(**kw):
    kw.setdefault("active_ids", set(SIDS))
    kw.setdefault("roster_ids", set(SIDS))
    return H.Facts(**kw)


def herd_ledger(n_days, n_long=5, n_short=0, ticker="SPY"):
    rows = []
    for d in days(n_days):
        for i, sid in enumerate(SIDS[:n_long + n_short]):
            rows.append(rec(sid, d, ticker, "long" if i < n_long else "short"))
        for sid in SIDS[n_long + n_short:]:                  # the rest trade elsewhere
            rows.append(rec(sid, d, "XLE", "short"))
    return rows


# ── 1. herding ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("state,verdict", [("TREND", "market_driven"), ("WATCH", "behavioural"),
                                           (None, "unclassified")])
def test_herding_flag_and_market_vs_behavioural(state, verdict):
    rows = herd_ledger(3)
    trend = {d: {"QQQ": state} for d in days(3)} if state else {}
    doc = H.evaluate(rows, days(3)[-1], facts(trend_by_day=trend))
    flags = doc["herding"]["flags"]
    assert len(flags) == 1
    f = flags[0]
    assert (f["group"], f["direction"], f["days"], f["verdict"]) == ("us_equity_index", "long", 3, verdict)
    assert f["joint_p"] <= C.HERDING_MAX_JOINT_P
    assert "us_equity_index long 3d " + verdict in H.summary_line(doc)


def test_short_consensus_in_cash_group_is_market_driven():
    rows = herd_ledger(3, ticker="TLT")
    rows = [r if r.ticker != "TLT" else rec(r.source_id, r.meta["run_date"], "TLT", "short") for r in rows]
    trend = {d: {"TLT": "CASH", "IEF": "EXIT"} for d in days(3)}
    f = H.evaluate(rows, days(3)[-1], facts(trend_by_day=trend))["herding"]["flags"][0]
    assert (f["group"], f["direction"], f["verdict"]) == ("long_rates", "short", "market_driven")


def test_no_herding_flag_for_short_streak_or_weak_or_small_votes():
    assert H.evaluate(herd_ledger(2), days(2)[-1], facts())["herding"]["flags"] == []
    # 4 long / 1 short = 80% but p per day 0.375 -> joint p 0.05 > 0.01
    assert H.evaluate(herd_ledger(3, 4, 1), days(3)[-1], facts())["herding"]["flags"] == []
    # 3 voters: below the minimum vote
    assert H.evaluate(herd_ledger(5, 3), days(5)[-1], facts())["herding"]["flags"] == []


def test_herding_streak_must_reach_today_and_past_episodes_are_kept():
    rows = herd_ledger(3)
    later = days(5)[3:]
    rows += [rec(s, d, "XLE", "short") for d in later for s in SIDS]
    doc = H.evaluate(rows, later[-1], facts())
    assert doc["herding"]["flags"] == []
    assert [e["days"] for e in doc["herding"]["episodes"] if e["group"] == "us_equity_index"] == [3]


def test_trial_variants_and_missed_path_do_not_vote():
    rows = herd_ledger(3, n_long=3)
    for d in days(3):
        rows.append(rec("trial:t1", d, "SPY", stype="temp_shadow"))
        rows.append(rec("missed_path:main", d, "SPY", stype="temp_shadow"))
    assert H.evaluate(rows, days(3)[-1], facts())["herding"]["flags"] == []


def test_weekend_crypto_run_is_not_a_full_run_day():
    rows = herd_ledger(3)
    rows.append(rec("s0", "2026-01-10", "BTC-USD"))           # Saturday, one shadow only
    doc = H.evaluate(rows, "2026-01-10", facts())
    assert doc["population"]["full_run_days"] == 3
    assert len(doc["herding"]["flags"]) == 1


# ── 2. diversity ────────────────────────────────────────────────────────

def pnl_ledger(n=25, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    base = rng.normal(0, 50, n)
    other = rng.normal(0, 50, n)
    for i, d in enumerate(days(n)):
        for sid, pnl in (("s0", base[i]), ("s1", base[i] * 1.01 + 1), ("s2", other[i]),
                         ("trial:t1", base[i] * 0.99)):
            rows.append(rec(sid, d, stype="temp_shadow" if sid.startswith("trial") else "shadow",
                            status="settled", exit_date=d, pnl_usd=float(pnl), net_return=float(pnl) / 100))
    return rows


def test_pnl_duplicate_cluster_and_n_eff():
    doc = H.evaluate(pnl_ledger(), days(25)[-1], facts(trial_parent={"trial:t1": "s0"}))
    pnl = doc["diversity"]["pnl"]
    # headline N_eff: long-term shadows only (s0, s1, s2); the trial variant only under `all`
    assert pnl["scope"] == "long-term shadows" and pnl["eligible"] == 3
    assert 1.5 < pnl["n_eff"] < 2.5                        # two independent streams
    assert pnl["all"]["eligible"] == 4 and 1.5 < pnl["all"]["n_eff"] < 2.5
    # clusters still cover every actor
    assert pnl["clusters"] == [{"members": ["s0", "s1", "trial:t1"], "expected": False}]
    exp = {(p["a"], p["b"]): p["expected"] for p in pnl["pairs_high"]}
    assert exp[("s0", "trial:t1")] is True and exp[("s0", "s1")] is False
    assert all(p["nonzero_days"] == 25 for p in pnl["pairs_high"]) and pnl["pairs_sparse"] == 0
    assert f"N_eff {pnl['n_eff']:.1f}/3 (null~{pnl['n_eff_null']:.1f})" in H.summary_line(doc)


def test_corr_matrix_matches_numpy_on_the_overlap():
    rng = np.random.default_rng(3)
    a = {d: float(v) for d, v in zip(days(30), rng.normal(size=30))}
    b = {d: float(v) for d, v in zip(days(30)[5:], rng.normal(size=25))}
    x, m = H._series_matrix({"a": a, "b": b}, ["a", "b"])
    rho, cnt = H._corr_matrix(x, m)
    common = sorted(a.keys() & b.keys())
    want = np.corrcoef([a[d] for d in common], [b[d] for d in common])[0, 1]
    assert cnt[0, 1] == 25 and rho[0, 1] == pytest.approx(want)
    flat = {d: 0.0 for d in days(30)}
    rho, _ = H._corr_matrix(*H._series_matrix({"a": a, "f": flat}, ["a", "f"]))
    assert np.isnan(rho[0, 1])                             # no variance on the overlap


def test_sparse_pnl_pair_is_not_a_duplicate():
    """Exit-day P&L is mostly zeros: one shared exit day gives rho ~1 over 25 'common'
    days. A duplicate needs DUP_MIN_NONZERO_DAYS days with non-zero P&L on both sides."""
    ds = days(25)
    rows = []
    for k, d in enumerate(ds):
        big = 500.0 if k == 10 else 0.0
        rows += [rec("s0", d, status="settled", exit_date=d, pnl_usd=big + (3.0 if k == 3 else 0.0),
                     net_return=0.0),
                 rec("s1", d, status="settled", exit_date=d, pnl_usd=big + (2.0 if k == 17 else 0.0),
                     net_return=0.0)]
    pnl = H.evaluate(rows, ds[-1], facts())["diversity"]["pnl"]
    assert pnl["pairs_high"] == [] and pnl["clusters"] == [] and pnl["pairs_sparse"] == 1
    # the same pair with >= DUP_MIN_NONZERO_DAYS shared non-zero days is a duplicate
    rows = [rec(s, d, status="settled", exit_date=d,
                pnl_usd=float((k % 5) + 1) * (1.01 if s == "s1" else 1), net_return=0.0)
            for k, d in enumerate(ds) for s in ("s0", "s1")]
    pnl = H.evaluate(rows, ds[-1], facts())["diversity"]["pnl"]
    assert [(p["a"], p["b"]) for p in pnl["pairs_high"]] == [("s0", "s1")]
    assert pnl["pairs_high"][0]["nonzero_days"] >= C.DUP_MIN_NONZERO_DAYS


def test_n_eff_null_is_deterministic_and_below_n_for_sparse_series():
    rng = np.random.default_rng(7)
    series = {}
    for i in range(12):                                    # independent, ~2 exits in 30 days
        v = np.zeros(30)
        v[rng.choice(30, 2, replace=False)] = rng.normal(0, 1, 2)
        series[f"s{i}"] = dict(zip(days(30), v.tolist()))
    ids = sorted(series)
    x, m = H._series_matrix(series, ids)
    null = H.n_eff_null(x, m)
    assert null == H.n_eff_null(x, m)                      # fixed seed
    assert null < 0.9 * len(ids)                           # sparsity alone pulls N_eff below N
    dense = {s: dict(zip(days(60), rng.normal(size=60).tolist())) for s in ids}
    xd, md = H._series_matrix(dense, ids)
    assert H.n_eff_null(xd, md) > null                     # dense independent series sit nearer N


def test_playground_is_left_out_of_headline_n_eff():
    rows = [r for r in pnl_ledger() if r.source_id != "trial:t1"]
    ds = days(25)
    rng = np.random.default_rng(5)
    rows += [rec("playground:x", d, stype="playground", status="settled", exit_date=d,
                 pnl_usd=float(v), net_return=0.0) for d, v in zip(ds, rng.normal(0, 50, 25))]
    pnl = H.evaluate(rows, ds[-1], facts())["diversity"]["pnl"]
    assert pnl["eligible"] == 3 and pnl["all"]["eligible"] == 4
    assert pnl["all"]["n_eff"] > pnl["n_eff"]


def test_pnl_needs_twenty_days():
    pnl = H.evaluate(pnl_ledger(n=10), days(10)[-1], facts())["diversity"]["pnl"]
    assert pnl["n_eff"] is None and pnl["eligible"] == 0
    assert "n/a (0 eligible)" in H.summary_line(H.evaluate(pnl_ledger(n=10), days(10)[-1], facts()))


def test_participation_ratio():
    assert H.participation_ratio(np.eye(4)) == pytest.approx(4.0)
    assert H.participation_ratio(np.ones((4, 4))) == pytest.approx(1.0)


def test_direction_duplicates():
    rows = []
    rng = np.random.default_rng(1)
    for d in days(22):
        dirs = rng.choice(["long", "short"], 2)
        for sid in ("s0", "s1"):                            # identical books
            rows += [rec(sid, d, "SPY", dirs[0]), rec(sid, d, "GLD", dirs[1])]
        rows.append(rec("s2", d, "XLE", "long"))            # disjoint book
    direc = H.evaluate(rows, days(22)[-1], facts())["diversity"]["direction"]
    assert direc["clusters"] == [{"members": ["s0", "s1"], "expected": False}]
    assert direc["n_eff"] == pytest.approx(9 / 5)           # [[1,1,0],[1,1,0],[0,0,1]]


# ── 3. homogenisation ───────────────────────────────────────────────────

def test_homogenisation_group_and_news_not_recorded_and_llm_not_flagged():
    rows = []
    for d in days(3):
        rows += [rec("s0", d, "SPY", meta={"llm": "a"}), rec("s1", d, "QQQ", meta={"llm": "a"}),
                 rec("s2", d, "GLD", meta={"llm": "b"})]
    doc = H.evaluate(rows, days(3)[-1], facts())
    hom = doc["homogenisation"]
    assert hom["dominant_group"]["top"] == "us_equity_index" and hom["dominant_group"]["flag"]
    assert hom["news_source"]["status"] == "not_recorded"
    assert "llm" not in hom                                # no modal-LLM homogenisation flag
    line = H.summary_line(doc)
    assert "homogenised: us_equity_index 67%" in line and "homogenised: a" not in line


def test_llm_today_counts_todays_voter_records_only():
    ds = days(3)
    rows = [rec(s, d, meta={"llm": "deepseek"}) for d in ds[:2] for s in ("s0", "s1", "s2")]
    rows += [rec("s0", ds[2], meta={"llm": "claude"}), rec("s1", ds[2], meta={"llm": "claude"}),
             rec("s1", ds[2], "GLD", meta={"llm": "claude"}), rec("s2", ds[2], meta={"llm": "deepseek"}),
             rec("s3", ds[2]),                                               # no meta.llm: not counted
             rec("trial:t1", ds[2], stype="temp_shadow", meta={"llm": "claude"})]  # not a voter
    doc = H.evaluate(rows, ds[2], facts())
    llm = doc["homogenisation"]["llm_today"]
    assert llm == {"day": ds[2], "records": 4, "top": "claude", "count": 3, "share": 0.75,
                   "by_model": {"claude": 3, "deepseek": 1}}
    assert H.summary_line(doc).endswith("llm today: claude 3/4")


# ── 4. stagnation ───────────────────────────────────────────────────────

def test_repetition_and_plateau():
    rows = [rec("s0", d, "SPY", "long", conf=0.55) for d in days(20)]
    rows += [rec("s1", d, t, "long", conf=c) for d, t, c in
             zip(days(20), ["SPY", "GLD", "TLT", "XLE"] * 5, [0.5, 0.6, 0.7, 0.55] * 5)]
    rows += [rec("s2", d, "SPY") for d in days(5)]
    st = H.evaluate(rows, days(20)[-1], facts())["stagnation"]
    kinds = {(f["shadow_id"], f["kind"]) for f in st["flags"]}
    assert kinds == {("s0", "repetition"), ("s0", "plateau")}
    assert st["insufficient"]["s2"] == 5


# ── 5. integrity ────────────────────────────────────────────────────────

def test_zombies_orphans_retired():
    ds = days(5)
    rows = [rec(s, d) for d in ds for s in ("s0", "s1", "s2", "old")]
    rows += [rec("s3", d) for d in ds[:2]]                          # silent for 3 run days
    rows += [rec("ghost", ds[0]), rec("playground:gone", ds[0], stype="playground"),
             rec("weird:x", ds[0], stype="temp_shadow"), rec("trial:zz", ds[0], stype="temp_shadow")]
    f = facts(active_ids={"s0", "s1", "s2", "s3", "s4@2"},
              roster_ids={"s0", "s1", "s2", "s3", "old", "s4@2"},
              retired={"old": ds[2]}, successor_start={"s4@2": ds[3]},
              trial_parent={}, playground_ids=set())
    integ = H.evaluate(rows, ds[-1], f)["integrity"]
    assert [(z["shadow_id"], z["silent_run_days"]) for z in integ["zombies"]] == [("s3", 3)]
    assert {o["source_id"] for o in integ["orphans"]} == {"ghost", "playground:gone", "weird:x", "trial:zz"}
    assert integ["retired_submitting"] == [{"shadow_id": "old", "retired_on": ds[2],
                                            "days_after": 2, "last_day": ds[-1]}]


# ── 6. degradation ──────────────────────────────────────────────────────

def test_mann_kendall():
    assert H.mann_kendall(list(range(12)))["trend"] == "increasing"
    assert H.mann_kendall(list(range(12, 0, -1)))["trend"] == "decreasing"
    assert H.mann_kendall([1, 2] * 6)["trend"] == "no trend"
    assert H.mann_kendall([1, 2, 3])["trend"] == "insufficient"


def test_beat_random_share_series():
    rows = []
    for i, d in enumerate(days(70)):
        for k in range(5):
            sid = f"s{k}"
            good = k < 3                                    # 3 of 5 beat their baseline
            rows.append(rec(sid, d, status="settled", exit_date=d, pnl_usd=1.0,
                            net_return=0.01 if good else -0.01))
            rows.append(rec(f"random:{sid}", d, stype="benchmark", status="settled", exit_date=d,
                            pnl_usd=0.0, net_return=0.0))
    deg = H.evaluate(rows, days(70)[-1], facts(active_ids={f"s{k}" for k in range(5)}))["degradation"]
    assert deg["beat_random"] and all(p["share"] == 0.6 and p["eligible"] == 5 for p in deg["beat_random"])
    assert deg["beat_random"][-1]["window_end"] == days(70)[-1] and len(deg["beat_random"]) == 11
    assert deg["beat_random_trend"]["trend"] == "no trend"
    assert len(deg["entropy"]) == 60 and deg["entropy"][0]["direction_entropy"] == 0.0


def test_group_trend_state():
    st = {"GLD": "CASH", "SLV": "EXIT", "SPY": "TREND", "QQQ": "WATCH", "TLT": "UNAVAILABLE"}
    assert H.group_trend_state(st, "precious_metals") == "CASH"
    assert H.group_trend_state(st, "us_equity_index") == "TREND"
    assert H.group_trend_state(st, "long_rates") is None
    assert H.group_trend_state({"QQQ": "WATCH", "SPY": "CASH"}, "us_equity_index") == "WATCH"


def test_homogenisation_reads_news_sources_when_recorded():
    rows = []
    for d in days(3):
        rows += [rec("s0", d, "SPY", meta={"news_sources": ["Bloomberg Markets", "CNBC Top News"]}),
                 rec("s1", d, "QQQ", meta={"news_sources": ["Bloomberg Markets"]}),
                 rec("s2", d, "GLD", meta={"news_sources": ["Kitco"]})]
    news = H.evaluate(rows, days(3)[-1], facts())["homogenisation"]["news_source"]
    assert news["status"] == "recorded" and news["top"] == "Bloomberg Markets"
    assert news["share"] == pytest.approx(0.667) and news["flag"]
    assert news["mean_source_jaccard"] == pytest.approx((0.5 + 0 + 0) / 3, abs=1e-3)
