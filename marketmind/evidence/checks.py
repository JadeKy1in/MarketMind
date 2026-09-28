"""Deterministic checks: claim type + primary data -> observed direction (docs/S5_DESIGN.md).

Each check returns an Observation: the direction the data shows (up | down | flat),
or None when the data is unavailable. Verdicts compare that with the direction
the news asserted. No LLM here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

UP, DOWN, FLAT = "up", "down", "flat"
SUPPORT, CONTRADICT, UNVERIFIABLE = "support", "contradict", "unverifiable"
VERDICT_CN = {SUPPORT: "支持", CONTRADICT: "矛盾（背离）", UNVERIFIABLE: "无法验证"}

REVENUE_BAND = 0.005
# News about "results" usually concerns a quarter SEC has not received yet; if the
# latest XBRL quarter was filed longer ago than this, the claim cannot be checked.
REVENUE_FRESH_DAYS = 30
SHORT_INTEREST_BAND = 0.05
SHORT_VOLUME_BAND = 0.10
SOFR_BAND_PCT = 0.05          # 5 bp, in percentage points
SOFR_LOOKBACK = 20
AUCTION_BAND = 0.03
AUCTION_DAYS = 7
AUCTION_PRIOR = 6
STABLE_BAND = 0.01
STABLE_DAYS = 30
# SOMA total over ~4 weeks. 0.1% of ~$6.4T is ~$6B (~$80B a year): week-to-week
# noise is ~$1-3B, while QT (~$40-95B a month) or reserve-management bill buying
# (~$10B a month, 2026-09) clears it.
SOMA_BAND = 0.001
SOMA_LOOKBACK_DAYS = 28

# type -> (needs ticker, ledger proxy (None = the claim's own ticker), ledger direction when data is up)
CLAIM_TYPES: dict[str, tuple[bool, str | None, str | None]] = {
    "revenue_growth": (True, None, "long"),
    "short_interest": (True, None, "short"),
    "short_selling_pressure": (True, None, "short"),
    "filing_red_flag": (True, None, None),
    "funding_rates": (False, "TLT", "short"),
    "treasury_demand": (False, "TLT", "long"),
    "stablecoin_supply": (False, "BTC-USD", "long"),
    "fed_liquidity": (False, "TLT", "long"),
    "etf_flows": (False, None, None),
}


@dataclass
class Observation:
    direction: str | None          # up | down | flat | None (unavailable)
    summary: str                   # human-readable evidence line (Chinese)
    data: dict = field(default_factory=dict)


def _band(change: float, band: float) -> str:
    return UP if change > band else DOWN if change < -band else FLAT


def verdict(asserted: str, observed: str | None) -> str:
    if observed is None:
        return UNVERIFIABLE
    return SUPPORT if observed == asserted else CONTRADICT


async def observe(claim_type: str, ticker: str | None, data) -> Observation:
    fn = _CHECKS.get(claim_type)
    if fn is None:
        return Observation(None, "该类型没有一手数据核对")
    try:
        return await fn(ticker, data)
    except Exception as e:     # a broken source must not take the day down
        return Observation(None, f"核对失败：{type(e).__name__}")


async def _revenue(ticker, data) -> Observation:
    r = await data.revenue_yoy(ticker)
    if r is None:
        return Observation(None, f"SEC XBRL 没有 {ticker} 的季度营收")
    today = getattr(data, "today", None)
    if today is not None and r.filed:
        from datetime import date
        age = (today - date.fromisoformat(r.filed)).days
        if age > REVENUE_FRESH_DAYS:
            return Observation(None, f"SEC 最新季度营收（截至 {r.period_end}）报送于 {r.filed}，"
                                     f"已过 {age} 天；新闻很可能指更新的季度，无法核对",
                               {"period_end": r.period_end, "filed": r.filed})
    return Observation(_band(r.yoy, REVENUE_BAND),
                       f"SEC XBRL {r.concept}：{r.period_end} 季度营收 {r.value:,.0f}，"
                       f"去年同期（{r.prior_end}）{r.prior_value:,.0f}，同比 {r.yoy:+.1%}",
                       {"period_end": r.period_end, "value": r.value,
                        "prior_end": r.prior_end, "prior_value": r.prior_value, "yoy": r.yoy})


async def _short_interest(ticker, data) -> Observation:
    si = await data.short_interest(ticker)
    if si is None or si.change_pct is None:
        return Observation(None, f"Nasdaq 没有 {ticker} 的空头持仓（可能是纽交所上市）")
    change = si.change_pct / 100
    return Observation(_band(change, SHORT_INTEREST_BAND),
                       f"Nasdaq 空头持仓 {si.settlement_date}：{si.shares_short:,.0f} 股，"
                       f"较 {si.previous_date} {change:+.1%}",
                       {"date": si.settlement_date, "shares": si.shares_short, "change": change})


async def _short_volume(ticker, data) -> Observation:
    rows = await data.short_volume_ratios(ticker, 5)
    if len(rows) < 3:
        return Observation(None, f"FINRA RegSHO 没有足够的 {ticker} 卖空成交数据")
    last_day, last = rows[-1]
    base = mean(v for _, v in rows[:-1])
    change = last / base - 1 if base > 0 else 0.0
    return Observation(_band(change, SHORT_VOLUME_BAND),
                       f"FINRA RegSHO {last_day} 卖空占比 {last:.1%}，前 {len(rows) - 1} 日均值 "
                       f"{base:.1%}（{change:+.0%}）",
                       {"date": last_day, "ratio": last, "baseline": base, "change": change})


async def _funding(_ticker, data) -> Observation:
    rows = await data.sofr()
    if len(rows) < 2:
        return Observation(None, "纽约联储 SOFR 数据不可用")
    past = rows[max(0, len(rows) - 1 - SOFR_LOOKBACK)]
    last = rows[-1]
    diff = last[1] - past[1]
    return Observation(_band(diff, SOFR_BAND_PCT),
                       f"纽约联储 SOFR {last[0]} {last[1]:.2f}%，{past[0]} {past[1]:.2f}%"
                       f"（{diff * 100:+.0f}bp）",
                       {"last": last, "past": past, "diff_pct": diff})


async def _treasury(_ticker, data) -> Observation:
    auctions = await data.auctions()
    if not auctions:
        return Observation(None, "FiscalData 国债拍卖数据不可用")
    from datetime import date, timedelta
    today = getattr(data, "today", None) or date.fromisoformat(auctions[0]["date"])
    cutoff = (today - timedelta(days=AUCTION_DAYS)).isoformat()
    ratios, lines = [], []
    for a in auctions:
        if a["date"] <= cutoff:
            break
        if a["date"] > today.isoformat():
            continue
        prior = [b["bid_to_cover"] for b in auctions
                 if b["date"] < a["date"] and b["term"] == a["term"] and b["type"] == a["type"]
                 ][:AUCTION_PRIOR]
        if len(prior) < 3:
            continue
        rel = a["bid_to_cover"] / mean(prior)
        ratios.append(rel)
        lines.append(f"{a['date']} {a['term']} {a['type']} {a['bid_to_cover']:.2f}（前 "
                     f"{len(prior)} 次均值 {mean(prior):.2f}）")
    if not ratios:
        return Observation(None, "近 7 天没有可比较的国债拍卖")
    avg = mean(ratios)
    return Observation(_band(avg - 1, AUCTION_BAND),
                       f"近 7 天 {len(ratios)} 场拍卖认购倍数为同期限均值的 {avg:.2f} 倍：" + "；".join(lines[:4]),
                       {"relative_bid_to_cover": avg, "auctions": len(ratios)})


async def _stablecoins(_ticker, data) -> Observation:
    rows = await data.stablecoin_supply()
    if len(rows) < STABLE_DAYS + 1:
        return Observation(None, "DefiLlama 稳定币数据不可用")
    last, past = rows[-1], rows[-1 - STABLE_DAYS]
    change = last[1] / past[1] - 1
    return Observation(_band(change, STABLE_BAND),
                       f"DefiLlama 稳定币总供应 {last[0]} ${last[1] / 1e9:,.1f}B，"
                       f"{STABLE_DAYS} 天前 ${past[1] / 1e9:,.1f}B（{change:+.1%}）",
                       {"last": last, "past": past, "change": change})


async def _fed_liquidity(_ticker, data) -> Observation:
    rows = await data.soma()
    if len(rows) < 2:
        return Observation(None, "纽约联储 SOMA 持仓数据不可用")
    from datetime import date, timedelta
    last = rows[-1]
    cutoff = (date.fromisoformat(last[0]) - timedelta(days=SOMA_LOOKBACK_DAYS)).isoformat()
    prior = [r for r in rows if r[0] <= cutoff]
    if not prior:
        return Observation(None, "纽约联储 SOMA 持仓历史不足 4 周")
    past = prior[-1]
    change = last[1] / past[1] - 1
    return Observation(_band(change, SOMA_BAND),
                       f"纽约联储 SOMA 持仓 {last[0]} ${last[1] / 1e9:,.1f}B，{past[0]} "
                       f"${past[1] / 1e9:,.1f}B（{(last[1] - past[1]) / 1e9:+,.1f}B，{change:+.2%}）",
                       {"last": last, "past": past, "change": change})


async def _red_flags(ticker, data) -> Observation:
    hits = await data.red_flag_filings(ticker)
    if hits is None:
        return Observation(None, f"SEC 全文检索不可用或找不到 {ticker}")
    if not hits:
        return Observation(None, f"SEC 近 90 天没有 {ticker} 的红旗用语申报（没查到不等于不存在）")
    lines = [f"{h.get('filed')} {h.get('form')}「{h.get('phrase')}」" for h in hits[:4]]
    return Observation(UP, f"SEC 近 90 天 {len(hits)} 份申报含红旗用语：" + "；".join(lines),
                       {"hits": hits[:10]})


async def _etf_flows(_ticker, _data) -> Observation:
    return Observation(None, "ETF 资金流没有免费的一手数据源")


_CHECKS = {
    "revenue_growth": _revenue, "short_interest": _short_interest,
    "short_selling_pressure": _short_volume, "funding_rates": _funding,
    "treasury_demand": _treasury, "stablecoin_supply": _stablecoins,
    "filing_red_flag": _red_flags, "etf_flows": _etf_flows,
    "fed_liquidity": _fed_liquidity,
}


def ledger_bet(claim_type: str, ticker: str | None, asserted: str,
               observed: str) -> tuple[str, str] | None:
    """(ticker, direction) betting that the data is right and the narrative wrong."""
    _, proxy, dir_if_up = CLAIM_TYPES.get(claim_type, (False, None, None))
    target = proxy or ticker
    if not target or dir_if_up is None:
        return None
    opposite = "short" if dir_if_up == "long" else "long"
    side = observed if observed in (UP, DOWN) else (DOWN if asserted == UP else UP)
    return target, dir_if_up if side == UP else opposite
