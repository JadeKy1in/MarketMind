"""Summaries, baselines, random-direction distribution, cluster bootstrap, decomposition.
Reads entries.json (from replay.py); writes results.json and prints markdown tables."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
D = json.loads((HERE / "entries.json").read_text())
ROWS = D["rows"]
RNG = np.random.default_rng(20261002)
NB, NR = 5000, 5000
RULES = list(ROWS[0]["rules"].keys())


def cluster_ci(vals, dates, nb=NB):
    vals, dates = np.asarray(vals, float), np.asarray(dates)
    u = np.unique(dates)
    groups = [vals[dates == x] for x in u]
    means = []
    for _ in range(nb):
        pick = RNG.integers(0, len(u), len(u))
        v = np.concatenate([groups[i] for i in pick])
        means.append(v.mean())
    return np.percentile(means, [2.5, 97.5]), len(u)


def iid_ci(vals, nb=NB):
    vals = np.asarray(vals, float)
    m = vals[RNG.integers(0, len(vals), (nb, len(vals)))].mean(1)
    return np.percentile(m, [2.5, 97.5])


def summarize(rows, rule):
    rs = [r["rules"][rule] for r in rows]
    net = np.array([x["net"] for x in rs])
    exc = np.array([x["excess"] for x in rs if x["excess"] is not None])
    dates = [r["entry_date"] for r in rows]
    cci, k = cluster_ci(net, dates)
    return dict(n=len(rs), realized=float(np.mean([x["realized"] for x in rs])),
                win=float((net > 0).mean()), mean=float(net.mean()), median=float(np.median(net)),
                stop=float(np.mean([x["reason"] == "stop" for x in rs])),
                fals=float(np.mean([x["reason"] == "falsifier" for x in rs])),
                target=float(np.mean([x["reason"] == "target" for x in rs])),
                excess=float(exc.mean()) if len(exc) else None, n_exc=len(exc),
                ci_cluster=[float(cci[0]), float(cci[1])], k_clusters=k,
                ci_iid=[float(v) for v in iid_ci(net)])


def baselines(rows):
    s = np.array([r["sign"] for r in rows])
    lg = np.array([r["long_gross"] for r in rows])
    c = np.array([r["cost"] for r in rows])
    dates = [r["entry_date"] for r in rows]
    spy = np.array([np.nan if r["spy"] is None else r["spy"] for r in rows])
    m20 = np.sign([r["mom20"] for r in rows])
    m12 = np.array([0.0 if r["mom12"] is None else np.sign(r["mom12"]) for r in rows])
    tr = np.array([1.0 if r["trend"] == "TREND" else 0.0 for r in rows])
    b = {
        "LLM_dir_expiry": s * lg - c,
        "always_long_expiry": lg - c,
        "SPY_buyhold": spy - 2 * 5e-4,
        "trend_state(TREND=long,else cash)": tr * (lg - c),
        "mom20_sign": m20 * lg - c,
        "mom12_1_sign": m12 * lg - np.abs(m12) * c,
        "LLM_current_rule": np.array([r["rules"]["R0_current"]["net"] for r in rows]),
    }
    out = {}
    for k, v in b.items():
        ok = ~np.isnan(v)
        cci, kk = cluster_ci(v[ok], np.array(dates)[ok])
        out[k] = dict(n=int(ok.sum()), mean=float(v[ok].mean()), median=float(np.median(v[ok])),
                      win=float((v[ok] > 0).mean()), ci_cluster=[float(x) for x in cci],
                      ci_iid=[float(x) for x in iid_ci(v[ok])])
    # random direction: NR seeds
    rs = RNG.choice([-1.0, 1.0], size=(NR, len(rows)))
    rmeans = (rs * lg - c).mean(1)
    llm = float((s * lg - c).mean())
    out["random_dir_expiry"] = dict(n=len(rows), mean=float(rmeans.mean()),
                                    p2_5=float(np.percentile(rmeans, 2.5)),
                                    p97_5=float(np.percentile(rmeans, 97.5)),
                                    llm_percentile=float((rmeans < llm).mean()))
    out["agreement"] = dict(
        long_share=float((s > 0).mean()),
        dir_hit_rate_expiry=float((s * lg > 0).mean()),
        agree_mom20=float((s == m20).mean()), agree_mom12=float((s == m12).mean()),
        trend_TREND_share=float(tr.mean()),
        long_when_TREND=float((s[tr == 1] > 0).mean()) if tr.sum() else None,
        realized_share_expiry=float(np.mean([r["r1_realized"] for r in rows])))
    # decomposition (gross terms; cost separate)
    g0 = np.array([r["rules"]["R0_current"]["gross"] for r in rows])
    g1 = s * lg
    out["decomp"] = dict(current_net=float((g0 - c).mean()), cost=float(-c.mean()),
                         direction_gross_expiry=float(g1.mean()),
                         exit_structure=float((g0 - g1).mean()),
                         random_dir_gross_expected=0.0,
                         market_drift_long_gross=float(lg.mean()),
                         dir_alpha_vs_always_long=float((g1 - lg).mean()),
                         ci_exit_cluster=[float(x) for x in cluster_ci(g0 - g1, dates)[0]],
                         ci_dir_cluster=[float(x) for x in cluster_ci(g1, dates)[0]])
    return out


def per_date(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["entry_date"]].append(r)
    return {d: dict(n=len(v), long_share=float(np.mean([r["sign"] > 0 for r in v])),
                    always_long=float(np.mean([r["long_gross"] for r in v])),
                    llm_expiry=float(np.mean([r["sign"] * r["long_gross"] - r["cost"] for r in v])),
                    llm_current=float(np.mean([r["rules"]["R0_current"]["net"] for r in v])))
            for d, v in sorted(g.items())}


LLM = [r for r in ROWS if r["source_type"] != "benchmark"]
GROUPS = {
    "LLM_settled": [r for r in LLM if r["status"] == "settled"],
    "LLM_all_opened": LLM,
    "BENCH_random_all": [r for r in ROWS if r["source_type"] == "benchmark"],
}
res = dict(match=dict(settled=sum(r["status"] == "settled" for r in ROWS),
                      matched=sum(bool(r["match"]) for r in ROWS if r["status"] == "settled")),
           rules={g: {k: summarize(v, k) for k in RULES} for g, v in GROUPS.items()},
           baselines={g: baselines(v) for g, v in GROUPS.items()},
           per_date={g: per_date(v) for g, v in GROUPS.items()},
           stop_dist=dict(orig_med=float(np.nanmedian([r["orig_stop_pct"] or np.nan for r in LLM])),
                          atr_med=float(np.median([r["atr_pct"] for r in LLM])),
                          sig_med=float(np.median([r["sig_d"] for r in LLM])),
                          orig_over_atr_med=float(np.nanmedian([(r["orig_stop_pct"] or np.nan) / r["atr_pct"] for r in LLM]))),
           source_counts={k: sum(r["source_type"] == k for r in LLM) for k in {r["source_type"] for r in LLM}})
(HERE / "results.json").write_text(json.dumps(res, indent=1))

pc = lambda x: "—" if x is None else f"{100 * x:+.2f}%"
pp = lambda x: f"{100 * x:.0f}%"
for g in GROUPS:
    print(f"\n### {g} rules")
    print("| rule | n | realized | win | mean | median | stop | fals | target | excess vs SPY | 95% CI cluster(date) | 95% CI iid |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, s in res["rules"][g].items():
        print(f"| {k} | {s['n']} | {pp(s['realized'])} | {pp(s['win'])} | {pc(s['mean'])} | {pc(s['median'])} | "
              f"{pp(s['stop'])} | {pp(s['fals'])} | {pp(s['target'])} | {pc(s['excess'])} | "
              f"[{pc(s['ci_cluster'][0])}, {pc(s['ci_cluster'][1])}] (K={s['k_clusters']}) | [{pc(s['ci_iid'][0])}, {pc(s['ci_iid'][1])}] |")
    print(f"\n### {g} baselines (expiry-only window)")
    b = res["baselines"][g]
    for k, v in b.items():
        if k in ("random_dir_expiry", "agreement", "decomp"):
            continue
        print(f"| {k} | {v['n']} | win {pp(v['win'])} | mean {pc(v['mean'])} | med {pc(v['median'])} | "
              f"CIc [{pc(v['ci_cluster'][0])}, {pc(v['ci_cluster'][1])}] | CIi [{pc(v['ci_iid'][0])}, {pc(v['ci_iid'][1])}] |")
    print("random:", {k: (round(v, 5) if isinstance(v, float) else v) for k, v in b["random_dir_expiry"].items()})
    print("agreement:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in b["agreement"].items()})
    print("decomp:", {k: (round(v, 5) if isinstance(v, float) else [round(x, 5) for x in v] if isinstance(v, list) else v) for k, v in b["decomp"].items()})
    print("per_date:", json.dumps(res["per_date"][g], indent=None)[:900])
print("\nmatch", res["match"], "stopdist", res["stop_dist"], res["source_counts"])
