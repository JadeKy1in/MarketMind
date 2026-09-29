"""Paper-to-live gap for promotion candidates (docs/S7_DESIGN.md §四). Reporting only:
no ladder gate reads the result (wiring it into gates is an owner decision).

A conservative "live-expected" version of each shadow's record: the same matured
settled trades the ladder evaluates, with extra execution costs ON TOP of the ledger's
own costs (settlement.cost_bps, already in net_return):

    per side = SLIP_ATR_FRACTION * ATR%_entry * liquidity multiplier
             + IMPACT_Y * sigma_20d * sqrt(position / ADV_20d)        (square-root impact)
    live net return = ledger net return - 2 * per side

- ATR% = ATR14 / last close before entry: the settlement review's `atr_pct` when
  present, else computed the same way from the bars (close-only bars skipped).
- ADV_20d = mean(close * volume) of the 20 bars before entry; sigma_20d = standard
  deviation of the 20 close-to-close returns before entry.
- Liquidity multiplier by ADV_20d (a stand-in for market cap, which we do not have):
  >= $50M "liquid" x1, $5M-50M "mid" x2, < $5M "illiquid" x4. No volume data: FX
  pairs (deep markets, volume not reported) x1; anything else x4 ("unknown").
  Futures (volume in contracts, multiplier unknown) and non-US listings (volume value
  in local currency) have no dollar ADV: x2 ("future" / "non_usd"), no impact term
  and no capacity check (`capacity.priced` counts the trades that were checked).
- No ATR at all (no bars): UNKNOWN_SIDE_COST per side, counted in `unknown_cost`.
- Capacity: a trade breaches when its position exceeds CAPACITY_ADV_SHARE (1%) of
  ADV_20d; `capacity_usd_p10` is the 10th percentile over trades of 1% of ADV_20d,
  i.e. the position size at which ~10% of the shadow's trades would breach.
- live_ready (diagnostic flag): enough sample (>= LIVE_MIN_TRADES matured trades on
  >= LIVE_MIN_DAYS decision days), mean live excess return over the domain benchmark
  > 0 (the ladder's "beats domain ETF" measure after the haircut), capacity breaches
  <= CAPACITY_MAX_BREACH_SHARE of trades, and <= MAX_UNKNOWN_SHARE of trades priced
  with the unknown-cost fallback.

Why an explicit model instead of the legacy blanket 20% return discount: a
proportional discount shrinks losses as well as gains (a -1% record becomes -0.8%),
ignores turnover and liquidity (the gap is cost per trade x number of trades), and
the statistical part of the paper/live gap (overfitting, selection) is already
charged by the ladder's MinTRL, Monte Carlo, DSR and PBO gates. Execution costs
scale with volatility and with trade size relative to daily volume, close to a
square root (Frazzini, Israel & Moskowitz 2018; Almgren et al. 2005); costs are
higher for small and more volatile stocks (Frazzini et al. 2018). See the design
doc for the calibration and the evidence.
"""
from __future__ import annotations

import math
from statistics import mean

import numpy as np

from marketmind.ledger.store import LedgerEntry
from marketmind.markets import market_for

SLIP_ATR_FRACTION = 0.05         # per side, times ATR% (ATR 2% -> 10 bp per side)
LIQUIDITY_TIERS = ((50e6, "liquid", 1.0), (5e6, "mid", 2.0), (0.0, "illiquid", 4.0))
UNKNOWN_MULTIPLIER = 4.0         # no volume data (except FX)
FUTURE_MULTIPLIER = 2.0          # futures: volume in contracts, dollar ADV unknown
NON_USD_MULTIPLIER = 2.0         # non-US listings: volume value in local currency
IMPACT_Y = 1.0                   # square-root impact coefficient (order 1 in the literature)
UNKNOWN_SIDE_COST = 0.005        # per side when no ATR can be computed (no bars)
ADV_BARS = 20
ATR_BARS = 14
CAPACITY_ADV_SHARE = 0.01        # position <= 1% of 20-day average dollar volume
CAPACITY_MAX_BREACH_SHARE = 0.10
LIVE_MIN_TRADES = 30
LIVE_MIN_DAYS = 40
MAX_UNKNOWN_SHARE = 0.20


def _before(bars, day: str) -> list:
    return [b for b in (bars or []) if b.date < day]


def trade_inputs(e: LedgerEntry, bars) -> dict:
    """ATR%, sigma, ADV and liquidity tier at entry, from the bars before entry."""
    from marketmind.pipeline.l3_indicators import true_ranges
    before = _before(bars, (e.entry_date or "")[:10])
    atr_pct = (e.review or {}).get("atr_pct") if isinstance(e.review, dict) else None
    if atr_pct is None and len(before) > ATR_BARS and before[-1].close > 0:
        trs = true_ranges(before)[-ATR_BARS:]
        if len(trs) == ATR_BARS:
            atr_pct = sum(trs) / ATR_BARS / before[-1].close
    tail = before[-(ADV_BARS + 1):]
    closes = np.array([b.close for b in tail], dtype=float)
    sigma = None
    if closes.size >= 3 and np.all(closes > 0):
        sigma = float(np.std(closes[1:] / closes[:-1] - 1.0, ddof=1))
    m = market_for(e.ticker)
    adv = None
    if m.asset_class == "future":
        # volume is in contracts and the contract multiplier is unknown: no dollar ADV
        tier, mult = "future", FUTURE_MULTIPLIER
    elif m.asset_class == "equity" and m.code != "US":
        # close * volume is in the local currency: no dollar ADV without an FX leg
        tier, mult = "non_usd", NON_USD_MULTIPLIER
    else:
        dv = [b.close * b.volume for b in before[-ADV_BARS:] if b.volume and b.volume > 0]
        adv = mean(dv) if len(dv) >= ADV_BARS // 2 else None
        if adv is not None:
            tier, mult = next((name, k) for floor, name, k in LIQUIDITY_TIERS if adv >= floor)
        elif m.asset_class == "fx":
            tier, mult = "fx", 1.0
        else:
            tier, mult = "unknown", UNKNOWN_MULTIPLIER
    return {"atr_pct": atr_pct, "sigma": sigma, "adv": adv, "tier": tier, "multiplier": mult}


def extra_cost(e: LedgerEntry, inp: dict) -> tuple[float, bool]:
    """(round-trip extra cost as a return, priced with the unknown fallback?)."""
    if inp["atr_pct"] is None:
        return 2 * UNKNOWN_SIDE_COST, True
    side = SLIP_ATR_FRACTION * inp["atr_pct"] * inp["multiplier"]
    if inp["adv"] and inp["sigma"] is not None and e.position_usd > 0:
        side += IMPACT_Y * inp["sigma"] * math.sqrt(e.position_usd / inp["adv"])
    return 2 * side, False


def analyze(trades: list[LedgerEntry], bars: dict, record_days: int) -> dict:
    """Live-expected record of one shadow's matured settled trades (see module doc)."""
    rows = [e for e in trades if e.status == "settled" and e.net_return is not None
            and e.entry_date]
    if not rows:
        return {"status": "empty", "trades": 0, "live_ready": False,
                "live_ready_checks": {"sample": False}}
    extra, unknown, tiers, breaches, cap = [], 0, {}, 0, []
    for e in rows:
        inp = trade_inputs(e, bars.get(e.ticker))
        x, unk = extra_cost(e, inp)
        extra.append(x)
        unknown += unk
        tiers[inp["tier"]] = tiers.get(inp["tier"], 0) + 1
        if inp["adv"]:
            cap.append(CAPACITY_ADV_SHARE * inp["adv"])
            breaches += e.position_usd > CAPACITY_ADV_SHARE * inp["adv"]
    extra_a = np.array(extra)
    net = np.array([e.net_return for e in rows])
    pnl = np.array([e.pnl_usd or 0.0 for e in rows])
    pos = np.array([e.position_usd for e in rows])
    dom_idx = [i for i, e in enumerate(rows) if e.excess_domain is not None]
    paper_dom = float(np.mean([rows[i].excess_domain for i in dom_idx])) if dom_idx else None
    live_dom = (float(np.mean([rows[i].excess_domain - extra[i] for i in dom_idx]))
                if dom_idx else None)
    n = len(rows)
    checks = {
        "sample": n >= LIVE_MIN_TRADES and record_days >= LIVE_MIN_DAYS,
        "beats_domain_after_costs": live_dom is not None and live_dom > 0,
        "capacity": breaches <= CAPACITY_MAX_BREACH_SHARE * n,
        "cost_data": unknown <= MAX_UNKNOWN_SHARE * n,
    }
    return {
        "status": "ok" if checks["sample"] else "insufficient",
        "trades": n, "record_days": record_days,
        "paper_mean_net": float(net.mean()), "live_mean_net": float((net - extra_a).mean()),
        "extra_cost_mean": float(extra_a.mean()),
        "extra_cost_median_bps": float(np.median(extra_a) * 1e4),
        "paper_pnl_usd": float(pnl.sum()), "live_pnl_usd": float((pnl - pos * extra_a).sum()),
        "domain_trades": len(dom_idx),
        "paper_mean_excess_domain": paper_dom, "live_mean_excess_domain": live_dom,
        "unknown_cost": unknown, "tiers": tiers,
        "capacity": {"adv_share": CAPACITY_ADV_SHARE, "breaches": breaches,
                     "priced": len(cap),
                     "capacity_usd_p10": float(np.percentile(cap, 10)) if cap else None},
        "live_ready": all(checks.values()), "live_ready_checks": checks,
    }
