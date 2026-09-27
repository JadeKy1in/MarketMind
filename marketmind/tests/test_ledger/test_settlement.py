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

    report = await settle_all(store, src)
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
    assert c.market_benchmark == "BTC-USD" and c.cost_return == pytest.approx(0.01)
    assert c.exit_date == "2026-09-04"   # 3 calendar bars: 09-02, 09-03, 09-04

    m = store.get(missing_id)
    assert m.status == "pending" and "unavailable" in m.settle_note

    again = await settle_all(store, src)          # idempotent: settled records are left alone
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
