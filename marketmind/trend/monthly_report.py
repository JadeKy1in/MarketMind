"""Render the monthly-rule backtest report (docs/TREND_BACKTEST_MONTHLY_<date>.md).

Rules, criterion and grid were pre-registered in docs/TREND_DESIGN.md §10 before this
was run. Every number is computed here from the cached bars (SPEC L3). Run:
  python -m marketmind.trend.monthly_report --out docs/TREND_BACKTEST_MONTHLY_2026-09-29.md
(the cache is the git-ignored cache/trend/, filled by `python -m marketmind.trend.report --fetch`).
"""
from __future__ import annotations

import argparse
import statistics
from dataclasses import replace
from datetime import date
from pathlib import Path

from marketmind.trend.backtest import (
    PortfolioConfig, BIG_MOVE_RISE, big_move_bars, big_moves, bh_series, cagr, max_drawdown,
    move_capture, result_from_sim, run_portfolio, run_universe, slice_metrics, tbill_hurdle_fn,
    yearly_returns,
)
from marketmind.trend.data import DEFAULT_CACHE, load_cached
from marketmind.trend.monthly import (
    ALWAYS, CHECK_MID_MONTH, M1, M2, MONTHLY_UNIVERSE, SLOTS, MonthlyConfig, simulate_monthly,
    whipsaws,
)
from marketmind.trend.report import NA, PORTFOLIO_START, SPLIT, _irx_rate, num, pct
from marketmind.trend.rules import TrendConfig
from marketmind.trend.universe import TBILL_PROXY, TREND_UNIVERSE

# Pre-registered criterion (docs/TREND_DESIGN.md §10)
MAX_ENTRIES_PY = 10.0
MAX_TIM = 0.60
MDD_FRACTION = 0.5
CAGR_SLACK = 0.03
DAILY_WHIPSAW_DAYS = 61
NON_CRYPTO = ("SPY", "QQQ", "GLD", "TLT")          # daily rules: fill-to-exit shorter than ~2 months


def grid() -> list[MonthlyConfig]:
    out = []
    for base, lens in ((M1, (8, 10, 12)), (M2, (9, 12, 15))):
        for check in (M1.check, CHECK_MID_MONTH):
            out += [replace(base, months=m, check=check) for m in lens]
    return out


def _entries(results: dict) -> dict[str, int]:
    return {t: sum(1 for tr in r.trades if tr.fill_date and tr.fill_date >= PORTFOLIO_START)
            for t, r in results.items()}


def _whips_daily(results: dict) -> int:
    return sum(1 for r in results.values() for tr in r.trades if tr.closed and
               (date.fromisoformat(tr.exit_date) - date.fromisoformat(tr.fill_date)).days
               < DAILY_WHIPSAW_DAYS)


def evaluate(results: dict, pcfg: PortfolioConfig = SLOTS, cash_rate=None,
             whips: int | None = None) -> dict:
    port = run_portfolio(results, pcfg, cash_rate=cash_rate, start=PORTFOLIO_START)
    m = port.metrics
    per = _entries(results)
    tims = [r.metrics["time_in_market"] for r in results.values() if "time_in_market" in r.metrics]
    return {
        "results": results, "port": port, "m": m, "per_asset_entries": per,
        "entries": sum(per.values()), "entries_py": sum(per.values()) / m["years"],
        "tim": statistics.fmean(tims) if tims else None,
        "any_pos": 1 - m.get("flat_share", 1.0), "exposure": m.get("avg_exposure"),
        "cagr": m["cagr"], "mdd": m["mdd"], "worst": m["worst_year"],
        "h1": slice_metrics(port.dates, port.equity, PORTFOLIO_START, SPLIT),
        "h2": slice_metrics(port.dates, port.equity, SPLIT, "9999"),
        "whipsaws": whips,
    }


def monthly_results(data: dict, cfg: MonthlyConfig, hurdle,
                    universe: tuple[str, ...] = MONTHLY_UNIVERSE) -> tuple[dict, int]:
    sims = {t: simulate_monthly(t, data[t][1], cfg, hurdle) for t in universe if t in data}
    return ({t: result_from_sim(s, data[t][0]) for t, s in sims.items()},
            sum(whipsaws(s, cfg.check) for s in sims.values()))


def verdict(ev: dict, bench: dict) -> list[tuple[str, bool, str]]:
    """The five pre-registered conditions (docs/TREND_DESIGN.md §10)."""
    h1, h2 = ev["h1"].get("cagr"), ev["h2"].get("cagr")
    return [
        ("入场 ≤ 10 次/年", ev["entries_py"] <= MAX_ENTRIES_PY, f"{num(ev['entries_py'])} 次/年"),
        ("在场时间 ≤ 60%", ev["tim"] <= MAX_TIM, pct(ev["tim"], 0)),
        ("最大回撤 ≤ 等权持有的一半", abs(ev["mdd"]) <= MDD_FRACTION * abs(bench["mdd"]),
         f"{pct(ev['mdd'])} vs 一半 {pct(MDD_FRACTION * bench['mdd'])}"),
        ("CAGR ≥ 等权持有 − 3 点", ev["cagr"] >= bench["cagr"] - CAGR_SLACK,
         f"{pct(ev['cagr'])} vs {pct(bench['cagr'] - CAGR_SLACK)}"),
        ("前后两半 CAGR 都 > 0", h1 is not None and h2 is not None and h1 > 0 and h2 > 0,
         f"{pct(h1)} / {pct(h2)}"),
    ]


def passed(v) -> bool:
    return all(ok for _, ok, _ in v)


def common_moves(data: dict, rules: dict[str, dict]) -> dict[str, dict]:
    """Big-move capture of several rule sets on the SAME moves: per instrument, moves are
    found from the latest first-ready date among the rules (so every rule can trade)."""
    out = {name: [] for name in rules}
    per_asset: dict[str, dict[str, list]] = {}
    for t in MONTHLY_UNIVERSE:
        if t not in data:
            continue
        bars = data[t][1]
        starts = [rs[t].eval_start for rs in rules.values() if t in rs and rs[t].eval_start]
        if len(starts) < len(rules):
            continue
        s = next(i for i, b in enumerate(bars) if b.date >= max(max(starts), PORTFOLIO_START))
        closes = [b.close for b in bars]
        mv = big_moves(closes, s, BIG_MOVE_RISE, big_move_bars(t))
        per_asset[t] = {}
        for name, rs in rules.items():
            caps = [move_capture(closes, rs[t].gross_ret, rs[t].held, a, b) for a, b in mv]
            out[name] += caps
            per_asset[t][name] = caps
    return {"pooled": {k: _cap(v) for k, v in out.items()},
            "per_asset": {t: {k: _cap(v) for k, v in d.items()} for t, d in per_asset.items()}}


def _cap(moves: list[dict]) -> dict:
    if not moves:
        return {"n": 0, "part": None, "mid": None, "cap": None}
    return {"n": len(moves), "part": sum(m["participated"] for m in moves) / len(moves),
            "mid": sum(m["in_at_mid"] for m in moves) / len(moves),
            "cap": statistics.fmean(m["capture"] for m in moves)}


def compute(cache_dir: Path = DEFAULT_CACHE) -> dict:
    data, missing = {}, []
    for t in TREND_UNIVERSE:
        got = load_cached(t, cache_dir)
        (missing.append(t) if got is None else data.__setitem__(t, got))
    irx = load_cached(TBILL_PROXY, cache_dir)
    irx_bars = irx[1] if irx else None
    hurdle, hurdle_src = tbill_hurdle_fn(irx_bars)
    cash = _irx_rate(irx_bars) if irx_bars else None
    out: dict = {"data": data, "missing": missing, "hurdle_src": hurdle_src}
    out["grid"] = {}
    for cfg in grid():
        res, wh = monthly_results(data, cfg, hurdle)
        out["grid"][cfg] = evaluate(res, whips=wh)
    out["m1"], out["m2"] = out["grid"][M1], out["grid"][M2]
    out["m1_tbill"] = evaluate(out["m1"]["results"], cash_rate=cash)
    out["m2_tbill"] = evaluate(out["m2"]["results"], cash_rate=cash)
    bench, _ = monthly_results(data, ALWAYS, hurdle)
    out["bench"] = evaluate(bench)
    cfg = TrendConfig()
    six = {t: data[t] for t in MONTHLY_UNIVERSE if t in data}
    daily6 = run_universe(six, cfg, hurdle)
    out["daily6"] = evaluate(daily6, whips=_whips_daily(daily6))
    full = run_universe(data, cfg, hurdle)
    ev_full = evaluate(full, PortfolioConfig(), whips=_whips_daily(full))
    ev_full["signals_py"] = sum(1 for r in full.values() for tr in r.trades
                                if tr.signal_date >= PORTFOLIO_START) / ev_full["m"]["years"]
    ev_full["moves"] = _cap([m for r in full.values() for m in r.moves])
    out["full"] = ev_full
    spy = data["SPY"][1]
    port = out["m1"]["port"]
    spy_eq = bh_series(spy, port.dates)
    out["spy"] = {"cagr": cagr(spy_eq[0], spy_eq[-1], port.dates[0], port.dates[-1]),
                  "mdd": max_drawdown(spy_eq), "yearly": yearly_returns(port.dates, spy_eq),
                  "h1": slice_metrics(port.dates, spy_eq, PORTFOLIO_START, SPLIT),
                  "h2": slice_metrics(port.dates, spy_eq, SPLIT, "9999")}
    out["spy"]["worst"] = min(out["spy"]["yearly"].items(), key=lambda kv: kv[1])
    out["moves"] = common_moves(data, {"M1": out["m1"]["results"], "M2": out["m2"]["results"],
                                       "daily": daily6})
    # post-hoc diagnostic (not part of the verdict): the four ETFs only, 1/4 slots
    ex, slots4 = NON_CRYPTO, PortfolioConfig(risk_per_trade=1.0, max_weight=0.25, max_positions=4)
    diag = {}
    for name, c in (("m1", M1), ("m2", M2), ("bench", ALWAYS)):
        res, wh = monthly_results(data, c, hurdle, ex)
        diag[name] = evaluate(res, slots4, whips=wh)
    out["excrypto"] = diag
    out["verdict"] = {k: verdict(out[k], out["bench"]) for k in ("m1", "m2")}
    out["grid_verdict"] = {c: verdict(ev, out["bench"]) for c, ev in out["grid"].items()}
    return out


# ── rendering ───────────────────────────────────────────────────────────────

def _yr(w) -> str:
    return NA if not w else f"{w[0]} {pct(w[1])}"


def _half(ev: dict, h: str) -> str:
    x = ev[h]
    return f"{pct(x.get('cagr'))} / {pct(x.get('mdd'))}" if x else NA


def _fails(v) -> str:
    bad = [name for name, ok, _ in v if not ok]
    return "全部通过" if not bad else "未过：" + "；".join(bad)


def _trip(c: dict) -> str:
    return f"{pct(c['part'], 0)} / {pct(c['mid'], 0)} / {pct(c['cap'], 0)}"


def _by_year(results: dict) -> dict[int, int]:
    c: dict[int, int] = {}
    for r in results.values():
        for tr in r.trades:
            if tr.fill_date and tr.fill_date >= PORTFOLIO_START:
                y = int(tr.fill_date[:4])
                c[y] = c.get(y, 0) + 1
    return c


def build(cache_dir: Path = DEFAULT_CACHE) -> str:
    o = compute(cache_dir)
    m1, m2, bench, d6, full, spy = (o[k] for k in ("m1", "m2", "bench", "daily6", "full", "spy"))
    data, mv = o["data"], o["moves"]
    pooled = mv["pooled"]
    v1, v2 = o["verdict"]["m1"], o["verdict"]["m2"]
    n_grid = len(o["grid_verdict"])
    n_grid_pass = sum(passed(v) for v in o["grid_verdict"].values())
    period = f"{m1['m']['start']} 至 {m1['m']['end']}（{m1['m']['years']:.1f} 年）"
    r1, r2 = m1["results"], m2["results"]
    diag = o["excrypto"]
    y17 = m1["m"]["yearly"].get(2017)
    L: list[str] = []
    w = L.append

    w("# 月度长周期趋势规则回测（2026-09-29）\n")
    w("> 纯代码生成（`python -m marketmind.trend.monthly_report`），所有数字由 `marketmind/trend/` 从缓存行情计算（SPEC L3）。"
      "规则、参数与通过标准在看结果之前登记在 `docs/TREND_DESIGN.md` §10（单独一次提交）。**只回测，未接入每日运行或警报。**\n")

    w("## 给所有人的摘要\n")
    w(f"- **结论：两条月度规则都没有通过事先定的标准，不建议按现在的形式采用。** "
      f"M1（10 个月均线）{_fails(v1)}。M2（12 个月动量）{_fails(v2)}。"
      f"事先登记的 {n_grid} 组相邻参数里 {n_grid_pass} 组通过。"
      if not (passed(v1) or passed(v2)) else
      f"- **结论**：M1 {'通过' if passed(v1) else _fails(v1)}；M2 {'通过' if passed(v2) else _fails(v2)}。"
      f"相邻参数 {n_grid} 组里 {n_grid_pass} 组通过。")
    w(f"- **做到了的**：警报很少——6 个标的合计每年入场 M1 {num(m1['entries_py'])} 次、M2 {num(m2['entries_py'])} 次"
      f"（日线版同样 6 个标的 {num(d6['entries_py'])} 次，全池 28 标的 {num(full['signals_py'])} 个）。"
      f"大行情吃得更多：同样 {pooled['M1']['n']} 段大行情里，行情走到一半时在场的比例 M1 {pct(pooled['M1']['mid'], 0)}、"
      f"M2 {pct(pooled['M2']['mid'], 0)}（日线版 {pct(pooled['daily']['mid'], 0)}），平均吃到整段涨幅的 "
      f"{pct(pooled['M1']['cap'], 0)} / {pct(pooled['M2']['cap'], 0)}（日线版 {pct(pooled['daily']['cap'], 0)}）。")
    w(f"- **没做到的 1：不是\"大部分时间持币\"**。每个标的平均有 {pct(m1['tim'], 0)}（M1）/ {pct(m2['tim'], 0)}（M2）的时间在场，"
      f"超过 60% 的上限；组合平均投入 {pct(m1['exposure'], 0)} / {pct(m2['exposure'], 0)}。"
      "月度规则的本质是\"大部分时间跟着趋势持有，只躲开大熊市\"。")
    w(f"- **没做到的 2：会被套**。组合最大回撤 M1 {pct(m1['mdd'])}、M2 {pct(m2['mdd'])}，等权买入持有 {pct(bench['mdd'])}；"
      f"最差年 M1 {_yr(m1['worst'])}、M2 {_yr(m2['worst'])}。原因是加密：月度检查离场太慢，ETH 单独按 M1 做的最大回撤 "
      f"{pct(r1['ETH-USD'].metrics['mdd'])}（持有 {pct(r1['ETH-USD'].metrics['bh_mdd'])}），BTC {pct(r1['BTC-USD'].metrics['mdd'])}"
      f"（持有 {pct(r1['BTC-USD'].metrics['bh_mdd'])}）；而且持有期间不再平衡，涨上去的加密占了组合的大头。")
    w(f"- **收益**：CAGR M1 {pct(m1['cagr'])}、M2 {pct(m2['cagr'])}，等权买入持有 {pct(bench['cagr'])}，SPY 买入持有 {pct(spy['cagr'])}。"
      f"高数字主要来自少数几年的加密暴涨（M1 2017 年 {pct(y17, 0)}），"
      f"前半段（2006-2015，还没有加密）M1 只有 {pct(m1['h1']['cagr'])}、M2 {pct(m2['h1']['cagr'])}，不能当作以后的预期。")
    w(f"- **事后诊断（不参与判定）**：只看 4 个 ETF（SPY/QQQ/GLD/TLT，每个 1/4）时，M1 最大回撤 {pct(diag['m1']['mdd'])} "
      f"vs 等权持有 {pct(diag['bench']['mdd'])}，CAGR {pct(diag['m1']['cagr'])} vs {pct(diag['bench']['cagr'])}，在场时间 {pct(diag['m1']['tim'], 0)}。"
      "也就是说，月度均线在传统资产上\"降回撤\"有效（与 Faber 的结论一致），但在加密上保护不够，且在场时间始终偏高。")
    w("- **建议**：不接入。如果还想要\"少警报 + 吃中段\"，下一步可以事先登记一个组合方案再回测"
      "（例如 ETF 用月度规则、加密用更快的离场或更小的仓位上限），本次不做。")
    w("- **注意**：不含税；加密从 2016/2017 年才有足够月线；2017 年加密的百倍行情对组合数字影响极大；缓存为 2026-09-29 重新抓取。\n")

    w("## 1. 设置\n")
    w(f"- 标的：{', '.join(MONTHLY_UNIVERSE)}；6 个等权名额，入场时买当时总权益的 1/6，持有期间不再平衡，离场全部卖出；"
      "没有足够历史的名额留作现金。")
    w("- M1：月末收盘 > 最近 10 个月末收盘均值 → 持有，否则现金。M2：12 个月收益 > 同期 T-bill 收益（`^IRX` 252 日均值，按当时已知）→ 持有。")
    w("- 检查日 = 每个标的自己日历上每月最后一个交易日（加密是当月最后一个 UTC 日）；信号次日开盘成交；"
      "成本（单边）美股/ETF 5bp，BTC/ETH 100bp，每次买卖都扣。")
    w(f"- 组合区间 {period}；现金 0 息（主口径）；前后两半以 {SPLIT} 分界。门槛：{o['hurdle_src']}。")
    w("- 等权买入持有（主基准）= 同样 6 个名额，信号永远\"持有\"（每个标的第一次可检查时买入 1/6，之后不卖）。")
    w("- 日线版对照 = `TREND_DESIGN.md` §3 的主设计（55 日突破 + SMA200 + 12 个月动量，吊灯止损），同一份缓存重新计算；"
      "\"日线版 6 标的\"用同样 1/6 名额，\"全池 28 标的\"用原报告的每笔风险 1% 仓位。")
    w("- 数据：" + "；".join(f"{t} {data[t][0]} {data[t][1][0].date} 起" for t in MONTHLY_UNIVERSE if t in data)
      + f"；缺失：{', '.join(o['missing']) or '无'}。\n")

    w("## 2. 预先登记的通过标准与判定\n")
    w("| 条件 | M1 | M2 |")
    w("|---|---|---|")
    for (name, ok1, x1), (_, ok2, x2) in zip(v1, v2):
        w(f"| {name} | {x1} {'✓' if ok1 else '✗'} | {x2} {'✓' if ok2 else '✗'} |")
    w(f"| **判定** | **{'通过' if passed(v1) else '未通过'}** | **{'通过' if passed(v2) else '未通过'}** |")
    w(f"\n等权买入持有（6 名额）：CAGR {pct(bench['cagr'])}，最大回撤 {pct(bench['mdd'])}。\n")

    w("## 3. 主要结果\n")
    w("| 版本 | 入场/年（警报） | 在场时间（每标的平均） | 至少一仓天数 | 平均投入 | CAGR | 最大回撤 | 最差年 | "
      "2006-2015 CAGR / 回撤 | 2016- CAGR / 回撤 | 来回震荡 |")
    w("|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|")
    rows = [("M1 月度 10 个月均线", m1), ("M2 月度 12 个月动量", m2),
            ("M1（现金按 T-bill）", o["m1_tbill"]), ("M2（现金按 T-bill）", o["m2_tbill"]),
            ("等权买入持有（6 名额）", bench), ("日线版 6 标的（1/6 名额）", d6)]
    for name, e in rows:
        wh = e["whipsaws"] if e["whipsaws"] is not None else "—"
        w(f"| {name} | {num(e['entries_py'])} | {pct(e['tim'], 0)} | {pct(e['any_pos'], 0)} | {pct(e['exposure'], 0)} | "
          f"{pct(e['cagr'])} | {pct(e['mdd'])} | {_yr(e['worst'])} | {_half(e, 'h1')} | {_half(e, 'h2')} | {wh} |")
    w(f"| 日线全池 28 标的（1% 风险） | {num(full['signals_py'])}（接 {num(full['m']['taken_per_year'])}） | {pct(full['tim'], 0)} | "
      f"{pct(full['any_pos'], 0)} | {pct(full['exposure'], 0)} | {pct(full['cagr'])} | {pct(full['mdd'])} | {_yr(full['worst'])} | "
      f"{_half(full, 'h1')} | {_half(full, 'h2')} | {full['whipsaws']} |")
    w(f"| SPY 买入持有 | — | 100% | 100% | 100% | {pct(spy['cagr'])} | {pct(spy['mdd'])} | {_yr(spy['worst'])} | "
      f"{_half(spy, 'h1')} | {_half(spy, 'h2')} | — |")
    w("\n入场 = 空仓变持有（按成交日在组合区间内计）。在场时间 = 每个标的持有天数 ÷ 它可检查以来的天数，再对标的取平均。"
      "来回震荡：月度规则 = 入场后下一个检查日就离场（持有不到 2 个月）；日线版 = 成交到离场不足 61 个自然日。"
      "全池版的\"入场/年\"是全部原始信号（组合实际接的在括号里）。\n")

    w("## 4. 按标的（主参数，扣成本，与该标的买入持有同一区间）\n")
    w("| 标的 | 首次检查 | M1 入场/年 | M1 在场 | M1 震荡 | M1 CAGR | M1 回撤 | M2 入场/年 | M2 在场 | M2 震荡 | "
      "M2 CAGR | M2 回撤 | 持有 CAGR | 持有回撤 | 日线版入场/年 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in MONTHLY_UNIVERSE:
        if t not in r1:
            continue
        a, b, d = r1[t].metrics, r2[t].metrics, d6["results"][t].metrics
        w(f"| {t} | {r1[t].eval_start} | {num(a['signals_per_year'])} | {pct(a['time_in_market'], 0)} | {whipsaws(r1[t].sim)} | "
          f"{pct(a['cagr'])} | {pct(a['mdd'])} | {num(b['signals_per_year'])} | {pct(b['time_in_market'], 0)} | "
          f"{whipsaws(r2[t].sim)} | {pct(b['cagr'])} | {pct(b['mdd'])} | {pct(a['bh_cagr'])} | {pct(a['bh_mdd'])} | "
          f"{num(d['signals_per_year'])} |")
    w("\n单标的是满仓进出、空仓 0 息；持有列按 M1 的首次检查日起算（M2 需要 13 个月线，起点晚 3 个月）。\n")

    w("## 5. 大行情捕获（同一批行情上对比）\n")
    w("大行情定义与日线版报告相同：收盘低点到高点 ≥20%、≤120 个交易日（加密 174 根日线）；从三种规则都能交易的日期"
      "（且不早于组合起点）开始找，所以三者比较的是同一批行情。参与 = 行情期间有持仓；中段 = 行情涨到一半（对数）那天在场；"
      "捕获 = 行情期间持仓日对数收益之和 ÷ 整段对数涨幅。\n")
    w("| 标的 | 行情段 | M1 参与 / 中段 / 捕获 | M2 参与 / 中段 / 捕获 | 日线版 参与 / 中段 / 捕获 |")
    w("|---|---:|---|---|---|")
    for t, dct in mv["per_asset"].items():
        w(f"| {t} | {dct['M1']['n']} | {_trip(dct['M1'])} | {_trip(dct['M2'])} | {_trip(dct['daily'])} |")
    w(f"| **合计** | {pooled['M1']['n']} | {_trip(pooled['M1'])} | {_trip(pooled['M2'])} | {_trip(pooled['daily'])} |")
    w(f"\n全池 28 标的日线版在它自己的 {full['moves']['n']} 段行情上：{_trip(full['moves'])}（与原报告同口径）。"
      "注意：捕获比例只看行情期间，不含行情结束后月度规则晚离场时回吐的部分——那部分体现在最大回撤里。\n")

    w("## 6. 逐年\n")
    w("| 年份 | M1 入场 | M2 入场 | M1 收益 | M2 收益 | 等权持有 | 日线版 6 标的 | SPY |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    e1, e2 = _by_year(r1), _by_year(r2)
    for y in sorted(m1["m"]["yearly"]):
        w(f"| {y} | {e1.get(y, 0)} | {e2.get(y, 0)} | {pct(m1['m']['yearly'][y])} | {pct(m2['m']['yearly'].get(y))} | "
          f"{pct(bench['m']['yearly'].get(y))} | {pct(d6['m']['yearly'].get(y))} | {pct(spy['yearly'].get(y))} |")
    w(f"\n{max(m1['m']['yearly'])} 年为年初至今。\n")

    w("## 7. 稳健性（事先登记的 12 组，同一标准判定）\n")
    w("| 参数 | 入场/年 | 在场时间 | CAGR | 最大回撤 | 最差年 | 2006-2015 CAGR | 2016- CAGR | 来回震荡 | 通过条件数 | 判定 |")
    w("|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|")
    for cfg, ev in o["grid"].items():
        v = o["grid_verdict"][cfg]
        w(f"| {cfg.label} | {num(ev['entries_py'])} | {pct(ev['tim'], 0)} | {pct(ev['cagr'])} | {pct(ev['mdd'])} | "
          f"{_yr(ev['worst'])} | {pct(ev['h1'].get('cagr'))} | {pct(ev['h2'].get('cagr'))} | {ev['whipsaws']} | "
          f"{sum(ok for _, ok, _ in v)}/5 | {'通过' if passed(v) else _fails(v)} |")
    oks = [dict((n, ok) for n, ok, _ in gv) for gv in o["grid_verdict"].values()]
    names = [n for n, _, _ in v1]
    fail_all = [n for n in names if not any(d[n] for d in oks)]
    pass_all = [n for n in names if all(d[n] for d in oks)]
    w(f"\n所有 {n_grid} 组都未过的条件：{'、'.join(fail_all) or '无'}；所有组都通过的条件：{'、'.join(pass_all) or '无'}。"
      "月中检查的基准仍用月末版等权持有。\n")

    w("## 8. 事后诊断：去掉加密（看完结果后加的，不参与判定）\n")
    w("用来区分\"规则本身\"与\"加密\"的影响：只用 SPY、QQQ、GLD、TLT，每个名额 1/4，其他完全相同，基准是这 4 个的等权持有。\n")
    w("| 版本 | 入场/年 | 在场时间 | 平均投入 | CAGR | 最大回撤 | 最差年 | 2006-2015 CAGR / 回撤 | 2016- CAGR / 回撤 | 按同一标准 |")
    w("|---|---:|---:|---:|---:|---:|---|---|---|---|")
    for name, key in (("M1（4 个 ETF）", "m1"), ("M2（4 个 ETF）", "m2"), ("等权持有（4 个 ETF）", "bench")):
        e = diag[key]
        vv = _fails(verdict(e, diag["bench"])) if key != "bench" else "—"
        w(f"| {name} | {num(e['entries_py'])} | {pct(e['tim'], 0)} | {pct(e['exposure'], 0)} | {pct(e['cagr'])} | "
          f"{pct(e['mdd'])} | {_yr(e['worst'])} | {_half(e, 'h1')} | {_half(e, 'h2')} | {vv} |")
    w("")

    w("## 9. 结论与建议\n")
    w(f"1. **按事先标准**：M1 {'通过' if passed(v1) else '未通过（' + _fails(v1) + '）'}；"
      f"M2 {'通过' if passed(v2) else '未通过（' + _fails(v2) + '）'}。未通过的不采用，也不接入每日运行。")
    w(f"2. **月度规则满足了\"少警报\"和\"吃中段\"**：每年 {num(min(m1['entries_py'], m2['entries_py']))}-"
      f"{num(max(m1['entries_py'], m2['entries_py']))} 次入场，大行情中段在场 "
      f"{pct(min(pooled['M1']['mid'], pooled['M2']['mid']), 0)}-{pct(max(pooled['M1']['mid'], pooled['M2']['mid']), 0)}，"
      f"日线版 {pct(pooled['daily']['mid'], 0)}。")
    w("3. **但它与\"大部分时间持币、不被套\"相矛盾**：长周期规则天然大部分时间在场，离场要等月线跌破均线或 12 个月收益转负；"
      "对一个月能跌 30%-50% 的加密，离场时往往已从高点回吐一半以上。")
    w("4. **下一步（未做，需所有人决定、另行预先登记）**：例如\"ETF 用月度规则 + 加密用日线吊灯止损离场\"，"
      "或给加密单独设较小的仓位上限并定期削减；也可以接受\"在场约七成\"的画像，只把月度规则当作传统资产的风险开关。")
    w("5. **注意事项**：回测不含税；加密早期（2016-2017）的百倍行情主导了组合收益，未来不可重复；yfinance 复权价含分红；"
      "月度规则两次检查之间没有止损，单月暴跌风险完全暴露。")
    return "\n".join(L) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    text = build()
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
