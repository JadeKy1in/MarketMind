"""Watchlist lifecycle (docs/S10_DESIGN.md §3): add, daily check, push, report views.

add_items     validate new items; the same ticker + direction + source while
              watching refreshes the existing item instead of duplicating it.
              Each new item writes an "enter now" counterfactual to the ledger
              (source_type watch_counterfactual), so the value of waiting is
              measured against the triggered entry later.
check_all     walks every complete bar since the last check: any invalidation
              condition -> invalidated; all conditions on the same bar ->
              triggered (ledger entry source_type watch, next-open entry);
              expiry_bars complete bars without a trigger -> expired.
notify_triggers  pushes main-pipeline triggers only (owner decision 2026-09-28);
              anomaly-origin triggers go to the daily report and dashboard.

Stops and targets: L3 levels for longs when L3 has enough history; otherwise
(and for every short, since L3 levels describe long setups only) the L3 risk
cap mirrored: stop 2 x ATR14 from the close, target 2R. No ATR -> none, and the
ledger falls back to expiry. Numbers come from code only (SPEC_v3 L3).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from marketmind.gateway.price_history import Bar, PriceHistory, complete_bars, to_weekly
from marketmind.ledger.prices import PriceSource, source_of
from marketmind.ledger.settlement import bars_after_creation
from marketmind.ledger.store import LedgerEntry, LedgerStore, default_ledger_path
from marketmind.markets import market_for
from marketmind.pipeline.l3_indicators import MAX_RISK_ATR, atr, compute_snapshot
from marketmind.watchlist.conditions import describe, evaluate
from marketmind.watchlist.store import (
    WatchItem, WatchlistStore, default_watchlist_path, now_iso,
)

logger = logging.getLogger("marketmind.watchlist.runner")

POSITION_USD = 1000.0
DEFAULT_CONFIDENCE = 0.5
ATR_BARS = 15                       # ATR14 needs 14 true ranges
REWARD_RISK = 2.0                   # ATR fallback target = 2R (L3 "enter" threshold)
INPUT_KEYS = ("ticker", "direction", "source", "thesis", "conditions", "invalidation",
              "expiry_bars", "hold_bars", "confidence", "origin")


# ── helpers ────────────────────────────────────────────────────────────────

def _stores(store: WatchlistStore | None, ledger: LedgerStore | None):
    return (store or WatchlistStore(default_watchlist_path()),
            ledger or LedgerStore(default_ledger_path()))


def _ts(now: datetime | str | None, today: str | None = None) -> str:
    if isinstance(now, str):
        return now
    if now is None and today:
        return f"{today}T00:00:00Z"
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _bars(source: PriceSource, ticker: str, today: str | None = None) -> list[Bar]:
    """Complete daily bars only: before `today` (replay/tests) or each market's close (live)."""
    try:
        bars = await source.daily_bars(ticker) or []
    except Exception:
        logger.warning("Watchlist: price data for %s failed", ticker, exc_info=True)
        return []
    if today:
        return [b for b in bars if b.date < today]
    return complete_bars(ticker, bars)


def levels(ticker: str, direction: str, bars: list[Bar], source_name: str = "static") -> dict:
    """Stop / target from code: L3 for longs, else the ATR mirror of L3's risk cap."""
    if not bars:
        return {"basis": "none", "stop": None, "target": None, "close": None}
    close = bars[-1].close
    if direction == "long":
        snap = compute_snapshot(PriceHistory(ticker, source_name, list(bars), to_weekly(bars)))
        if snap is not None:
            return {"basis": "l3", "stop": snap.stop_loss or None,
                    "target": snap.target_price or None, "close": close, "as_of": snap.as_of}
    if len(bars) >= ATR_BARS:
        a = atr(bars)
        if a > 0:
            risk = MAX_RISK_ATR * a
            sign = 1 if direction == "long" else -1
            return {"basis": "atr", "stop": round(close - sign * risk, 4),
                    "target": round(close + sign * REWARD_RISK * risk, 4), "close": close,
                    "atr14": round(a, 4), "as_of": bars[-1].date}
    return {"basis": "none", "stop": None, "target": None, "close": close}


def _ledger_entry(item: WatchItem, source_type: str, lv: dict, snapshot_id: str | None,
                  extra_meta: dict) -> LedgerEntry:
    from marketmind.ledger.recorder import classify_ticker
    layer, asset_type = classify_ticker(item.ticker)
    stop, target = lv.get("stop"), lv.get("target")
    long = item.direction == "long"
    if stop:
        falsifier = f"{item.ticker} 收盘{'跌破' if long else '上破'}止损 {stop:g}"
        rule = {"type": "close_below" if long else "close_above", "price": float(stop)}
    else:
        falsifier = f"{item.ticker} {'做多' if long else '做空'}持有 {item.hold_bars} 个交易日净收益为负"
        rule = None
    label = "观察对照（立即入场）" if source_type == "watch_counterfactual" else "观察触发"
    conf = item.confidence
    return LedgerEntry(
        source_type=source_type, source_id=f"watch:{item.source}", ticker=item.ticker,
        direction=item.direction, hold_bars=item.hold_bars,
        confidence=DEFAULT_CONFIDENCE if conf is None else conf,
        confidence_is_default=conf is None, position_usd=POSITION_USD,
        falsifier=falsifier, falsifier_rule=rule, thesis=f"[{label}] {item.thesis}"[:2000],
        layer=layer, asset_type=asset_type, entry_rule="next_open",
        stop_loss=stop, target_price=target, snapshot_id=snapshot_id,
        meta={"origin": dict(item.origin), "watch_id": item.id, "watch_source": item.source,
              "conditions": item.conditions, "invalidation": item.invalidation,
              "levels": lv, **extra_meta},
    )


def _snapshot(ledger: LedgerStore, source: PriceSource, ticker: str, bars: list[Bar],
              taken_at: str) -> str:
    quote = ((bars[-1].close, bars[-1].date, source_of(source, ticker)) if bars
             else (None, None, None))
    if not bars:
        logger.warning("Watchlist snapshot: no price for %s (recorded as unavailable)", ticker)
    return ledger.save_snapshot({ticker: quote}, taken_at=taken_at)


def _to_item(raw) -> WatchItem:
    if isinstance(raw, WatchItem):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(f"watch item must be an object, got {type(raw).__name__}")
    unknown = set(raw) - set(INPUT_KEYS)
    if unknown:
        raise ValueError(f"unexpected keys {sorted(unknown)} (allowed: {', '.join(INPUT_KEYS)})")
    for k in ("ticker", "direction", "source", "thesis"):
        if k not in raw:
            raise ValueError(f"{k} is required")
    kw = {k: raw[k] for k in INPUT_KEYS if raw.get(k) is not None}
    return WatchItem(**kw)


def _row(item: WatchItem) -> dict:
    return {"watch_id": item.id, "ticker": item.ticker, "direction": item.direction,
            "source": item.source, "thesis": item.thesis, "status": item.status,
            "origin": item.origin}


# ── add ────────────────────────────────────────────────────────────────────

async def add_items(items, price_source: PriceSource, *, store: WatchlistStore | None = None,
                    ledger: LedgerStore | None = None, now: datetime | str | None = None,
                    today: str | None = None) -> dict:
    """Add watch items (dicts with INPUT_KEYS, or WatchItem). Never raises on one bad item.

    `today` bounds the bars used for the counterfactual's levels (replay/tests).

    Returns {"added": [ids], "refreshed": [ids], "rejected": [{"input", "error"}],
             "counterfactuals": {watch_id: ledger entry id}}.
    """
    store, ledger = _stores(store, ledger)
    at = _ts(now, today)
    out = {"added": [], "refreshed": [], "rejected": [], "counterfactuals": {}}
    for raw in items or []:
        try:
            item = _to_item(raw)
            item.validate()
        except (TypeError, ValueError) as exc:
            logger.warning("Watchlist: rejected %r: %s", raw, exc)
            out["rejected"].append({"input": raw if isinstance(raw, dict) else repr(raw),
                                    "error": str(exc)})
            continue
        existing = store.find_watching(item.ticker, item.direction, item.source)
        if existing is not None:
            _refresh(existing, item, at)
            store.update(existing)
            out["refreshed"].append(existing.id)
            continue
        item.id = item.id or uuid.uuid4().hex[:16]
        item.created_at = at
        item.status = "watching"
        bars = await _bars(price_source, item.ticker, today)
        lv = levels(item.ticker, item.direction, bars, source_of(price_source, item.ticker))
        snap = _snapshot(ledger, price_source, item.ticker, bars, at)
        entry_id = ledger.add(_ledger_entry(item, "watch_counterfactual", lv, snap, {}),
                              created_at=at)
        item.counterfactual_entry_id = entry_id
        item.history.append({"at": at, "event": "created", "counterfactual_entry_id": entry_id,
                             "price_data": bool(bars)})
        store.add(item)
        out["added"].append(item.id)
        out["counterfactuals"][item.id] = entry_id
    logger.info("Watchlist: %d added, %d refreshed, %d rejected",
                len(out["added"]), len(out["refreshed"]), len(out["rejected"]))
    return out


def _refresh(existing: WatchItem, new: WatchItem, at: str) -> None:
    """Same idea seen again while watching: take the new wording and conditions and
    extend the window by the new expiry from today; the counterfactual stays the original."""
    existing.thesis = new.thesis
    existing.conditions = new.conditions
    existing.invalidation = new.invalidation
    existing.hold_bars = new.hold_bars
    if new.confidence is not None:
        existing.confidence = new.confidence
    existing.origin = {**existing.origin, **new.origin}
    existing.expiry_bars = existing.bars_seen + new.expiry_bars
    existing.refreshed_at = at
    existing.history.append({"at": at, "event": "refreshed", "expiry_bars": existing.expiry_bars})


# ── daily check ────────────────────────────────────────────────────────────

def _is_crypto(ticker: str) -> bool:
    return market_for(ticker).code == "CRYPTO"


async def check_all(price_source: PriceSource, today: str | None = None, *,
                    store: WatchlistStore | None = None, ledger: LedgerStore | None = None,
                    now: datetime | str | None = None, crypto_only: bool = False) -> dict:
    """Evaluate every watching item on the complete bars it has not seen yet.

    `today` (YYYY-MM-DD) bounds the bars like settle_all (replay/tests); live runs
    leave it None and use each market's session close. `crypto_only` is for the
    weekend run. Returns {"date", "checked_at", "checked", "triggered", "expired",
    "invalidated", "still_watching", "unavailable", "errors"}; each triggered /
    expired / invalidated row has watch_id, ticker, direction, source, thesis,
    bar_date, fired (condition, label, detail); triggered rows add entry_id,
    stop, target, levels_basis.
    """
    store, ledger = _stores(store, ledger)
    at = _ts(now, today)
    report = {"date": today or at[:10], "checked_at": at, "checked": 0, "triggered": [],
              "expired": [], "invalidated": [], "still_watching": 0, "unavailable": [],
              "errors": []}
    cache: dict[str, list[Bar]] = {}
    for item in store.watching():
        if crypto_only and not _is_crypto(item.ticker):
            continue
        report["checked"] += 1
        try:
            if item.ticker not in cache:
                cache[item.ticker] = await _bars(price_source, item.ticker, today)
            bars = cache[item.ticker]
            if not bars:
                report["unavailable"].append(item.ticker)
                report["still_watching"] += 1
                continue
            row = _step(item, bars)
            if row is None:
                report["still_watching"] += 1
            elif item.status == "triggered":
                lv = levels(item.ticker, item.direction, bars, source_of(price_source, item.ticker))
                snap = _snapshot(ledger, price_source, item.ticker, bars, at)
                entry_id = ledger.add(_ledger_entry(
                    item, "watch", lv, snap,
                    {"trigger_bar": item.close_bar_date, "fired": row["fired"],
                     "counterfactual_entry_id": item.counterfactual_entry_id}), created_at=at)
                item.triggered_entry_id = entry_id
                row |= {"entry_id": entry_id, "stop": lv.get("stop"), "target": lv.get("target"),
                        "levels_basis": lv["basis"]}
                report["triggered"].append(row)
            else:
                report[item.status].append(row)
            if item.status != "watching":
                item.closed_at = at
            store.update(item)
        except Exception as exc:
            # one bad item must not block the rest of the list
            logger.error("Watchlist: checking %s (%s) failed", item.id, item.ticker, exc_info=True)
            report["errors"].append({"watch_id": item.id, "error": f"{type(exc).__name__}: {exc}"})
    logger.info("Watchlist: %d checked, %d triggered, %d expired, %d invalidated",
                report["checked"], len(report["triggered"]), len(report["expired"]),
                len(report["invalidated"]))
    return report


def _step(item: WatchItem, bars: list[Bar]) -> dict | None:
    """Evaluate new bars in order; set the terminal status on `item` and return its
    report row, or None while it keeps watching. Invalidation beats a trigger on
    the same bar (conservative); a trigger on the last allowed bar beats expiry."""
    after = bars_after_creation(SimpleNamespace(created_at=item.created_at, ticker=item.ticker,
                                                asset_type=""), bars)
    first_new = [b for b in after if item.last_bar_date is None or b.date > item.last_bar_date]
    index = {b.date: i for i, b in enumerate(bars)}
    for b in first_new:
        window = bars[:index[b.date] + 1]
        inv = [evaluate(c, window, item.direction) for c in item.invalidation]
        met = [evaluate(c, window, item.direction) for c in item.conditions]
        item.bars_seen += 1
        item.last_bar_date = b.date
        item.history.append({"bar": b.date, "close": b.close, "met": [m for m, _ in met],
                             "invalidation": [m for m, _ in inv]})
        if any(m for m, _ in inv):
            fired = [_fired(c, d, item.direction) for c, (m, d) in zip(item.invalidation, inv) if m]
            return _close(item, "invalidated", b.date, fired)
        if all(m for m, _ in met):
            fired = [_fired(c, d, item.direction) for c, (_, d) in zip(item.conditions, met)]
            return _close(item, "triggered", b.date, fired)
        if item.bars_seen >= item.expiry_bars:
            return _close(item, "expired", b.date,
                          [], note=f"{item.bars_seen} bars without confirmation")
    return None


def _fired(cond: dict, detail: str, direction: str) -> dict:
    return {"condition": cond, "label": describe(cond, direction), "detail": detail}


def _close(item: WatchItem, status: str, bar_date: str, fired: list[dict], note: str = "") -> dict:
    item.status = status
    item.close_bar_date = bar_date
    item.close_detail = {"fired": fired, "note": note}
    item.history.append({"bar": bar_date, "event": status})
    return _row(item) | {"bar_date": bar_date, "fired": fired, "note": note,
                         "bars_seen": item.bars_seen}


# ── push ───────────────────────────────────────────────────────────────────

def format_message(rows: list[dict]) -> tuple[str, str]:
    """One message for all of today's pushable triggers (Server酱 free plan: 5 a day)."""
    names = "、".join(f"{r['ticker']} {'做多' if r['direction'] == 'long' else '做空'}" for r in rows)
    title = f"MarketMind 观察触发：{names}"[:90]
    blocks = []
    for r in rows:
        side = "做多" if r["direction"] == "long" else "做空"
        fired = "；".join(f"{f['label']}（{f['detail']}）" for f in r.get("fired", []))
        lines = [f"【{r['ticker']} {side}】触发：{fired}",
                 f"论点：{(r.get('thesis') or '')[:200]}"]
        if r.get("stop") or r.get("target"):
            lines.append(f"止损 {r.get('stop')}，目标 {r.get('target')}（{r.get('levels_basis')}）")
        lines.append(f"账本编号：{r.get('entry_id')}，按次日开盘价入账")
        blocks.append("\n".join(lines))
    blocks.append("系统不下单，是否执行由你决定。")
    return title, "\n\n".join(blocks)


async def notify_triggers(report: dict, send=None, *, store: WatchlistStore | None = None) -> dict:
    """Push main-pipeline triggers only; anomaly triggers stay in the report and dashboard.

    `send(title, body) -> [{channel, ok, status}]`, default marketmind.alerts.notify.send.
    Returns {"pushed": [watch ids], "skipped": [watch ids], "results": [...]}.
    """
    rows = [r for r in report.get("triggered", []) if r.get("source") == "main_pipeline"]
    skipped = [r["watch_id"] for r in report.get("triggered", []) if r.get("source") != "main_pipeline"]
    out = {"pushed": [], "skipped": skipped, "results": []}
    if not rows:
        return out
    if send is None:
        from marketmind.alerts.notify import send
    title, body = format_message(rows)
    try:
        results = await send(title, body)
    except Exception as exc:
        logger.warning("Watchlist push failed: %s", type(exc).__name__)
        results = [{"channel": "error", "ok": False, "status": 0}]
    out["pushed"] = [r["watch_id"] for r in rows]
    out["results"] = results
    if store is not None:
        at = now_iso()
        for r in rows:
            item = store.get(r["watch_id"])
            if item is not None:
                item.history.append({"at": at, "event": "notified", "results": results})
                store.update(item)
    return out


# ── report / dashboard views ───────────────────────────────────────────────

def _view(item: WatchItem) -> dict:
    return _row(item) | {
        "created_at": item.created_at, "refreshed_at": item.refreshed_at,
        "conditions": [describe(c, item.direction) for c in item.conditions],
        "invalidation": [describe(c, item.direction) for c in item.invalidation],
        "bars_seen": item.bars_seen, "expiry_bars": item.expiry_bars,
        "bars_left": max(0, item.expiry_bars - item.bars_seen) if item.status == "watching" else 0,
        "counterfactual_entry_id": item.counterfactual_entry_id,
        "triggered_entry_id": item.triggered_entry_id, "closed_at": item.closed_at,
        "close_bar_date": item.close_bar_date,
        "fired": [f["label"] for f in (item.close_detail or {}).get("fired", [])],
    }


def daily_summary(date: str | None = None, store: WatchlistStore | None = None) -> dict:
    """Watchlist changes on `date` (UTC, default today) for the daily report."""
    store = store or WatchlistStore(default_watchlist_path())
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = store.list()
    closed_on = lambda i, s: i.status == s and (i.closed_at or "")[:10] == date  # noqa: E731
    return {
        "date": date,
        "new": [_view(i) for i in items if i.created_at[:10] == date],
        "refreshed": [_view(i) for i in items
                      if (i.refreshed_at or "")[:10] == date and i.created_at[:10] != date],
        "triggered": [_view(i) for i in items if closed_on(i, "triggered")],
        "expired": [_view(i) for i in items if closed_on(i, "expired")],
        "invalidated": [_view(i) for i in items if closed_on(i, "invalidated")],
        "watching": sum(1 for i in items if i.status == "watching"),
    }


def dashboard_items(store: WatchlistStore | None = None, status: str | None = None,
                    limit: int = 200) -> list[dict]:
    """Newest first; watching items carry bars_left."""
    store = store or WatchlistStore(default_watchlist_path())
    items = sorted(store.list(status=status), key=lambda i: (i.created_at, i.id), reverse=True)
    return [_view(i) for i in items[:limit]]
