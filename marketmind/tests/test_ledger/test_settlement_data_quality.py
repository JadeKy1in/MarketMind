"""Settlement data-quality rules (docs/S2_DESIGN.md §4): close-only bars and
unsettleable markets."""
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.settlement import settle_all, simulate
from marketmind.ledger.store import LedgerEntry, LedgerStore

CREATED = "2026-09-01T21:00:00Z"
DAYS = [f"2026-09-{d:02d}" for d in range(1, 30)]


def bar(date, o, h, l, c):
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=1.0)


def close_only(date, c, o=None, h=None, l=None):
    """A close-only bar; o/h/l may differ to prove only the close is used."""
    return Bar(date=date, open=c if o is None else o, high=c if h is None else h,
               low=c if l is None else l, close=c, volume=0.0, close_only=True)


def flat(dates, px=100.0):
    return [bar(d, px, px + 1, px - 1, px) for d in dates]


def entry(**kw):
    base = dict(source_type="main", source_id="t", ticker="AAA", direction="long", hold_bars=5,
                confidence=0.7, position_usd=1000.0, falsifier="wrong if it falls",
                created_at=CREATED)
    base.update(kw)
    return LedgerEntry(**base)


def test_next_open_on_a_close_only_bar_fills_at_the_close_and_notes_it():
    bars = flat(DAYS[:1]) + [close_only("2026-09-02", 102.0, o=100.0, h=105.0, l=95.0)]
    bars += flat(DAYS[2:4], 102)
    out = simulate(entry(), bars)
    assert out.status == "open" and out.fill.price == 102.0
    assert "close-only bar 2026-09-02" in out.note and "filled at the close" in out.note


def test_intrabar_touch_on_a_close_only_bar_does_not_count():
    # the (unreliable) low reaches the stop, the close does not -> no stop
    bars = flat(DAYS[:3]) + [close_only("2026-09-04", 99.0, l=90.0, h=99.0)] + flat(DAYS[4:6])
    out = simulate(entry(stop_loss=96.0, target_price=110.0), bars)
    assert out.status == "settled" and out.exit_reason == "expiry"
    assert "close-only bar 2026-09-04" in out.note


def test_close_beyond_stop_or_target_exits_at_the_close():
    stop = flat(DAYS[:3]) + [close_only("2026-09-04", 95.0, h=101.0, l=94.0)]
    out = simulate(entry(stop_loss=96.0, target_price=110.0), stop)
    assert (out.exit_reason, out.exit_price) == ("stop", 95.0)
    target = flat(DAYS[:3]) + [close_only("2026-09-04", 111.0, o=100.0, h=112.0, l=94.0)]
    out = simulate(entry(stop_loss=96.0, target_price=110.0), target)
    assert (out.exit_reason, out.exit_price) == ("target", 111.0)
    short = flat(DAYS[:3]) + [close_only("2026-09-04", 105.5, o=100.0, h=106.0, l=89.0)]
    out = simulate(entry(direction="short", stop_loss=105.0, target_price=90.0), short)
    assert (out.exit_reason, out.exit_price) == ("stop", 105.5)


def test_one_bar_record_on_a_close_only_fill_bar_is_void():
    bars = flat(DAYS[:1]) + [close_only("2026-09-02", 102.0)]
    out = simulate(entry(hold_bars=1), bars)
    assert out.status == "void" and out.exit_reason == "close_only"
    assert "2026-09-02" in out.note
    # a normal fill bar is still scored fill-to-close
    assert simulate(entry(hold_bars=1), flat(DAYS[:2])).status == "settled"


def test_full_bars_get_no_close_only_note():
    out = simulate(entry(), flat(DAYS[:8]))
    assert out.status == "settled" and "close-only" not in out.note


@pytest.mark.asyncio
async def test_settle_all_writes_the_close_only_note(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    bars = flat(DAYS[:1]) + [close_only("2026-09-02", 100.0)] + flat(DAYS[2:8])
    src = StaticPriceSource({"PL=F": bars, "DBC": flat(DAYS[:8], 20)})
    rid = store.add(entry(ticker="PL=F", asset_type="future"), created_at=CREATED)
    report = await settle_all(store, src, today="2026-09-30")
    e = store.get(rid)
    assert report.settled == 1 and e.status == "settled"
    assert "close-only bar 2026-09-02" in e.settle_note and e.entry_price == 100.0

