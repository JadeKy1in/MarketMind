"""Daily big-move alert run (docs/S8_DESIGN.md): evaluate, record, notify, report."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marketmind.alerts.conditions import MIN_ADVISORS, MIN_GROUPS, Candidate, evaluate
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.alerts.runner")

HOLD_BARS = 20
POSITION_USD = 1000.0
CONFIDENCE = 0.6
DEDUPE_DAYS = 14                  # ~10 trading days
OBSERVE, LIVE = "observe", "live"


def alerts_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "alerts"


def can_satisfy_a(advisors: dict[str, str]) -> bool:
    """Whether these advisors could ever meet condition A (>= MIN_ADVISORS from
    >= MIN_GROUPS roster groups)."""
    return len(advisors) >= MIN_ADVISORS and len(set(advisors.values())) >= MIN_GROUPS


def load_advisors() -> tuple[str, dict[str, str]]:
    """(mode, shadow_id -> group). S7 writes data/advisors.json. Live mode (only
    advisors vote, alerts are pushed) starts once the advisors can satisfy condition A
    on their own; until then every active roster shadow stands in and alerts stay
    observation-only (fix 2026-09-29: switching to live with 1-2 advisors, or with
    advisors from a single group, silenced every alert until a third cross-group
    advisor appeared)."""
    from marketmind.shadows.v3 import roster
    groups = {r.shadow_id: r.group for r in roster.ROSTER}
    path = Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "advisors.json"
    if path.exists():
        try:
            ids = json.loads(path.read_text(encoding="utf-8")).get("advisors", [])
        except (OSError, ValueError):
            logger.warning("advisors.json unreadable; using observation mode")
            ids = []
        chosen = {i: groups[i] for i in ids if i in groups}
        if can_satisfy_a(chosen):
            return LIVE, chosen
        if chosen:
            logger.info("%d advisor(s) in %d group(s) cannot meet condition A yet; "
                        "staying in observation mode", len(chosen), len(set(chosen.values())))
    return OBSERVE, {r.shadow_id: r.group for r in roster.active()}


def _tradable(ticker: str) -> bool:
    from marketmind.holdings.store import validate_ticker
    from marketmind.pipeline.decision_guard import is_robinhood_tradable
    try:
        validate_ticker(ticker)           # rejects options and bare indices
    except ValueError:
        return False
    return is_robinhood_tradable(ticker)


async def _snapshot(ticker: str):
    from marketmind.gateway.price_history import completed_history, get_price_history
    from marketmind.pipeline.l3_indicators import compute_snapshot
    hist = await get_price_history(ticker)
    return compute_snapshot(completed_history(hist)) if hist is not None else None


def _recently_alerted(store: LedgerStore, ticker: str, now: datetime) -> str | None:
    cutoff = (now - timedelta(days=DEDUPE_DAYS)).isoformat()
    for e in store.list(source_type="alert"):
        if e.ticker.upper() == ticker and e.created_at >= cutoff:
            return e.entry_id
    return None


def _entry(c: Candidate, mode: str, snapshot_id: str | None) -> LedgerEntry:
    stop = c.l3.get("stop")
    names = ", ".join(x["shadow_id"].rsplit(":", 1)[-1] for x in c.advisors_long)
    return LedgerEntry(
        source_type="alert", source_id=f"alert:{mode}", ticker=c.ticker, direction="long",
        hold_bars=HOLD_BARS, confidence=CONFIDENCE, position_usd=POSITION_USD,
        falsifier=f"收盘跌破 L3 止损 {stop}" if stop else "持有期内净收益为负",
        falsifier_rule={"type": "close_below", "price": float(stop)} if stop else None,
        thesis=(f"大行情警报（{'观察' if mode == OBSERVE else '正式'}）：{len(c.advisors_long)} 个"
                f"{'影子' if mode == OBSERVE else '顾问'}做多（{names}），证据层背离 "
                f"{len(c.evidence)} 条，L3 三灯全绿")[:600],
        entry_rule="next_open", stop_loss=stop, target_price=c.l3.get("target"),
        snapshot_id=snapshot_id,
        meta={"mode": mode, "advisors_long": c.advisors_long, "advisors_short": c.advisors_short,
              "groups": c.groups, "evidence": c.evidence, "l3": c.l3},
    )


def format_message(c: Candidate, entry_id: str) -> tuple[str, str]:
    l3 = c.l3
    title = f"MarketMind 大行情警报：{c.ticker} 做多"
    lines = [
        f"标的：{c.ticker}（做多）",
        f"A 顾问一致：{len(c.advisors_long)} 个做多，组别 {', '.join(c.groups)}；做空 {len(c.advisors_short)} 个",
        "B 证据背离：" + "；".join(x.get("claim", "")[:60] for x in c.evidence[:2]),
        f"C 趋势确认：L3 绿灯，收盘 {l3.get('close')}（{l3.get('as_of')}）",
        f"入场区间 {l3.get('entry_low')}–{l3.get('entry_high')}，止损 {l3.get('stop')}，目标 {l3.get('target')}",
        f"账本编号：{entry_id}",
        "系统不下单，是否执行由你决定。回应：python -m marketmind.alerts ack " + entry_id + " accept|reject",
    ]
    return title, "\n".join(lines)


async def run_alerts(store: LedgerStore, *, now: datetime | None = None, snapshot_fn=None,
                     tradable=None, notifier=None, price_source=None,
                     report_dir: Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    mode, advisors = load_advisors()
    cands = await evaluate(store.list(), now, advisors, tradable or _tradable,
                           snapshot_fn or _snapshot)
    fired, near = [], []
    for c in cands:
        if not c.fired:
            if c.met >= 2:
                near.append(asdict(c) | {"met": c.met})
            continue
        dup = _recently_alerted(store, c.ticker, now)
        if dup:
            near.append(asdict(c) | {"met": c.met, "note": f"10 个交易日内已警报过（{dup}）"})
            continue
        from marketmind.ledger.prices import HistoryPriceSource, latest_quotes
        quotes = await latest_quotes(price_source or HistoryPriceSource(), [c.ticker])
        entry_id = store.add(_entry(c, mode, store.save_snapshot(quotes)))
        row = asdict(c) | {"met": 3, "entry_id": entry_id, "mode": mode, "notified": []}
        if mode == LIVE and notifier is not None:
            title, body = format_message(c, entry_id)
            row["notified"] = await notifier(title, body)
        fired.append(row)
    report = {"date": now.strftime("%Y-%m-%d"), "written_at": now.isoformat(timespec="seconds"),
              "mode": mode, "advisors": len(advisors), "fired": fired, "near_misses": near,
              "candidates": len(cands)}
    folder = report_dir or alerts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{report['date']}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
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
