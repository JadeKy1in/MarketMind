"""Paired ledger-only counterfactual for the L3 target rule (owner decision 2026-10-22).

The live L3 target (nearest swing high, capped) often leaves green lights at R/R < 1;
the owner keeps the live rule and records the alternative target_v2
(pipeline.l3_indicators.alt_target) next to it so the data can decide later.

Every daily run, for each L3 ticker whose target_v2 differs from the live target, two
rows with the same entry zone, stop, hold and size, one per target:

  source_id "baseline:l3_target_v1"  live target (target_price)
  source_id "baseline:l3_target_v2"  target_v2

Which tickers: data available, light green or yellow (red = avoid, never an L3 trade),
usable levels (entry zone, stop below it, target above close). Yellow is included
because greens are rare and their target_v2 usually equals the live one (dry run
2026-10-22: 0 of 3 greens differed, 22 of 41 yellows did), so greens alone would
take years to reach a testable sample. At most MAX_PAIRS_PER_DAY pairs (greens first,
then lowest live R/R, then ticker).

Rows are source_type "baseline" (store.COMPARISON_SOURCES): settled like every record,
hidden from list() by default, so promotion, ecosystem, consensus, alerts, arena scores
never see them; ledger.comparison ignores them (meta.baseline is not one of its KINDS).
Read them with ledger.l3_target_compare.

Idempotent: one add_submission per market, so the ledger's one-submission-per-session
rule (docs/S2_DESIGN.md §4) applies per source and market; a rerun of the same session
writes nothing (both versions are in one transaction, never half a pair).
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone

from marketmind.ledger.prices import PriceSource, latest_quotes
from marketmind.ledger.settlement import target_session
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.ledger.l3_target_pairs")

SOURCE_TYPE = "baseline"
VERSIONS = ("v1", "v2")
KIND = {"v1": "l3_target_v1", "v2": "l3_target_v2"}
SOURCE_IDS = {v: f"baseline:{k}" for v, k in KIND.items()}
LIGHTS = ("green", "yellow")
MAX_PAIRS_PER_DAY = 12             # <= 24 rows / day
POSITION_USD = 1_000.0             # size is irrelevant to the comparison (returns, R)


def _usable(r) -> bool:
    try:
        close, lo, hi, stop = (float(r.close), float(r.entry_zone_low),
                               float(r.entry_zone_high), float(r.stop_loss))
        t1, t2 = float(r.target_price), float(r.target_price_v2)
    except (TypeError, ValueError, AttributeError):
        return False
    vals = (close, lo, hi, stop, t1, t2)
    return (all(math.isfinite(x) and x > 0 for x in vals) and stop < lo <= hi
            and t1 > close and t2 > close)


def select(results) -> list:
    """L3 results to pair today (see module doc), in priority order."""
    picked = [r for r in results
              if getattr(r, "data_available", False) and getattr(r, "light", "") in LIGHTS
              and _usable(r) and float(r.target_price_v2) > float(r.target_price) + 1e-9]
    picked.sort(key=lambda r: (r.light != "green", r.reward_risk_ratio, r.ticker))
    if len(picked) > MAX_PAIRS_PER_DAY:
        logger.info("L3 target pairs: %d candidates, keeping %d", len(picked), MAX_PAIRS_PER_DAY)
    return picked[:MAX_PAIRS_PER_DAY]


def build_pair(r, run_date: str, snapshot_id: str | None = None) -> list[LedgerEntry]:
    """The v1 / v2 rows for one L3 result (same entry, stop, hold, size)."""
    from marketmind.ledger.recorder import classify_ticker
    layer, asset_type = classify_ticker(r.ticker)
    pair_id = uuid.uuid4().hex[:16]
    l3 = {"light": r.light, "recommendation": r.recommendation, "as_of": r.as_of,
          "close": r.close, "target_v1": r.target_price, "target_v2": r.target_price_v2,
          "rr_v1": r.reward_risk_ratio, "rr_v2": r.reward_risk_ratio_v2,
          "levels_skipped": r.target_v2_levels_skipped}
    rows = []
    for v in VERSIONS:
        target = r.target_price if v == "v1" else r.target_price_v2
        e = LedgerEntry(
            source_type=SOURCE_TYPE, source_id=SOURCE_IDS[v], ticker=r.ticker.upper(),
            direction="long", hold_bars=max(1, int(r.max_hold_days or 1)),
            confidence=0.5, confidence_is_default=True, position_usd=POSITION_USD,
            falsifier=f"code counterfactual (L3 target {v}); no thesis, not advice",
            layer=layer, asset_type=asset_type, entry_rule="zone",
            entry_low=r.entry_zone_low, entry_high=r.entry_zone_high,
            stop_loss=r.stop_loss, target_price=target, snapshot_id=snapshot_id,
            meta={"baseline": KIND[v], "counterfactual": "l3_target", "version": v,
                  "pair_id": pair_id, "pairs_key": [r.ticker.upper(), run_date],
                  "run_date": run_date, "l3": l3})
        e.validate()
        rows.append(e)
    return rows


def _market(ticker: str) -> str:
    from marketmind.markets import market_for
    return market_for(ticker).code


def _already_recorded(store: LedgerStore, probe: LedgerEntry, created_at: str) -> bool:
    """Cheap pre-check (add_submission stays the atomic one): does either source already
    have a row for this market's target session?"""
    want = target_session(probe)
    mkt = _market(probe.ticker)
    for sid in SOURCE_IDS.values():
        for e in store.recent(SOURCE_TYPE, sid, created_at):
            if _market(e.ticker) == mkt and target_session(e) == want:
                return True
    return False


async def record_pairs(l3, store: LedgerStore, source: PriceSource | None = None,
                       created_at: str | None = None) -> int:
    """Write today's pairs; returns the number of rows written (0 on a rerun).
    Never raises for one bad ticker or market: logged, the rest goes in."""
    results = list(getattr(l3, "results", None) or [])
    chosen = select(results)
    if not chosen:
        return 0
    created_at = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_date = created_at[:10]
    by_market: dict[str, list[LedgerEntry]] = {}
    for r in chosen:
        try:
            pair = build_pair(r, run_date)
        except Exception:
            logger.error("L3 target pair for %s not built", r.ticker, exc_info=True)
            continue
        for e in pair:
            e.created_at = created_at
        by_market.setdefault(_market(r.ticker), []).extend(pair)
    # drop markets whose session is already in (resume / second run): no quote fetch
    todo = {}
    for mkt, rows in by_market.items():
        if _already_recorded(store, rows[0], created_at):
            logger.info("L3 target pairs: %s session already recorded; skipped", mkt)
        else:
            todo[mkt] = rows
    if not todo:
        return 0
    if source is not None:
        try:
            tickers = [e.ticker for rows in todo.values() for e in rows]
            snapshot_id = store.save_snapshot(await latest_quotes(source, tickers),
                                              taken_at=created_at)
            for rows in todo.values():
                for e in rows:
                    e.snapshot_id = snapshot_id
        except Exception:
            logger.warning("L3 target pairs: snapshot failed; rows go in without one",
                           exc_info=True)
    written = 0
    for mkt, rows in todo.items():
        try:
            ids = store.add_submission(rows, target_session, created_at=created_at)
        except Exception:
            logger.error("L3 target pairs for %s not recorded", mkt, exc_info=True)
            continue
        if ids is None:
            logger.info("L3 target pairs: %s session already recorded; nothing written", mkt)
            continue
        written += len(ids)
    logger.info("L3 target pairs: %d rows (%d pairs) recorded, ledger only", written, written // 2)
    return written
