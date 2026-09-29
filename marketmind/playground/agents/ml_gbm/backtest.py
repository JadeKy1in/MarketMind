"""Out-of-sample walk-forward validation of the ml_gbm model (docs/ML_GBM_BACKTEST_2026-09-29.md).

Same features, label, hyperparameters and purged training window as the live agent;
the model is refitted every RETRAIN_STEP calendar bars (weekly) on an expanding window
and scores only the rows dated from its as-of date up to the next refit. No stop-loss,
no intrabar fills: close-to-close 10-bar returns, round-trip cost from the ledger.

Run (network I/O, read-only; writes only the given markdown/cache paths):
    python -m marketmind.playground.agents.ml_gbm.backtest OUT.md [--cache bars.pkl]
"""
from __future__ import annotations

import argparse
import asyncio
import math
import pickle
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from marketmind.playground.agents.ml_gbm import features as F
from marketmind.playground.agents.ml_gbm import model as M

RETRAIN_STEP = 5                  # SPY bars between refits (weekly)
MIN_TRAIN_DAYS = 365              # calendar days of feature rows before the first refit
TOP_K, THRESHOLD = 2, 0.55        # the live rule (adapter.MAX_CALLS / THRESHOLD)
REBALANCE = F.HORIZON             # non-overlapping 10-bar holding periods
BINS = (0.0, 0.4, 0.45, 0.5, 0.55, 0.6, 1.0)


def walk_forward(panel: F.Panel, step: int = RETRAIN_STEP,
                 min_train_days: int = MIN_TRAIN_DAYS) -> dict:
    cal = panel.calendar
    pred = np.full(len(panel.date), np.nan)
    base = np.full(len(panel.date), np.nan)
    first = panel.date.min() + np.timedelta64(min_train_days, "D")
    start = int(np.searchsorted(cal, first))
    fits = []
    for i in range(start, len(cal), step):
        asof = F.to_date(cal[i])
        bundle = M.fit(panel, asof, importance=False)
        if bundle is None:
            continue
        lo = cal[i]
        hi = cal[i + step] if i + step < len(cal) else np.datetime64("9999-12-31")
        rows = (panel.date >= lo) & (panel.date < hi)
        if rows.any():
            pred[rows] = M.predict(bundle, panel.X[rows])[1]
            base[rows] = bundle["base_rate"]
        fits.append({k: bundle[k] for k in ("asof", "row_cutoff", "label_cutoff", "train_last",
                                            "train_label_end_max", "n_fit", "n_calib")})
    return {"pred": pred, "base": base, "fits": fits}


def _metrics(y, p, base) -> dict:
    from sklearn.metrics import roc_auc_score
    out = {"n": int(len(y)), "base_rate": float(y.mean()) if len(y) else math.nan}
    if len(y) == 0:
        return out
    out["hit_rate"] = float(((p >= 0.5) == (y == 1)).mean())
    out["auc"] = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else math.nan
    out["brier"] = float(np.mean((p - y) ** 2))
    out["brier_ref"] = float(np.mean((base - y) ** 2))           # training base rate forecast
    out["bss"] = 1 - out["brier"] / out["brier_ref"] if out["brier_ref"] > 0 else math.nan
    return out


def _curve(rets: list[float]) -> dict:
    r = np.array(rets, dtype=float)
    if not len(r):
        return {"periods": 0}
    eq = np.cumprod(1 + r)
    per_year = 252 / REBALANCE
    years = len(r) / per_year
    dd = eq / np.maximum.accumulate(eq) - 1
    return {"periods": len(r), "total": float(eq[-1] - 1),
            "cagr": float(eq[-1] ** (1 / years) - 1) if years > 0 and eq[-1] > 0 else math.nan,
            "sharpe": float(r.mean() / r.std() * math.sqrt(per_year)) if r.std() > 0 else math.nan,
            "max_dd": float(dd.min()), "mean": float(r.mean())}


def evaluate(panel: F.Panel, wf: dict) -> dict:
    pred, base = wf["pred"], wf["base"]
    oos = ~np.isnan(pred) & ~np.isnan(panel.label)
    y, p, b = panel.label[oos], pred[oos], base[oos]
    rep = {"overall": _metrics(y, p, b), "fits": len(wf["fits"]),
           "first": str(panel.date[oos].min()) if oos.any() else None,
           "last": str(panel.date[oos].max()) if oos.any() else None}
    years = panel.date[oos].astype("datetime64[Y]").astype(int) + 1970
    rep["by_year"] = {int(yr): _metrics(y[years == yr], p[years == yr], b[years == yr])
                      for yr in np.unique(years)}
    crypto = np.array([F.is_crypto_ticker(panel.tickers[k]) for k in panel.ticker[oos]])
    rep["by_class"] = {"ETF": _metrics(y[~crypto], p[~crypto], b[~crypto]),
                       "crypto": _metrics(y[crypto], p[crypto], b[crypto])}
    rel = []
    for lo, hi in zip(BINS, BINS[1:]):
        m = (p >= lo) & (p < hi)
        if m.any():
            rel.append({"bin": f"[{lo:.2f}, {hi:.2f})", "n": int(m.sum()),
                        "mean_p": float(p[m].mean()), "freq": float(y[m].mean())})
    rep["reliability"] = rel
    # long-only top-k on non-overlapping 10-bar periods of the SPY calendar
    cal = panel.calendar
    reb = [d for d in cal[::REBALANCE] if rep["first"] and str(d) >= rep["first"]]
    strat, strat_all, ew, invested = [], [], [], 0
    for d in reb:
        m = (panel.date == d) & ~np.isnan(pred) & ~np.isnan(panel.fwd_ret)
        if not m.any():
            continue
        idx = np.flatnonzero(m)
        order = idx[np.argsort(-pred[idx], kind="stable")]
        net = panel.fwd_ret - panel.cost_rt
        top = order[:TOP_K]
        strat_all.append(float(net[top].mean()))
        picks = [i for i in top if pred[i] >= THRESHOLD]
        strat.append(float(net[picks].mean()) if picks else 0.0)
        invested += bool(picks)
        ew.append(float(panel.fwd_ret[idx].mean()))
    rep["strategy"] = {"top_k_threshold": _curve(strat), "top_k_always": _curve(strat_all),
                       "equal_weight": _curve(ew), "invested_share": invested / len(strat) if strat else math.nan}
    return rep


def buy_and_hold(histories: dict, first: str, last: str) -> dict[str, float]:
    out = {}
    for t in F.UNIVERSE:
        bars = [b for b in (histories.get(t) or []) if first <= b.date <= last]
        if len(bars) > 1 and bars[0].date <= (date.fromisoformat(first) + timedelta(days=7)).isoformat():
            out[t] = bars[-1].close / bars[0].close - 1
    return out


def _pct(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{nd}f}%"


def _f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def render(rep: dict, coverage: dict, bh: dict, importance: list) -> str:
    L = []
    o = rep["overall"]
    L.append(f"样本外区间 {rep['first']} 至 {rep['last']}，共 {rep['fits']} 次每周重训，"
             f"{o['n']} 个（标的，日）样本外预测。\n")
    L.append("### 数据覆盖\n\n| 标的 | 首根完整日线 | 末根 | 根数 | 来源 |\n|---|---|---|---|---|")
    for t, c in coverage.items():
        L.append(f"| {t} | {c['first']} | {c['last']} | {c['n']} | {c['source']} |")
    L.append("\n### 分类指标（全部样本外行）\n")
    L.append("| 范围 | 样本数 | 正例占比 | 命中率 (p≥0.5) | AUC | Brier | 基准 Brier（训练期正例率） | Brier 技能分 |")
    L.append("|---|---|---|---|---|---|---|---|")
    rows = [("全部", o)] + [(k, v) for k, v in rep["by_class"].items()] + \
           [(str(k), v) for k, v in rep["by_year"].items()]
    for name, m in rows:
        if m["n"] == 0:
            continue
        L.append(f"| {name} | {m['n']} | {_pct(m['base_rate'])} | {_pct(m.get('hit_rate'))} | "
                 f"{_f(m.get('auc'))} | {_f(m.get('brier'), 4)} | {_f(m.get('brier_ref'), 4)} | "
                 f"{_f(m.get('bss'), 4)} |")
    L.append("\n### 校准（样本外）\n\n| 预测概率区间 | 样本数 | 平均预测 | 实际正例率 |\n|---|---|---|---|")
    for r in rep["reliability"]:
        L.append(f"| {r['bin']} | {r['n']} | {_pct(r['mean_p'])} | {_pct(r['freq'])} |")
    s = rep["strategy"]
    L.append(f"\n### 只做多 top-{TOP_K} 策略（每 {REBALANCE} 根 SPY 交易日调仓一次，不重叠）\n")
    L.append("| 策略 | 期数 | 累计收益 | 年化 | 夏普（按期年化） | 最大回撤 | 每期平均 |")
    L.append("|---|---|---|---|---|---|---|")
    names = {"top_k_threshold": f"top-{TOP_K}，概率 ≥ {THRESHOLD}，否则空仓（线上规则，扣成本）",
             "top_k_always": f"top-{TOP_K}，不设阈值（扣成本）",
             "equal_weight": "全体等权（每期再平衡，不扣成本）"}
    for k, label in names.items():
        c = s[k]
        L.append(f"| {label} | {c.get('periods', 0)} | {_pct(c.get('total'))} | {_pct(c.get('cagr'))} | "
                 f"{_f(c.get('sharpe'), 2)} | {_pct(c.get('max_dd'))} | {_pct(c.get('mean'), 2)} |")
    L.append(f"\n阈值策略持仓（非空仓）期数占比：{_pct(s['invested_share'])}。\n")
    if bh:
        mean_bh = sum(bh.values()) / len(bh)
        L.append(f"同区间逐一买入持有（不再平衡）的平均总收益：{_pct(mean_bh)}（{len(bh)} 个标的："
                 + "，".join(f"{t} {_pct(v)}" for t, v in sorted(bh.items())) + "）。\n")
    if importance:
        L.append("### 最终模型的置换重要性（校准段 AUC 下降，越大越重要）\n")
        L.append("| 特征 | AUC 下降 |\n|---|---|")
        for f, v in importance:
            L.append(f"| {f} | {v:.4f} |")
    return "\n".join(L) + "\n"


async def main(out: Path, cache: Path | None = None) -> dict:
    from marketmind.playground.agents.ml_gbm.adapter import fetch_histories
    if cache and cache.exists():
        histories, sources = pickle.loads(cache.read_bytes())
    else:
        histories, sources = await fetch_histories(list(F.UNIVERSE) + [F.VIX_TICKER])
        if cache:
            cache.write_bytes(pickle.dumps((histories, sources)))
    coverage = {t: {"first": h[0].date, "last": h[-1].date, "n": len(h), "source": sources.get(t)}
                for t, h in histories.items() if h}
    panel = F.build_panel(histories)
    wf = walk_forward(panel)
    rep = evaluate(panel, wf)
    last = F.to_date(panel.calendar[-1])
    final = M.fit(panel, last)
    imp = sorted((final or {}).get("importance", {}).items(), key=lambda kv: -kv[1])
    bh = buy_and_hold(histories, rep["first"], rep["last"]) if rep["first"] else {}
    out.write_text(render(rep, coverage, bh, imp), encoding="utf-8")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--cache", type=Path)
    a = ap.parse_args()
    r = asyncio.run(main(a.out, a.cache))
    print({k: r[k] for k in ("overall", "first", "last", "fits")})
    print(r["strategy"])
