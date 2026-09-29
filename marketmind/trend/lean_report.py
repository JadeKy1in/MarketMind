"""Render the lean-variant backtest report (docs/TREND_BACKTEST_LEAN_<date>.md).

Rules pre-registered in docs/TREND_DESIGN.md §8 before this was run. Every number is
computed here from the cached bars (SPEC L3). Run:
  python -m marketmind.trend.lean_report --out docs/TREND_BACKTEST_LEAN_2026-09-29.md
(the cache is the git-ignored cache/trend/, filled by `python -m marketmind.trend.report --fetch`).
"""
from __future__ import annotations

import argparse
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

from marketmind.trend.backtest import (
    PortfolioConfig, bh_series, cagr, max_drawdown, result_from_sim, run_portfolio,
    run_universe, slice_metrics, tbill_hurdle_fn, trade_net_return, variants, yearly_returns,
)
from marketmind.trend.data import DEFAULT_CACHE, load_cached
from marketmind.trend.lean import LEAN_CORE, SECTORS, LeanConfig, lean_states, simulate_lean
from marketmind.trend.report import NA, PORTFOLIO_START, SPLIT, num, pct
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import hurdle_from_tbill
from marketmind.trend.universe import TBILL_PROXY, TREND_UNIVERSE

RISK_1PCT = PortfolioConfig()                                             # sizing (a)
FIXED_20 = PortfolioConfig(risk_per_trade=1.0, max_weight=0.20, max_positions=5)   # sizing (b)
TARGET = (4.0, 8.0)             # owner's target alerts (entries) per year
MDD_SLACK = 0.02                # pre-registered: filter may not deepen MaxDD by more than 2pp


def lean_results(data: dict, cfg: TrendConfig, hurdle, lean: LeanConfig) -> dict:
    res = simulate_lean({t: b for t, (_, b) in data.items()}, cfg, hurdle, lean)
    return {t: result_from_sim(sim, data[t][0]) for t, sim in res.sims.items()}, res


def evaluate(results: dict, pcfg: PortfolioConfig) -> dict:
    port = run_portfolio(results, pcfg, start=PORTFOLIO_START)
    m = port.metrics
    entries = sum(1 for r in results.values() for tr in r.trades if tr.signal_date >= PORTFOLIO_START)
    return {"port": port, "m": m, "entries": entries, "entries_py": entries / m["years"],
            "tim": 1 - m.get("flat_share", 1.0), "exposure": m.get("avg_exposure"),
            "h1": slice_metrics(port.dates, port.equity, PORTFOLIO_START, SPLIT),
            "h2": slice_metrics(port.dates, port.equity, SPLIT, "9999")}


def _target_gap(x: float) -> float:
    lo, hi = TARGET
    return 0.0 if lo <= x <= hi else min(abs(x - lo), abs(x - hi))


def filter_verdict(base: dict, strict: dict) -> tuple[bool, list[str]]:
    """The pre-registered adoption test (TREND_DESIGN.md §8) for one sizing."""
    notes, ok = [], True
    for half in ("h1", "h2"):
        b, s = base[half], strict[half]
        c_ok = s["cagr"] >= b["cagr"]
        d_ok = s["mdd"] >= b["mdd"] - MDD_SLACK
        ok &= c_ok and d_ok
        notes.append(f"{'前半' if half == 'h1' else '后半'} CAGR {pct(s['cagr'], 2)} vs {pct(b['cagr'], 2)} "
                     f"{'✓' if c_ok else '✗'}，回撤 {pct(s['mdd'])} vs {pct(b['mdd'])} {'✓' if d_ok else '✗'}")
    gs, gb = _target_gap(strict["entries_py"]), _target_gap(base["entries_py"])
    closer = gs < gb or gs == gb == 0
    ok &= closer
    notes.append(f"入场/年 {num(strict['entries_py'])} vs {num(base['entries_py'])}（目标 4-8）"
                 f"{'更接近 ✓' if closer else '没有更接近 ✗'}")
    return ok, notes


def capture(moves: list[dict]) -> dict:
    if not moves:
        return {"n": 0, "part": None, "mid": None, "cap": None}
    return {"n": len(moves), "part": sum(m["participated"] for m in moves) / len(moves),
            "mid": sum(m["in_at_mid"] for m in moves) / len(moves),
            "cap": statistics.fmean(m["capture"] for m in moves)}


def build(cache_dir: Path = DEFAULT_CACHE, as_of: str | None = None) -> str:
    data, missing = {}, []
    for t in TREND_UNIVERSE:
        got = load_cached(t, cache_dir)
        (missing.append(t) if got is None else data.__setitem__(t, got))
    irx = load_cached(TBILL_PROXY, cache_dir)
    irx_bars = irx[1] if irx else None
    hurdle, hurdle_src = tbill_hurdle_fn(irx_bars)
    cfg = TrendConfig()
    base_lc, strict_lc = LeanConfig(), LeanConfig(top_n=3)
    lean_data = {t: v for t, v in data.items() if t in base_lc.tickers}

    full = run_universe(data, cfg, hurdle)
    lean, lean_raw = lean_results(lean_data, cfg, hurdle, base_lc)
    strict, strict_raw = lean_results(lean_data, cfg, hurdle, strict_lc)
    rows = {}
    for key, res in (("lean", lean), ("strict", strict), ("full", full)):
        for sz, pcfg in (("a", RISK_1PCT), ("b", FIXED_20)):
            rows[(key, sz)] = evaluate(res, pcfg)
    ref = rows[("lean", "a")]["port"]
    spy = bh_series(data["SPY"][1], ref.dates)
    spy_yr = yearly_returns(ref.dates, spy)
    spy_row = {"cagr": cagr(spy[0], spy[-1], ref.dates[0], ref.dates[-1]), "mdd": max_drawdown(spy),
               "worst": min(spy_yr.items(), key=lambda kv: kv[1]),
               "h1": slice_metrics(ref.dates, spy, PORTFOLIO_START, SPLIT),
               "h2": slice_metrics(ref.dates, spy, SPLIT, "9999")}
    full_signals_py = rows[("full", "a")]["entries_py"]
    verdicts = {sz: filter_verdict(rows[("lean", sz)], rows[("strict", sz)]) for sz in ("a", "b")}
    adopt = all(v[0] for v in verdicts.values())

    # robustness: the same 10 neighbouring parameter sets
    rob = []
    for name, vcfg in variants(cfg):
        line = [name, vcfg == cfg]
        for lc in (base_lc, strict_lc):
            vres = lean_results(lean_data, vcfg, hurdle, lc)[0] if vcfg != cfg else \
                (lean if lc is base_lc else strict)
            line.append((evaluate(vres, RISK_1PCT), evaluate(vres, FIXED_20)))
        rob.append(line)

    last_bar = max(b[-1].date for _, b in data.values())
    today_h = hurdle_from_tbill(irx_bars) if irx_bars else None
    now = lean_states({t: b for t, (_, b) in lean_data.items()}, today_h or 0.0, cfg, base_lc,
                      today=date.fromisoformat(as_of or last_bar))

    L: list[str] = []
    w = L.append
    la, lb, sa, sb = rows[("lean", "a")], rows[("lean", "b")], rows[("strict", "a")], rows[("strict", "b")]
    fa, fb = rows[("full", "a")], rows[("full", "b")]
    rob_b = [x[2][1]["m"] for x in rob]
    w(f"# 趋势状态机·精简版回测（{as_of or date.today().isoformat()}）\n")
    w("> 纯代码生成（`python -m marketmind.trend.lean_report`），所有数字由 `marketmind/trend/` 从缓存行情计算（SPEC L3）。"
      "规则在看结果之前登记在 `docs/TREND_DESIGN.md` §8（单独一次提交）。**尚未接入警报**。\n")
    w("## 给所有人的摘要\n")
    solo = sum(len(lean[t].trades) for t in ("GLD", "TLT", "USO") if t in lean)
    total = sum(len(r.trades) for r in lean.values())
    solo_hit = [sum(trade_net_return(tr, lean[t].cost) > 0 for tr in lean[t].trades if tr.closed)
                / max(1, sum(tr.closed for tr in lean[t].trades)) for t in ("GLD", "TLT", "USO") if t in lean]
    lo, hi = TARGET
    hit = "达到" if lo <= la["entries_py"] <= hi else "没有达到"
    w(f"- **警报数量{hit}目标**：精简版每年 {num(la['entries_py'])} 次入场（目标 {lo:g}-{hi:g}），加上预先登记的\"12 个月动量排名前 3\"过滤后 {num(sa['entries_py'])} 次；"
      f"全池 28 标的版每年 {num(full_signals_py)} 个信号。单独成组的 GLD、TLT、USO 占精简版全部入场的 {pct(solo / total if total else None, 0)}，"
      f"它们的单笔胜率在 {pct(min(solo_hit), 0)}-{pct(max(solo_hit), 0)}（见第 3 节）。")
    pnl = Counter()
    for p_ in lb["port"].taken:
        if "pnl" in p_:
            pnl[p_["ticker"]] += p_["pnl"]
    gain = sum(pnl.values())
    top_pnl = "、".join(f"{t} {v / gain:.0%}" for t, v in pnl.most_common(3)) if gain > 0 else NA
    w(f"- **收益从哪里来**：精简版 2006-2015 年 CAGR {pct(lb['h1']['cagr'])}（基本不赚钱），2016 年以后 {pct(lb['h2']['cagr'])}；"
      f"已平仓盈亏（20%/仓）按标的占比前三：{top_pnl}。"
      + ("也就是说，精简版的收益主要靠加密货币的几波大行情。" if pnl and pnl.most_common(1)[0][0].endswith("-USD") else ""))
    w(f"- **收益与回撤（每仓固定 20%）**：精简版 CAGR {pct(lb['m']['cagr'])}、最大回撤 {pct(lb['m']['mdd'])}、最差年 {lb['m']['worst_year'][0]}（{pct(lb['m']['worst_year'][1])}），"
      f"在场时间 {pct(lb['tim'], 0)}（平均投入 {pct(lb['exposure'], 0)}）；加过滤 CAGR {pct(sb['m']['cagr'])}、回撤 {pct(sb['m']['mdd'])}。"
      f"同期 SPY 买入持有 CAGR {pct(spy_row['cagr'])}、回撤 {pct(spy_row['mdd'])}；全池版（同样 20%/仓、最多 5 仓）CAGR {pct(fb['m']['cagr'])}、回撤 {pct(fb['m']['mdd'])}。")
    w(f"- **每笔风险 1% 的仓位**（与全池版原报告相同）：精简版 CAGR {pct(la['m']['cagr'])}、回撤 {pct(la['m']['mdd'])}，平均投入只有 {pct(la['exposure'], 0)}；全池版 CAGR {pct(fa['m']['cagr'])}、回撤 {pct(fa['m']['mdd'])}。")
    w(f"- **\"大部分时间持币\"**：精简版有持仓的天数占 {pct(lb['tim'], 0)}，不是\"大部分时间持币\"；全池版 {pct(fb['tim'], 0)}。")
    w(f"- **预先登记的过滤（12 个月超额收益排名前 3）**：{'通过' if adopt else '未通过'}事先定的采用标准（两种仓位都要通过），"
      f"{'建议采用' if adopt else '按规则不采用，保留不加过滤的精简版'}。细节见第 5 节。")
    w(f"- **稳健性**：10 组相邻参数下精简版（20%/仓）CAGR {pct(min(r['cagr'] for r in rob_b))} 至 {pct(max(r['cagr'] for r in rob_b))}，"
      f"最大回撤 {pct(min(r['mdd'] for r in rob_b))} 至 {pct(max(r['mdd'] for r in rob_b))}；"
      f"主参数前后两半（2006-2015 / 2016-）CAGR {pct(lb['h1']['cagr'])} / {pct(lb['h2']['cagr'])}。")
    w("- **注意**：不含税；最强行业用的是 10 个行业 ETF 的 12 个月收益（事后不会变）；加密从 2016/2017 年才加入；缓存为 2026-09-29 重新抓取（与全池版原报告同一来源）。\n")

    w("## 1. 设置\n")
    w(f"- 核心标的：{', '.join(LEAN_CORE)}；最强行业从 {', '.join(SECTORS)} 中每天按 12 个月超额收益取第一。")
    w(f"- 相关组：{' / '.join('{' + ', '.join(g) + '}' for g in base_lc.groups)}（SECTOR = 当天最强行业）；GLD、TLT、USO 各自一组。每组最多一个仓位，同日取 12 个月超额收益最高者。")
    w(f"- 规则参数：`{cfg}`（与全池版相同）；12 个月门槛：{hurdle_src}。")
    w(f"- 仓位 (a)：`{RISK_1PCT}`；仓位 (b)：`{FIXED_20}`（风险参数设为 1.0 使 20% 上限生效）。现金 0 息，成交 = 信号次日开盘，成本同全池版。")
    w(f"- 区间：{PORTFOLIO_START} 起；前后两半以 {SPLIT} 分界。")
    if missing:
        w(f"- **数据不可用**：{', '.join(missing)}")
    w("")

    w("## 2. 主要结果\n")
    w("| 版本 | 仓位 | 入场/年（警报） | 在场时间 | 平均投入 | CAGR | 最大回撤 | 最差年 | 2006-2015 CAGR / 回撤 | 2016- CAGR / 回撤 |")
    w("|---|---|---:|---:|---:|---:|---:|---|---|---|")
    names = {"lean": "精简版", "strict": "精简版 + 排名前 3", "full": "全池 28 标的"}
    for key in ("lean", "strict", "full"):
        for sz, label in (("b", "20%/仓"), ("a", "1% 风险")):
            r = rows[(key, sz)]
            m = r["m"]
            ent = f"{num(r['entries_py'])}" + (f"（接 {num(m['taken_per_year'])}）" if key == "full" else "")
            w(f"| {names[key]} | {label} | {ent} | {pct(r['tim'], 0)} | {pct(r['exposure'], 0)} | {pct(m['cagr'])} | {pct(m['mdd'])} | "
              f"{m['worst_year'][0]} {pct(m['worst_year'][1])} | {pct(r['h1'].get('cagr'))} / {pct(r['h1'].get('mdd'))} | "
              f"{pct(r['h2'].get('cagr'))} / {pct(r['h2'].get('mdd'))} |")
    w(f"| SPY 买入持有 | 100% | — | 100% | 100% | {pct(spy_row['cagr'])} | {pct(spy_row['mdd'])} | {spy_row['worst'][0]} {pct(spy_row['worst'][1])} | "
      f"{pct(spy_row['h1'].get('cagr'))} / {pct(spy_row['h1'].get('mdd'))} | {pct(spy_row['h2'].get('cagr'))} / {pct(spy_row['h2'].get('mdd'))} |")
    w(f"\n区间 {la['m']['start']} 至 {la['m']['end']}（{la['m']['years']:.1f} 年）。\"在场时间\" = 至少持有一个仓位的交易日占比。"
      "全池版的\"入场/年\"是全部原始信号（组合实际接的在括号里）；精简版每个信号都接（组互斥保证不超过 5 仓）。\n")

    w("## 3. 逐年入场次数与收益（20%/仓）\n")
    years = sorted(set(lb["m"]["yearly"]))
    ent_y = {k: Counter(int(tr.signal_date[:4]) for r in res.values() for tr in r.trades
                        if tr.signal_date >= PORTFOLIO_START)
             for k, res in (("lean", lean), ("strict", strict), ("full", full))}
    w("| 年份 | 精简版入场 | +排名前 3 入场 | 全池信号 | 精简版收益 | +排名前 3 收益 | 全池（20%/仓）收益 | SPY |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for y in years:
        w(f"| {y} | {ent_y['lean'].get(y, 0)} | {ent_y['strict'].get(y, 0)} | {ent_y['full'].get(y, 0)} | "
          f"{pct(lb['m']['yearly'].get(y))} | {pct(sb['m']['yearly'].get(y))} | {pct(fb['m']['yearly'].get(y))} | {pct(spy_yr.get(y))} |")
    w(f"\n{years[-1]} 年为年初至今。\n")
    w("**按标的**（精简版，全部区间）：\n")
    w("| 标的 | 入场 | 已平仓 | 胜率 | 平均净收益 | 中位 | 最好一笔 | 全池版同标的入场 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for t in base_lc.tickers:
        if t not in lean:
            continue
        r = lean[t]
        rets = [trade_net_return(tr, r.cost) for tr in r.trades if tr.closed]
        if not r.trades and t in SECTORS:
            continue
        w(f"| {t} | {len(r.trades)} | {len(rets)} | {pct(sum(x > 0 for x in rets) / len(rets), 0) if rets else NA} | "
          f"{pct(statistics.fmean(rets)) if rets else NA} | {pct(statistics.median(rets)) if rets else NA} | "
          f"{pct(max(rets)) if rets else NA} | {len(full[t].trades)} |")
    st_count = Counter(lean_raw.strongest.values())
    w("\n最强行业出现天数：" + "，".join(f"{t} {n}" for t, n in st_count.most_common()) + "。")
    vc = Counter(v["why"].split(" (")[0] for v in lean_raw.vetoes)
    w("被挡掉的信号日（同一标的连续多天创新高会重复计）：" + "，".join(f"{k} {n}" for k, n in vc.most_common()) + "。\n")

    w("## 4. 大行情捕获（低点到高点 ≥20%、≤120 个交易日；与全池版在同样行情上对比）\n")
    w("| 标的 | 行情段 | 精简版参与 | 中段在场 | 捕获 | 全池版参与 | 中段在场 | 捕获 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for t in LEAN_CORE:
        if t not in lean:
            continue
        a, b = capture(lean[t].moves), capture(full[t].moves)
        w(f"| {t} | {a['n']} | {pct(a['part'], 0)} | {pct(a['mid'], 0)} | {pct(a['cap'], 0)} | {pct(b['part'], 0)} | {pct(b['mid'], 0)} | {pct(b['cap'], 0)} |")
    core_l = capture([m for t in LEAN_CORE if t in lean for m in lean[t].moves])
    core_f = capture([m for t in LEAN_CORE if t in full for m in full[t].moves])
    sec_l = capture([m for t in SECTORS if t in lean for m in lean[t].moves])
    sec_f = capture([m for t in SECTORS if t in full for m in full[t].moves])
    w(f"| **7 个代表合计** | {core_l['n']} | {pct(core_l['part'], 0)} | {pct(core_l['mid'], 0)} | {pct(core_l['cap'], 0)} | {pct(core_f['part'], 0)} | {pct(core_f['mid'], 0)} | {pct(core_f['cap'], 0)} |")
    w(f"| 10 个行业合计 | {sec_l['n']} | {pct(sec_l['part'], 0)} | {pct(sec_l['mid'], 0)} | {pct(sec_l['cap'], 0)} | {pct(sec_f['part'], 0)} | {pct(sec_f['mid'], 0)} | {pct(sec_f['cap'], 0)} |")
    w("\n行业一行是全部 10 个行业的所有行情段：精简版只拿一个\"最强行业\"名额，所以大部分行业行情本来就不参与。\n")

    w("## 5. 预先登记的更严过滤：12 个月超额收益排名前 3\n")
    w("判定标准（事先写定）：前后两半 CAGR 都不低于精简版；前后两半最大回撤都不比精简版深超过 2 个百分点；每年入场次数更接近 4-8。两种仓位都要满足。\n")
    for sz, label in (("b", "20%/仓"), ("a", "1% 风险")):
        ok, notes = verdicts[sz]
        w(f"- **{label}：{'通过' if ok else '未通过'}** — " + "；".join(notes))
    w(f"\n结论：{'采用' if adopt else '不采用'}（按事先的标准，不因结果调整）。\n")

    w("## 6. 稳健性（与全池版相同的 10 组相邻参数）\n")
    w("| 参数 | 精简版 入场/年 | 在场 | CAGR 20%/仓 | 回撤 20%/仓 | CAGR 1%风险 | 回撤 1%风险 | 前半/后半 CAGR（20%） | +前3 入场/年 | +前3 CAGR 20% | +前3 回撤 20% | +前3 前半/后半 CAGR |")
    w("|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|")
    for name, is_base, (ba, bb), (xa, xb) in rob:
        label = f"**{name}（主）**" if is_base else name
        w(f"| {label} | {num(bb['entries_py'])} | {pct(bb['tim'], 0)} | {pct(bb['m']['cagr'])} | {pct(bb['m']['mdd'])} | "
          f"{pct(ba['m']['cagr'])} | {pct(ba['m']['mdd'])} | {pct(bb['h1'].get('cagr'))} / {pct(bb['h2'].get('cagr'))} | "
          f"{num(xb['entries_py'])} | {pct(xb['m']['cagr'])} | {pct(xb['m']['mdd'])} | {pct(xb['h1'].get('cagr'))} / {pct(xb['h2'].get('cagr'))} |")
    w("")

    w(f"## 7. 当前精简版状态（缓存最后一根完整日线 {last_bar}，门槛 {pct(today_h, 2) if today_h is not None else '不可用→0'}）\n")
    w(f"最强行业：**{now['strongest_sector'] or '无'}**。由 `trend.lean.lean_states`（与每日运行同一代码）计算。\n")
    w("| 标的 | 组 | 状态 | 事件 | 日期 | 收盘 | 12月收益 | SMA200 | 55日高 | 止损位 | 入场信号日 | 说明 |")
    w("|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for t, s in now["states"].items():
        w(f"| {t} | {now['groups'].get(t, '')} | {s.state} | {s.event or ''} | {s.as_of or '—'} | {num(s.close, 2)} | {pct(s.ret_12m)} | "
          f"{num(s.sma200, 2)} | {num(s.high_55, 2)} | {num(s.stop_level, 2)} | {s.entry_signal_date or ''} | {s.reason or ''} |")
    w("")

    w("## 8. 注意事项\n")
    w("- **同一组互斥的副作用**：组内已持有时，其他成员的信号被挡掉，它们不进入\"假想持仓\"，之后再创 55 日收盘新高才可能入场，所以可能在行情较晚的位置入场（预先登记的规则）。")
    w("- **最强行业**：只决定哪个行业可以发入场信号；已持有的行业不因不再最强而卖出，只按吊灯止损离场。")
    w("- **单独成组的 GLD、TLT、USO** 不受组互斥约束，是入场次数的主要来源；是否再把它们并组或提高门槛，需要另行登记后回测（本报告不做）。")
    w("- **仓位 (b)** 5 个组各 20%，满仓时 100% 投入，不加杠杆；成本使最后一个仓位略小于 20%。")
    w("- 其他注意事项同全池版报告（不含税、加密早期交易所数据、yfinance 复权价、成交按次日开盘）。")
    w("")
    w("## References（访问日期 2026-09-29）\n")
    w("见 `docs/TREND_DESIGN.md` References 第 1-10 条；本报告新增规则的依据是第 8 条（Faber 2010，最强行业）、第 9 条（Antonacci，双动量 / 排名过滤）、第 10 条（海龟规则相关市场上限，组互斥）。")
    return "\n".join(L) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args(argv)
    text = build(as_of=a.as_of)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
