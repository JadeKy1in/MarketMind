"""Watchlist lifecycle (docs/S10_DESIGN.md §3): add, dedupe, counterfactual, trigger,
expiry, invalidation, push filtering and report views. Fully offline."""
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.settlement import settle_all
from marketmind.ledger.store import LedgerStore
from marketmind.watchlist import (
    WatchItem, WatchlistStore, add_items, check_all, daily_summary, dashboard_items,
    notify_triggers,
)
from marketmind.watchlist.store import default_watchlist_path


def business_days(start: str, n: int) -> list[str]:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


D = business_days("2026-05-04", 120)
CREATED_IDX = 59                                    # 60 bars of history at creation -> L3 works
CREATED = f"{D[CREATED_IDX]}T21:00:00Z"             # after the US close


def flat_bars(n=len(D), px=100.0, vol=1000.0):
    return [Bar(D[i], px, px + 1, px - 1, px, vol) for i in range(n)]


def set_close(bars, i, close, vol=1000.0):
    bars[i] = Bar(D[i], close, max(close, bars[i].high), min(close, bars[i].low), close, vol)


def cut(i):
    """`today` for check_all so bars up to and including D[i] are complete."""
    return D[i + 1]


def main_item(**kw):
    base = dict(ticker="nvda", direction="long", source="main_pipeline", thesis="AI capex 未反映",
                conditions=[{"type": "close_above", "price": 105}],
                origin={"kind": "news", "series": []}, confidence=0.6)
    base.update(kw)
    return base


def anomaly_item(**kw):
    base = dict(ticker="TLT", direction="short", source="anomaly", thesis="准备金大降，未反映",
                origin={"kind": "anomaly", "series": ["fred:WRESBAL"],
                        "anomaly_id": f"{D[CREATED_IDX]}:fred:WRESBAL", "priced_in": "none",
                        "coverage": 1})
    base.update(kw)
    return base


@pytest.fixture
def env(tmp_path):
    return WatchlistStore(tmp_path / "watchlist.db"), LedgerStore(tmp_path / "ledger.db")


async def _add(env, items, bars_by_ticker):
    store, ledger = env
    return await add_items(items, StaticPriceSource(bars_by_ticker), store=store, ledger=ledger,
                           now=CREATED, today=cut(CREATED_IDX))


async def _check(env, bars_by_ticker, idx, **kw):
    store, ledger = env
    return await check_all(StaticPriceSource(bars_by_ticker), cut(idx), store=store,
                           ledger=ledger, now=f"{cut(idx)}T01:00:00Z", **kw)


# ── validation & store ─────────────────────────────────────────────────────

def test_item_validation_defaults_and_rejections():
    a = WatchItem(**anomaly_item())
    a.validate()
    assert a.conditions == [{"type": "breakout_20d"}] and a.expiry_bars == 20
    m = WatchItem(**main_item(origin={}, confidence=65))
    m.validate()
    assert m.ticker == "NVDA" and m.origin == {"kind": "watch"} and m.confidence == 0.65
    for bad in (dict(conditions=[]), dict(direction="flat"), dict(source="llm"),
                dict(thesis=" "), dict(expiry_bars=0), dict(origin={"kind": "rumour"}),
                dict(conditions=[{"type": "looks_strong"}]), dict(confidence=1.5e3)):
        with pytest.raises(ValueError):
            WatchItem(**main_item(**bad)).validate()


def test_store_roundtrip_and_default_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    assert default_watchlist_path() == tmp_path / "watchlist.db"
    store = WatchlistStore(default_watchlist_path())
    item = WatchItem(**main_item(invalidation=[{"type": "close_below", "price": 90}]))
    wid = store.add(item)
    back = store.get(wid)
    assert back.conditions == [{"type": "close_above", "price": 105.0}]
    assert back.invalidation == [{"type": "close_below", "price": 90.0}]
    assert back.origin["kind"] == "news" and back.status == "watching" and back.created_at
    assert store.find_watching("nvda", "long", "main_pipeline").id == wid
    assert store.find_watching("NVDA", "short", "main_pipeline") is None


# ── add: counterfactual & dedupe ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_writes_counterfactual_ledger_entry(env):
    store, ledger = env
    out = await _add(env, [main_item(), anomaly_item()],
                     {"NVDA": flat_bars(), "TLT": flat_bars()})
    assert len(out["added"]) == 2 and not out["rejected"]
    nvda = store.get(out["added"][0])
    e = ledger.get(nvda.counterfactual_entry_id)
    assert (e.source_type, e.source_id, e.entry_rule, e.hold_bars) == (
        "watch_counterfactual", "watch:main_pipeline", "next_open", 20)
    assert e.created_at == CREATED and e.confidence == 0.6 and not e.confidence_is_default
    assert e.meta["watch_id"] == nvda.id and e.meta["origin"] == {"kind": "news", "series": []}
    # long with 60 bars: L3 levels (flat 100 +/- 1: ATR 2, stop = max(99 - 2, 100 - 4), cap 100 + 12)
    assert (e.stop_loss, e.target_price, e.meta["levels"]["basis"]) == (97.0, 112.0, "l3")
    assert e.falsifier_rule == {"type": "close_below", "price": 97.0} and "97" in e.falsifier
    assert ledger.snapshot(e.snapshot_id)["NVDA"]["price"] == 100.0
    tlt = ledger.get(out["counterfactuals"][out["added"][1]])
    # short: ATR mirror of the L3 risk cap, 2R target
    assert (tlt.stop_loss, tlt.target_price, tlt.meta["levels"]["basis"]) == (104.0, 92.0, "atr")
    assert tlt.falsifier_rule == {"type": "close_above", "price": 104.0}
    assert tlt.confidence == 0.5 and tlt.confidence_is_default
    assert tlt.meta["origin"]["anomaly_id"].endswith("fred:WRESBAL")


@pytest.mark.asyncio
async def test_add_rejects_bad_items_but_keeps_good_ones(env):
    out = await _add(env, [main_item(conditions=[{"type": "vibes"}]), main_item(extra="x"),
                           "NVDA", main_item(ticker="AMD")],
                     {"AMD": flat_bars()})
    assert len(out["added"]) == 1 and len(out["rejected"]) == 3
    assert "unknown condition type" in out["rejected"][0]["error"]


@pytest.mark.asyncio
async def test_add_without_price_data_still_records_counterfactual(env):
    store, ledger = env
    out = await _add(env, [main_item(ticker="ZZZZ")], {})
    e = ledger.get(out["counterfactuals"][out["added"][0]])
    assert e.stop_loss is None and "净收益为负" in e.falsifier and e.falsifier_rule is None
    assert ledger.snapshot(e.snapshot_id)["ZZZZ"]["price"] is None


@pytest.mark.asyncio
async def test_same_ticker_direction_source_refreshes_instead_of_duplicating(env):
    store, ledger = env
    bars = {"NVDA": flat_bars()}
    first = await _add(env, [main_item()], bars)
    wid = first["added"][0]
    await _check(env, bars, CREATED_IDX + 3)                     # 3 bars seen
    again = await _add(env, [main_item(thesis="新论点", conditions=[
        {"type": "close_above", "price": 108}])], bars)
    assert again["added"] == [] and again["refreshed"] == [wid]
    item = store.get(wid)
    assert item.thesis == "新论点" and item.conditions[0]["price"] == 108.0
    assert item.expiry_bars == 3 + 20 and item.refreshed_at
    assert len(ledger.list(source_type="watch_counterfactual")) == 1
    # other direction or other source is a separate item
    other = await _add(env, [main_item(direction="short"),
                             main_item(source="anomaly", conditions=[])], bars)
    assert len(other["added"]) == 2
    # a duplicate inside one batch is refreshed too
    batch = await _add(env, [main_item(ticker="AMD"), main_item(ticker="AMD")], {"AMD": flat_bars()})
    assert len(batch["added"]) == 1 and len(batch["refreshed"]) == 1


# ── check: trigger / AND / expiry / invalidation ───────────────────────────

@pytest.mark.asyncio
async def test_all_conditions_must_hold_on_the_same_bar(env):
    store, ledger = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 106.0)                          # price ok, volume not
    set_close(bars, CREATED_IDX + 2, 100.0, vol=3000.0)              # volume ok, price not
    set_close(bars, CREATED_IDX + 3, 107.0, vol=3000.0)              # both
    out = await _add(env, [main_item(conditions=[
        {"type": "close_above", "price": 105}, {"type": "volume_ratio_at_least", "ratio": 2}])],
        {"NVDA": bars})
    wid = out["added"][0]
    rep = await _check(env, {"NVDA": bars}, CREATED_IDX + 2)
    assert rep["triggered"] == [] and rep["still_watching"] == 1
    rep = await _check(env, {"NVDA": bars}, CREATED_IDX + 3)
    [row] = rep["triggered"]
    assert row["watch_id"] == wid and row["bar_date"] == D[CREATED_IDX + 3]
    assert [f["label"] for f in row["fired"]] == ["收盘价上破 105", "成交量 ≥ 2 倍 20 日均量"]
    item = store.get(wid)
    assert item.status == "triggered" and item.bars_seen == 3 and len(item.history) >= 4
    e = ledger.get(item.triggered_entry_id)
    assert (e.source_type, e.source_id, e.entry_rule, e.hold_bars) == (
        "watch", "watch:main_pipeline", "next_open", 20)
    assert e.meta["watch_id"] == wid and e.meta["origin"]["kind"] == "news"
    assert e.meta["counterfactual_entry_id"] == item.counterfactual_entry_id
    assert e.meta["trigger_bar"] == D[CREATED_IDX + 3] and e.falsifier
    assert e.stop_loss and e.target_price and e.meta["levels"]["basis"] == "l3"
    # a later run does not trigger or record again
    rep = await _check(env, {"NVDA": bars}, CREATED_IDX + 5)
    assert rep["checked"] == 0 and len(ledger.list(source_type="watch")) == 1


@pytest.mark.asyncio
async def test_catch_up_evaluates_every_missed_bar_in_order(env):
    store, _ = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 2, 106.0)          # the only qualifying bar
    out = await _add(env, [main_item()], {"NVDA": bars})
    rep = await _check(env, {"NVDA": bars}, CREATED_IDX + 6)       # first run 6 bars later
    assert rep["triggered"][0]["bar_date"] == D[CREATED_IDX + 2]
    assert store.get(out["added"][0]).bars_seen == 2


@pytest.mark.asyncio
async def test_only_bars_after_creation_count(env):
    store, _ = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX, 106.0)              # already true when the item was made
    out = await _add(env, [main_item()], {"NVDA": bars})
    rep = await _check(env, {"NVDA": bars}, CREATED_IDX + 1)
    assert rep["triggered"] == []
    assert store.get(out["added"][0]).last_bar_date == D[CREATED_IDX + 1]


@pytest.mark.asyncio
async def test_expiry_after_expiry_bars_and_trigger_on_last_bar_wins(env):
    store, ledger = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 5, 106.0)
    out = await _add(env, [main_item(expiry_bars=4), main_item(ticker="AMD", expiry_bars=5)],
                     {"NVDA": bars, "AMD": bars})
    rep = await _check(env, {"NVDA": bars, "AMD": bars}, CREATED_IDX + 3)
    assert rep["expired"] == [] and rep["still_watching"] == 2
    rep = await _check(env, {"NVDA": bars, "AMD": bars}, CREATED_IDX + 5)
    [expired] = rep["expired"]
    assert expired["ticker"] == "NVDA" and expired["bar_date"] == D[CREATED_IDX + 4]
    assert store.get(out["added"][0]).status == "expired"
    assert [r["ticker"] for r in rep["triggered"]] == ["AMD"]      # 5th bar = last allowed
    assert len(ledger.list(source_type="watch")) == 1


@pytest.mark.asyncio
async def test_invalidation_any_condition_and_beats_same_bar_trigger(env):
    store, ledger = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 101.0)
    set_close(bars, CREATED_IDX + 2, 94.0)
    both = flat_bars()
    set_close(both, CREATED_IDX + 1, 106.0, vol=3000.0)
    out = await _add(env, [
        main_item(invalidation=[{"type": "close_above", "price": 120},
                                {"type": "close_below", "price": 95}]),
        main_item(ticker="AMD", invalidation=[{"type": "volume_ratio_at_least", "ratio": 2}]),
    ], {"NVDA": bars, "AMD": both})
    rep = await _check(env, {"NVDA": bars, "AMD": both}, CREATED_IDX + 2)
    got = {r["ticker"]: r for r in rep["invalidated"]}
    assert set(got) == {"NVDA", "AMD"} and rep["triggered"] == []
    assert got["NVDA"]["bar_date"] == D[CREATED_IDX + 2]
    assert got["NVDA"]["fired"][0]["label"] == "收盘价跌破 95"
    assert store.get(out["added"][0]).status == "invalidated"
    assert ledger.list(source_type="watch") == []


@pytest.mark.asyncio
async def test_anomaly_default_breakout_short(env):
    store, ledger = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 98.5)           # below the prior 20-day low of 99
    out = await _add(env, [anomaly_item()], {"TLT": bars})
    rep = await _check(env, {"TLT": bars}, CREATED_IDX + 1)
    [row] = rep["triggered"]
    assert row["source"] == "anomaly" and row["fired"][0]["label"] == "收盘跌破前 20 日低点"
    e = ledger.get(store.get(out["added"][0]).triggered_entry_id)
    assert e.direction == "short" and e.source_id == "watch:anomaly"
    assert e.meta["levels"]["basis"] == "atr" and e.stop_loss > 98.5 > e.target_price


@pytest.mark.asyncio
async def test_missing_prices_keep_watching_and_crypto_only_filter(env):
    store, _ = env
    await _add(env, [main_item(), main_item(ticker="BTC-USD", conditions=[
        {"type": "close_above", "price": 1}])], {"NVDA": flat_bars(), "BTC-USD": flat_bars()})
    rep = await _check(env, {}, CREATED_IDX + 2)
    assert sorted(rep["unavailable"]) == ["BTC-USD", "NVDA"] and rep["still_watching"] == 2
    rep = await _check(env, {"BTC-USD": flat_bars(), "NVDA": flat_bars()}, CREATED_IDX + 2,
                       crypto_only=True)
    assert rep["checked"] == 1 and [r["ticker"] for r in rep["triggered"]] == ["BTC-USD"]
    assert len(store.watching()) == 1


@pytest.mark.asyncio
async def test_watch_entries_settle_like_any_ledger_record(env):
    _, ledger = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 106.0)
    await _add(env, [main_item()], {"NVDA": bars})
    await _check(env, {"NVDA": bars}, CREATED_IDX + 1)
    rep = await settle_all(ledger, StaticPriceSource({"NVDA": bars, "SPY": flat_bars()}),
                           today=cut(CREATED_IDX + 30))
    assert rep.errors == [] and rep.settled == 2
    assert {e.source_type for e in ledger.list(status="settled")} == {"watch", "watch_counterfactual"}


# ── push & views ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_only_main_pipeline_triggers_are_pushed(env):
    store, _ = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 106.0)
    tlt = flat_bars()
    set_close(tlt, CREATED_IDX + 1, 98.5)
    await _add(env, [main_item(), anomaly_item()], {"NVDA": bars, "TLT": tlt})
    rep = await _check(env, {"NVDA": bars, "TLT": tlt}, CREATED_IDX + 1)
    assert len(rep["triggered"]) == 2
    sent = []

    async def fake_send(title, body):
        sent.append((title, body))
        return [{"channel": "serverchan", "ok": True, "status": 200}]

    out = await notify_triggers(rep, send=fake_send, store=store)
    assert len(sent) == 1
    title, body = sent[0]
    assert "NVDA 做多" in title and "TLT" not in title and "TLT" not in body
    assert "收盘价上破 105" in body and "AI capex 未反映" in body and "账本编号" in body
    nvda = next(r for r in rep["triggered"] if r["ticker"] == "NVDA")
    tlt_row = next(r for r in rep["triggered"] if r["ticker"] == "TLT")
    assert out["pushed"] == [nvda["watch_id"]] and out["skipped"] == [tlt_row["watch_id"]]
    assert out["results"][0]["ok"] is True
    assert store.get(nvda["watch_id"]).history[-1]["event"] == "notified"

    async def must_not_send(title, body):
        raise AssertionError("anomaly-only report must not push")

    anomaly_only = {"triggered": [tlt_row]}
    assert (await notify_triggers(anomaly_only, send=must_not_send))["pushed"] == []


@pytest.mark.asyncio
async def test_daily_summary_and_dashboard(env):
    store, _ = env
    bars = flat_bars()
    set_close(bars, CREATED_IDX + 1, 106.0)
    await _add(env, [main_item(), anomaly_item(), main_item(ticker="AMD", expiry_bars=1)],
               {"NVDA": bars, "TLT": flat_bars(), "AMD": flat_bars()})
    new_day = daily_summary(CREATED[:10], store)
    assert len(new_day["new"]) == 3 and new_day["watching"] == 3
    await _check(env, {"NVDA": bars, "TLT": flat_bars(), "AMD": flat_bars()}, CREATED_IDX + 1)
    day = daily_summary(cut(CREATED_IDX + 1), store)
    assert [r["ticker"] for r in day["triggered"]] == ["NVDA"]
    assert [r["ticker"] for r in day["expired"]] == ["AMD"]
    assert day["new"] == [] and day["watching"] == 1
    assert day["triggered"][0]["fired"] == ["收盘价上破 105"]
    rows = dashboard_items(store)
    assert len(rows) == 3
    tlt = next(r for r in rows if r["ticker"] == "TLT")
    assert tlt["status"] == "watching" and tlt["bars_left"] == 19
    assert tlt["conditions"] == ["收盘跌破前 20 日低点"]
    assert [r["ticker"] for r in dashboard_items(store, status="watching")] == ["TLT"]
