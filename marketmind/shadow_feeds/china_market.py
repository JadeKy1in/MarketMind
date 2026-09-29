"""China / Hong Kong market data for dragon_watch via akshare (gateway/china_akshare.py).

Sections: index closes (Sina), Stock Connect net buying (Eastmoney), whole-market
margin balances (Eastmoney). Calls run one at a time in the akshare worker thread;
the feed stops starting new calls when its time budget is spent and labels the
skipped parts. Every number is a published value or a difference computed here.
"""
from __future__ import annotations

import time

from marketmind.gateway import china_akshare as ak
from marketmind.shadow_feeds import FEED_TIMEOUT_S, Feed

SHADOWS = ("dragon_watch",)
BUDGET_S = FEED_TIMEOUT_S - 15


def _pct(now: float, then: float) -> str:
    return f"{(now / then - 1) * 100:+.2f}%" if then else "n/a"


def index_line(label: str, s) -> str:
    if isinstance(s, Exception):
        return f"- {label}: unavailable ({s})"
    if not s:
        return f"- {label}: no data"
    d, c = s[-1]
    parts = [f"- {label} {c:,.2f} (close {d}"]
    if len(s) > 1:
        parts.append(f"1d {_pct(c, s[-2][1])}")
    if len(s) > 5:
        parts.append(f"5d {_pct(c, s[-6][1])}")
    if len(s) > 20:
        parts.append(f"20d {_pct(c, s[-21][1])}")
    return ", ".join(parts) + ")"


def connect_line(label: str, doc) -> str:
    if isinstance(doc, Exception):
        return f"- {label}: unavailable ({doc})"
    s = doc["series"]
    if doc.get("blank_since"):
        last = f"; last published value {s[-1][1]:+,.2f} on {s[-1][0]}" if s else ""
        return (f"- {label}: unavailable — source rows since {doc['blank_since']} carry no "
                f"net-buy value (latest row {doc['last_date']}){last}")
    if not s:
        return f"- {label}: no data"
    d, v = s[-1]
    sums = [f"{n}-session sum {sum(x for _, x in s[-n:]):+,.2f}" for n in (5, 20) if len(s) >= n]
    return f"- {label} {v:+,.2f} on {d}" + (f"; {'; '.join(sums)}" if sums else "")


def margin_line(rows) -> str:
    if isinstance(rows, Exception):
        return f"- A-share margin balances: unavailable ({rows})"
    if not rows:
        return "- A-share margin balances: no data"
    last = rows[-1]
    line = f"- A-share margin financing balance {last['financing']:,.1f} (亿元) on {last['date']}"
    for n in (5, 20):
        if len(rows) > n:
            ref = rows[-1 - n]
            line += (f"; {n} sessions {last['financing'] - ref['financing']:+,.1f} "
                     f"({_pct(last['financing'], ref['financing'])})")
    if last.get("lending") is not None:
        line += f"; securities lending balance {last['lending']:,.1f}"
    return line


async def fetch(today: str) -> list[str]:
    start = time.monotonic()
    lines: list[str] = []

    def spent() -> bool:
        return time.monotonic() - start > BUDGET_S

    indexes = await ak.index_closes()
    lines += [index_line(k, v) for k, v in indexes.items()]
    steps = (("Southbound Stock Connect net buy (mainland -> HK; 亿, Eastmoney 当日成交净买额)", ak.southbound, connect_line),
             ("A-share margin balances", ak.margin_balance, None),
             ("Northbound Stock Connect net buy (HK -> mainland; 亿, Eastmoney)", ak.northbound, connect_line))
    results = [v for v in indexes.values() if not isinstance(v, Exception)]
    for label, loader, fmt in steps:
        if spent():
            lines.append(f"- {label}: skipped (feed time budget spent)")
            continue
        try:
            doc = await loader()
            results.append(doc)
        except ak.AkshareUnavailable as e:
            doc = e
        lines.append(fmt(label, doc) if fmt else margin_line(doc))
    if not results:
        raise RuntimeError("every akshare call failed")
    lines.append(f"- Data via akshare {ak.version()} (Sina, Eastmoney); {ak.LICENCE_NOTE}")
    return lines


FEEDS = [Feed("china_akshare", "China / Hong Kong market data (akshare)", SHADOWS, fetch)]
