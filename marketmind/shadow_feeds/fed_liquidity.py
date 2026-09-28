"""Fed liquidity: NY Fed repo / reverse-repo operations and SOMA holdings.

Sources (keyless, verified 2026-09-28):
- https://markets.newyorkfed.org/api/rp/all/all/results/lastTwoWeeks.json
  {"repo": {"operations": [{operationDate, operationType: "Repo" | "Reverse Repo",
  totalAmtAccepted (USD), participatingCpty?, details: [{percentAwardRate?, ...}]}]}},
  newest first. Standing repo runs twice a day; ON RRP once.
- https://markets.newyorkfed.org/api/soma/summary.json
  {"soma": {"summary": [{asOfDate, total, bills, notesbonds, mbs, ...} (USD strings)]}},
  weekly (Wednesdays), oldest first.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx

from marketmind.shadow_feeds import Feed

RP_URL = "https://markets.newyorkfed.org/api/rp/all/all/results/lastTwoWeeks.json"
SOMA_URL = "https://markets.newyorkfed.org/api/soma/summary.json"
TIMEOUT_S = 30.0
B = 1e9


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True,
                             headers={"Accept": "application/json"})


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── parsers (pure) ──────────────────────────────────────────────────────────

def daily_operations(payload: dict, op_type: str) -> list[dict]:
    """Per-day totals for one operation type, oldest first:
    {date, accepted (USD), ops, rate (award %, if any), cpty (participants, if any)}."""
    days: dict[str, dict] = {}
    for o in ((payload or {}).get("repo") or {}).get("operations") or []:
        if o.get("operationType") != op_type or o.get("auctionStatus", "Results") != "Results":
            continue
        d, amt = o.get("operationDate"), _f(o.get("totalAmtAccepted"))
        if not d or amt is None:
            continue
        row = days.setdefault(d, {"date": d, "accepted": 0.0, "ops": 0, "rate": None, "cpty": None})
        row["accepted"] += amt
        row["ops"] += 1
        rates = [_f(x.get("percentAwardRate")) for x in o.get("details") or []]
        rates = [r for r in rates if r is not None]
        if rates:
            row["rate"] = rates[0]
        if o.get("participatingCpty") is not None:
            row["cpty"] = (row["cpty"] or 0) + int(o["participatingCpty"])
    return [days[d] for d in sorted(days)]


def soma_totals(payload: dict) -> list[dict]:
    """Weekly SOMA holdings, oldest first: {date, total, bills, coupons, mbs} in USD."""
    out = []
    for r in ((payload or {}).get("soma") or {}).get("summary") or []:
        total = _f(r.get("total"))
        if not r.get("asOfDate") or total is None:
            continue
        # `total` excludes tipsInflationCompensation, so the buckets do too
        coupons = sum(_f(r.get(k)) or 0.0 for k in ("notesbonds", "tips", "frn"))
        out.append({"date": r["asOfDate"], "total": total, "bills": _f(r.get("bills")) or 0.0,
                    "coupons": coupons, "mbs": (_f(r.get("mbs")) or 0.0) + (_f(r.get("cmbs")) or 0.0)})
    return sorted(out, key=lambda r: r["date"])


def _at_or_before(rows: list[dict], day: str) -> dict | None:
    prior = [r for r in rows if r["date"] <= day]
    return prior[-1] if prior else None


def _usd(x: float, nd: int = 1) -> str:
    """Signed USD billions: +$1.2B / -$0.3B."""
    return f"{'-' if x < 0 else '+'}${abs(x) / B:,.{nd}f}B"


def _chg(now: float, then: float) -> str:
    return f"{_usd(now - then)} ({(now / then - 1) * 100:+.2f}%)" if then else "n/a"


def rp_lines(payload: dict) -> list[str]:
    lines = []
    rrp = daily_operations(payload, "Reverse Repo")
    if rrp:
        last, first = rrp[-1], rrp[0]
        extra = ", ".join(x for x in (
            f"award {last['rate']:.2f}%" if last["rate"] is not None else "",
            f"{last['cpty']} counterparties" if last["cpty"] is not None else "") if x)
        lines.append(f"- ON RRP (Fed reverse repo, liquidity parked at the Fed) {last['date']}: "
                     f"${last['accepted'] / B:,.2f}B" + (f" ({extra})" if extra else "")
                     + f"; {first['date']}: ${first['accepted'] / B:,.2f}B "
                     f"(2-week change {_usd(last['accepted'] - first['accepted'], 2)}); "
                     f"{len(rrp)}-day avg ${sum(r['accepted'] for r in rrp) / len(rrp) / B:,.2f}B")
    repo = daily_operations(payload, "Repo")
    if repo:
        last = repo[-1]
        peak = max(repo, key=lambda r: r["accepted"])
        total = sum(r["accepted"] for r in repo)
        lines.append(f"- Standing repo (Fed lending cash to dealers) {last['date']}: "
                     f"${last['accepted'] / B:,.2f}B over {last['ops']} operation(s); "
                     f"{repo[0]['date']}..{last['date']} total ${total / B:,.2f}B, "
                     f"peak ${peak['accepted'] / B:,.2f}B on {peak['date']}")
    return lines


def soma_lines(payload: dict) -> list[str]:
    rows = soma_totals(payload)
    if not rows:
        return []
    last = rows[-1]
    d = date.fromisoformat(last["date"])
    lines = [f"- SOMA (Fed balance-sheet securities) {last['date']}: ${last['total'] / B:,.1f}B"]
    for label, days in (("1w", 7), ("4w", 28), ("13w", 91)):
        ref = _at_or_before(rows, (d - timedelta(days=days)).isoformat())
        if ref is not None and ref is not last:
            lines[-1] += f"; {label} {_chg(last['total'], ref['total'])}"
    ref4 = _at_or_before(rows, (d - timedelta(days=28)).isoformat())
    if ref4 is not None and ref4 is not last:
        weeks = (d - date.fromisoformat(ref4["date"])).days / 7
        pace = (last["total"] - ref4["total"]) / weeks * 52 / 12 / B
        lines.append(f"- SOMA pace since {ref4['date']}: {_usd(pace * B)} per month "
                     f"({'growing = adding liquidity' if pace > 0 else 'shrinking = QT / draining'}); "
                     f"4w change by bucket: bills {_usd(last['bills'] - ref4['bills'])}, "
                     f"notes/bonds/TIPS/FRN {_usd(last['coupons'] - ref4['coupons'])}, "
                     f"MBS {_usd(last['mbs'] - ref4['mbs'])}")
    return lines


# ── feed ────────────────────────────────────────────────────────────────────

async def _get_json(client: httpx.AsyncClient, url: str):
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()


async def fetch(today: str) -> list[str]:
    async with _client() as c:
        rp, soma = await asyncio.gather(_get_json(c, RP_URL), _get_json(c, SOMA_URL),
                                        return_exceptions=True)
    lines: list[str] = []
    if isinstance(rp, Exception):
        lines.append(f"- NY Fed repo / reverse-repo operations: unavailable ({type(rp).__name__})")
    else:
        lines += rp_lines(rp) or ["- NY Fed repo / reverse-repo operations: no results in the last two weeks"]
    if isinstance(soma, Exception):
        lines.append(f"- SOMA holdings: unavailable ({type(soma).__name__})")
    else:
        lines += soma_lines(soma) or ["- SOMA holdings: no data"]
    if isinstance(rp, Exception) and isinstance(soma, Exception):
        raise rp
    return lines


FEEDS = [Feed("fed_liquidity", "Fed liquidity (NY Fed operations and balance sheet, USD)",
              ("yield_whisperer", "cycle_reader", "bank_examiner"), fetch)]
