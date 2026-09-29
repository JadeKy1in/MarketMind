"""Settlement rules (docs/S2_DESIGN.md §4): every record type must settle from bars alone."""
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.settlement import settle_all, simulate
from marketmind.ledger.store import LedgerEntry, LedgerStore

CREATED = "2026-09-01T21:00:00Z"


def bar(date, o, h, l, c):
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=1.0)


def flat(dates, px=100.0):
    return [bar(d, px, px + 1, px - 1, px) for d in dates]


DAYS = [f"2026-09-{d:02d}" for d in range(1, 30)]


def entry(**kw):
    base = dict(source_type="main", source_id="t", ticker="AAA", direction="long", hold_bars=5,
                confidence=0.7, position_usd=1000.0, falsifier="wrong if it falls",
                created_at=CREATED)
    base.update(kw)
    return LedgerEntry(**base)


def test_next_open_fills_first_bar_after_creation_and_expires():
    bars = flat(DAYS[:1], 90) + [bar("2026-09-02", 100, 101, 99, 100)] + flat(DAYS[2:10], 100)
    bars[5] = bar(bars[5].date, 100, 111, 99, 110)   # 5th bar after creation closes at 110
    out = simulate(entry(), bars)
    assert out.status == "settled" and out.exit_reason == "expiry"
    assert out.fill.price == 100 and out.exit_price == 110


def test_pending_before_any_bar_and_open_mid_hold():
    assert simulate(entry(), flat(DAYS[:1])).status == "pending"
    out = simulate(entry(), flat(DAYS[:3]))
    assert out.status == "open" and out.fill is not None


def test_stop_hit_and_gap_through_stop_uses_open():
    bars = flat(DAYS[:3]) + [bar("2026-09-04", 99, 99, 94, 95)]
    out = simulate(entry(stop_loss=96.0), bars)
    assert (out.exit_reason, out.exit_price) == ("stop", 96.0)
    gap = flat(DAYS[:3]) + [bar("2026-09-04", 90, 91, 89, 90)]
    assert simulate(entry(stop_loss=96.0), gap).exit_price == 90


def test_target_and_same_bar_double_touch_is_stop():
    bars = flat(DAYS[:3]) + [bar("2026-09-04", 100, 112, 99, 111)]
    out = simulate(entry(stop_loss=95.0, target_price=110.0), bars)
    assert (out.exit_reason, out.exit_price) == ("target", 110.0)
    both = flat(DAYS[:3]) + [bar("2026-09-04", 100, 112, 94, 100)]
    assert simulate(entry(stop_loss=95.0, target_price=110.0), both).exit_reason == "stop"


def test_zone_entry_fill_price_and_void_when_never_reached():
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 105, 106, 102, 103)] + flat(DAYS[2:10], 103)
    e = entry(entry_rule="zone", entry_low=100.0, entry_high=103.0)
    out = simulate(e, bars)
    assert out.fill.index == 0 and out.fill.price == 103.0 and not out.fill.at_open
    high = flat(DAYS[:12], 120)
    assert simulate(e, high).status == "void"
    assert simulate(e, flat(DAYS[:3], 120)).status == "pending"


def test_zone_entry_window_is_five_bars_even_with_long_hold():
    e = entry(entry_rule="zone", entry_low=100.0, entry_high=103.0, hold_bars=30)
    # 5 bars after creation all above the zone -> void, although the hold is 30 bars
    assert simulate(e, flat(DAYS[:6], 120)).status == "void"
    assert simulate(e, flat(DAYS[:5], 120)).status == "pending"
    # reaching the zone on the 6th bar is too late
    late = flat(DAYS[:6], 120) + [bar("2026-09-07", 104, 105, 101, 102)]
    assert simulate(e, late).status == "void"
    # reaching it on the 5th bar still fills
    ok = flat(DAYS[:5], 120) + [bar("2026-09-06", 104, 105, 101, 102)]
    assert simulate(e, ok).fill.index == 4


def test_zone_fill_bar_does_not_credit_target_but_does_stop():
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 105, 120, 102, 104)] + flat(DAYS[2:10], 104)
    e = entry(entry_rule="zone", entry_low=100.0, entry_high=103.0, target_price=115.0)
    assert simulate(e, bars).exit_reason == "expiry"
    stop_bar = flat(DAYS[:1]) + [bar("2026-09-02", 105, 106, 90, 92)]
    e2 = entry(entry_rule="zone", entry_low=100.0, entry_high=103.0, stop_loss=95.0)
    assert simulate(e2, stop_bar).exit_reason == "stop"


def test_falsifier_rule_exits_on_close():
    bars = flat(DAYS[:3]) + [bar("2026-09-04", 100, 100, 97, 97.5)]
    out = simulate(entry(falsifier_rule={"type": "close_below", "price": 98.0}), bars)
    assert (out.exit_reason, out.exit_price) == ("falsifier", 97.5)


def test_short_mirrors_stop_and_target():
    bars = flat(DAYS[:3]) + [bar("2026-09-04", 100, 106, 99, 105)]
    out = simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), bars)
    assert (out.exit_reason, out.exit_price) == ("stop", 105.0)
    down = flat(DAYS[:3]) + [bar("2026-09-04", 100, 100, 89, 90)]
    assert simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), down).exit_reason == "target"


@pytest.mark.asyncio
async def test_settle_all_scores_returns_costs_benchmarks_brier(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    stock = flat(DAYS[:1]) + [bar(d, 100, 101, 99, 100) for d in DAYS[1:5]] + [bar(DAYS[5], 100, 111, 99, 110)]
    spy = flat(DAYS[:1]) + [bar(d, 500, 501, 499, 500) for d in DAYS[1:5]] + [bar(DAYS[5], 500, 506, 499, 505)]
    xlk = flat(DAYS[:6], 200)
    btc = [bar(d, 100, 101, 99, 100) for d in DAYS[:10]]
    src = StaticPriceSource({"AAA": stock, "SPY": spy, "XLK": xlk, "ETH-USD": btc, "BTC-USD": btc})

    long_id = store.add(entry(domain_benchmark="XLK"), created_at=CREATED)
    short_id = store.add(entry(direction="short", confidence=0.2), created_at=CREATED)
    crypto_id = store.add(entry(ticker="ETH-USD", asset_type="crypto", hold_bars=3), created_at=CREATED)
    missing_id = store.add(entry(ticker="NODATA"), created_at=CREATED)

    report = await settle_all(store, src, today="2026-09-30")
    assert (report.settled, report.unavailable) == (3, ["NODATA"])

    e = store.get(long_id)
    assert e.status == "settled" and e.gross_return == pytest.approx(0.10)
    assert e.cost_return == pytest.approx(0.001) and e.net_return == pytest.approx(0.099)
    assert e.pnl_usd == pytest.approx(99.0)
    assert e.market_benchmark == "SPY" and e.excess_market == pytest.approx(0.099 - 0.01)
    assert e.excess_domain == pytest.approx(0.099)
    assert e.brier == pytest.approx(0.09) and e.falsifier_triggered is False

    s = store.get(short_id)
    assert s.net_return == pytest.approx(-0.101) and s.brier == pytest.approx(0.04)

    c = store.get(crypto_id)
    assert c.market_benchmark == "BTC-USD" and c.cost_return == pytest.approx(0.02)    # 2 x 100 bp (Robinhood crypto spread)
    assert c.exit_date == "2026-09-04"   # 3 calendar bars: 09-02, 09-03, 09-04

    m = store.get(missing_id)
    assert m.status == "pending" and "unavailable" in m.settle_note

    again = await settle_all(store, src, today="2026-09-30")          # idempotent: settled records are left alone
    assert again.checked == 1


def test_entry_validation_requires_falsifier_and_valid_fields(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    with pytest.raises(ValueError):
        store.add(entry(falsifier=" "))
    with pytest.raises(ValueError):
        store.add(entry(confidence=1.5))
    with pytest.raises(ValueError):
        store.add(entry(entry_rule="zone"))
    with pytest.raises(ValueError):
        store.add(entry(source_type="nobody"))


def test_store_roundtrip_json_bool_and_snapshot(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static"), "BBB": (None, None, None)})
    eid = store.add(entry(falsifier_rule={"type": "close_below", "price": 1.0},
                          meta={"k": "v"}, snapshot_id=sid))
    e = store.get(eid)
    assert e.falsifier_rule == {"type": "close_below", "price": 1.0} and e.meta == {"k": "v"}
    assert e.confidence_is_default is False and e.falsifier_triggered is None
    snap = store.snapshot(sid)
    assert snap["AAA"]["price"] == 100.0 and snap["BBB"]["price"] is None


@pytest.mark.asyncio
async def test_partial_bar_for_today_is_not_used(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    bars = flat(DAYS[:5]) + [bar("2026-09-06", 100, 130, 99, 125)]   # running session
    eid = store.add(entry(hold_bars=5), created_at=CREATED)
    await settle_all(store, StaticPriceSource({"AAA": bars}), today="2026-09-06")
    e = store.get(eid)
    assert e.status == "open" and e.exit_price is None
    await settle_all(store, StaticPriceSource({"AAA": bars}), today="2026-09-07")
    assert store.get(eid).exit_price == 125


def test_us_record_created_before_the_open_fills_that_day():
    # 2026-09-02T01:00Z = 2026-09-01 21:00 ET (after close) -> fill on 09-02
    # 2026-09-02T12:00Z = 08:00 ET on 09-02 (before open)   -> fill on 09-02 too
    bars = [bar("2026-09-01", 90, 91, 89, 90), bar("2026-09-02", 100, 101, 99, 100),
            bar("2026-09-03", 110, 111, 109, 110)]
    for created in ("2026-09-02T01:00:00Z", "2026-09-02T12:00:00Z"):
        assert simulate(entry(created_at=created), bars).fill.price == 100
    assert simulate(entry(created_at="2026-09-02T15:00:00Z"), bars).fill.price == 110
    crypto = entry(ticker="ETH-USD", asset_type="crypto", created_at="2026-09-02T01:00:00Z")
    assert simulate(crypto, bars).fill.price == 110


def test_benchmark_window_must_cover_entry_and_exit_dates():
    from marketmind.ledger.settlement import benchmark_return
    spy = [bar("2026-09-02", 100, 101, 99, 100), bar("2026-09-03", 100, 106, 99, 105)]
    assert benchmark_return(spy, "2026-09-02", "2026-09-03") == pytest.approx(0.05)
    assert benchmark_return(spy, "2026-09-02", "2026-09-20") is None   # stale series
    assert benchmark_return(spy, "2026-09-01", "2026-09-03") is None   # missing start


@pytest.mark.asyncio
async def test_one_bad_record_does_not_block_the_rest(tmp_path, monkeypatch):
    from marketmind.ledger import settlement
    store = LedgerStore(tmp_path / "l.db")
    bad = store.add(entry(ticker="BAD"), created_at=CREATED)
    good = store.add(entry(), created_at=CREATED)
    real = settlement.simulate

    def flaky(e, bars):
        if e.ticker == "BAD":
            raise RuntimeError("corrupt record")
        return real(e, bars)

    monkeypatch.setattr(settlement, "simulate", flaky)
    src = StaticPriceSource({"BAD": flat(DAYS[:8]), "AAA": flat(DAYS[:8]), "SPY": flat(DAYS[:8])})
    report = await settle_all(store, src, today="2026-09-30")
    assert store.get(good).status == "settled"
    assert report.errors == [bad] and "corrupt record" in store.get(bad).settle_note


@pytest.mark.asyncio
async def test_zero_entry_price_is_not_settled(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(entry(), created_at=CREATED)
    zero = flat(DAYS[:1]) + [bar(d, 0, 1, 0, 0.5) for d in DAYS[1:8]]
    await settle_all(store, StaticPriceSource({"AAA": zero}), today="2026-09-30")
    e = store.get(eid)
    assert e.status == "open" and e.net_return is None and "invalid entry price" in e.settle_note


def test_falsifier_rule_is_validated(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    with pytest.raises(ValueError):
        store.add(entry(falsifier_rule={"type": "close_below", "price": "n/a"}))
    with pytest.raises(ValueError):
        store.add(entry(falsifier_rule={"type": "vibes", "price": 1}))
    eid = store.add(entry(falsifier_rule={"type": "close_below", "price": "98.5"}))
    assert store.get(eid).falsifier_rule["price"] == 98.5


@pytest.mark.asyncio
async def test_price_source_is_recorded_per_ticker(tmp_path):
    from marketmind.ledger.prices import source_of
    src = StaticPriceSource({})
    src.served_by = {"ETH-USD": "binance"}
    assert source_of(src, "ETH-USD") == "binance" and source_of(src, "SPY") == "static"


def test_gap_open_beyond_target_exits_at_open_even_if_stop_touched_later():
    # opens above the target, then trades down through the stop the same day
    bars = flat(DAYS[:3]) + [bar("2026-09-04", 113, 114, 94, 95)]
    out = simulate(entry(stop_loss=95.0, target_price=110.0), bars)
    assert (out.exit_reason, out.exit_price) == ("target", 113)
    short = flat(DAYS[:3]) + [bar("2026-09-04", 88, 106, 87, 105)]
    out = simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), short)
    assert (out.exit_reason, out.exit_price) == ("target", 88)


@pytest.mark.asyncio
async def test_levels_rescaled_when_adjusted_series_changes(tmp_path):
    # Recorded when the series showed 100 on 09-01 (stop 95); a later 2:1 split
    # re-adjusts history to 50, so the stop must be read as 47.5, not 95.
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static")})
    eid = store.add(entry(stop_loss=95.0, target_price=130.0, snapshot_id=sid),
                    created_at=CREATED)
    adjusted = flat(DAYS[:8], 50.0)
    spy = flat(DAYS[:8])
    await settle_all(store, StaticPriceSource({"AAA": adjusted, "SPY": spy}), today="2026-09-30")
    e = store.get(eid)
    assert e.exit_reason == "expiry" and e.entry_price == 50.0
    assert "rescaled x0.5000" in e.settle_note


@pytest.mark.asyncio
async def test_missing_benchmark_is_backfilled_later(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(entry(), created_at=CREATED)
    stock = flat(DAYS[:8])
    report = await settle_all(store, StaticPriceSource({"AAA": stock}), today="2026-09-30")
    e = store.get(eid)
    assert e.status == "settled" and e.market_return is None
    assert "benchmark data unavailable: SPY" in e.settle_note
    net = e.net_return
    report = await settle_all(store, StaticPriceSource({"AAA": stock, "SPY": flat(DAYS[:8])}),
                              today="2026-09-30")
    e = store.get(eid)
    assert report.benchmarks_backfilled == 1 and "backfilled 1" in report.summary()
    assert e.market_return == 0.0 and e.excess_market == net and e.settle_note == ""
    assert e.net_return == net  # outcome itself untouched


def test_entry_open_past_target_is_void_but_past_stop_is_a_stop_loss():
    # next_open fill on 09-02 opens below the stop: stopped at that open, measured
    # against the stop level (owner decision 2026-09-29, second revision)
    below = flat(DAYS[:1]) + [bar("2026-09-02", 94, 96, 93, 95)] + flat(DAYS[2:8])
    out = simulate(entry(stop_loss=95.0, target_price=110.0), below)
    assert (out.status, out.exit_reason, out.exit_index) == ("settled", "stop", 0)
    assert (out.entry_price, out.fill.price, out.exit_price) == (95.0, 94, 94)
    above = flat(DAYS[:1]) + [bar("2026-09-02", 111, 112, 109, 110)] + flat(DAYS[2:8])
    out = simulate(entry(stop_loss=95.0, target_price=110.0), above)
    assert (out.status, out.exit_reason) == ("void", "gap_target") and out.fill is None
    short = flat(DAYS[:1]) + [bar("2026-09-02", 89, 90, 88, 89)] + flat(DAYS[2:8])
    out = simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), short)
    assert (out.status, out.exit_reason) == ("void", "gap_target")
    short_stop = flat(DAYS[:1]) + [bar("2026-09-02", 110, 111, 108, 109)] + flat(DAYS[2:8])
    out = simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), short_stop)
    assert (out.status, out.exit_reason, out.entry_price, out.exit_price) == (
        "settled", "stop", 105.0, 110)
    # a zone fill at the open below the stop is stopped the same way
    zone = flat(DAYS[:1]) + [bar("2026-09-02", 94, 96, 93, 95)] + flat(DAYS[2:8])
    out = simulate(entry(entry_rule="zone", entry_low=97.0, entry_high=99.0, stop_loss=95.0,
                         target_price=110.0), zone)
    assert (out.status, out.exit_reason, out.entry_price) == ("settled", "stop", 95.0)


@pytest.mark.asyncio
async def test_gap_through_the_stop_is_scored_as_a_loss(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    long_id = store.add(entry(stop_loss=95.0, target_price=110.0), created_at=CREATED)
    short_id = store.add(entry(ticker="BBB", direction="short", stop_loss=105.0,
                               target_price=90.0), created_at=CREATED)
    exact_id = store.add(entry(ticker="CCC", stop_loss=95.0), created_at=CREATED)
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 90, 96, 89, 95)] + flat(DAYS[2:8])
    bbb = flat(DAYS[:1]) + [bar("2026-09-02", 110, 111, 108, 109)] + flat(DAYS[2:8])
    ccc = flat(DAYS[:1]) + [bar("2026-09-02", 95, 96, 94, 95)] + flat(DAYS[2:8])
    rep = await settle_all(store, StaticPriceSource({"AAA": bars, "BBB": bbb, "CCC": ccc,
                                                     "SPY": flat(DAYS[:8])}), today="2026-09-30")
    assert rep.settled == 3 and rep.voided == 0
    e = store.get(long_id)
    assert (e.status, e.exit_reason, e.entry_date, e.exit_date) == (
        "settled", "stop", "2026-09-02", "2026-09-02")
    assert (e.entry_price, e.exit_price) == (95.0, 90.0)
    assert e.gross_return == pytest.approx(90 / 95 - 1, abs=1e-6) and e.net_return < e.gross_return < 0
    assert e.brier == pytest.approx(0.49) and e.falsifier_triggered is True
    assert e.settle_note == "gapped through the stop at the open"
    s = store.get(short_id)
    assert s.gross_return == pytest.approx(-(110 / 105 - 1), abs=1e-6) and s.net_return < 0
    c = store.get(exact_id)                # open exactly at the stop: costs make it a loss
    assert c.gross_return == 0.0 and c.net_return < 0 and c.brier == pytest.approx(0.49)


def test_one_bar_record_still_ignores_a_gap_through_the_stop():
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 90, 96, 89, 95)]
    out = simulate(entry(hold_bars=1, stop_loss=95.0), bars)
    assert (out.status, out.exit_reason, out.entry_price) == ("settled", "expiry", None)
    assert (out.fill.price, out.exit_price) == (90, 95)


def test_one_bar_record_scores_fill_to_close_only():
    # the bar touches both stop and target and closes above the falsifier level:
    # only the open -> close direction counts
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 100, 112, 94, 103)] + flat(DAYS[2:5])
    e = entry(hold_bars=1, stop_loss=95.0, target_price=110.0,
              falsifier_rule={"type": "close_below", "price": 104.0})
    out = simulate(e, bars)
    assert (out.status, out.exit_reason) == ("settled", "expiry")
    assert (out.fill.price, out.exit_price, out.exit_index) == (100, 103, 0)


def test_one_bar_record_ignores_the_gap_rule():
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 90, 91, 88, 89)]
    out = simulate(entry(hold_bars=1, stop_loss=95.0), bars)
    assert (out.status, out.exit_price) == ("settled", 89)
    assert simulate(entry(hold_bars=1), flat(DAYS[:1])).status == "pending"
