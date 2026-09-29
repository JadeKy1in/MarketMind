"""Alternative macro / consumer data (owner decision 2026-09-29).

- Indeed Hiring Lab job postings (gateway/hiring_lab.py, CC BY 4.0, attributed in
  every section): a few countries and US sectors, latest value and 4-week change.
- Apple App Store charts (gateway/app_charts.py): today's archived snapshot (or a
  live one, labelled, when the daily archive has not run), rank changes against
  the latest earlier archived day, and where listed companies' apps rank.
"""
from __future__ import annotations

from marketmind.gateway import app_charts, hiring_lab
from marketmind.shadow_feeds import Feed

HIRING_SHADOWS = ("cycle_reader", "wallet_watcher")
APP_SHADOWS = ("wallet_watcher", "silicon_oracle")
COUNTRY_NAMES = {"US": "United States", "GB": "United Kingdom", "DE": "Germany",
                 "FR": "France", "CA": "Canada", "AU": "Australia"}
FEED_CHARTS = ("us/all/free", "us/all/grossing", "us/finance/free", "us/shopping/free",
               "us/games/grossing", "jp/all/grossing", "cn/all/grossing")
TOP_SHOWN = 5
COMPANIES_SHOWN = 15


# ── Hiring Lab ──────────────────────────────────────────────────────────────

def _series_line(label: str, s: dict) -> str:
    if "error" in s:
        return f"- {label}: unavailable ({s['error']})"
    line = f"- {label}: {s['value']:.1f} on {s['date']}"
    if "ref_date" in s:
        pct = f", {s['chg_pct']:+.1f}%" if s.get("chg_pct") is not None else ""
        line += f"; 4-week change {s['chg_pts']:+.1f} pts{pct} (vs {s['ref_value']:.1f} on {s['ref_date']})"
    else:
        line += "; 4-week change n/a (history too short)"
    return line


def hiring_lines(doc: dict) -> list[str]:
    lines = ["- Index = seasonally adjusted job postings, 7-day average, 1 Feb 2020 = 100; "
             "data refreshed weekly, so the latest date trails today"]
    for cc, s in doc["countries"].items():
        lines.append(_series_line(f"{COUNTRY_NAMES.get(cc, cc)} total postings", s))
    for name, s in doc["sectors"].items():
        lines.append(_series_line(f"US sector {name}", s))
    lines += [f"- NOTE: {n}" for n in doc.get("notes") or []]
    lines.append(f"- {doc['attribution']}")
    return lines


async def fetch_hiring(today: str) -> list[str]:
    return hiring_lines(await hiring_lab.load_postings())


# ── App Store charts ────────────────────────────────────────────────────────

def _name(a: dict, n: int = 28) -> str:
    name = (a.get("name") or "").replace("‎", "").strip()
    name = name if len(name) <= n else name[: n - 1] + "…"
    t = app_charts.ticker_for(a.get("artist", ""))
    return f"{name} [{t}]" if t else name


def _prev_txt(a: dict) -> str:
    return f"was #{a['prev_rank']}" if a.get("prev_rank") else "new in top 100"


def app_lines(snap: dict, live: bool, prev_day: str | None, prev: dict | None,
              n_days: int) -> list[str]:
    day = snap.get("date")
    head = f"- Snapshot {day} ({app_charts.SOURCE}"
    head += ("; live fetch, today's archive has not run yet" if live else "; archived") + ")"
    if prev is not None:
        head += f"; rank changes vs archived {prev_day}"
    else:
        head += (f"; rank changes need >= 2 archived days (archive has {n_days}), "
                 "none shown")
    lines = [head]
    charts = snap.get("charts") or {}
    pcharts = (prev or {}).get("charts") or {}
    for key in FEED_CHARTS:
        ch = charts.get(key)
        if not ch:
            continue
        if "error" in ch:
            lines.append(f"- {key}: unavailable ({ch['error']})")
            continue
        apps = ch.get("apps") or []
        line = f"- {key} top {TOP_SHOWN}: " + ", ".join(
            f"#{a['rank']} {_name(a)}" for a in apps[:TOP_SHOWN])
        pch = pcharts.get(key)
        if pch and "error" not in pch:
            rc = app_charts.rank_changes(pch.get("apps") or [], apps)
            parts = []
            if rc["entrants"]:
                parts.append("into top 25: " + ", ".join(
                    f"{_name(a)} #{a['rank']} ({_prev_txt(a)})" for a in rc["entrants"][:3]))
            if rc["risers"]:
                parts.append("up: " + ", ".join(
                    f"{_name(a)} #{a['rank']} (+{a['move']})" for a in rc["risers"]))
            if rc["fallers"]:
                parts.append("down: " + ", ".join(
                    f"{_name(a)} #{a['rank']} ({a['move']})" for a in rc["fallers"]))
            line += "; " + ("; ".join(parts) if parts else "no rank changes in the top 50")
        elif prev is not None:
            line += "; no comparable chart on the earlier day"
        lines.append(line)
    cur = app_charts.company_ranks(snap)
    old = app_charts.company_ranks(prev) if prev is not None else {}
    ranked = sorted(cur.items(), key=lambda kv: kv[1][0]["rank"])[:COMPANIES_SHOWN]
    if ranked:
        parts = []
        for t, rows in ranked:
            seen, bits = set(), []
            for r in rows:
                if r["chart"] in seen or len(bits) >= 3:
                    continue
                seen.add(r["chart"])
                was = next((o["rank"] for o in old.get(t, []) if o["chart"] == r["chart"]
                            and o["id"] == r["id"]), None)
                note = ("" if prev is None else " (unranked before)" if not was
                        else " (unch.)" if was == r["rank"] else f" (was #{was})")
                bits.append(f"{r['chart']} #{r['rank']}{note}")
            parts.append(f"{t} {', '.join(bits)}")
        lines.append("- Listed companies' best chart ranks (ticker from developer name): "
                     + "; ".join(parts))
    return lines


async def fetch_apps(today: str) -> list[str]:
    snap = app_charts.load_day(today)
    live = snap is None
    if live:
        snap = await app_charts.fetch_snapshot(today)
        if not any("error" not in c for c in snap["charts"].values()):
            raise RuntimeError("every App Store chart failed")
    days = app_charts.archived_days()
    earlier = [d for d in days if d < today]
    prev_day = earlier[-1] if earlier else None
    prev = app_charts.load_day(prev_day) if prev_day else None
    return app_lines(snap, live, prev_day, prev, len(days))


FEEDS = [
    Feed("indeed_postings", "Job postings (Indeed Hiring Lab, CC BY 4.0)", HIRING_SHADOWS, fetch_hiring),
    Feed("app_store_charts", "App Store top charts (Apple, daily archive)", APP_SHADOWS, fetch_apps),
]
