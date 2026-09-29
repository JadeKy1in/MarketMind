"""Render the trend backtest report (docs/TREND_BACKTEST_<date>.md) from cached data.

Every number in the report is computed here from the cached bars (SPEC L3).
Run:  python -m marketmind.trend.report --out docs/TREND_BACKTEST_2026-09-29.md
(fetch first with --fetch; the cache is the git-ignored cache/trend/).
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
from datetime import date
from pathlib import Path

from marketmind.gateway.price_history import is_crypto_ticker
from marketmind.trend.backtest import (
    PortfolioConfig, bh_series, cagr, max_drawdown, run_portfolio, run_universe, slice_metrics,
    tbill_hurdle_fn, trade_net_return, variants, yearly_returns,
)
from marketmind.trend.data import DEFAULT_CACHE, fetch_all, load_cached
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import compute_states, hurdle_from_tbill
from marketmind.trend.universe import TBILL_PROXY, TREND_UNIVERSE

PORTFOLIO_START = "2006-01-01"
SPLIT = "2016-01-01"
BIG_WIN = 0.20          # a closed trade netting >= +20% counts as "caught a big move"
NA = "n/a"


def pct(x, nd=1):
    return NA if x is None else f"{x * 100:.{nd}f}%"


def num(x, nd=1):
    return NA if x is None else f"{x:.{nd}f}"


def pooled(results) -> dict:
    rets, holds = [], []
    big_wins: dict[int, int] = {}
    for r in results.values():
        for tr in r.trades:
            if tr.closed:
                rets.append(trade_net_return(tr, r.cost))
                if rets[-1] >= BIG_WIN:
                    y = int(tr.signal_date[:4])
                    big_wins[y] = big_wins.get(y, 0) + 1
                holds.append((date.fromisoformat(tr.exit_date) - date.fromisoformat(tr.fill_date)).days)
    moves = [m for r in results.values() for m in r.moves]
    sig = sum(len(r.trades) for r in results.values())
    yrs = sum(r.years for r in results.values())
    return {
        "signals": sig, "closed": len(rets),
        "hit_rate": sum(x > 0 for x in rets) / len(rets) if rets else None,
        "avg_trade": statistics.fmean(rets) if rets else None,
        "median_trade": statistics.median(rets) if rets else None,
        "worst_trade": min(rets) if rets else None,
        "big_wins": big_wins,
        "avg_hold": statistics.fmean(holds) if holds else None,
        "moves": len(moves),
        "participation": sum(m["participated"] for m in moves) / len(moves) if moves else None,
        "in_at_mid": sum(m["in_at_mid"] for m in moves) / len(moves) if moves else None,
        "capture": statistics.fmean(m["capture"] for m in moves) if moves else None,
        "signals_per_instr_year": sig / yrs if yrs else None,
        "tim": statistics.fmean(r.metrics["time_in_market"] for r in results.values()
                                if "time_in_market" in r.metrics),
        "beat_bh_mdd": sum(r.metrics["mdd"] > r.metrics["bh_mdd"] for r in results.values()
                           if "mdd" in r.metrics),
        "beat_bh_cagr": sum(r.metrics["cagr"] > r.metrics["bh_cagr"] for r in results.values()
                            if "cagr" in r.metrics),
        "n": sum(1 for r in results.values() if "cagr" in r.metrics),
    }


def build(cache_dir: Path = DEFAULT_CACHE, as_of: str | None = None) -> str:
    data = {}
    missing = []
    for t in TREND_UNIVERSE:
        got = load_cached(t, cache_dir)
        if got is None:
            missing.append(t)
        else:
            data[t] = got
    irx = load_cached(TBILL_PROXY, cache_dir)
    irx_bars = irx[1] if irx else None
    hurdle, hurdle_src = tbill_hurdle_fn(irx_bars)
    cfg, pcfg = TrendConfig(), PortfolioConfig()
    res = run_universe(data, cfg, hurdle)
    port = run_portfolio(res, pcfg, start=PORTFOLIO_START)
    port_cash = run_portfolio(res, pcfg, start=PORTFOLIO_START,
                              cash_rate=_irx_rate(irx_bars) if irx_bars else None)
    pm, pmc = port.metrics, port_cash.metrics
    spy = bh_series(data["SPY"][1], port.dates)
    spy_cagr = cagr(spy[0], spy[-1], port.dates[0], port.dates[-1])
    spy_mdd = max_drawdown(spy)
    spy_yr = yearly_returns(port.dates, spy)
    agg = pooled(res)
    var_rows = []
    for name, vcfg in variants(cfg):
        vres = res if vcfg == cfg else run_universe(data, vcfg, hurdle)
        vp = run_portfolio(vres, pcfg, start=PORTFOLIO_START)
        va = pooled(vres)
        h1 = slice_metrics(vp.dates, vp.equity, PORTFOLIO_START, SPLIT)
        h2 = slice_metrics(vp.dates, vp.equity, SPLIT, "9999")
        var_rows.append((name, vcfg == cfg, vp.metrics, va, h1, h2))
    # today's states on the cached (complete) bars
    last_bar = max(b[-1].date for _, b in data.values())
    today_h = hurdle_from_tbill(irx_bars) if irx_bars else None
    states = compute_states({t: b for t, (_, b) in data.items()}, today_h or 0.0, cfg,
                            hurdle_source=(f"{TBILL_PROXY} 252d mean" if today_h is not None
                                           else "unavailable -> 0"),
                            today=date.fromisoformat(as_of or last_bar),
                            sources={t: s for t, (s, _) in data.items()})
    taken_ids = {id(p["trade"]) for p in port.taken}
    L: list[str] = []
    w = L.append
    years_list = sorted(set(pm["yearly"]) | set(pm["signals_by_year"]))
    full_years = [y for y in years_list if y < int(pm["end"][:4])]
    avg_sig = statistics.fmean(pm["signals_by_year"].get(y, 0) for y in full_years)
    avg_taken = statistics.fmean(pm["taken_by_year"].get(y, 0) for y in full_years)
    h1 = slice_metrics(port.dates, port.equity, PORTFOLIO_START, SPLIT)
    h2 = slice_metrics(port.dates, port.equity, SPLIT, "9999")
    avg_big = statistics.fmean(agg["big_wins"].get(y, 0) for y in full_years)
    skip_why: dict[str, int] = {}
    for x in port.skipped:
        skip_why[x["why"]] = skip_why.get(x["why"], 0) + 1
    cagrs = [r[2]["cagr"] for r in var_rows]
    mdds = [r[2]["mdd"] for r in var_rows]

    w(f"# 趋势状态机回测报告（{as_of or date.today().isoformat()}）\n")
    w("> 纯代码生成（`python -m marketmind.trend.report`），所有数字由 `marketmind/trend/` 从缓存行情计算（SPEC L3）。"
      "规则见 `docs/TREND_DESIGN.md`。**尚未接入警报**，等所有人审阅。\n")
    w("## 给所有人的摘要\n")
    w(f"- **区间**：组合 {pm['start']} 至 {pm['end']}（{pm['years']:.1f} 年），{len(data)} 个标的；上市晚的标的（META、SOL、ETH、BTC 等）有数据后才加入。")
    w(f"- **信号多少**：整个池子平均每年 {avg_sig:.0f} 个入场信号（单个标的平均每年 {agg['signals_per_instr_year']:.1f} 个）；"
      f"按 3 万美元、每笔风险 1%、最多 6 个仓位的规则，每年实际接 {avg_taken:.0f} 笔。"
      f"信号远多于\"一年 3-4 波\"，所以接警报时还需要再筛（见文末建议）。")
    w(f"- **组合收益与回撤**：CAGR {pct(pm['cagr'])}，最大回撤 {pct(pm['mdd'])}，最差年份 {pm['worst_year'][0]}（{pct(pm['worst_year'][1])}）；"
      f"同期 SPY 买入持有 CAGR {pct(spy_cagr)}，最大回撤 {pct(spy_mdd)}。"
      f"闲置现金按 T-bill 计息时 CAGR {pct(pmc['cagr'])}、最大回撤 {pct(pmc['mdd'])}。")
    w(f"- **单笔交易**：{agg['closed']} 笔已平仓，胜率 {pct(agg['hit_rate'])}，平均 {pct(agg['avg_trade'])}，中位数 {pct(agg['median_trade'])}，平均持有 {num(agg['avg_hold'], 0)} 天。"
      f"最差一笔 {pct(agg['worst_trade'])}（跳空穿过止损）。典型的趋势跟踪形态：多数小亏，少数大赚。")
    w(f"- **\"大赚\"的交易**：全池每年平均 {avg_big:.1f} 笔已平仓交易净赚 ≥20%（按信号年份计，{full_years[0]}-{full_years[-1]}），"
      f"和\"一年 3-4 波\"的量级接近，但事先无法区分哪一笔会成为大赚的那笔，所以只能每个信号都按小风险接。")
    w(f"- **大行情捕获**（低点到高点 ≥20%、≤120 个交易日）：共 {agg['moves']} 段，系统参与了 {pct(agg['participation'], 0)}，"
      f"行情走到一半时在场的占 {pct(agg['in_at_mid'], 0)}，平均吃到整段涨幅（对数）的 {pct(agg['capture'], 0)}。")
    w(f"- **单标的对比买入持有**：{agg['n']} 个标的中，{agg['beat_bh_mdd']} 个最大回撤更小，{agg['beat_bh_cagr']} 个 CAGR 更高；平均在场时间 {pct(agg['tim'], 0)}。")
    w(f"- **稳健性**：{len(var_rows)} 组相邻参数的组合 CAGR 在 {pct(min(cagrs))} 至 {pct(max(cagrs))}，最大回撤在 {pct(min(mdds))} 至 {pct(max(mdds))}；"
      f"前后两半（{PORTFOLIO_START[:4]}-2015 / 2016-{pm['end'][:4]}）主参数 CAGR 分别 {pct(h1.get('cagr'))} / {pct(h2.get('cagr'))}。")
    w("- **注意**：回测不含税；大型股是今天的赢家（幸存者偏差）；加密早期数据来自交易所（BTC/ETH 用 Coinbase 美元对，SOL 用 Binance USDT 对）。详见文末。\n")

    w("## 1. 设置\n")
    w(f"- 规则参数：`{cfg}`")
    w(f"- 组合参数：`{pcfg}`；同一天多个信号按 12 个月超额收益从高到低；满仓时跳过。")
    w(f"- 12 个月门槛：{hurdle_src}（按日期取当时已知的值，无前视）。")
    w("- 成本（单边，来自 `ledger.settlement.cost_bps`）：美股/ETF 5bp；BTC/ETH 100bp；SOL 125bp；每笔来回扣两次；成交价 = 信号次日开盘。")
    w(f"- 大行情：收盘低点到高点 ≥20%，且 ≤120 个交易日（加密 ≤174 根日线，同样约 6 个自然月）；只统计规则热身期之后的行情。\n")

    w("## 2. 数据来源（实际使用）\n")
    w("| 标的 | 来源 | 首根 | 末根 | 完整日线数 | 可发信号起始日 |")
    w("|---|---|---|---|---:|---|")
    for t, r in res.items():
        w(f"| {t} | {r.source} | {r.first_date} | {r.last_date} | {len(r.sim.bars)} | {r.eval_start or NA} |")
    if irx_bars:
        w(f"| {TBILL_PROXY}（门槛） | {irx[0]} | {irx_bars[0].date} | {irx_bars[-1].date} | {len(irx_bars)} | — |")
    for t in missing:
        w(f"| {t} | **数据不可用** | — | — | 0 | — |")
    w("")

    w("## 3. 单标的结果（满仓进出，扣成本，同一区间对比买入持有）\n")
    w("| 标的 | 年数 | 信号 | 信号/年 | 胜率 | 平均 | 中位 | 平均持有天 | 在场 | CAGR | 持有CAGR | 最大回撤 | 持有回撤 | 大行情段 | 参与 | 中段在场 | 捕获 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t, r in res.items():
        m = r.metrics
        if "cagr" not in m:
            w(f"| {t} | — | 数据不足：{m.get('unavailable')} |" + " |" * 15)
            continue
        w(f"| {t} | {r.years:.1f} | {m['signals']} | {num(m['signals_per_year'])} | {pct(m['hit_rate'], 0)} | "
          f"{pct(m['avg_trade'])} | {pct(m['median_trade'])} | {num(m['avg_hold_days'], 0)} | {pct(m['time_in_market'], 0)} | "
          f"{pct(m['cagr'])} | {pct(m['bh_cagr'])} | {pct(m['mdd'], 0)} | {pct(m['bh_mdd'], 0)} | {m['moves']} | "
          f"{pct(m['participation'], 0)} | {pct(m['in_at_mid'], 0)} | {pct(m['capture'], 0)} |")
    w(f"| **合计/汇总** | | {agg['signals']} | {num(agg['signals_per_instr_year'])} | {pct(agg['hit_rate'], 0)} | "
      f"{pct(agg['avg_trade'])} | {pct(agg['median_trade'])} | {num(agg['avg_hold'], 0)} | {pct(agg['tim'], 0)} | | | | | "
      f"{agg['moves']} | {pct(agg['participation'], 0)} | {pct(agg['in_at_mid'], 0)} | {pct(agg['capture'], 0)} |")
    w("\n胜率、平均、中位、持有天数只算已平仓交易；汇总行是全部已平仓交易合并计算（不是各标的的平均）。"
      "\"捕获\"= 行情期间持仓日的对数收益之和 ÷ 整段对数涨幅（可为负：在场但入场后又被止损）。\n")

    w("## 4. 组合层面（$30,000，每笔风险 1%，单仓 ≤25%，最多 6 仓）\n")
    w("| 指标 | 趋势组合（现金 0 息） | 趋势组合（现金按 T-bill） | SPY 买入持有 |")
    w("|---|---:|---:|---:|")
    w(f"| 区间 | {pm['start']} 至 {pm['end']} | 同左 | 同左 |")
    w(f"| 期末权益 | ${pm['final']:,.0f} | ${pmc['final']:,.0f} | ${pcfg.capital * spy[-1] / spy[0]:,.0f} |")
    w(f"| CAGR | {pct(pm['cagr'])} | {pct(pmc['cagr'])} | {pct(spy_cagr)} |")
    w(f"| 最大回撤 | {pct(pm['mdd'])} | {pct(pmc['mdd'])} | {pct(spy_mdd)} |")
    w(f"| 最差年份 | {pm['worst_year'][0]}（{pct(pm['worst_year'][1])}） | {pmc['worst_year'][0]}（{pct(pmc['worst_year'][1])}） | "
      f"{min(spy_yr.items(), key=lambda kv: kv[1])[0]}（{pct(min(spy_yr.values()))}） |")
    w(f"| 接的交易 | {pm['taken']}（{num(pm['taken_per_year'])}/年），胜率 {pct(pm['hit_rate'], 0)} | 同左 | — |")
    w(f"| 平均单仓权重（开仓时） | {pct(pm['avg_weight'])} | | |")
    w(f"| 平均投入比例 / 完全空仓天数占比 | {pct(pm.get('avg_exposure'), 0)} / {pct(pm.get('flat_share'), 0)} | | |")
    w(f"| 跳过的信号 | {len(port.skipped)}（" + "，".join(f"{k} {v}" for k, v in sorted(skip_why.items())) + "） | | |")
    w(f"| {PORTFOLIO_START[:4]}-2015 CAGR / 回撤 | {pct(h1.get('cagr'))} / {pct(h1.get('mdd'))} | | |")
    w(f"| 2016-{pm['end'][:4]} CAGR / 回撤 | {pct(h2.get('cagr'))} / {pct(h2.get('mdd'))} | | |")
    w("")
    w("| 年份 | 全池信号 | 组合接的 | 全池净赚≥20%的交易 | 组合收益 | 组合收益（T-bill 现金） | SPY |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for y in years_list:
        w(f"| {y} | {pm['signals_by_year'].get(y, 0)} | {pm['taken_by_year'].get(y, 0)} | {agg['big_wins'].get(y, 0)} | "
          f"{pct(pm['yearly'].get(y))} | {pct(pmc['yearly'].get(y))} | {pct(spy_yr.get(y))} |")
    w(f"\n{pm['end'][:4]} 年为年初至今。\n")

    w("## 5. 最近 3 年的信号\n")
    cutoff = f"{int(last_bar[:4]) - 3}{last_bar[4:]}"
    rows = sorted(((tr, r) for r in res.values() for tr in r.trades if tr.signal_date >= cutoff),
                  key=lambda x: (x[0].signal_date, x[0].ticker))
    w(f"信号日 ≥ {cutoff}，共 {len(rows)} 个。收益扣成本；未平仓的按 {last_bar} 前最后收盘估值。\n")
    w("| 信号日 | 标的 | 信号收盘 | 初始止损 | 买入日/价 | 离场信号日 | 卖出日/价 | 净收益 | 持有天 | 状态 | 组合是否接 |")
    w("|---|---|---:|---:|---|---|---|---:|---:|---|---|")
    for tr, r in rows:
        mark = r.sim.bars[-1].close
        ret = trade_net_return(tr, r.cost, None if tr.closed else mark)
        end = tr.exit_date or r.sim.bars[-1].date
        held = (date.fromisoformat(end) - date.fromisoformat(tr.fill_date)).days if tr.fill_date else None
        status = "已平仓" if tr.closed else ("待卖出" if tr.exit_signal_date else ("待买入" if tr.fill_date is None else "持有中"))
        w(f"| {tr.signal_date} | {tr.ticker} | {tr.signal_close:.2f} | {tr.initial_stop:.2f} | "
          f"{tr.fill_date or '—'} / {num(tr.fill_price, 2)} | {tr.exit_signal_date or '—'} | "
          f"{tr.exit_date or '—'} / {num(tr.exit_price, 2) if tr.exit_price else '—'} | {pct(ret)} | "
          f"{held if held is not None else '—'} | {status} | {'是' if id(tr) in taken_ids else '否'} |")
    w("")

    w("## 6. 稳健性（相邻参数 + 前后两半样本）\n")
    w("所有组合用同一套组合规则。规则没有在样本上优化过，前后两半都算样本外检查。\n")
    w(f"| 参数 | 组合 CAGR | 最大回撤 | 最差年 | 平均投入 | 开仓平均权重 | 接的/年 | 全池信号/标的/年 | 胜率 | 中位交易 | 大行情参与 | 中段在场 | 捕获 | {PORTFOLIO_START[:4]}-2015 CAGR | 2016- CAGR |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, is_base, vm, va, vh1, vh2 in var_rows:
        label = f"**{name}（主）**" if is_base else name
        w(f"| {label} | {pct(vm['cagr'])} | {pct(vm['mdd'])} | {vm['worst_year'][0]} {pct(vm['worst_year'][1])} | "
          f"{pct(vm.get('avg_exposure'), 0)} | {pct(vm['avg_weight'], 0)} | {num(vm['taken_per_year'])} | {num(va['signals_per_instr_year'])} | {pct(va['hit_rate'], 0)} | "
          f"{pct(va['median_trade'])} | {pct(va['participation'], 0)} | {pct(va['in_at_mid'], 0)} | "
          f"{pct(va['capture'], 0)} | {pct(vh1.get('cagr'))} | {pct(vh2.get('cagr'))} |")
    w("")

    w(f"## 7. 当前状态（最后一根完整日线，门槛 {pct(today_h, 2) if today_h is not None else '不可用→0'}）\n")
    w("由 `trend.state.compute_states` 在缓存数据上计算（与每日函数同一代码）。缓存取数时间见第 2 节末根日期。\n")
    w("| 标的 | 状态 | 事件 | 日期 | 收盘 | 12月收益 | SMA200 | 55日高 | ATR20 | 止损位 | 入场信号日 | 说明 |")
    w("|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    order = {"TREND": 0, "EXIT": 1, "WATCH": 2, "CASH": 3, "UNAVAILABLE": 4}
    for t, s in sorted(states.items(), key=lambda kv: (order.get(kv[1].state, 9), kv[0])):
        w(f"| {t} | {s.state} | {s.event or ''} | {s.as_of or '—'} | {num(s.close, 2)} | {pct(s.ret_12m)} | "
          f"{num(s.sma200, 2)} | {num(s.high_55, 2)} | {num(s.atr, 2)} | {num(s.stop_level, 2)} | "
          f"{s.entry_signal_date or ''} | {s.reason or ''} |")
    w("")

    w("## 8. 注意事项\n")
    w("- **幸存者偏差**：标的池是今天选的。NVDA、AAPL、MSFT、AMZN、META 是事后已知的赢家，单标的结果和组合结果都因此偏乐观；SMH、XLK 同理。")
    w("- **ETF 上市日**：SLV（2006-04）、USO（2006-04）、UNG（2007-04）、META（2012-05）只从上市后开始；规则需要约 1 年热身，所以各标的可发信号的起始日不同（第 2 节）。")
    w("- **加密数据**：BTC、ETH 用 Coinbase 美元对（最早分别 2015-07、2016-05）；SOL 用 Binance 的 SOLUSDT（USDT 当作美元），Coinbase 的 SOL 历史更短。早期加密市场流动性差，成本假设（100/125bp）可能偏低。")
    w("- **复权**：美股/ETF 用 yfinance 复权价（拆股 + 分红），所以买入持有含分红再投资；开盘价同样按复权因子调整。")
    w("- **UNG、USO**：期货展期损耗，买入持有长期大幅亏损；这里保留是为了检验规则能否避开。")
    w("- **不含税**：短线交易在美国按普通所得税计税，实际到手收益会低于表中数字。")
    w("- **现金收益**：主结果假设现金 0 利息；另一列按 ^IRX 计息，只作参考。")
    w("- **成交**：离场只看收盘价是否跌破止损，次日开盘成交；跳空低开会让实际亏损大于 1% 风险预算，这已如实计入。碎股按可成交处理（Robinhood 支持碎股）。")
    w("- **组合跳过的信号**：满仓时的信号不会稍后补进，这会让组合结果依赖同日排序规则。")
    w("- **重叠**：池子里 SPY/QQQ/DIA/XLK/SMH 与大型股高度相关，同一波行情会同时触发多个信号，组合实际分散度低于 6 个仓位看上去的样子。")
    w("")
    base_v = next(r for r in var_rows if r[1])
    sma_v = next(r for r in var_rows if "SMA100" in r[0])
    w("## 9. 接入警报的建议（待所有人确认，未实现）\n")
    w(f"1. **先当\"代码确认趋势\"这一条件用，不单独发警报**（SPEC §10 三条件之一）。原始信号全池每年约 {avg_sig:.0f} 个、单笔胜率 {pct(agg['hit_rate'], 0)}，"
      f"单独推送会太频繁；状态为 TREND 才算\"趋势已确认\"，WATCH 只在仪表盘显示（附到突破价的距离）。")
    w(f"2. **参数保持主规则（55 日突破 / 3×ATR 吊灯止损）**：相邻参数的组合 CAGR 在 {pct(min(cagrs))}-{pct(max(cagrs))}，"
      f"4×ATR 三组偏弱（推论：同样 1% 风险下止损越宽、仓位越小，见稳健性表的平均权重），2.5-3×ATR 与 40-80 日突破之间差别不大，不是刀刃上的结果。"
      f"100 日均线离场的交易更少（每年接 {num(sma_v[2]['taken_per_year'])} 笔）、捕获更高（{pct(sma_v[3]['capture'], 0)}），"
      f"但最大回撤 {pct(sma_v[2]['mdd'])} 比主规则的 {pct(base_v[2]['mdd'])} 深，和\"不被套\"冲突，不建议换。")
    w(f"3. **仓位与\"大部分时间持币\"**：每笔风险 1%、单仓上限 25% 时，开仓平均权重 {pct(pm['avg_weight'])}，"
      f"组合平均投入 {pct(pm.get('avg_exposure'), 0)}，完全空仓的天数只占 {pct(pm.get('flat_share'), 0)}；"
      f"6 仓上限和现金都经常用满（跳过 {skip_why.get('max positions', 0)} + {skip_why.get('no cash', 0)} 次）。"
      f"也就是说，按全池每个信号都接，账户**并不是**大部分时间持币；要符合所有人的画像，需要第 4 条的筛选或更小的单笔风险。"
      f"警报里应给出代码算的止损价和按 1% 风险换算的建议金额。")
    w("4. **如果所有人想要更少、更集中的信号**，可以考虑（均**未回测**，需要单独回测后再用）：同一相关组（SPY/QQQ/DIA/XLK/SMH/大型股）只取最强一个；"
      "只在 12 个月超额收益排名前若干的标的上接信号。")
    w("5. **每日运行**：`trend.state.today_states()` 已可直接调用（5 年重放、只用完整日线、取不到数据标 UNAVAILABLE）；接入时由编排层每天调用一次并写入账本（L5），这一步留到所有人确认后再做。")
    return "\n".join(L) + "\n"


def _irx_rate(irx_bars):
    """Annual cash rate on a date: the latest ^IRX close on or before it, / 100."""
    import bisect
    dates = [b.date for b in irx_bars]

    def rate(d: str) -> float:
        i = bisect.bisect_right(dates, d) - 1
        return irx_bars[i].close / 100.0 if i >= 0 else 0.0
    return rate


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="fetch missing instruments into the cache")
    ap.add_argument("--refresh", action="store_true", help="re-fetch every instrument")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args(argv)
    if a.fetch or a.refresh:
        for k, v in asyncio.run(fetch_all(list(TREND_UNIVERSE) + [TBILL_PROXY],
                                          refresh=a.refresh)).items():
            print(k, v)
    text = build(as_of=a.as_of)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
