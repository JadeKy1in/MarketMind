"""Read-only comparison of the L3 target v1 / v2 counterfactual pairs (ledger.l3_target_pairs).

    python -m marketmind.ledger.l3_target_compare [--db data/ledger.db] [--json]

Opens the ledger with sqlite mode=ro (never writes). Per version, over pairs whose two
rows are both settled: hit-target rate (exit_reason "target"), mean net return, mean R
(net return / initial risk, risk = (entry price - stop) / entry price, the stop taken in
the series the record was settled in, meta.price_factor). Plus the paired difference
v2 - v1 clustered by decision day: one mean difference per run_date, in date order,
tested with the HAC (Newey-West, fixed-b) t-test of promotion.metrics.hac_t_test and
the variant-trial bandwidth (shadows.v3.trials.hac_bandwidth, at least the longest hold:
consecutive days' pairs overlap). Voids (unfilled zone entry, gap past target) are
counted per version; a pair with a void side is not compared.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import mean

from marketmind.ledger.l3_target_pairs import KIND, SOURCE_IDS, SOURCE_TYPE, VERSIONS
from marketmind.ledger.settlement import settle_factor
from marketmind.ledger.store import LedgerEntry, LedgerStore

MIN_DAYS_FOR_TEST = 2


def load_rows(db: str | Path) -> list[LedgerEntry]:
    """The pair rows only, read-only (sqlite URI mode=ro)."""
    uri = f"file:{Path(db).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        marks = ", ".join("?" for _ in SOURCE_IDS)
        rows = conn.execute(f"SELECT * FROM ledger WHERE source_type = ? AND source_id IN ({marks}) "
                            "ORDER BY created_at, entry_id",
                            (SOURCE_TYPE, *SOURCE_IDS.values())).fetchall()
    finally:
        conn.close()
    return [LedgerStore._from_row(r) for r in rows]


def r_multiple(e: LedgerEntry) -> float | None:
    """Net return in units of the initial risk (long: entry above the stop)."""
    if e.net_return is None or not e.entry_price or not e.stop_loss:
        return None
    stop = e.stop_loss * settle_factor(e)
    sign = 1.0 if e.direction == "long" else -1.0
    risk = sign * (e.entry_price - stop) / e.entry_price
    return e.net_return / risk if risk > 0 else None


def _settled(e: LedgerEntry | None) -> bool:
    return e is not None and e.status == "settled" and e.net_return is not None


def pairs(rows: list[LedgerEntry]) -> list[tuple[str, LedgerEntry, LedgerEntry]]:
    """(run_date, v1, v2) for every pair id with both versions present."""
    by: dict[str, dict[str, LedgerEntry]] = {}
    for e in rows:
        m = e.meta or {}
        v = m.get("version")
        if e.source_type == SOURCE_TYPE and m.get("pair_id") and v in VERSIONS \
                and m.get("baseline") == KIND[v]:
            by.setdefault(m["pair_id"], {})[v] = e
    out = []
    for p in by.values():
        if "v1" in p and "v2" in p:
            run = (p["v1"].meta or {}).get("run_date") or p["v1"].created_at[:10]
            out.append((run, p["v1"], p["v2"]))
    return sorted(out, key=lambda x: (x[0], x[1].ticker))


def _version_stats(rows: list[LedgerEntry]) -> dict:
    rs = [x for x in (r_multiple(e) for e in rows) if x is not None]
    n = len(rows)
    return {"n": n,
            "hit_target_rate": round(sum(e.exit_reason == "target" for e in rows) / n, 4) if n else None,
            "mean_net_return": round(mean(e.net_return for e in rows), 6) if n else None,
            "win_rate": round(sum(e.net_return > 0 for e in rows) / n, 4) if n else None,
            "mean_r": round(mean(rs), 4) if rs else None, "r_n": len(rs)}


def compare(rows: list[LedgerEntry]) -> dict:
    """Pure aggregation (no I/O); see module doc."""
    from marketmind.promotion.metrics import hac_t_test
    from marketmind.shadows.v3.trials import hac_bandwidth
    allp = pairs(rows)
    done = [(d, a, b) for d, a, b in allp if _settled(a) and _settled(b)]
    voids = {v: sum(1 for _, a, b in allp if (a if v == "v1" else b).status == "void")
             for v in VERSIONS}
    by_day: dict[str, list[float]] = {}
    for d, a, b in done:
        by_day.setdefault(d, []).append(b.net_return - a.net_return)
    days = sorted(by_day)
    series = [mean(by_day[d]) for d in days]
    hold = max((a.hold_bars for _, a, _ in done), default=1)
    test = None
    if len(series) >= MIN_DAYS_FOR_TEST:
        lag = hac_bandwidth(hold, len(series))
        up, down = hac_t_test(series, lag), hac_t_test([-x for x in series], lag)
        test = {"days": len(series), "lag": up["lag"], "mean_daily_diff": up["mean"],
                "se": up["se"], "t": up["t"],
                "p_v2_better": up["p_value"], "p_v1_better": down["p_value"],
                "inference": up.get("inference")}
    return {
        "pairs_total": len(allp), "pairs_settled": len(done),
        "pairs_open": sum(1 for _, a, b in allp if a.status in ("pending", "open")
                          or b.status in ("pending", "open")),
        "voids": voids, "days": len(days), "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "v1": _version_stats([a for _, a, _ in done]),
        "v2": _version_stats([b for _, _, b in done]),
        "paired_diff": {"mean_pair_diff": round(mean(b.net_return - a.net_return
                                                     for _, a, b in done), 6) if done else None,
                        "v2_better_share": round(sum(b.net_return > a.net_return
                                                     for _, a, b in done) / len(done), 4)
                        if done else None,
                        "day_clustered": test},
        "note": "只记账的对照：v1 = 现行目标价，v2 = R/R < 1.5 时改用更高一级阻力（同一上限）；"
                "入场、止损、持有期相同。只统计两边都已结算的配对；日聚类差 = 每个决策日的平均 (v2 - v1)。",
    }


def _pct(v):
    return "—" if v is None else f"{v * 100:+.2f}%"


def format_report(c: dict) -> str:
    lines = [f"L3 目标价 v1/v2 对照：配对 {c['pairs_total']}，已结算 {c['pairs_settled']}，"
             f"未结算 {c['pairs_open']}，作废 v1 {c['voids']['v1']} / v2 {c['voids']['v2']}；"
             f"决策日 {c['days']}（{c['first_day'] or '—'} 至 {c['last_day'] or '—'}）"]
    for v in VERSIONS:
        s = c[v]
        hit = "—" if s["hit_target_rate"] is None else f"{s['hit_target_rate'] * 100:.0f}%"
        r = "—" if s["mean_r"] is None else f"{s['mean_r']:+.2f}R"
        lines.append(f"  {v}: n={s['n']} 到达目标 {hit}  平均净收益 {_pct(s['mean_net_return'])}  平均 {r}")
    pd = c["paired_diff"]
    t = pd["day_clustered"]
    lines.append(f"  配对差 v2-v1：均值 {_pct(pd['mean_pair_diff'])}，v2 更好占比 "
                 f"{'—' if pd['v2_better_share'] is None else f'{pd['v2_better_share'] * 100:.0f}%'}")
    if t is None:
        lines.append("  按日聚类检验：决策日不足，未检验")
    else:
        tt = "—" if t["t"] is None else f"{t['t']:.2f}"
        lines.append(f"  按日聚类（{t['days']} 天，HAC lag {t['lag']}）：日均差 {_pct(t['mean_daily_diff'])}，"
                     f"t={tt}，p(v2 更好)={t['p_v2_better']}，p(v1 更好)={t['p_v1_better']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "ledger.db"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    c = compare(load_rows(a.db))
    print(json.dumps(c, ensure_ascii=False, indent=2) if a.json else format_report(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
