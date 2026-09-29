"""SEC fails-to-deliver for the short-side shadows (owner decision 2026-09-29).

Data: marketmind/gateway/sec_ftd.py (latest two half-month SEC files, cached).
Watched symbols: the served shadows' US-listed watchlist symbols (ETFs included,
FTDs on ETFs are meaningful). Every section states the SEC's 2-4 week lag.
"""
from __future__ import annotations

from marketmind.gateway import sec_ftd
from marketmind.shadow_feeds import Feed

SHADOWS = ("squeeze_watch", "bear_tracker")
TOP_N = 5


def _us_symbol(t: str) -> bool:
    t = t.upper()
    return t.isascii() and t.isalnum() and not t[0].isdigit()


def watched(shadows=SHADOWS) -> list[str]:
    from marketmind.shadows.v3 import roster
    by_name = {e.name: e for e in roster.ROSTER}
    out: list[str] = []
    for n in shadows:
        for t in (by_name[n].watchlist if n in by_name else ()):
            if _us_symbol(t) and t.upper() not in out:
                out.append(t.upper())
    return out


def _money(x: float | None) -> str:
    if x is None:
        return "value n/a (no SEC price)"
    a = abs(x)
    if a >= 1e9:
        return f"${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"${a / 1e6:.2f}M"
    return f"${a / 1e3:.0f}K" if a >= 1e3 else f"${a:.0f}"


def build_lines(doc: dict, symbols: list[str]) -> list[str]:
    lt, pr = doc["latest"], doc["prior"]
    head = (f"- Period {lt['period']} = settlement dates {lt['first']}..{lt['last']} "
            f"({lt['n_dates']} dates)")
    head += (f"; compared with {pr['period']} ({pr['first']}..{pr['last']})" if pr
             else "; prior period unavailable, no change shown")
    lines = [f"- NOTE: {doc['lag_note']}.", head]
    if doc.get("note"):
        lines.append(f"- NOTE: {doc['note']}")
    missing = []
    for s in symbols:
        r = doc["tickers"].get(s) or {}
        if not r.get("in_latest"):
            missing.append(s)
            continue
        chg = (f"avg {r['chg_avg_shares_pct']:+.0f}% vs prior period"
               if "chg_avg_shares_pct" in r else
               "not in the prior period file" if pr else "no prior period")
        lines.append(f"- {s}: fails on {r['days']}/{r['n_dates']} dates; latest {r['last_date']} "
                     f"{r['last_shares']:,} sh ({_money(r['last_value'])}); avg on reported dates "
                     f"{r['avg_shares']:,.0f} sh ({_money(r['avg_value'])}), max {r['max_shares']:,} sh; {chg}")
    if missing:
        lines.append(f"- No fails reported in {lt['period']} for: {', '.join(missing)}")
    if doc.get("top"):
        lines.append("- Largest average daily fails by value, all securities: " + "; ".join(
            f"{t['symbol']} {_money(t['avg_value'])} ({t['days']} dates)" for t in doc["top"][:TOP_N]))
    return lines


async def fetch(today: str) -> list[str]:
    symbols = watched()
    return build_lines(await sec_ftd.load_ftd(symbols), symbols)


FEEDS = [Feed("sec_ftd", "SEC fails-to-deliver (half-month files, 2-4 week lag)", SHADOWS, fetch)]
