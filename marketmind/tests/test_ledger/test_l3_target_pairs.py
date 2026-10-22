"""L3 target v1 / v2 counterfactual pairs (ledger/l3_target_pairs.py, l3_target_compare.py):
selection, paired rows, idempotency per session and market, exclusion from every score,
settlement, and the comparison math."""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace

import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger import comparison, l3_target_compare as C, l3_target_pairs as P
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.settlement import settle_all
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline.layer3_technical import Layer3BatchResult, Layer3Result
from marketmind.tests.test_ledger.test_baseline_exclusion import _saturday_after, _store
from marketmind.tests.test_promotion.test_promotion import BARS, DAYS, _roster, _world


def l3(ticker, light="yellow", close=100.0, stop=96.0, t1=102.0, t2=108.0, rr=0.5,
       available=True, **kw) -> Layer3Result:
    return Layer3Result(
        ticker=ticker, light=light, above_200wma=True, daily_structure_intact=False,
        near_key_resistance=False, resistance_distance_pct=5.0,
        support_zone_low=97.0, support_zone_high=98.0, resistance_zone_low=110.0,
        resistance_zone_high=110.0, entry_zone_low=98.0, entry_zone_high=100.5,
        stop_loss=stop, target_price=t1, max_hold_days=30, reward_risk_ratio=rr,
        recommendation="wait" if light != "red" else "avoid", close=close, as_of="2026-10-21",
        data_available=available, target_price_v2=t2,
        reward_risk_ratio_v2=None if t2 is None else round((t2 - close) / (close - stop), 2),
        target_v2_levels_skipped=1, **kw)


def run(coro):
    return asyncio.run(coro)


# ── selection ───────────────────────────────────────────────────────────

def test_select_green_and_yellow_with_a_different_usable_v2():
    rs = [l3("Y1"), l3("G1", light="green", rr=0.9), l3("R1", light="red"),
          l3("SAME", t2=102.0), l3("NOV2", t2=None), l3("NODATA", available=False),
          l3("BADSTOP", stop=99.0), l3("Y0", rr=0.3)]
    assert [r.ticker for r in P.select(rs)] == ["G1", "Y0", "Y1"]   # greens first, then R/R


def test_select_caps_the_daily_volume():
    rs = [l3(f"T{i:02d}", rr=1.0 - i / 100) for i in range(20)]
    got = P.select(rs)
    assert len(got) == P.MAX_PAIRS_PER_DAY
    assert got[0].ticker == "T19"                                   # lowest live R/R first


# ── recording ───────────────────────────────────────────────────────────

WED_EVENING = "2026-10-21T22:00:00Z"        # US session 10-22


def _bars(ticker, closes, start="2026-10-14"):
    import datetime as dt
    d, out = dt.date.fromisoformat(start), []
    for c in closes:
        while d.weekday() >= 5 and not ticker.endswith("-USD"):
            d += dt.timedelta(days=1)
        out.append(Bar(d.isoformat(), c, c * 1.01, c * 0.99, c, 1_000_000))
        d += dt.timedelta(days=1)
    return out


def test_pairs_are_written_once_per_session(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    batch = Layer3BatchResult(results=[l3("AAA"), l3("BBB", light="green"), l3("CCC", light="red")])
    src = StaticPriceSource({"AAA": _bars("AAA", [100] * 5), "BBB": _bars("BBB", [100] * 5)})
    assert run(P.record_pairs(batch, store, src, created_at=WED_EVENING)) == 4
    rows = store.list(source_type="baseline")
    assert len(rows) == 4
    by_pair = {}
    for e in rows:
        by_pair.setdefault(e.meta["pair_id"], {})[e.meta["version"]] = e
    assert len(by_pair) == 2
    for p in by_pair.values():
        a, b = p["v1"], p["v2"]
        assert (a.source_id, b.source_id) == ("baseline:l3_target_v1", "baseline:l3_target_v2")
        assert (a.target_price, b.target_price) == (102.0, 108.0)
        for f in ("ticker", "entry_rule", "entry_low", "entry_high", "stop_loss", "hold_bars",
                  "position_usd", "direction", "created_at", "snapshot_id"):
            assert getattr(a, f) == getattr(b, f), f
        assert a.entry_rule == "zone" and a.hold_bars == 30 and a.snapshot_id
        assert a.confidence_is_default and a.meta["run_date"] == "2026-10-21"
        assert a.meta["l3"]["target_v2"] == 108.0 and a.meta["baseline"] == "l3_target_v1"
    # a rerun of the same session (same evening, or the next morning before the open)
    assert run(P.record_pairs(batch, store, src, created_at="2026-10-21T23:30:00Z")) == 0
    assert run(P.record_pairs(batch, store, src, created_at="2026-10-22T03:00:00Z")) == 0
    assert len(store.list(source_type="baseline")) == 4
    # the next session records again
    assert run(P.record_pairs(batch, store, src, created_at="2026-10-22T22:00:00Z")) == 4


def test_add_submission_is_the_atomic_guard(tmp_path, monkeypatch):
    """Even when the pre-check is bypassed, a repeated session writes nothing."""
    store = LedgerStore(tmp_path / "ledger.db")
    batch = Layer3BatchResult(results=[l3("AAA")])
    assert run(P.record_pairs(batch, store, None, created_at=WED_EVENING)) == 2
    monkeypatch.setattr(P, "_already_recorded", lambda *a: False)
    assert run(P.record_pairs(batch, store, None, created_at=WED_EVENING)) == 0
    assert len(store.list(source_type="baseline")) == 2


def test_markets_are_deduplicated_separately(tmp_path):
    """Friday evening, then Saturday: US is still Monday's session (skipped), crypto is a
    new UTC day (recorded)."""
    store = LedgerStore(tmp_path / "ledger.db")
    batch = Layer3BatchResult(results=[l3("AAA"), l3("BTC-USD", light="green")])
    assert run(P.record_pairs(batch, store, None, created_at="2026-10-23T22:00:00Z")) == 4
    assert run(P.record_pairs(batch, store, None, created_at="2026-10-24T22:00:00Z")) == 2
    rows = store.list(source_type="baseline")
    assert sorted(e.ticker for e in rows) == ["AAA", "AAA", "BTC-USD", "BTC-USD", "BTC-USD",
                                              "BTC-USD"]


def test_nothing_to_pair_writes_nothing(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    assert run(P.record_pairs(Layer3BatchResult(), store, None)) == 0
    assert run(P.record_pairs(None, store, None)) == 0
    assert run(P.record_pairs(Layer3BatchResult(results=[l3("X", t2=102.0)]), store, None)) == 0
    assert store.list(include_baselines=True) == []


def test_pairs_settle_like_every_record(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    batch = Layer3BatchResult(results=[l3("AAA")])
    run(P.record_pairs(batch, store, None, created_at=WED_EVENING))
    # 10-22 fills in the zone at the open 100; 10-23 high 104.04 hits v1 (102) only;
    # the stop 96 is never touched; v2 (108) runs to expiry (hold 2 for the test)
    for e in store.list(source_type="baseline"):
        e.hold_bars = 2
        store.update(e)
    bars = _bars("AAA", [100] * 7 + [103, 100], start="2026-10-14")   # 10-14 .. 10-26
    report = run(settle_all(store, StaticPriceSource({"AAA": bars, "SPY": bars}),
                            today="2026-10-30"))
    assert report is not None
    got = {e.meta["version"]: e for e in store.list(source_type="baseline")}
    assert got["v1"].status == got["v2"].status == "settled"
    assert got["v1"].exit_reason == "target" and got["v2"].exit_reason == "expiry"


# ── exclusion: no score, calendar, view or voter changes ────────────────

def _pairs_for(rows: list[LedgerEntry]) -> list[LedgerEntry]:
    """Settled v1 / v2 rows next to every main record, exiting on Saturdays with big P&L."""
    out = []
    for e in rows:
        if e.source_type not in ("main", "main_forced"):
            continue
        pid = f"p{len(out)}"
        for v in P.VERSIONS:
            out.append(replace(
                e, source_type="baseline", source_id=P.SOURCE_IDS[v], entry_id="",
                exit_date=_saturday_after(e.exit_date), net_return=0.5, pnl_usd=500.0,
                confidence_is_default=True, exit_reason="target",
                meta={"baseline": P.KIND[v], "version": v, "pair_id": pid,
                      "counterfactual": "l3_target", "run_date": e.created_at[:10]}))
    return out


def test_promotion_and_comparison_unchanged_by_pairs(tmp_path):
    from marketmind.promotion.runner import run_promotion
    rows = _world(days=90)
    extra = _pairs_for(rows)
    assert extra
    outs, states = [], []
    for name, data in (("plain", rows), ("with", rows + extra)):
        root = tmp_path / name
        store = _store(root / "ledger.db", data)
        assert len(store.list()) == len(rows)
        kw = dict(data_dir=root, roster=_roster("A", "B"), active_ids={"A", "B"},
                  price_source=StaticPriceSource(BARS))
        for day in (DAYS[10], DAYS[60]):
            run_promotion(store, today=day, **kw)
        outs.append(run_promotion(store, today=DAYS[81], **kw))
        states.append((root / "promotion" / "state.json").read_text(encoding="utf-8"))
        if name == "with":
            # the LLM-vs-code-baseline comparison is not polluted either
            every = store.list(include_baselines=True)
            assert comparison.compute(every) == comparison.compute(store.list())
    assert outs[0] == outs[1]
    assert states[0] == states[1]


def test_ecosystem_alert_inputs_and_arena_ignore_pairs(tmp_path, monkeypatch):
    from marketmind.api import whitebox
    from marketmind.ecosystem import run_ecosystem
    from marketmind.ecosystem.runner import load_entries
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    rows = _world(days=5)
    store = _store(tmp_path / "ledger.db", rows + _pairs_for(rows))
    assert {e.source_type for e in load_entries(tmp_path / "ledger.db")} == \
        {e.source_type for e in rows}
    arena = whitebox.get_arena()
    assert not [s for s in arena["other_sources"] if s["source_type"] == "baseline"]
    assert whitebox.get_ledger(limit=500)["total"] == len(rows)
    doc = run_ecosystem(tmp_path, today=DAYS[4], write=False)
    plain = tmp_path / "plain"
    _store(plain / "ledger.db", rows)
    doc2 = run_ecosystem(plain, today=DAYS[4], write=False)
    for d in (doc, doc2):
        d.pop("written_at", None)
    assert doc == doc2
    # alerts voters and holdings read store.list(): no pair rows
    assert not [e for e in store.list() if e.source_type == "baseline"]


# ── comparison math ─────────────────────────────────────────────────────

def _settled(v, pid, day, net, reason, entry=100.0, stop=96.0, status="settled", factor=None):
    meta = {"baseline": P.KIND[v], "version": v, "pair_id": pid, "run_date": day}
    if factor:
        meta["price_factor"] = factor
    return LedgerEntry(source_type="baseline", source_id=P.SOURCE_IDS[v], ticker="AAA",
                       direction="long", hold_bars=10, confidence=0.5, position_usd=1000.0,
                       falsifier="x", entry_rule="zone", entry_low=98, entry_high=100.5,
                       stop_loss=stop, status=status, entry_price=entry if status == "settled" else None,
                       net_return=net if status == "settled" else None,
                       exit_reason=reason, created_at=f"{day}T22:00:00Z", meta=meta)


def _sample():
    return [
        # day 1: two pairs
        _settled("v1", "a", "2026-10-01", 0.02, "target"), _settled("v2", "a", "2026-10-01", 0.04, "expiry"),
        _settled("v1", "b", "2026-10-01", 0.02, "target"), _settled("v2", "b", "2026-10-01", -0.04, "stop"),
        # day 2: one pair
        _settled("v1", "c", "2026-10-02", -0.04, "stop"), _settled("v2", "c", "2026-10-02", -0.04, "stop"),
        # day 3: one pair, a split later (stop in the settled series = 96 * 0.5 = 48, entry 50)
        _settled("v1", "d", "2026-10-03", 0.01, "target", entry=50.0, factor=0.5),
        _settled("v2", "d", "2026-10-03", 0.06, "target", entry=50.0, factor=0.5),
        # open pair and a void pair: not compared
        _settled("v1", "e", "2026-10-04", None, None, status="open"),
        _settled("v2", "e", "2026-10-04", None, None, status="open"),
        _settled("v1", "f", "2026-10-04", None, "gap_target", status="void"),
        _settled("v2", "f", "2026-10-04", None, None, status="open"),
        # a lone row (its mate missing) is ignored
        _settled("v2", "g", "2026-10-04", 0.5, "target"),
    ]


def test_r_multiple_uses_the_settled_series_stop():
    assert C.r_multiple(_settled("v1", "a", "d", 0.02, "target")) == pytest.approx(0.5)
    split = _settled("v1", "d", "d", 0.01, "target", entry=50.0, factor=0.5)
    assert C.r_multiple(split) == pytest.approx(0.01 / (2 / 50))
    assert C.r_multiple(_settled("v1", "e", "d", None, None, status="open")) is None


def test_compare_per_version_and_day_clustered_difference():
    c = C.compare(_sample())
    assert c["pairs_total"] == 6 and c["pairs_settled"] == 4 and c["pairs_open"] == 2
    assert c["voids"] == {"v1": 1, "v2": 0}
    assert c["days"] == 3 and (c["first_day"], c["last_day"]) == ("2026-10-01", "2026-10-03")
    v1, v2 = c["v1"], c["v2"]
    assert v1["n"] == v2["n"] == 4
    assert v1["hit_target_rate"] == 0.75 and v2["hit_target_rate"] == 0.25
    assert v1["mean_net_return"] == pytest.approx((0.02 + 0.02 - 0.04 + 0.01) / 4)
    assert v2["mean_net_return"] == pytest.approx((0.04 - 0.04 - 0.04 + 0.06) / 4)
    assert v1["mean_r"] == pytest.approx((0.5 + 0.5 - 1.0 + 0.25) / 4, abs=1e-4)
    assert v2["mean_r"] == pytest.approx((1.0 - 1.0 - 1.0 + 1.5) / 4, abs=1e-4)
    pd = c["paired_diff"]
    assert pd["mean_pair_diff"] == pytest.approx((0.02 - 0.06 + 0 + 0.05) / 4)
    assert pd["v2_better_share"] == 0.5
    t = pd["day_clustered"]
    # day means: 10-01 (0.02 - 0.06) / 2 = -0.02, 10-02 0, 10-03 0.05
    assert t["days"] == 3
    assert t["mean_daily_diff"] == pytest.approx((-0.02 + 0 + 0.05) / 3)
    from marketmind.promotion.metrics import hac_t_test
    ref = hac_t_test([-0.02, 0.0, 0.05], t["lag"])
    assert t["t"] == pytest.approx(ref["t"]) and t["p_v2_better"] == ref["p_value"]
    assert t["p_v1_better"] == hac_t_test([0.02, 0.0, -0.05], t["lag"])["p_value"]
    assert "v1" in C.format_report(c)


def test_compare_empty_and_single_day():
    c = C.compare([])
    assert c["pairs_total"] == 0 and c["v1"]["n"] == 0 and c["paired_diff"]["day_clustered"] is None
    one = C.compare(_sample()[:4])
    assert one["days"] == 1 and one["paired_diff"]["day_clustered"] is None
    assert "未检验" in C.format_report(one)


def test_load_rows_is_read_only(tmp_path, capsys):
    db = tmp_path / "ledger.db"
    store = LedgerStore(db)
    for e in _sample():
        store.add(e, created_at=e.created_at)
    store.add(LedgerEntry(source_type="main", source_id="main_pipeline", ticker="SPY",
                          direction="long", hold_bars=10, confidence=0.5, position_usd=1.0,
                          falsifier="x"))
    before = db.read_bytes()
    rows = C.load_rows(db)
    assert len(rows) == len(_sample()) and all(e.source_type == "baseline" for e in rows)
    assert C.compare(rows) == C.compare(_sample())
    assert C.main(["--db", str(db)]) == 0
    assert "L3 目标价" in capsys.readouterr().out
    assert db.read_bytes() == before
    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM ledger")
    conn.close()


# ── daily-run hook ──────────────────────────────────────────────────────

def test_hook_runs_after_the_main_record_and_never_raises(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from marketmind.ledger import recorder
    from marketmind.pipeline import orchestration as O
    config = SimpleNamespace(data_dir=str(tmp_path))
    batch = Layer3BatchResult(results=[l3("AAA")])

    async def main_fails(*a, **k):
        raise RuntimeError("main record broke")
    monkeypatch.setattr(recorder, "record_main_decision", main_fails)
    from marketmind.ledger import prices
    monkeypatch.setattr(prices, "HistoryPriceSource",
                        lambda: StaticPriceSource({"AAA": _bars("AAA", [100] * 5)}))
    monkeypatch.setattr(O, "_step_failures", [])
    run(O._record_to_ledger(config, None, batch))
    assert O._step_failures == ["ledger record"]            # the pairs add no failure
    rows = LedgerStore(tmp_path / "ledger.db").list(source_type="baseline")
    assert len(rows) == 2 and rows[0].snapshot_id

    async def pairs_fail(*a, **k):
        raise RuntimeError("pairs broke")
    monkeypatch.setattr(P, "record_pairs", pairs_fail)
    run(O._record_l3_target_pairs(config, batch))            # logged, not raised
