"""Code baseline rows never change promotion, ecosystem, consensus or other scores
(docs/S7_DESIGN.md §六: ledger only, shown only in the comparison view)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

from marketmind.ledger.baselines import KINDS
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import metrics as M
from marketmind.promotion.ladder import default_calendar, trial_ids
from marketmind.promotion.runner import run_promotion
from marketmind.tests.test_promotion.test_promotion import BARS, DAYS, _roster, _world


def _saturday_after(day: str) -> str:
    d = date.fromisoformat(day)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d.isoformat()


def _baselines_for(rows: list[LedgerEntry]) -> list[LedgerEntry]:
    """Settled baseline rows paired with every decision, exiting on dates no other row
    exits on (a Saturday) and with large P&L, to stress calendars and scores."""
    out = []
    for e in rows:
        if e.source_type not in ("shadow", "main", "main_forced"):
            continue
        for i, kind in enumerate(KINDS):
            out.append(replace(
                e, source_type="baseline", source_id=f"baseline:{kind}:{e.source_id}",
                entry_id="", direction="short" if i % 2 else "long",
                exit_date=_saturday_after(e.exit_date), net_return=0.5, pnl_usd=500.0,
                confidence_is_default=True,
                meta={"baseline": kind, "pairs_with": e.entry_id, "run_date": e.created_at[:10]}))
    return out


def _store(path, rows):
    store = LedgerStore(path)
    for e in rows:
        store.add(replace(e), created_at=e.created_at)
    return store


def test_list_hides_baselines_unless_asked(tmp_path):
    rows = _world(days=5)
    store = _store(tmp_path / "l.db", rows + _baselines_for(rows))
    assert not any(e.source_type == "baseline" for e in store.list())
    assert not any(e.source_type == "baseline" for e in store.list(status="settled"))
    assert len(store.list(source_type="baseline")) == 5 * 3 * len(KINDS)    # A, B, main
    assert len(store.list(include_baselines=True)) == len(rows) + 5 * 3 * len(KINDS)


def test_promotion_outputs_unchanged_by_baselines(tmp_path):
    rows = _world(days=90)
    extra = _baselines_for(rows)
    # pure functions given every row (as a raw reader would)
    for day in (DAYS[30], DAYS[81]):
        assert default_calendar(rows + extra, day) == default_calendar(rows, day)
    assert M.trading_calendar(rows + extra) == M.trading_calendar(rows)
    assert trial_ids(rows + extra) == trial_ids(rows)

    outs, states = [], []
    for name, data in (("plain", rows), ("with", rows + extra)):
        root = tmp_path / name
        store = _store(root / "ledger.db", data)
        kw = dict(data_dir=root, roster=_roster("A", "B"), active_ids={"A", "B"},
                  price_source=StaticPriceSource(BARS))
        for day in (DAYS[10], DAYS[60]):
            run_promotion(store, today=day, **kw)
        outs.append(run_promotion(store, today=DAYS[81], **kw))
        states.append((root / "promotion" / "state.json").read_text(encoding="utf-8"))
    assert outs[0] == outs[1]
    assert states[0] == states[1]


def test_ecosystem_and_consensus_unchanged_by_baselines(tmp_path):
    from marketmind.ecosystem import run_ecosystem
    from marketmind.shadows.v3 import roster, runner
    days = ("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")
    docs, consensus = [], []
    for name in ("plain", "with"):
        root = tmp_path / name
        store = LedgerStore(root / "ledger.db")
        for i, d in enumerate(days):
            for j, r in enumerate(roster.active(root)):
                e = LedgerEntry(source_type="shadow", source_id=r.shadow_id, ticker="SPY",
                                direction="long" if (i + j) % 3 else "short", hold_bars=1,
                                confidence=0.55, position_usd=100.0, falsifier="x",
                                status="settled", exit_date=days[min(i + 1, 3)],
                                net_return=0.01, pnl_usd=1.0,
                                meta={"run_date": d, "llm": "m"})
                eid = store.add(e, created_at=f"{d}T15:00:00Z")
                if name == "with":
                    for kind in KINDS:
                        store.add(replace(e, entry_id="", source_type="baseline",
                                          source_id=f"baseline:{kind}:{r.shadow_id}",
                                          direction="short", exit_date="2026-01-10",
                                          pnl_usd=50.0, net_return=0.5,
                                          meta={"baseline": kind, "pairs_with": eid,
                                                "run_date": d}),
                                  created_at=f"{d}T15:00:00Z")
        (root / "trend").mkdir()
        for d in days:
            (root / "trend" / f"{d}.json").write_text(
                json.dumps({"full": {"SPY": {"state": "WATCH"}}}), encoding="utf-8")
        doc = run_ecosystem(root, today=days[-1], write=False)
        doc.pop("written_at", None)
        docs.append(doc)
        consensus.append(sorted(runner._previous_consensus(store, days[-1])))   # ids are random
    assert docs[0] == docs[1]
    assert consensus[0] == consensus[1] and consensus[0]


def test_other_consumers_never_see_baselines(tmp_path, monkeypatch):
    """Arena scores, the raw ledger view, the reporter's context source and the self-
    feedback experiment ignore baseline rows; only the comparison block uses them."""
    from marketmind.api import whitebox
    from marketmind.shadows.v3.self_feedback import compare_arms
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    rows = _world(days=5)
    store = _store(tmp_path / "ledger.db", rows + _baselines_for(rows))
    arena = whitebox.get_arena()
    assert not [s for s in arena["other_sources"] if s["source_type"] == "baseline"]
    assert arena["comparison"] is not None
    led = whitebox.get_ledger(limit=500)
    assert led["total"] == len(rows)
    assert whitebox.get_ledger(source_type="baseline")["total"] == 5 * 3 * len(KINDS)
    every = store.list(include_baselines=True)
    assert compare_arms(every) == compare_arms(store.list())
