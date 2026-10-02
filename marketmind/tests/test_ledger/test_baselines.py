"""Trend tags and comparable code baselines (docs/S7_DESIGN.md §六, owner 2026-10-02)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory, to_weekly
from marketmind.ledger import baselines as B
from marketmind.ledger import comparison
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.recorder import record_main_decision
from marketmind.ledger.settlement import settle_all
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.ledger.trend_tag import TrendTagger, resolve_hurdle

TODAY = "2026-09-28"


def bars(n=400, start=50.0, step=0.1, end="2026-09-25"):
    """n weekday bars ending on `end`; step > 0 is a steady up-trend, < 0 a down-trend."""
    days, d = [], date.fromisoformat(end)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    days.reverse()
    out = []
    for i, day in enumerate(days):
        c = start + step * i
        out.append(Bar(day, c, c * 1.01, c * 0.99, c, 1e6))
    return out


def hist(t, b):
    return PriceHistory(t, "synthetic", daily=b, weekly=to_weekly(b))


def trend_file(root, hurdle=0.04, day="2026-09-26"):
    (root / "trend").mkdir(parents=True, exist_ok=True)
    (root / "trend" / f"{day}.json").write_text(
        json.dumps({"hurdle": hurdle, "hurdle_source": "^IRX test"}), encoding="utf-8")


def decision(ticker="GLD", direction="long", **kw):
    d = dict(source_type="shadow", source_id="expert:gold:bullion_broker", ticker=ticker,
             direction=direction, hold_bars=7, confidence=0.6, position_usd=300.0,
             falsifier="x", stop_loss=95.0, target_price=110.0, snapshot_id="s1",
             domain_benchmark="GLD", meta={"run_date": TODAY})
    d.update(kw)
    return LedgerEntry(**d)


# ── trend tag ───────────────────────────────────────────────────────────

def test_hurdle_from_recent_trend_file_else_zero(tmp_path):
    assert resolve_hurdle(tmp_path, TODAY)[0] == 0.0
    assert "unavailable" in resolve_hurdle(tmp_path, TODAY)[1]
    trend_file(tmp_path, 0.037, "2026-09-26")
    trend_file(tmp_path, 0.5, "2026-09-30")             # after today: not used
    h, src = resolve_hurdle(tmp_path, TODAY)
    assert h == 0.037 and "2026-09-26" in src and "^IRX test" in src
    assert resolve_hurdle(tmp_path, "2026-10-20")[0] == 0.0     # too old


def test_tagger_states_and_unavailable_reasons(tmp_path):
    tg = TrendTagger(TODAY, hurdle=0.04, hurdle_source="given")
    up = tg.tag("AAA", bars(step=0.1))
    assert up["state"] == "TREND" and up["as_of"] == "2026-09-25" and up["hurdle"] == 0.04
    down = tg.tag("BBB", bars(start=200, step=-0.1))
    assert down["state"] == "CASH" and "12m return" in down["reason"]
    short = tg.tag("CCC", bars(n=100))
    assert short["state"] == "UNAVAILABLE" and "insufficient history" in short["reason"]
    stale = tg.tag("DDD", bars(end="2026-08-01"))
    assert stale["state"] == "UNAVAILABLE" and "stale" in stale["reason"]
    assert tg.tag("EEE", None)["state"] == "UNAVAILABLE"
    # cached per ticker
    assert tg.tag("AAA", None)["state"] == "TREND"


# ── baseline rows ───────────────────────────────────────────────────────

def test_build_baselines_kinds_levels_and_seed():
    d = decision(meta={"run_date": TODAY, "trend": {"state": "TREND", "as_of": "2026-09-25"}})
    B.ensure_ids([d])
    rows = B.build([d], run_date=TODAY, p_long=1.0, bars={"GLD": bars(step=0.1)},
                   ref_prices={"GLD": 100.0})
    kinds = {r.meta["baseline"]: r for r in rows}
    assert set(kinds) == set(B.KINDS)
    for r in rows:
        assert r.source_type == "baseline" and r.source_id == f"baseline:{r.meta['baseline']}:{d.source_id}"
        assert (r.ticker, r.hold_bars, r.entry_rule, r.snapshot_id) == ("GLD", 7, "next_open", "s1")
        assert r.meta["pairs_with"] == d.entry_id and r.meta["pairs_key"] == [d.source_id, "GLD", TODAY]
        assert r.falsifier_rule is None and r.confidence_is_default
    for k in ("always_long", "momentum20", "trend"):
        assert kinds[k].direction == "long" and kinds[k].stop_loss is None and kinds[k].target_price is None
    mr = kinds["matched_random"]
    assert mr.direction == "long" and mr.stop_loss == pytest.approx(95.0) and mr.target_price == pytest.approx(110.0)
    # mirrored for a short draw: same distances above / below the decision price
    short = B.build([d], run_date=TODAY, p_long=0.0, bars={}, ref_prices={"GLD": 100.0})
    mr = next(r for r in short if r.meta["baseline"] == "matched_random")
    assert mr.direction == "short" and mr.stop_loss == pytest.approx(105.0) and mr.target_price == pytest.approx(90.0)
    # no momentum without (fresh) bars; no trend row unless TREND
    assert "momentum20" not in {r.meta["baseline"] for r in short}
    cash = replace(d, meta={"trend": {"state": "CASH"}})
    assert "trend" not in {r.meta["baseline"] for r in B.build([cash], run_date=TODAY, p_long=0.5,
                                                               bars={}, ref_prices={})}
    # reproducible draw
    again = B.build([d], run_date=TODAY, p_long=0.5, bars={}, ref_prices={"GLD": 100.0})
    again2 = B.build([d], run_date=TODAY, p_long=0.5, bars={}, ref_prices={"GLD": 100.0})
    assert [r.direction for r in again] == [r.direction for r in again2]
    assert next(r for r in again if r.meta["baseline"] == "matched_random").meta["seed"] == \
        f"{TODAY}:{d.source_id}:GLD"


def test_momentum_sign_and_staleness():
    assert B.momentum20(bars(step=0.1), TODAY) > 0
    assert B.momentum20(bars(start=200, step=-0.1), TODAY) < 0
    assert B.momentum20(bars(end="2026-08-01"), TODAY) is None
    assert B.momentum20(bars(n=15), TODAY) is None
    d = decision()
    B.ensure_ids([d])
    rows = B.build([d], run_date=TODAY, p_long=0.5, bars={"GLD": bars(start=200, step=-0.1)},
                   ref_prices={})
    assert next(r for r in rows if r.meta["baseline"] == "momentum20").direction == "short"


def test_zone_decision_levels_use_the_zone_midpoint():
    d = decision(source_type="main", source_id="main_pipeline", entry_rule="zone",
                 entry_low=98.0, entry_high=102.0, stop_loss=90.0, target_price=120.0)
    stop, target, dist = B.mirrored_levels(d, "long", 50.0)
    assert dist["stop_pct"] == pytest.approx(0.1) and dist["target_pct"] == pytest.approx(0.2)
    assert stop == pytest.approx(45.0) and target == pytest.approx(60.0)


def test_long_share_counts_today_then_history(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    assert B.long_share(store, ("shadow",), "s", []) == 0.5
    for i, direction in enumerate(["short"] * 3 + ["long"]):
        store.add(decision(source_id="s", direction=direction), created_at=f"2026-09-2{i}T10:00:00Z")
    assert B.long_share(store, ("shadow",), "s", ["long"]) == pytest.approx(2 / 5)
    assert B.long_share(store, ("shadow",), "s", ["long"], window=2) == pytest.approx(1.0)
    assert B.long_share(store, ("shadow",), "s", ["short", "short"], window=3) == pytest.approx(1 / 3)


# ── shadow run integration ──────────────────────────────────────────────

@pytest.fixture
def fresh_prices(monkeypatch, tmp_path):
    from marketmind.shadows.v3 import runner
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    trend_file(tmp_path)

    async def fake(tickers, years=5):
        return {t: hist(t, bars(step=0.1 if t != "GDX" else -0.1, start=50 if t != "GDX" else 200))
                for t in tickers}
    monkeypatch.setattr(runner, "get_price_histories", fake)


async def no_fred(shadow_id):
    return {}


def _reply(*decisions):
    return json.dumps({"decisions": list(decisions)})


def _good(ticker, **kw):
    d = {"ticker": ticker, "direction": "long", "hold_days": 10, "confidence": 0.62,
         "thesis": "测试理由", "falsifier": "跌破支撑说明我错了"}
    d.update(kw)
    return d


@pytest.mark.asyncio
async def test_shadow_run_tags_records_and_writes_baselines_atomically(tmp_path, fresh_prices):
    from marketmind.shadows.v3 import roster, runner
    store = LedgerStore(tmp_path / "l.db")

    async def call(system, user, stage):
        return _reply(_good("GLD"), _good("GDX", direction="short", hold_days=3))

    entry = roster.by_id()["expert:gold:bullion_broker"]
    report = await runner.run_shadow_day(store, [], today=TODAY, entries=[entry], call=call,
                                         fred_fetch=no_fred, pending_path=tmp_path / "p.json")
    r = report.results[0]
    assert r.status == "submitted" and len(r.entry_ids) == 2 and r.benchmark_id
    rows = {e.ticker: e for e in store.list(source_type="shadow")}
    assert rows["GLD"].meta["trend"]["state"] == "TREND"
    assert rows["GDX"].meta["trend"]["state"] == "CASH"
    assert rows["GLD"].meta["trend"]["hurdle"] == 0.04
    base = store.list(source_type="baseline")
    assert {e.entry_id for e in base} == set(r.baseline_ids)
    by = {(e.meta["pairs_with"], e.meta["baseline"]): e for e in base}
    gld, gdx = rows["GLD"].entry_id, rows["GDX"].entry_id
    assert set(by) == {(gld, k) for k in B.KINDS} | {(gdx, k) for k in B.KINDS if k != "trend"}
    assert by[(gdx, "momentum20")].direction == "short" and by[(gdx, "always_long")].hold_bars == 3
    assert all(e.created_at == rows["GLD"].created_at for e in base)
    # hidden from every ordinary listing; still visible to settlement
    assert not [e for e in store.list() if e.source_type == "baseline"]
    assert len(store.unsettled()) == len(store.list()) + len(base)

    # a duplicate submission for the same session writes nothing at all
    n = len(store.list(include_baselines=True))
    again = await runner.run_shadow_day(store, [], today=TODAY, entries=[entry], call=call,
                                        fred_fetch=no_fred, created_at=rows["GLD"].created_at,
                                        pending_path=tmp_path / "p.json")
    assert again.results[0].status in ("skipped", "duplicate")
    assert len(store.list(include_baselines=True)) == n


@pytest.mark.asyncio
async def test_temp_shadow_is_tagged_without_baselines(tmp_path, fresh_prices):
    from marketmind.shadows.v3 import roster, runner
    store = LedgerStore(tmp_path / "l.db")
    trial = replace(roster.by_id()["expert:gold:bullion_broker"],
                    shadow_id="trial:t1", source_type="temp_shadow", group="trial")

    async def call(system, user, stage):
        return _reply(_good("GLD"))

    await runner.run_shadow_day(store, [], today=TODAY, entries=[trial], call=call,
                                fred_fetch=no_fred, pending_path=tmp_path / "p.json")
    row = store.list(source_type="temp_shadow")[0]
    assert row.meta["trend"]["state"] == "TREND"
    assert store.list(source_type="baseline") == []


@pytest.mark.asyncio
async def test_tag_failure_never_blocks_the_submission(tmp_path, fresh_prices, monkeypatch):
    from marketmind.ledger import trend_tag
    from marketmind.shadows.v3 import roster, runner

    def boom(*a, **k):
        raise RuntimeError("bad state machine")
    monkeypatch.setattr("marketmind.trend.state.compute_states", boom)
    store = LedgerStore(tmp_path / "l.db")

    async def call(system, user, stage):
        return _reply(_good("GLD"))

    report = await runner.run_shadow_day(store, [], today=TODAY,
                                         entries=[roster.by_id()["expert:gold:bullion_broker"]],
                                         call=call, fred_fetch=no_fred,
                                         pending_path=tmp_path / "p.json")
    assert report.results[0].status == "submitted"
    tag = store.list(source_type="shadow")[0].meta["trend"]
    assert tag["state"] == trend_tag.UNAVAILABLE and "bad state machine" in tag["reason"]


# ── main pipeline ───────────────────────────────────────────────────────

def _card(ticker="SPY", direction="long"):
    return SimpleNamespace(ticker=ticker, direction=direction, max_hold_days=5, confidence=0.7,
                           position_size_pct=5.0, llm_size_pct=None, invalidation="breaks support",
                           thesis="t", entry_low=99.0, entry_high=101.0, stop_loss=95.0,
                           target_price=110.0, reward_risk_ratio=2.0, risk_statement="",
                           red_team_note="")


@pytest.mark.asyncio
async def test_main_decision_tagged_with_baselines(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    trend_file(tmp_path)
    store = LedgerStore(tmp_path / "l.db")
    src = StaticPriceSource({"SPY": bars(step=0.1)})
    decision_obj = SimpleNamespace(decision_cards=[_card()], paper_trade=None)
    ids = await record_main_decision(decision_obj, None, store, src,
                                     created_at="2026-09-28T01:00:00Z")
    assert len(ids) == 1
    main = store.get(ids[0])
    assert main.source_type == "main" and main.meta["trend"]["state"] == "TREND"
    base = store.list(source_type="baseline")
    assert {e.meta["baseline"] for e in base} == set(B.KINDS)
    assert all(e.meta["pairs_with"] == ids[0] and e.source_id.endswith(":main_pipeline")
               for e in base)
    mr = next(e for e in base if e.meta["baseline"] == "matched_random")
    assert mr.direction == "long"                    # P(long) = 1 (only long history)
    snap = store.snapshot(main.snapshot_id)["SPY"]["price"]
    assert mr.stop_loss == pytest.approx(snap * 0.95) and mr.target_price == pytest.approx(snap * 1.10)
    # second run for the same session: nothing written
    again = await record_main_decision(decision_obj, None, store, src,
                                       created_at="2026-09-28T02:00:00Z")
    assert again == [] and len(store.list(include_baselines=True)) == 5


# ── settlement and comparison ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_baselines_settle_and_compare(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    b = bars(n=300, step=0.1, end="2026-09-25")
    trend = {"state": "TREND", "as_of": b[-12].date}
    cash = {"state": "CASH", "as_of": b[-12].date}
    created = f"{b[-12].date}T22:00:00Z"
    d1 = decision(ticker="AAA", direction="short", hold_bars=3, stop_loss=None,
                  target_price=None, snapshot_id=None, meta={"trend": trend})
    d2 = decision(ticker="AAA", source_id="other", direction="long", hold_bars=3,
                  stop_loss=None, target_price=None, snapshot_id=None, meta={"trend": cash})
    for d in (d1, d2):
        B.ensure_ids([d])
        comps = B.build([d], run_date=b[-12].date, p_long=1.0, bars={"AAA": b[:-11]},
                        ref_prices={"AAA": b[-12].close})
        assert store.add_submission([d], lambda e: None, created_at=created, companions=comps)
    await settle_all(store, StaticPriceSource({"AAA": b, "SPY": b}), today="2026-09-26")
    rows = store.list(include_baselines=True)
    assert all(e.status == "settled" for e in rows)
    comp = comparison.compute(rows)
    sh = {r["baseline"]: r for r in comp["baselines"] if r["group"] == "shadows"}
    assert sh["always_long"]["pairs"] == 2
    assert sh["always_long"]["mean_diff"] < 0                    # the short lost in an up-trend
    assert sh["trend"]["pairs"] == 2                             # d2: cash counted as 0
    assert sh["matched_random"]["pairs"] == 2
    tags = {(r["direction"], r["state"]): r for r in comp["trend_tags"]}
    assert tags[("short", "TREND")]["n"] == 1 and tags[("short", "TREND")]["win_rate"] == 0
    assert tags[("long", "CASH")]["win_rate"] == 1
    line = comparison.summary_line(comp)
    assert "always_long 2 对" in line and "多·CASH" in line


def test_triggered_conditional_signal_is_tagged_with_baselines(tmp_path):
    from marketmind.shadows.v3 import pending_signals as P
    path = tmp_path / "pending.json"
    b = bars(step=0.1)
    jump = b[-1].close * 1.2                                  # a clear 20-day breakout
    b[-1] = Bar(b[-1].date, jump, jump * 1.01, jump * 0.99, jump, 1e6)
    rec = {"signal_id": "s0", "status": "pending", "shadow_id": "expert:gold:bullion_broker",
           "lineage_id": "expert:gold:bullion_broker", "source_type": "shadow",
           "shadow_name": "x", "domain_benchmark": "SPY", "ticker": "SPY", "direction": "long",
           "condition": {"type": "breakout_20d"}, "hold_days": 5, "confidence": 0.6,
           "expires_in_days": 5, "thesis": "t", "falsifier": "f", "run_date": b[-3].date,
           "created_at": f"{b[-3].date}T08:00:00Z", "as_of": b[-3].date,
           "last_bar_date": b[-3].date, "bars_seen": 0, "meta": {}}
    P.save({"signals": [rec]}, path)
    store = LedgerStore(tmp_path / "l.db")
    out = P.check(path, store, {"SPY": hist("SPY", b)}, shadow_ids={rec["shadow_id"]},
                  today=TODAY, created_at=f"{TODAY}T08:00:00Z",
                  tagger=TrendTagger(TODAY, hurdle=0.0))
    eid = out["triggered"][0]["entry_id"]
    row = store.get(eid)
    assert row.meta["trend"]["state"] == "TREND" and row.meta["pending_signal_id"] == "s0"
    base = store.list(source_type="baseline")
    assert {e.meta["baseline"] for e in base} == set(B.KINDS)
    assert all(e.meta["pairs_with"] == eid for e in base)
