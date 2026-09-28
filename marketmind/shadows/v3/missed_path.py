"""missed_path temporary shadow (docs/S7_DESIGN.md §二, SPEC_v3 §6.3, C17).

Pure code, no LLM: every L2 candidate or L3 green light the main pipeline did not
turn into a trade card becomes a virtual long for 30 trading days, so the value
of "passing" can be measured. Only instruments the owner can execute. Rejected
big-move alerts are the other missed path; they settle as their own alert
records (marketmind/alerts).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.shadows.v3.missed_path")

SOURCE_ID = "missed_path:main"
HOLD_BARS = 30
POSITION_USD = 100.0


def candidates(brief: dict) -> list[tuple[str, str]]:
    """(ticker, where it came from) the main pipeline considered but did not trade."""
    carded = {str(c.get("ticker", "")).upper() for c in brief.get("decision_cards") or []
              if isinstance(c, dict)}
    out: dict[str, str] = {}
    for t in brief.get("l3_green") or []:
        out.setdefault(str(t).upper(), "L3 绿灯未成卡")
    for t in brief.get("l2_ticker_candidates") or []:
        out.setdefault(str(t).upper(), "L2 候选未成卡")
    return [(t, why) for t, why in out.items() if t and t not in carded]


def record(store: LedgerStore, brief: dict, *, today: str | None = None, tradable=None,
           quotes: dict | None = None) -> list[str]:
    """Write today's missed-path records once; returns the new entry ids."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if tradable is None:
        from marketmind.pipeline.decision_guard import is_robinhood_tradable as tradable
    done = {e.ticker.upper() for e in store.list(source_type="temp_shadow")
            if e.source_id == SOURCE_ID and (e.meta or {}).get("run_date") == today}
    from marketmind.ledger.recorder import classify_ticker
    snapshot_id = store.save_snapshot(quotes) if quotes else None
    ids = []
    for ticker, why in candidates(brief):
        if ticker in done or not tradable(ticker):
            continue
        layer, asset_type = classify_ticker(ticker)
        ids.append(store.add(LedgerEntry(
            source_type="temp_shadow", source_id=SOURCE_ID, ticker=ticker, direction="long",
            hold_bars=HOLD_BARS, confidence=0.5, confidence_is_default=True,
            position_usd=POSITION_USD, falsifier="持有期内净收益为负（放弃是对的）",
            thesis=f"主管线放弃的候选（{why}），记录放弃的代价", layer=layer,
            asset_type=asset_type, entry_rule="next_open", snapshot_id=snapshot_id,
            meta={"run_date": today, "temp": "missed_path", "reason": why,
                  "brief_date": brief.get("date")})))
    return ids
