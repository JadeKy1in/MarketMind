"""Exit-structure replay + baselines for MarketMind ledger entries (read-only analysis).

Reads data/ledger.db in SQLite read-only mode and bars cached by fetch_bars.py.
Re-uses the project's own settlement simulator (marketmind.ledger.settlement.simulate)
with modified copies of each entry (stop / target / falsifier changed), so fill rules,
gap rules, close-only handling and crypto calendar rules are identical to the ledger.
Outputs results.json and per-entry rows (entries.csv) next to this file.
"""
from __future__ import annotations

import csv, json, math, os, sqlite3, sys
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO = Path("E:/AI_Studio_Workspace/MarketMind")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from marketmind.gateway.price_history import Bar
from marketmind.ledger.settlement import (simulate, price_adjustment, rescaled, cost_bps,
                                          bars_after_creation, calendar_run, is_crypto,
                                          _close_view, benchmark_return, first_bar_date)
from marketmind.ledger.store import LedgerStore
from marketmind.trend.rules import TrendConfig, wilder_atr
from marketmind.trend.state import simulate as trend_sim, TREND

TREND_HURDLE = 0.04          # assumption: ~4% annual T-bill hurdle (^IRX not fetched)
RNG = np.random.default_rng(20261002)
N_RANDOM = 5000
N_BOOT = 5000


def load_bars(t):
    p = HERE / "bars" / f"{t.replace('^', '_').replace('=', '_')}.json"
    if not p.exists():
        return None, None
    d = json.loads(p.read_text())
    return d["source"], [Bar(*r) for r in d["bars"]]


def load_entries():
    con = sqlite3.connect(f"file:{REPO / 'data/ledger.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from ledger where status in ('settled','open') "
                       "and entry_date is not null order by created_at, entry_id").fetchall()
    ents = [LedgerStore._from_row(r) for r in rows]
    snaps = {}
    for r in con.execute("select * from quote_snapshots"):
        snaps.setdefault(r["snapshot_id"], {})[r["ticker"]] = dict(r)
    return ents, snaps


def after_bars(e, bars):
    after = bars_after_creation(e, bars)
    if is_crypto(e):
        after, _ = calendar_run(e, after)
    return [_close_view(b) for b in after]


def pre_bars(e, bars):
    first = first_bar_date(e)
    return [b for b in bars if b.date < first] if first else bars


def run(e, bars, dec_px):
    """Simulate; open outcomes are marked to market at the last close in the window."""
    out = simulate(e, bars, decision_price=dec_px)
    if out.fill is None:
        return None
    after = after_bars(e, bars)
    entry = out.entry_price if out.entry_price is not None else out.fill.price
    if out.status == "settled":
        xi, xp, reason, realized = out.exit_index, out.exit_price, out.exit_reason, True
    else:
        xi = min(len(after) - 1, out.fill.index + e.hold_bars - 1)
        xp, reason, realized = after[xi].close, "mtm", False
    sign = 1.0 if e.direction == "long" else -1.0
    gross = sign * (xp / entry - 1)
    return dict(entry_date=after[out.fill.index].date, exit_date=after[xi].date, entry=entry,
                exit=xp, reason=reason, realized=realized, gross=gross,
                fill_open=after[out.fill.index].open if out.fill.at_open else out.fill.price,
                long_gross_fill=None)


def main():
    ents, snaps = load_entries()
    _, spy = load_bars("SPY")
    cfg = TrendConfig()
    rows, missing = [], set()
    for e in ents:
        src, bars = load_bars(e.ticker)
        if not bars:
            missing.add(e.ticker)
            continue
        snap = snaps.get(e.snapshot_id, {}) if e.snapshot_id else {}
        factor, _ = price_adjustment(e, bars, snap, src)
        sp = (snap.get(e.ticker.upper()) or snap.get(e.ticker) or {}).get("price")
        dec = sp * factor if sp else None
        er = rescaled(e, factor)
        pre = pre_bars(e, bars)
        if len(pre) < 30:
            missing.add(e.ticker + "(short pre-history)")
            continue
        ref = dec if dec else pre[-1].close
        atr = wilder_atr(pre[-60:], 14)[-1]
        lr = np.diff(np.log([b.close for b in pre[-21:]]))
        sig = float(np.std(lr, ddof=1))
        s = 1.0 if e.direction == "long" else -1.0
        cost = 2 * cost_bps(e.asset_type, e.ticker) / 1e4
        hb = e.hold_bars
        orig_stop_d = abs(ref - er.stop_loss) if er.stop_loss else None

        def lv(dist, side):           # side -1: stop side, +1: target side
            return None if dist is None else ref + side * s * dist

        variants = {
            "R0_current": er,
            "R0b_no_falsifier": replace(er, falsifier_rule=None),
            "R1_expiry_only": replace(er, stop_loss=None, target_price=None, falsifier_rule=None),
            "R2_atr1.5": replace(er, stop_loss=lv(1.5 * atr, -1), target_price=None, falsifier_rule=None),
            "R2_atr2": replace(er, stop_loss=lv(2 * atr, -1), target_price=None, falsifier_rule=None),
            "R2_atr3": replace(er, stop_loss=lv(3 * atr, -1), target_price=None, falsifier_rule=None),
            "R2_atr2_sym": replace(er, stop_loss=lv(2 * atr, -1), target_price=lv(2 * atr, 1), falsifier_rule=None),
            "R2_atr1_sqrtH": replace(er, stop_loss=lv(atr * math.sqrt(hb), -1), target_price=None, falsifier_rule=None),
            "R3_stop1.5x": replace(er, stop_loss=lv(orig_stop_d and 1.5 * orig_stop_d, -1), falsifier_rule=None),
            "R3_stop2x": replace(er, stop_loss=lv(orig_stop_d and 2 * orig_stop_d, -1), falsifier_rule=None),
            "R4_tb_origdist": replace(er, stop_loss=lv(orig_stop_d, -1), target_price=lv(orig_stop_d, 1), falsifier_rule=None),
            "R4_tb_vol": replace(er, stop_loss=lv(ref * sig * math.sqrt(hb), -1),
                                 target_price=lv(ref * sig * math.sqrt(hb), 1), falsifier_rule=None),
        }
        res = {}
        for k, v in variants.items():
            r = run(v, bars, dec)
            if r is None:
                break
            r["net"] = r["gross"] - cost
            spy_r = benchmark_return(spy, r["entry_date"], r["exit_date"])
            r["spy"] = spy_r
            r["excess"] = None if spy_r is None else r["net"] - s * spy_r
            res[k] = r
        if "R0_current" not in res or len(res) < len(variants):
            missing.add(e.ticker + "(no fill in replay)")
            continue
        # ledger match (settled records only)
        r0 = res["R0_current"]
        match = None
        if e.status == "settled":
            match = (r0["realized"] and r0["reason"] == e.exit_reason and r0["exit_date"] == e.exit_date
                     and abs(r0["net"] - e.net_return) < 2e-3)
        # baselines on the expiry-only window (R1): fill at the same price/date
        r1 = res["R1_expiry_only"]
        long_g = r1["exit"] / r1["entry"] - 1           # always-long gross, same window
        spy_r = r1["spy"]
        closes = [b.close for b in pre]
        n12, skip = (365, 30) if is_crypto(e) else (252, 21)
        mom20 = closes[-1] / closes[-21] - 1
        mom12 = (closes[-1 - skip] / closes[-1 - n12] - 1) if len(closes) > n12 + 1 else None
        try:
            tsim = trend_sim(e.ticker, pre, cfg, TREND_HURDLE)
            tstate = tsim.states[-1] if len(pre) >= cfg.min_bars(e.ticker) else "UNAVAILABLE"
        except Exception:
            tstate = "UNAVAILABLE"
        rows.append(dict(
            entry_id=e.entry_id, source_type=e.source_type, source_id=e.source_id, ticker=e.ticker,
            asset_type=e.asset_type, direction=e.direction, sign=s, hold_bars=hb, status=e.status,
            ledger_reason=e.exit_reason, ledger_net=e.net_return, entry_date=r1["entry_date"],
            cost=cost, atr_pct=atr / ref, sig_d=sig, orig_stop_pct=(orig_stop_d / ref) if orig_stop_d else None,
            match=match, long_gross=long_g, spy=spy_r, mom20=mom20, mom12=mom12, trend=tstate,
            r1_realized=r1["realized"], r1_exit_date=r1["exit_date"],
            rules={k: dict(net=v["net"], gross=v["gross"], reason=v["reason"], realized=v["realized"],
                           excess=v["excess"], exit_date=v["exit_date"]) for k, v in res.items()},
        ))
    out = dict(n=len(rows), missing=sorted(missing), rows=rows)
    (HERE / "entries.json").write_text(json.dumps(out, indent=1, default=str))
    print("rows", len(rows), "missing", sorted(missing))


if __name__ == "__main__":
    main()
