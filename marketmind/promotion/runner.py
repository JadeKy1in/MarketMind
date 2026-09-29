"""Daily promotion review (docs/S7_DESIGN.md §一): ledger -> state.json, events.jsonl, advisors.json.

Files under `data_dir` (default env MARKETMIND_DATA_DIR or "data"):
- promotion/state.json   each shadow's stage, gates, metrics, latest evaluation
- promotion/events.jsonl promote / pause / resume / challenge, one JSON object per line
- advisors.json          {"updated_at": ..., "advisors": [shadow ids]} read by the S8 alerts

DSR trials (fix 2026-09-29): every promotion candidate ever in the ledger (long-term
shadows, Playground agents, challenger / beta variants; SPEC §8 "全部历史试验次数"),
reduced to an effective number by clustering on return correlation
(ladder.trial_ids, metrics.effective_trials). Event shadows and missed_path are not
candidates and no longer count. `trial_count` below is the raw candidate count.

Bars for the Monte Carlo "beats random" gate come from `price_source` (default: the
ledger's HistoryPriceSource, which shares the per-process price cache with settlement
and the shadow run); they are only loaded when a probation shadow has reached the
days gate.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import config as C
from marketmind.promotion.ladder import advisors, evaluate, trial_ids
from marketmind.promotion.random_mc import source_loader
from marketmind.shadows.v3.roster import ROSTER

log = logging.getLogger(__name__)

def trial_count(entries: list[LedgerEntry]) -> int:
    """Raw number of promotion candidates ever in the ledger (at least 1)."""
    return max(1, len(trial_ids(entries)))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_promotion(store: LedgerStore, *, today: str | None = None,
                  data_dir: str | Path | None = None, roster=ROSTER,
                  active_ids: set[str] | None = None, price_source=None) -> dict:
    """Evaluate the ladder for `today` (UTC date by default) and persist the results."""
    live = today is None
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if price_source is None:
        from marketmind.ledger.prices import HistoryPriceSource
        price_source = HistoryPriceSource()
    bars_for = source_loader(price_source, today=today, live=live)
    root = Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data"))
    state_path = root / "promotion" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    entries = store.list()
    trials = trial_count(entries)
    new_state, events = evaluate(entries, list(roster), today, state,
                                 active_ids=active_ids, bars_for=bars_for)
    new_state["trial_count"] = trials
    _write_json(state_path, new_state)

    if events:
        events_path = root / "promotion" / "events.jsonl"
        with events_path.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    names = advisors(new_state)
    _write_json(root / "advisors.json", {"updated_at": today, "advisors": names})
    log.info("promotion %s: %d events, advisors=%s", today, len(events), names)

    shadows = new_state["shadows"]
    return {
        "date": today,
        "stages": dict(Counter(r["stage"] for r in shadows.values())),
        "probation_progress": {sid: r.get("metrics", {}).get("record_days", 0)
                               for sid, r in shadows.items() if r["stage"] == "probation"},
        "advisors": names,
        "events": events,
        "trial_count": trials,
        "thresholds": C.thresholds(),
    }
