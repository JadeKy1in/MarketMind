"""Conditional (pending) shadow signals: parsing, registry, trigger check, retirement
(docs/S3_DESIGN.md §9). Offline: fake LLM replies, synthetic bars, files under tmp_path."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory, to_weekly
from marketmind.ledger.store import LedgerStore
from marketmind.shadows.v3 import pending_signals as P
from marketmind.shadows.v3 import roster, runner
from marketmind.shadows.v3.decision import OUTPUT_INSTRUCTIONS, parse_decisions
from marketmind.tests.test_shadows_v3.test_roster_context import history

CLOSES = {"SPY": 100.0, "GLD": 200.0}
ATRS = {"SPY": 2.0, "GLD": 4.0}
GOLD = "expert:gold:bullion_broker"


def _d(**kw):
    base = {"ticker": "SPY", "direction": "long", "hold_days": 5, "confidence": 0.6,
            "thesis": "趋势向上", "falsifier": "收盘跌破 95 说明我错了"}
    base.update(kw)
    return base


def _c(cond, **kw):
    return _d(condition=cond, expires_in_days=10, **kw)


def _text(conds, decisions=None):
    return json.dumps({"decisions": decisions if decisions is not None else [_d()],
                       "conditional_signals": conds}, ensure_ascii=False)


# ── parsing ─────────────────────────────────────────────────────────────

def test_valid_conditional_signals_are_parsed_next_to_decisions():
    res = parse_decisions(_text([_c({"type": "close_above", "level": 102}),
                                 _c({"type": "pct_change_5d_below", "pct": -6}, ticker="GLD",
                                    direction="short")]),
                          CLOSES, atrs=ATRS, ret_5d={"GLD": -1.0})
    assert res.ok and not res.errors and not res.warnings
    assert [(c.ticker, c.condition) for c in res.conditionals] == [
        ("SPY", {"type": "close_above", "level": 102.0}),
        ("GLD", {"type": "pct_change_5d_below", "pct": -6.0})]
    assert res.conditionals[0].expires_in_days == 10 and res.conditionals[0].position_usd > 100


@pytest.mark.parametrize("cond,extra,why", [
    ({"type": "close_above", "level": 99}, {}, "already holds"),          # wrong side
    ({"type": "close_below", "level": 101}, {}, "already holds"),
    ({"type": "close_above", "level": 101.5}, {}, "×ATR"),                # < 1 ATR away
    ({"type": "close_below", "level": 98.5}, {}, "×ATR"),
    ({"type": "close_above", "level": 110}, {"atrs": {}}, "ATR14 unavailable"),
    ({"type": "pct_change_5d_above", "pct": 3}, {"ret_5d": {"SPY": 4.0}}, "already holds"),
    ({"type": "pct_change_5d_above", "pct": -3}, {}, "needs a percent"),
    ({"type": "close_above_ma", "period": 50}, {}, "is not one of"),
])
def test_bad_conditions_are_dropped_with_a_warning_never_an_error(cond, extra, why):
    kw = {"atrs": ATRS, **extra}
    res = parse_decisions(_text([_c(cond)]), CLOSES, **kw)
    assert res.ok and not res.errors and not res.conditionals
    assert any(why in w and "conditional signal 1" in w for w in res.warnings), res.warnings


def test_limits_expiry_and_off_context_levels():
    three = [_c({"type": "breakout_20d"}), _c({"type": "breakout_20d"}, direction="short"),
             _c({"type": "close_above", "level": 110})]
    res = parse_decisions(_text(three), CLOSES, atrs=ATRS)
    assert len(res.conditionals) == 2 and "only the first 2 kept" in res.warnings[0]

    res = parse_decisions(_text([_d(condition={"type": "breakout_20d"}, expires_in_days=21)]),
                          CLOSES, atrs=ATRS)
    assert not res.conditionals and "expires_in_days" in res.warnings[0]

    res = parse_decisions(_text([_c({"type": "close_above", "level": 200}, ticker="NVDA"),
                                 _c({"type": "breakout_20d"}, ticker="NVDA")]),
                          {**CLOSES, "NVDA": 150.0}, atrs={**ATRS, "NVDA": 5.0},
                          no_levels={"NVDA"})
    assert [c.condition["type"] for c in res.conditionals] == ["breakout_20d"]
    assert "not in your context" in res.warnings[0]


def test_a_day_without_decisions_is_still_missed_and_scalper_hold_is_fixed():
    res = parse_decisions(_text([_c({"type": "breakout_20d"})], decisions=[]), CLOSES)
    assert not res.ok                     # a conditional signal never replaces the decision
    res = parse_decisions(_text([_c({"type": "breakout_20d"}, hold_days=9)]), CLOSES,
                          fixed_hold=1)
    assert res.conditionals[0].hold_days == 1


def test_output_instructions_describe_the_optional_field():
    assert '"conditional_signals": []' in OUTPUT_INSTRUCTIONS
    assert "never" in OUTPUT_INSTRUCTIONS and "expires_in_days" in OUTPUT_INSTRUCTIONS


# ── evaluation ──────────────────────────────────────────────────────────

def _bars(closes, start="2026-08-03"):
    d, out = date.fromisoformat(start), []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(Bar(d.isoformat(), c, c * 1.01, c * 0.99, c, 1e6))
        d += timedelta(days=1)
    return out


def test_evaluate_reuses_watch_conditions_and_computes_5_day_change():
    bars = _bars([100] * 21 + [103])
    assert P.evaluate({"type": "close_above", "level": 102}, bars, "long")[0]
    assert not P.evaluate({"type": "close_below", "level": 99}, bars, "long")[0]
    assert P.evaluate({"type": "breakout_20d"}, bars, "long")[0]
    assert not P.evaluate({"type": "breakout_20d"}, bars, "short")[0]
    met, detail = P.evaluate({"type": "pct_change_5d_above", "pct": 2.5}, bars, "long")
    assert met and "+3.00%" in detail
    assert not P.evaluate({"type": "pct_change_5d_below", "pct": -1}, bars, "short")[0]
    assert not P.evaluate({"type": "pct_change_5d_above", "pct": 1}, bars[:5], "long")[0]


# ── runner: register, trigger, expire ───────────────────────────────────

@pytest.fixture
def market(monkeypatch):
    """GLD history that tests extend bar by bar; everything else static."""
    state = {"GLD": history("GLD")}

    async def fake(tickers, years=5):
        return {t: state.get(t) or history(t) for t in tickers if t != "SLV"}
    monkeypatch.setattr(runner, "get_price_histories", fake)
    return state


def _append(state, *closes):
    h = state["GLD"]
    d = date.fromisoformat(h.daily[-1].date) + timedelta(days=1)
    bars = list(h.daily)
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        bars.append(Bar(d.isoformat(), c, c * 1.001, c * 0.999, c, 1e6))
        d += timedelta(days=1)
    state["GLD"] = PriceHistory("GLD", "synthetic", daily=bars, weekly=to_weekly(bars))


async def no_fred(shadow_id):
    return {}


async def _run(store, tmp_path, day, reply, entries=None):
    async def call(system, user, stage):
        return reply
    return await runner.run_shadow_day(
        store, [], today=day, entries=entries or [roster.by_id()[GOLD]], call=call,
        fred_fetch=no_fred, created_at=f"{day}T08:00:00Z",
        pending_path=tmp_path / "shadows" / "pending_signals.json")


def _gld_close_atr(state):
    from marketmind.shadows.v3.context import ticker_view
    snap = ticker_view("GLD", state["GLD"]).snap
    return snap.close, snap.atr14


@pytest.mark.asyncio
async def test_signal_registers_then_triggers_as_a_normal_record(tmp_path, market):
    store = LedgerStore(tmp_path / "l.db")
    close, a = _gld_close_atr(market)
    level = round(close + 1.5 * a, 2)
    day1 = _text([_c({"type": "close_above", "level": level}, ticker="GLD", hold_days=7)],
                 decisions=[_d(ticker="GDX")])
    r1 = await _run(store, tmp_path, "2026-09-10", day1)
    res = r1.results[0]
    assert res.status == "submitted" and len(res.pending_ids) == 1
    reg = P.load(tmp_path / "shadows" / "pending_signals.json")["signals"][0]
    assert (reg["shadow_id"], reg["lineage_id"], reg["status"]) == (GOLD, GOLD, "pending")
    assert reg["as_of"] == market["GLD"].daily[-1].date and reg["atr14"] == pytest.approx(a)
    assert [e.ticker for e in store.list(source_type="shadow")] == ["GDX"]   # nothing traded yet

    _append(market, close, level + 0.5)                      # 2nd new bar closes above
    day2 = _text([], decisions=[_d(ticker="GDX", direction="short")])
    r2 = await _run(store, tmp_path, "2026-09-11", day2)
    fired = r2.pending["triggered"]
    assert len(fired) == 1 and fired[0]["bar"] == market["GLD"].daily[-1].date
    rec = store.get(fired[0]["entry_id"])
    assert (rec.source_type, rec.source_id, rec.ticker, rec.hold_bars) == ("shadow", GOLD, "GLD", 7)
    assert rec.entry_rule == "next_open" and rec.stop_loss is None and rec.target_price is None
    assert rec.meta["pending_signal_id"] == reg["signal_id"]
    assert rec.meta["signal_run_date"] == "2026-09-10" and rec.meta["run_date"] == "2026-09-11"
    assert rec.domain_benchmark == "GLD" and rec.thesis.startswith("[条件触发]")
    # the trigger does not stand in for day 2's forced decision
    assert r2.results[0].status == "submitted"
    assert sorted(e.ticker for e in store.list(source_type="shadow")) == ["GDX", "GDX", "GLD"]
    assert "1 triggered" in r2.summary()

    # a re-run the same day neither re-triggers nor re-asks the shadow
    r3 = await _run(store, tmp_path, "2026-09-11", day2)
    assert r3.results[0].status == "skipped" and not r3.pending["triggered"]
    log = (tmp_path / "shadows" / "pending_signals.jsonl").read_text(encoding="utf-8")
    assert [json.loads(x)["event"] for x in log.splitlines()] == ["registered", "triggered"]


@pytest.mark.asyncio
async def test_signal_expires_after_its_bars_and_is_logged(tmp_path, market):
    store = LedgerStore(tmp_path / "l.db")
    close, a = _gld_close_atr(market)
    day1 = _text([_d(ticker="GLD", condition={"type": "close_below", "level": close - 3 * a},
                     expires_in_days=2)], decisions=[_d(ticker="GDX")])
    await _run(store, tmp_path, "2026-09-10", day1)
    _append(market, close)
    r = await _run(store, tmp_path, "2026-09-11", _text([], [_d(ticker="GDX")]))
    assert not r.pending["expired"] and r.pending["waiting"] == 1
    _append(market, close)
    r = await _run(store, tmp_path, "2026-09-14", _text([], [_d(ticker="GDX")]))
    assert len(r.pending["expired"]) == 1 and not r.pending["triggered"]
    sig = P.load(tmp_path / "shadows" / "pending_signals.json")["signals"][0]
    assert sig["status"] == "expired" and sig["bars_seen"] == 2
    assert not any(e.ticker == "GLD" for e in store.list(source_type="shadow"))


@pytest.mark.asyncio
async def test_missed_day_registers_no_signal(tmp_path, market):
    store = LedgerStore(tmp_path / "l.db")
    r = await _run(store, tmp_path, "2026-09-10",
                   _text([_c({"type": "breakout_20d"}, ticker="GLD")], decisions=[]))
    assert r.results[0].status == "missed" and not r.results[0].pending_ids
    assert not (tmp_path / "shadows" / "pending_signals.json").exists()


def _signal(path, sid, run_date="2026-09-01", expires=5):
    rec = {"signal_id": f"s{len(P.load(path)['signals'])}", "status": "pending",
           "shadow_id": sid, "lineage_id": roster.lineage_id(sid), "source_type": "shadow",
           "shadow_name": "x", "domain_benchmark": "SPY", "ticker": "SPY", "direction": "long",
           "condition": {"type": "breakout_20d"}, "hold_days": 5, "confidence": 0.6,
           "expires_in_days": expires, "thesis": "t", "falsifier": "f", "run_date": run_date,
           "created_at": f"{run_date}T08:00:00Z", "as_of": run_date, "last_bar_date": run_date,
           "bars_seen": 0, "meta": {}}
    data = P.load(path)
    data["signals"].append(rec)
    P.save(data, path)


def test_unchecked_signals_expire_after_their_deadline(tmp_path):
    path = tmp_path / "p.json"
    store = LedgerStore(tmp_path / "l.db")
    _signal(path, "trial:abc", run_date="2026-09-01", expires=5)   # deadline 09-01 + 7 + 10
    out = P.check(path, store, {}, shadow_ids=set(), today="2026-09-18", created_at="x")
    assert not out["expired"]
    out = P.check(path, store, {}, shadow_ids=set(), today="2026-09-19", created_at="x")
    assert len(out["expired"]) == 1 and P.load(path)["signals"][0]["status"] == "expired"


def test_retired_owner_signals_expire_and_are_not_inherited(tmp_path):
    path = tmp_path / "p.json"
    store = LedgerStore(tmp_path / "l.db")
    old = "momentum:weekly:trend_rider"
    _signal(path, old)
    _signal(path, old)
    _signal(path, GOLD)
    ids = P.expire_for_retired(old, successor=f"{old}@2", today="2026-09-05", path=path)
    assert len(ids) == 2
    sigs = P.load(path)["signals"]
    assert [s["status"] for s in sigs] == ["cancelled", "cancelled", "pending"]
    assert "does not inherit" in sigs[0]["note"]
    assert not P.open_signals(P.load(path), f"{old}@2")
    # safety net in the daily check: a retired owner's leftover signal is cancelled
    _signal(path, old)
    out = P.check(path, store, {}, shadow_ids={GOLD}, retired={old}, today="2026-09-06",
                  created_at="2026-09-06T08:00:00Z")
    assert len(out["cancelled"]) == 1 and out["waiting"] == 1     # GOLD: no bars given


def test_terminal_signals_leave_the_registry_after_archive_days(tmp_path):
    path = tmp_path / "p.json"
    _signal(path, GOLD)
    P.expire_for_retired(GOLD, successor=None, today="2026-09-01", path=path)
    P.save(P.load(path), path, today="2026-10-01")
    assert len(P.load(path)["signals"]) == 1
    P.save(P.load(path), path, today="2026-10-02")
    assert P.load(path)["signals"] == []
    assert "cancelled" in P.log_path(path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_owner_approval_expires_the_retired_shadows_signals(tmp_path, monkeypatch):
    from marketmind.promotion import retirement as R
    from marketmind.tests.test_promotion.test_retirement import OLD, _propose_real
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    path = P.default_path(tmp_path)
    _signal(path, OLD)
    _propose_real(tmp_path, donor_score=None)

    async def call(system, user):
        raise AssertionError("no LLM call without a donor")
    await R.approve(OLD, data_dir=tmp_path, call=call, today="2026-06-01")
    succ = R.load(tmp_path)["proposals"][0]["successor"]
    assert succ["expired_pending_signals"] == ["s0"]
    assert P.load(path)["signals"][0]["status"] == "cancelled"
