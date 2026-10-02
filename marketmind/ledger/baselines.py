"""Comparable code baselines paired with LLM decisions (docs/S7_DESIGN.md §六, owner 2026-10-02).

Ledger only: never traded, never shown as advice, excluded from every score, voter,
calendar and view except the comparison (ledger.comparison). For each long-term shadow
decision and each main-pipeline record, on the same ticker, hold_bars, session and
entry rule (next_open), written in the decision's own add_submission transaction:

  always_long     long, expiry only.
  momentum20      sign of the 20-trading-day return at decision (skipped when 0 or
                  unavailable), expiry only.
  trend           long when the decision's trend tag is TREND, expiry only. Otherwise
                  the baseline holds cash: no record is written (the ledger has no flat
                  direction; settlement only scores long/short) and the comparison
                  counts it as a 0 return.
  matched_random  direction drawn with P(long) = the source's own long share over its
                  last LONG_SHARE_WINDOW records (today's included; 0.5 when none),
                  seeded by run date + source + ticker; stop / target at the paired
                  decision's percentage distances (mirrored for the drawn direction),
                  same hold, no falsifier.

Rows: source_type "baseline", source_id "baseline:<kind>:<paired source_id>",
meta {"baseline", "pairs_with" (paired entry_id), "pairs_key" [source_id, ticker,
run_date], "run_date", "paired_source_type"}.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import date
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.ledger.trend_tag import TREND

logger = logging.getLogger("marketmind.ledger.baselines")

SOURCE_TYPE = "baseline"
KINDS = ("always_long", "momentum20", "trend", "matched_random")
PAIRED_SOURCES = ("shadow", "main", "main_forced")
MAIN_SOURCES = ("main", "main_forced")
LONG_SHARE_WINDOW = 60
MOMENTUM_BARS = 20
MAX_LEVEL_DISTANCE = 0.9          # a stop / target this far (or farther) is not mirrored
MAX_STALENESS_DAYS = 7            # momentum needs a last bar this recent (as the trend rules)


def source_id_for(kind: str, paired_source_id: str) -> str:
    return f"baseline:{kind}:{paired_source_id}"


def momentum20(bars: Sequence[Bar] | None, today: str | None = None) -> float | None:
    """20-trading-day return on complete bars: close[-1] / close[-21] - 1 (None when the
    history is too short, or older than MAX_STALENESS_DAYS before `today`)."""
    if not bars or len(bars) < MOMENTUM_BARS + 1:
        return None
    if today and (date.fromisoformat(today) - date.fromisoformat(bars[-1].date)).days             > MAX_STALENESS_DAYS:
        return None
    base = bars[-MOMENTUM_BARS - 1].close
    if not base or base <= 0:
        return None
    return bars[-1].close / base - 1


def long_share(store: LedgerStore, source_types: tuple[str, ...], source_id: str,
               today_directions: Sequence[str], window: int = LONG_SHARE_WINDOW) -> float:
    """Long share over the source's last `window` records, today's (not yet written) first."""
    dirs = list(today_directions)[:window]
    if len(dirs) < window:
        try:
            dirs += store.recent_directions(source_types, source_id, window - len(dirs))
        except Exception:
            logger.warning("long share history for %s unreadable; using today's only",
                           source_id, exc_info=True)
    if not dirs:
        return 0.5
    return sum(d == "long" for d in dirs) / len(dirs)


def _reference(e: LedgerEntry, ref_price: float | None) -> float | None:
    """The paired decision's own reference price for its level distances: the zone
    midpoint for a zone entry, else the decision-time close."""
    if e.entry_rule == "zone" and e.entry_low and e.entry_high:
        return (e.entry_low + e.entry_high) / 2
    return ref_price


def _distance(level: float | None, ref: float | None) -> float | None:
    if not level or not ref or ref <= 0:
        return None
    d = abs(level / ref - 1)
    return d if 0 < d < MAX_LEVEL_DISTANCE else None


def mirrored_levels(e: LedgerEntry, direction: str, ref_price: float | None
                    ) -> tuple[float | None, float | None, dict]:
    """(stop, target, distances) at the paired decision's percentage distances, around the
    decision-time close (the baseline enters at the next open like a next_open decision)."""
    ref = _reference(e, ref_price)
    s, t = _distance(e.stop_loss, ref), _distance(e.target_price, ref)
    if not ref_price or ref_price <= 0:
        return None, None, {"stop_pct": s, "target_pct": t, "note": "no decision price"}
    sign = 1.0 if direction == "long" else -1.0
    stop = round(ref_price * (1 - sign * s), 6) if s is not None else None
    target = round(ref_price * (1 + sign * t), 6) if t is not None else None
    return stop, target, {"stop_pct": None if s is None else round(s, 6),
                          "target_pct": None if t is None else round(t, 6)}


def ensure_ids(entries: Sequence[LedgerEntry]) -> None:
    """Assign entry ids before the insert so baselines can name their pair."""
    for e in entries:
        e.entry_id = e.entry_id or uuid.uuid4().hex[:16]


def _row(d: LedgerEntry, kind: str, direction: str, run_date: str, **extra) -> LedgerEntry:
    meta = {"baseline": kind, "pairs_with": d.entry_id or None,
            "pairs_key": [d.source_id, d.ticker, run_date], "run_date": run_date,
            "paired_source_type": d.source_type}
    meta.update(extra.pop("meta", {}))
    return LedgerEntry(
        source_type=SOURCE_TYPE, source_id=source_id_for(kind, d.source_id), ticker=d.ticker,
        direction=direction, hold_bars=d.hold_bars, confidence=0.5, confidence_is_default=True,
        position_usd=d.position_usd, falsifier=f"code baseline ({kind}); no thesis, not advice",
        thesis="", layer=d.layer, asset_type=d.asset_type, entry_rule="next_open",
        domain_benchmark=d.domain_benchmark, snapshot_id=d.snapshot_id, meta=meta, **extra)


def build(decisions: Sequence[LedgerEntry], *, run_date: str, p_long: float,
          bars: dict[str, Sequence[Bar] | None], ref_prices: dict[str, float | None]
          ) -> list[LedgerEntry]:
    """Baseline rows for `decisions` (ids assigned by ensure_ids first). `bars`: complete
    daily bars per ticker (momentum); `ref_prices`: decision-time close per ticker.
    Never raises for one bad decision: it is logged and gets fewer baselines."""
    out: list[LedgerEntry] = []
    seen: dict[str, int] = {}
    for d in decisions:
        if d.source_type not in PAIRED_SOURCES:
            continue
        try:
            out.extend(_for_one(d, run_date, p_long, bars, ref_prices, seen))
        except Exception:
            logger.error("baselines for %s %s failed; decision recorded without them",
                         d.source_id, d.ticker, exc_info=True)
    return out


def _for_one(d: LedgerEntry, run_date: str, p_long: float, bars: dict, ref_prices: dict,
             seen: dict[str, int]) -> list[LedgerEntry]:
    rows = [_row(d, "always_long", "long", run_date)]
    t = d.ticker.upper()
    mom = momentum20(bars.get(d.ticker) or bars.get(t), run_date)
    if mom is not None and mom != 0:
        rows.append(_row(d, "momentum20", "long" if mom > 0 else "short", run_date,
                         meta={"momentum20": round(mom, 6)}))
    tag = (d.meta or {}).get("trend")
    if isinstance(tag, dict) and tag.get("state") == TREND:
        rows.append(_row(d, "trend", "long", run_date, meta={"trend_as_of": tag.get("as_of")}))
    seed = f"{run_date}:{d.source_id}:{t}"
    n = seen.get(seed, 0)
    seen[seed] = n + 1
    if n:                                   # the same ticker twice in one submission
        seed = f"{seed}:{n + 1}"
    direction = "long" if random.Random(seed).random() < p_long else "short"
    ref = ref_prices.get(d.ticker) or ref_prices.get(t)
    stop, target, dist = mirrored_levels(d, direction, ref)
    rows.append(_row(d, "matched_random", direction, run_date, stop_loss=stop,
                     target_price=target,
                     meta={"seed": seed, "p_long": round(p_long, 6), **dist}))
    for r in rows:
        r.validate()
    return rows


def tag_and_build(store: LedgerStore, records: list[LedgerEntry],
                  daily: dict[str, Sequence[Bar] | None], tagger, ref_prices: dict, today: str,
                  with_baselines: bool, sources: dict[str, str] | None = None,
                  long_share_sources: tuple[str, ...] | None = None) -> list[LedgerEntry]:
    """Set meta["trend"] on every record (annotate only, ledger.trend_tag) and return the
    paired code baselines when `with_baselines`. `daily`: raw daily bars per ticker (a
    partial last bar is dropped here). Never raises: a failure is logged, the record is
    tagged UNAVAILABLE and goes in without (some) baselines."""
    from marketmind.gateway.price_history import complete_bars
    from marketmind.ledger.trend_tag import unavailable
    for r in records:
        bars = daily.get(r.ticker)
        try:
            tag = (tagger.tag(r.ticker, bars, (sources or {}).get(r.ticker))
                   if tagger is not None else unavailable("trend tagger not available"))
        except Exception as exc:
            logger.error("trend tag for %s failed", r.ticker, exc_info=True)
            tag = unavailable(f"tag error: {type(exc).__name__}")
        r.meta = {**(r.meta or {}), "trend": tag}
    if not with_baselines or not records:
        return []
    try:
        ensure_ids(records)
        first = records[0]
        p_long = long_share(store, long_share_sources or (first.source_type,), first.source_id,
                            [r.direction for r in records])
        done = {t: complete_bars(t, list(b)) if b else None for t, b in daily.items()}
        return build(records, run_date=today, p_long=p_long, bars=done, ref_prices=ref_prices)
    except Exception:
        logger.error("baselines for %s not built", records[0].source_id, exc_info=True)
        return []
