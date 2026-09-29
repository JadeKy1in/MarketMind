"""Big-move alert run (docs/S8_DESIGN.md): trend trunk -> annotate -> record -> (push).

Observe mode (default) computes and records every alert - the report file and, for
entry alerts, a ledger record `source_id=alert:observe` - and never pushes. Live mode
is the owner's explicit switch (alerts/config.py, MARKETMIND_ALERTS_LIVE); only then
are the run's alerts sent, batched into one priority message.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marketmind.alerts import config as C
from marketmind.alerts.conditions import ENTRY, EXIT, STATUS_CN, SUPPORTED, VETOED, Candidate, evaluate
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.alerts.runner")

OBSERVE, LIVE = "observe", "live"
ADVISORS, STAND_IN = "advisors", "stand_in"
PLAYGROUND_PREFIX, PLAYGROUND_GROUP = "playground:", "playground"
TREND_KEYS = ("state", "event", "as_of", "close", "stop_level", "entry_signal_date",
              "entry_signal_close", "ret_12m", "hurdle", "sma200", "high_55", "reason")


def alerts_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "alerts"


def current_mode(env=os.environ) -> str:
    """Live only when the owner has switched it on (default off)."""
    return LIVE if C.live_enabled(env) else OBSERVE


def load_voters(entries=()) -> tuple[str, dict[str, str]]:
    """(basis, voter id -> roster group). S7 writes data/advisors.json; roster shadows and
    Playground agents ("playground:" ids, group "playground") on that list vote. With no
    advisor yet, every active roster shadow and every Playground agent in the ledger
    stands in (basis "stand_in")."""
    from marketmind.shadows.v3 import roster
    # successors of retired shadows included (docs/S7_DESIGN.md §一 退役)
    groups = {r.shadow_id: r.group for r in roster.all_entries()}

    def group_of(sid: str) -> str | None:
        return PLAYGROUND_GROUP if sid.startswith(PLAYGROUND_PREFIX) else groups.get(sid)

    path = Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "advisors.json"
    ids: list[str] = []
    if path.exists():
        try:
            ids = json.loads(path.read_text(encoding="utf-8")).get("advisors", [])
        except (OSError, ValueError):
            logger.warning("advisors.json unreadable; stand-in voters used")
    chosen = {i: group_of(i) for i in ids if group_of(i)}
    if chosen:
        return ADVISORS, chosen
    stand = {r.shadow_id: r.group for r in roster.active()}
    stand |= {e.source_id: PLAYGROUND_GROUP for e in entries if e.source_type == "playground"}
    return STAND_IN, stand


def _tradable(ticker: str) -> bool:
    from marketmind.holdings.store import validate_ticker
    from marketmind.pipeline.decision_guard import is_robinhood_tradable
    try:
        validate_ticker(ticker)           # rejects options and bare indices
    except ValueError:
        return False
    return is_robinhood_tradable(ticker)


def _seen_keys(store: LedgerStore, folder: Path, now: datetime) -> set[str]:
    """Keys of alerts already fired within DEDUPE_DAYS (report files + ledger)."""
    since = (now - timedelta(days=C.DEDUPE_DAYS)).strftime("%Y-%m-%d")
    keys: set[str] = set()
    if folder.is_dir():
        for p in folder.glob("????-??-??.json"):
            if p.stem < since:
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            keys |= {f.get("key") for f in doc.get("fired", []) if f.get("key")}
    for e in store.list(source_type="alert"):
        k = (e.meta or {}).get("key")
        if k and e.created_at[:10] >= since:
            keys.add(k)
    return keys


def _row(c: Candidate) -> dict:
    """Report row; a_ok / b_ok / c_ok / advisors_long / l3 keep the dashboard's first-
    version columns readable (A = advisors support, B = evidence note, C = trend trunk)."""
    longs, shorts = ((c.votes_for, c.votes_against) if c.direction == "long"
                     else (c.votes_against, c.votes_for))
    a_ok, b_ok = c.status == SUPPORTED, bool(c.evidence)
    return {"ticker": c.ticker, "kind": c.kind, "direction": c.direction, "asset_group": c.group,
            "key": c.key, "status": c.status, "status_cn": STATUS_CN[c.status],
            "veto": c.status == VETOED, "votes_for": c.votes_for, "votes_against": c.votes_against,
            "evidence": c.evidence, "evidence_against": c.evidence_against,
            "trend": {k: c.trend.get(k) for k in TREND_KEYS},
            "advisors_long": longs, "advisors_short": shorts, "groups": c.roster_groups,
            "a_ok": a_ok, "b_ok": b_ok, "c_ok": c.kind in (ENTRY, EXIT),
            "met": int(a_ok) + int(b_ok) + int(c.kind in (ENTRY, EXIT)),
            "l3": {"light": c.trend.get("state")}}


def _thesis(c: Candidate, mode: str, source: str) -> str:
    who = "顾问" if mode == LIVE else "投票者"
    return (f"大行情警报（{'观察' if mode == OBSERVE else '正式'}）：{c.ticker} 趋势状态进入 TREND"
            f"（来源 {source}）；{STATUS_CN[c.status]}：{who}同向 {len(c.votes_for)} / 反向 "
            f"{len(c.votes_against)}（资产组 {c.group}）；证据层同向背离 {len(c.evidence)} 条")[:600]


def _entry(c: Candidate, mode: str, source: str, universe: str | None,
           snapshot_id: str | None) -> LedgerEntry:
    stop = c.trend.get("stop_level")
    row = _row(c)
    return LedgerEntry(
        source_type="alert", source_id=f"alert:{mode}", ticker=c.ticker, direction="long",
        hold_bars=C.HOLD_BARS, confidence=C.CONFIDENCE, position_usd=C.POSITION_USD,
        falsifier=f"收盘跌破趋势止损 {stop}" if stop else "持有期内净收益为负",
        falsifier_rule={"type": "close_below", "price": float(stop)} if stop else None,
        thesis=_thesis(c, mode, source), entry_rule="next_open", stop_loss=stop,
        snapshot_id=snapshot_id,
        meta={"mode": mode, "kind": c.kind, "key": c.key, "trend_source": source,
              "universe": universe, **{k: row[k] for k in (
                  "asset_group", "status", "votes_for", "votes_against", "evidence",
                  "evidence_against", "trend", "advisors_long", "advisors_short", "groups")}},
    )


def format_batch(rows: list[dict], day: str) -> tuple[str, str]:
    """All of one run's alerts in ONE message (owner decision 2026-09-29)."""
    names = ", ".join(f"{r['ticker']}{'入场' if r['kind'] == ENTRY else '离场'}" for r in rows)
    title = f"MarketMind 大行情警报 {day}：{names}"
    lines: list[str] = []
    for r in rows:
        t = r["trend"]
        head = ("【入场】" if r["kind"] == ENTRY else "【离场】") + f"{r['ticker']}（{r['asset_group']}）"
        move = "CASH→TREND" if r["kind"] == ENTRY else f"TREND→{t.get('state')}"
        lines.append(f"{head}：趋势 {move}，收盘 {t.get('close')}（{t.get('as_of')}），"
                     f"趋势止损 {t.get('stop_level')}")
        lines.append(f"  顾问：{r['status_cn']}，同向 {len(r['votes_for'])} / 反向 "
                     f"{len(r['votes_against'])}" + (f"（{', '.join(r['groups'])}）" if r['groups'] else ""))
        if r["veto"]:
            lines.append("  ⚠ 否决标记：多数投票顾问方向相反，请特别审视")
        if r["evidence"]:
            lines.append("  证据层同向背离：" + "；".join(x.get("claim", "")[:60] for x in r["evidence"][:2]))
        if r.get("entry_id"):
            lines.append(f"  账本编号：{r['entry_id']}（回应：python -m marketmind.alerts ack "
                         f"{r['entry_id']} accept|reject）")
    lines.append("系统不下单，是否执行由你决定。")
    return title, "\n".join(lines)


async def run_alerts(store: LedgerStore, *, now: datetime | None = None, source=None,
                     tradable=None, notifier=None, price_source=None,
                     report_dir: Path | None = None, crypto_only: bool = False,
                     env=os.environ) -> dict:
    from marketmind.alerts.trend_source import get_source
    from marketmind.gateway.price_history import is_crypto_ticker
    from marketmind.trend.daily import ny_date
    now = now or datetime.now(timezone.utc)
    mode = current_mode(env)
    source = source or get_source()
    reading = source.read(ny_date(now))
    entries = store.list()
    basis, voters = load_voters(entries)
    include = is_crypto_ticker if crypto_only else (lambda t: True)
    cands, near, skipped = evaluate(reading, entries, now, voters, tradable or _tradable, include)
    folder = report_dir or alerts_dir()
    seen = _seen_keys(store, folder, now)
    fired, duplicates = [], []
    for c in cands:
        row = _row(c)
        if c.key in seen:
            duplicates.append(row | {"note": "同一趋势事件已警报过"})
            continue
        row |= {"entry_id": None, "mode": mode, "notified": []}
        if c.kind == ENTRY:                   # exits are report-only: the owner is long-only
            from marketmind.ledger.prices import HistoryPriceSource, latest_quotes
            quotes = await latest_quotes(price_source or HistoryPriceSource(), [c.ticker])
            row["entry_id"] = store.add(_entry(c, mode, reading.source, reading.universe,
                                               store.save_snapshot(quotes)))
        fired.append(row)
    pushed: list[dict] = []
    if mode == LIVE and notifier is not None and fired:
        title, body = format_batch(fired, reading.date)
        pushed = await notifier(title, body, priority=True)
        for row in fired:
            row["notified"] = pushed
    report = {"date": now.strftime("%Y-%m-%d"), "written_at": now.isoformat(timespec="seconds"),
              "mode": mode, "live_switch": C.live_enabled(env), "crypto_only": crypto_only,
              "trend_source": reading.summary(), "voter_basis": basis, "advisors": len(voters),
              "fired": fired, "near_misses": [_row(c) | {"note": "WATCH：只差 55 日突破"} for c in near],
              "duplicates": duplicates, "skipped": skipped, "pushed": pushed,
              "candidates": len(cands)}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{report['date']}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


# ── owner responses (SPEC §6.3 missed_path: rejected alerts keep settling) ──

def record_response(entry_id: str, decision: str, note: str = "",
                    store: LedgerStore | None = None) -> dict:
    if decision not in ("accept", "reject"):
        raise ValueError("decision must be accept or reject")
    if store is not None:
        e = store.get(entry_id)
        if e is None or e.source_type != "alert":
            raise ValueError(f"{entry_id} is not an alert record")
    row = {"entry_id": entry_id, "decision": decision, "note": note,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    folder = alerts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "responses.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_responses() -> dict[str, dict]:
    p = alerts_dir() / "responses.jsonl"
    out: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r["entry_id"]] = r          # latest response wins
    return out
