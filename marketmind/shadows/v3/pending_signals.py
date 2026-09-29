"""Pending (conditional) shadow signals: registry and daily trigger check.

docs/S3_DESIGN.md §9 (owner decision 2026-09-29; rebuilt from the deleted legacy
shadows/pending_signal_registry.py). Pure code, no LLM.

- A shadow may add up to decision.MAX_CONDITIONALS conditional signals next to its
  daily decisions. They are registered only with a recorded submission (a missed or
  duplicate day registers none), under the shadow id and its lineage id.
- Registry: <data_dir>/shadows/pending_signals.json, written atomically (tmp + replace).
  Status: pending -> triggered | expired | cancelled (terminal). Terminal signals stay
  in the registry for ARCHIVE_DAYS, then live only in the event log
  <data_dir>/shadows/pending_signals.jsonl (one line per registration and per close).
- Trigger check (each shadow run, for the signals of the shadows in that run): every
  completed daily bar after the last bar the shadow saw (`as_of`) is evaluated in order.
  The condition holding on a bar -> a normal ledger record (source_type of the shadow,
  meta.pending_signal_id, entry at the next open, no stop/target: the levels the shadow
  saw are stale by then). `expires_in_days` bars without a trigger -> expired.
  close_above / close_below / breakout_20d reuse the watch-card evaluation
  (marketmind/watchlist/conditions.py); the 5-day change is computed here.
- A triggered record counts toward the shadow's record but never toward the forced
  daily minimum: runner.py leaves records with meta.pending_signal_id out of the
  once-per-session submission check.
- Signals of a shadow that no run checks any more (an ended event shadow or trial)
  expire UNCHECKED_GRACE_DAYS calendar days after their longest possible wait.
- Retirement: the retired shadow's pending signals expire ("owner retired"); they
  are NOT handed to the successor, whose record starts from zero under a different
  methodology (docs/S7_DESIGN.md §一 退役). Called from promotion/retirement.approve.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

from marketmind.gateway.price_history import Bar, complete_bars
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.markets import market_for
from marketmind.shadows.v3.decision import ConditionalSignal, position_for
from marketmind.watchlist import conditions as watch_conditions

logger = logging.getLogger("marketmind.shadows.v3.pending_signals")

PENDING, TRIGGERED, EXPIRED, CANCELLED = "pending", "triggered", "expired", "cancelled"
MAX_OPEN_PER_SHADOW = 6          # open signals per shadow; extra new ones are not registered
ARCHIVE_DAYS = 30                # terminal signals kept in the registry this long
UNCHECKED_GRACE_DAYS = 10        # calendar slack before an unchecked signal expires
PCT_LOOKBACK = 5


def default_path(data_dir: str | Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else Path(os.getenv("MARKETMIND_DATA_DIR", "data"))
    return root / "shadows" / "pending_signals.json"


def log_path(path: Path) -> Path:
    return path.with_suffix(".jsonl")


def load(path: Path) -> dict:
    if not path.exists():
        return {"signals": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("signals", [])
    return data


def save(data: dict, path: Path, today: str | None = None) -> None:
    """Atomic write; terminal signals closed more than ARCHIVE_DAYS ago are dropped
    (they are already in the event log)."""
    if today:
        cutoff = (date.fromisoformat(today) - timedelta(days=ARCHIVE_DAYS)).isoformat()
        data["signals"] = [s for s in data["signals"]
                           if s.get("status") == PENDING or (s.get("closed_on") or today) >= cutoff]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _log(path: Path, events: list[dict]) -> None:
    if not events:
        return
    try:
        with log_path(path).open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("pending-signal event log not written", exc_info=True)


def open_signals(data: dict, shadow_id: str | None = None) -> list[dict]:
    return [s for s in data["signals"] if s.get("status") == PENDING
            and (shadow_id is None or s.get("shadow_id") == shadow_id)]


# ── register ─────────────────────────────────────────────────────────────

def register(path: Path, entry, signals: list[ConditionalSignal], *, today: str,
             created_at: str, closes: dict[str, float], as_of: dict[str, str],
             atrs: dict[str, float], meta: dict) -> tuple[list[str], list[str]]:
    """Store validated signals of one submission; returns (ids, warnings)."""
    if not signals:
        return [], []
    from marketmind.shadows.v3.roster import lineage_id
    data = load(path)
    room = MAX_OPEN_PER_SHADOW - len(open_signals(data, entry.shadow_id))
    ids, warnings, events = [], [], []
    # an off-context ticker has no bar the shadow saw: watch from the run date on
    fallback = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    for s in signals:
        if room <= 0:
            warnings.append(f"conditional signal {s.direction} {s.ticker} not registered: "
                            f"{MAX_OPEN_PER_SHADOW} signals already open")
            continue
        rec = {
            "signal_id": uuid.uuid4().hex[:16], "status": PENDING,
            "shadow_id": entry.shadow_id, "lineage_id": lineage_id(entry.shadow_id),
            "source_type": entry.source_type, "shadow_name": entry.name,
            "domain_benchmark": entry.domain_benchmark,
            "ticker": s.ticker, "direction": s.direction, "condition": dict(s.condition),
            "hold_days": s.hold_days, "confidence": s.confidence,
            "expires_in_days": s.expires_in_days, "thesis": s.thesis, "falsifier": s.falsifier,
            "run_date": today, "created_at": created_at,
            "as_of": as_of.get(s.ticker) or fallback, "close": closes.get(s.ticker),
            "atr14": atrs.get(s.ticker),
            "bars_seen": 0, "last_bar_date": as_of.get(s.ticker) or fallback,
            "meta": dict(meta),
        }
        data["signals"].append(rec)
        ids.append(rec["signal_id"])
        events.append({"at": created_at, "event": "registered", **_brief(rec)})
        room -= 1
    if ids:
        save(data, path, today)
        _log(path, events)
    return ids, warnings


def _brief(s: dict) -> dict:
    return {k: s.get(k) for k in ("signal_id", "shadow_id", "lineage_id", "ticker", "direction",
                                  "condition", "expires_in_days", "run_date")}


# ── evaluation ───────────────────────────────────────────────────────────

def evaluate(cond: dict, bars: list[Bar], direction: str) -> tuple[bool, str]:
    """(met, detail) on the last of `bars` (completed bars, oldest first)."""
    ctype = cond["type"]
    if ctype in ("close_above", "close_below"):
        return watch_conditions.evaluate({"type": ctype, "price": cond["level"]}, bars, direction)
    if ctype == "breakout_20d":
        return watch_conditions.evaluate({"type": "breakout_20d"}, bars, direction)
    if ctype in ("pct_change_5d_above", "pct_change_5d_below"):
        if len(bars) <= PCT_LOOKBACK or not bars[-1 - PCT_LOOKBACK].close:
            return False, f"only {len(bars)} bars; 5-day change unavailable"
        chg = (bars[-1].close / bars[-1 - PCT_LOOKBACK].close - 1) * 100
        met = chg > cond["pct"] if ctype == "pct_change_5d_above" else chg < cond["pct"]
        return met, f"5-day change {chg:+.2f}% vs {cond['pct']:+g}%"
    raise ValueError(f"unknown condition type {ctype!r}")


def describe(cond: dict, direction: str = "long") -> str:
    ctype = cond.get("type")
    if ctype == "close_above":
        return f"收盘上破 {cond['level']:g}"
    if ctype == "close_below":
        return f"收盘跌破 {cond['level']:g}"
    if ctype == "pct_change_5d_above":
        return f"5 日涨幅超过 {cond['pct']:g}%"
    if ctype == "pct_change_5d_below":
        return f"5 日跌幅超过 {abs(cond['pct']):g}%"
    if ctype == "breakout_20d":
        return "收盘跌破前 20 日低点" if direction == "short" else "收盘突破前 20 日高点"
    return str(ctype)


def _step(sig: dict, bars: list[Bar]) -> tuple[str, str | None, str]:
    """Walk the bars after sig['last_bar_date']: (status, bar date, detail)."""
    seen_until = sig.get("last_bar_date") or sig.get("as_of") or ""
    for i, b in enumerate(bars):
        if b.date <= seen_until:
            continue
        met, detail = evaluate(sig["condition"], bars[:i + 1], sig["direction"])
        sig["bars_seen"] = int(sig.get("bars_seen") or 0) + 1
        sig["last_bar_date"] = b.date
        if met:
            return TRIGGERED, b.date, detail
        if sig["bars_seen"] >= int(sig["expires_in_days"]):
            return EXPIRED, b.date, f"{sig['bars_seen']} bars without the condition ({detail})"
    return PENDING, None, ""


def _close(sig: dict, status: str, today: str, at: str, bar: str | None, note: str) -> dict:
    sig.update(status=status, closed_on=today, closed_at=at, close_bar=bar, note=note)
    return {"at": at, "event": status, "bar": bar, "note": note,
            "entry_id": sig.get("entry_id"), **_brief(sig)}


def _unchecked_deadline(sig: dict) -> str:
    """Last calendar day a signal could still be waiting (trading bars ~ 7/5 calendar days)."""
    days = int(sig["expires_in_days"]) * 7 // 5 + UNCHECKED_GRACE_DAYS
    return (date.fromisoformat(sig["run_date"]) + timedelta(days=days)).isoformat()


def _ledger_entry(sig: dict, bar_date: str, detail: str, today: str,
                  snapshot_id: str | None) -> LedgerEntry:
    from marketmind.ledger.recorder import classify_ticker
    return LedgerEntry(
        source_type=sig["source_type"], source_id=sig["shadow_id"], ticker=sig["ticker"],
        direction=sig["direction"], hold_bars=int(sig["hold_days"]),
        confidence=float(sig["confidence"]), position_usd=position_for(float(sig["confidence"])),
        falsifier=sig["falsifier"], thesis=f"[条件触发] {sig['thesis']}"[:2000],
        asset_type=classify_ticker(sig["ticker"])[1], entry_rule="next_open",
        domain_benchmark=sig.get("domain_benchmark"), snapshot_id=snapshot_id,
        meta={**(sig.get("meta") or {}), "pending_signal_id": sig["signal_id"],
              "condition": sig["condition"], "trigger_bar": bar_date, "fired": detail,
              "signal_run_date": sig["run_date"], "run_date": today,
              "market": market_for(sig["ticker"]).code},
    )


# ── daily check ──────────────────────────────────────────────────────────

def tickers_to_check(path: Path, shadow_ids: set[str]) -> list[str]:
    try:
        data = load(path)
    except (OSError, ValueError):
        return []
    return sorted({s["ticker"] for s in open_signals(data) if s["shadow_id"] in shadow_ids})


def check(path: Path, store: LedgerStore, histories: dict, *, shadow_ids: set[str],
          retired: set[str] | frozenset = frozenset(), today: str, created_at: str) -> dict:
    """Evaluate the open signals of `shadow_ids` on their completed bars.

    `histories`: ticker -> PriceHistory (None / missing = no data: keeps waiting).
    Signals of retired shadows are cancelled; signals past their unchecked deadline
    expire. Returns {"triggered": [...], "expired": [...], "cancelled": [...],
    "waiting": n, "unavailable": [tickers]}; triggered rows carry entry_id.
    """
    report = {"triggered": [], "expired": [], "cancelled": [], "waiting": 0, "unavailable": []}
    if not path.exists():
        return report
    data = load(path)
    events: list[dict] = []
    bars_cache: dict[str, list[Bar]] = {}
    for sig in open_signals(data):
        sid = sig["shadow_id"]
        if sid in retired:
            events.append(_close(sig, CANCELLED, today, created_at, None, "owner retired"))
            report["cancelled"].append(_brief(sig))
            continue
        if sid not in shadow_ids:
            if today > _unchecked_deadline(sig):
                events.append(_close(sig, EXPIRED, today, created_at, None,
                                     "not checked in time (owner no longer running)"))
                report["expired"].append(_brief(sig))
            continue
        t = sig["ticker"]
        if t not in bars_cache:
            hist = histories.get(t)
            bars_cache[t] = complete_bars(t, hist.daily) if hist is not None and hist.daily else []
        bars = bars_cache[t]
        if not bars:
            report["unavailable"].append(t)
            report["waiting"] += 1
            continue
        status, bar, detail = _step(sig, bars)
        if status == PENDING:
            report["waiting"] += 1
        elif status == EXPIRED:
            events.append(_close(sig, EXPIRED, today, created_at, bar, detail))
            report["expired"].append(_brief(sig) | {"bar": bar})
        else:
            last = bars[-1]
            src = getattr(histories.get(t), "source", None)
            snap = store.save_snapshot({t: (last.close, last.date, src)}, taken_at=created_at)
            entry_id = store.add(_ledger_entry(sig, bar, detail, today, snap),
                                 created_at=created_at)
            sig["entry_id"] = entry_id
            events.append(_close(sig, TRIGGERED, today, created_at, bar, detail))
            report["triggered"].append(_brief(sig) | {"bar": bar, "entry_id": entry_id,
                                                      "detail": detail})
    save(data, path, today)
    _log(path, events)
    for r in report["expired"]:
        logger.info("Pending signal %s (%s %s %s) expired", r["signal_id"], r["shadow_id"],
                    r["direction"], r["ticker"])
    return report


def expire_for_retired(shadow_id: str, *, successor: str | None, today: str,
                       path: Path | None = None, data_dir: str | Path | None = None) -> list[str]:
    """Retirement hand-over: the retired shadow's open signals expire (not transferred:
    the successor starts from zero with another methodology). Returns their ids."""
    path = path or default_path(data_dir)
    if not path.exists():
        return []
    data = load(path)
    at = f"{today}T00:00:00Z"
    note = f"owner retired (successor {successor} does not inherit it)" if successor \
        else "owner retired"
    events = [_close(s, CANCELLED, today, at, None, note) for s in open_signals(data, shadow_id)]
    if events:
        save(data, path, today)
        _log(path, events)
    return [e["signal_id"] for e in events]


def context_lines(data: dict, shadow_id: str) -> list[str]:
    """The shadow's own open signals for its context (avoids re-registering them)."""
    return [f"- {s['direction']} {s['ticker']} if {s['condition']['type']}"
            + (f" {s['condition'].get('level', s['condition'].get('pct')):g}"
               if s["condition"].get("level", s["condition"].get("pct")) is not None else "")
            + f" | registered {s['run_date']}, {s.get('bars_seen', 0)}/{s['expires_in_days']} bars"
            for s in open_signals(data, shadow_id)]
