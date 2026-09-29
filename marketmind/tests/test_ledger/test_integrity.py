"""Ledger integrity (docs/S2_DESIGN.md §4): session dedupe, concurrent writers,
series adjustments, crypto data gaps, benchmark alignment and direction."""
import sqlite3
import threading

import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.recorder import record_main_decision
from marketmind.ledger.settlement import (
    apply_benchmarks, benchmark_return, compute_review, needs_benchmark, settle_all, simulate,
    target_session,
)
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline.decision import DecisionOutput, PaperTrade

CREATED = "2026-09-01T21:00:00Z"          # Tuesday evening UTC
DAYS = [f"2026-09-{d:02d}" for d in range(1, 30)]


def bar(date, o, h, l, c):
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=1.0)


def flat(dates, px=100.0):
    return [bar(d, px, px + 1, px - 1, px) for d in dates]


def entry(**kw):
    base = dict(source_type="main", source_id="t", ticker="AAA", direction="long", hold_bars=5,
                confidence=0.7, position_usd=1000.0, falsifier="wrong if it falls",
                created_at=CREATED)
    base.update(kw)
    return LedgerEntry(**base)


# ── 1. one submission per (source, target session) ──────────────────────────

def test_target_session_is_market_aware():
    # Friday 22:00 UTC (18:00 New York) and Saturday both decide for Monday
    assert target_session(entry(created_at="2026-09-25T22:00:00Z")) == "2026-09-28"
    assert target_session(entry(created_at="2026-09-26T10:00:00Z")) == "2026-09-28"
    assert target_session(entry(created_at="2026-09-28T12:00:00Z")) == "2026-09-28"  # pre-open
    assert target_session(entry(created_at="2026-09-28T15:00:00Z")) == "2026-09-29"
    # crypto trades every day: the next UTC day, weekends included
    btc = dict(ticker="BTC-USD", asset_type="crypto")
    assert target_session(entry(created_at="2026-09-25T22:00:00Z", **btc)) == "2026-09-26"
    assert target_session(entry(created_at="2026-09-26T10:00:00Z", **btc)) == "2026-09-27"
    # Tokyo: 11:00 local on Friday -> Monday
    assert target_session(entry(ticker="7203.T", created_at="2026-09-25T02:00:00Z")) == "2026-09-28"


def test_second_submission_for_the_same_session_is_rejected(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    first = store.add_submission([entry(), entry(ticker="BBB")], target_session,
                                 created_at="2026-09-25T22:00:00Z")
    assert len(first) == 2
    bench = entry(source_type="benchmark", source_id="random:t", ticker="CCC")
    dup = store.add_submission([entry(ticker="DDD")], target_session,
                               created_at="2026-09-26T10:00:00Z", companions=[bench])
    assert dup is None and len(store.list()) == 2          # benchmark not written either
    # another source type of the same source id, and the next session, are fine
    assert store.add_submission([entry(source_type="main_forced")], target_session,
                                created_at="2026-09-26T10:00:00Z")
    nxt = store.add_submission([entry()], target_session, created_at="2026-09-28T22:00:00Z",
                               companions=[entry(source_type="benchmark", source_id="random:t")])
    assert len(nxt) == 2 and len(store.list()) == 5


def test_concurrent_submissions_only_one_wins(tmp_path):
    path = tmp_path / "l.db"
    LedgerStore(path)
    barrier = threading.Barrier(6)
    results = []

    def submit(i):
        s = LedgerStore(path)
        barrier.wait()
        results.append(s.add_submission([entry(ticker=f"T{i}")], target_session,
                                        created_at="2026-09-25T22:00:00Z"))

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1
    assert len(LedgerStore(path).list()) == 1


SRC = StaticPriceSource({"NVDA": [Bar("2026-09-24", 1, 1, 1, 225.0, 1)]})


@pytest.mark.asyncio
async def test_main_pipeline_records_once_per_session(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    out = DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 0.65, "green light", "L3"))
    assert await record_main_decision(out, None, store, SRC, created_at="2026-09-25T22:00:00Z")
    again = await record_main_decision(out, None, store, SRC, created_at="2026-09-26T09:00:00Z")
    assert again == [] and len(store.list()) == 1
    assert await record_main_decision(out, None, store, SRC, created_at="2026-09-28T21:00:00Z")


# ── 2. concurrent settlement / WAL / 3. migration race ──────────────────────

def test_wal_and_busy_timeout(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    with store._connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


@pytest.mark.asyncio
async def test_record_voided_meanwhile_is_not_resurrected(tmp_path):
    path = tmp_path / "l.db"
    store = LedgerStore(path)
    eid = store.add(entry(), created_at=CREATED)
    bars = {"AAA": flat(DAYS[:8]), "SPY": flat(DAYS[:8])}

    class VoidingSource:
        """Another process voids the record while settlement awaits prices."""
        name = "static"

        async def daily_bars(self, ticker):
            other = LedgerStore(path)
            e = other.get(eid)
            if e.status != "void":
                e.status, e.settle_note = "void", "voided by the owner"
                other.update(e)
            return bars.get(ticker)

    report = await settle_all(store, VoidingSource(), today="2026-09-30")
    e = store.get(eid)
    assert e.status == "void" and e.settle_note == "voided by the owner" and e.net_return is None
    assert report.changed_meanwhile == [eid] and report.settled == 0
    assert "changed by another process" in report.summary()


def test_update_if_status(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(entry())
    e = store.get(eid)
    e.settle_note = "x"
    assert store.update_if_status(e, ("pending", "open"))
    assert not store.update_if_status(e, ("settled",))
    assert store.get(eid).settle_note == "x"


def test_column_added_by_another_process_meanwhile(tmp_path, monkeypatch):
    path = tmp_path / "l.db"
    LedgerStore(path)                                  # has every column already
    real = LedgerStore._connect

    class StaleInfo:
        """PRAGMA table_info read before another process added `review`."""
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if sql.startswith("PRAGMA table_info"):
                return [r for r in self.conn.execute(sql, *args) if r[1] != "review"]
            return self.conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, *exc):
            return self.conn.__exit__(*exc)

    monkeypatch.setattr(LedgerStore, "_connect", lambda self: StaleInfo(real(self)))
    LedgerStore(path)                                  # "duplicate column name" is ignored

    class BrokenAlter(StaleInfo):
        def execute(self, sql, *args):
            if sql.startswith("ALTER"):
                raise sqlite3.OperationalError("disk I/O error")
            return super().execute(sql, *args)

    monkeypatch.setattr(LedgerStore, "_connect", lambda self: BrokenAlter(real(self)))
    with pytest.raises(sqlite3.OperationalError):     # other errors still surface
        LedgerStore(path)


# ── 4. review after a later split ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_after_a_later_split_matches_the_pre_split_review(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static")})
    eid = store.add(entry(stop_loss=95.0, target_price=120.0, snapshot_id=sid), created_at=CREATED)
    bars = flat(DAYS[:1]) + [bar("2026-09-02", 100, 104, 97, 102), bar("2026-09-03", 102, 108, 101, 107),
                             bar("2026-09-04", 107, 107, 98, 99)] + flat(DAYS[4:8], 103)
    spy = flat(DAYS[:8])
    await settle_all(store, StaticPriceSource({"AAA": bars, "SPY": spy}), today="2026-09-30")
    before = store.get(eid)
    assert before.status == "settled" and before.review is not None
    # a 1:2 split afterwards: the whole adjusted series halves
    split = [bar(b.date, b.open / 2, b.high / 2, b.low / 2, b.close / 2) for b in bars]
    after = compute_review(before, split, 0.5)
    for k in ("mfe", "mae", "stop_distance", "target_distance", "touched_stop", "r_multiple"):
        assert after[k] == pytest.approx(before.review[k]), k
    # the backfill path recomputes with the current factor too
    before.review = None
    store.update(before)
    await settle_all(store, StaticPriceSource({"AAA": split, "SPY": spy}), today="2026-09-30")
    again = store.get(eid).review
    got = (again["mfe"], again["mae"], again["stop_distance"])
    assert got == pytest.approx((after["mfe"], after["mae"], after["stop_distance"]))
    assert got == pytest.approx((0.08, -0.03, -0.05))


@pytest.mark.asyncio
async def test_settle_factor_is_recorded(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static")})
    eid = store.add(entry(stop_loss=90.0, snapshot_id=sid), created_at=CREATED)
    await settle_all(store, StaticPriceSource({"AAA": flat(DAYS[:8], 50.0), "SPY": flat(DAYS[:8])}),
                     today="2026-09-30")
    e = store.get(eid)
    assert e.meta["price_factor"] == 0.5
    assert compute_review(e, flat(DAYS[:8], 50.0), 0.5)["stop_distance"] == pytest.approx(-0.1)


# ── 5. crypto calendar days and data gaps ───────────────────────────────────

def crypto(**kw):
    return entry(ticker="ETH-USD", asset_type="crypto", **kw)


def test_crypto_fill_must_be_the_first_expected_day():
    bars = flat(["2026-09-01"]) + flat(DAYS[2:10])          # 09-02 missing
    out = simulate(crypto(), bars)
    assert (out.status, out.note) == ("pending", "data gap 2026-09-02")


def test_crypto_gap_inside_the_hold_keeps_the_record_open():
    days = [d for d in DAYS[:12] if d != "2026-09-04"]
    out = simulate(crypto(hold_bars=5), flat(days))
    assert out.status == "open" and out.note == "data gap 2026-09-04" and out.exit_index is None


def test_crypto_expiry_is_by_calendar_day_and_a_gap_after_exit_is_harmless():
    out = simulate(crypto(hold_bars=5), flat(DAYS[:12]))
    assert out.status == "settled" and out.exit_index == 4   # 09-02 .. 09-06
    stopped = flat(DAYS[:2]) + [bar("2026-09-03", 100, 101, 90, 91)] + flat(DAYS[4:12])
    # 09-04 is missing, but only after the stop on 09-03
    out = simulate(crypto(hold_bars=5, stop_loss=95.0), stopped)
    assert (out.status, out.exit_reason) == ("settled", "stop")


def test_crypto_series_that_simply_ends_is_not_a_gap():
    out = simulate(crypto(hold_bars=5), flat(DAYS[:4]))
    assert out.status == "open" and "data gap" not in out.note


@pytest.mark.asyncio
async def test_crypto_gap_note_is_stored(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(crypto(hold_bars=3), created_at=CREATED)
    days = [d for d in DAYS[:10] if d != "2026-09-03"]
    await settle_all(store, StaticPriceSource({"ETH-USD": flat(days), "BTC-USD": flat(days)}),
                     today="2026-09-30")
    e = store.get(eid)
    assert e.status == "open" and e.exit_price is None and e.settle_note == "data gap 2026-09-03"


# ── 6. adjustment only within the same data source ──────────────────────────

@pytest.mark.asyncio
async def test_cross_source_difference_is_not_a_rescale(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"ETH-USD": (100.0, "2026-09-01", "yfinance")})
    eid = store.add(crypto(hold_bars=3, stop_loss=90.0, snapshot_id=sid), created_at=CREATED)
    bars = [bar("2026-09-01", 100, 101, 99, 100.08)] + flat(DAYS[1:8])
    src = StaticPriceSource({"ETH-USD": bars, "BTC-USD": flat(DAYS[:8])})
    src.served_by = {"ETH-USD": "binance"}
    await settle_all(store, src, today="2026-09-30")
    e = store.get(eid)
    assert e.status == "settled" and "levels rescaled" not in e.settle_note
    assert "snapshot source yfinance, settlement source binance (not rescaled)" in e.settle_note
    assert "price_factor" not in e.meta


@pytest.mark.asyncio
async def test_same_source_rounding_below_threshold_is_ignored(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static")})
    eid = store.add(entry(snapshot_id=sid), created_at=CREATED)
    bars = [bar("2026-09-01", 100, 101, 99, 100.04)] + flat(DAYS[1:8])
    await settle_all(store, StaticPriceSource({"AAA": bars, "SPY": flat(DAYS[:8])}),
                     today="2026-09-30")
    assert store.get(eid).settle_note == ""


# ── 7. benchmark backfill keeps the other notes ─────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_backfill_keeps_the_rescale_note(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    sid = store.save_snapshot({"AAA": (100.0, "2026-09-01", "static")})
    eid = store.add(entry(snapshot_id=sid), created_at=CREATED)
    stock = flat(DAYS[:8], 50.0)
    await settle_all(store, StaticPriceSource({"AAA": stock}), today="2026-09-30")
    note = store.get(eid).settle_note
    assert "benchmark data unavailable: SPY" in note and "rescaled x0.5000" in note
    rep = await settle_all(store, StaticPriceSource({"AAA": stock, "SPY": flat(DAYS[:8])}),
                           today="2026-09-30")
    assert rep.benchmarks_backfilled == 1
    assert store.get(eid).settle_note == "price levels rescaled x0.5000 (adjusted series changed)"


# ── 9. benchmark alignment and the terminal "not comparable" ────────────────

def test_benchmark_aligns_to_the_nearest_bar_within_three_days():
    xlk = [bar("2026-09-01", 100, 101, 99, 100), bar("2026-09-02", 100, 101, 99, 101),
           bar("2026-09-04", 102, 103, 101, 102), bar("2026-09-08", 103, 105, 102, 104),
           bar("2026-09-09", 104, 105, 103, 104)]
    # entry on a US holiday (09-03) -> 09-04 open; exit 09-07 (holiday) -> 09-04 close
    assert benchmark_return(xlk, "2026-09-03", "2026-09-07") == pytest.approx(0.0)
    assert benchmark_return(xlk, "2026-09-02", "2026-09-07") == pytest.approx(0.02)
    assert benchmark_return(xlk, "2026-09-03", "2026-09-08") == pytest.approx(104 / 102 - 1)
    assert benchmark_return(xlk, "2026-09-05", "2026-09-09") == pytest.approx(104 / 103 - 1)
    no_0908 = [b for b in xlk if b.date != "2026-09-08"]
    assert benchmark_return(no_0908, "2026-09-05", "2026-09-09") is None  # 4 days away
    assert benchmark_return(xlk, "2026-09-02", "2026-09-12") is None      # stale: nothing after
    assert benchmark_return(xlk[2:], "2026-09-03", "2026-09-08") is None  # series starts later


def settled(**kw):
    base = dict(status="settled", entry_date="2026-09-02", exit_date="2026-09-08",
                entry_price=100.0, exit_price=101.0, gross_return=0.01, net_return=0.009,
                domain_benchmark="XLK", ticker="7203.T")
    base.update(kw)
    return entry(**base)


def test_foreign_record_benchmark_gives_up_ten_days_after_exit():
    topix = flat(DAYS[:12])
    xlk = flat(["2026-08-20", "2026-08-21"] + DAYS[10:12])     # no bar near the window
    e = settled(settle_note="price levels rescaled x0.5000 (adjusted series changed)")
    apply_benchmarks(e, topix, xlk, today="2026-09-12")
    assert e.settle_note.startswith("benchmark data unavailable: XLK") and needs_benchmark(e)
    apply_benchmarks(e, topix, xlk, today="2026-09-18")
    assert e.settle_note == ("benchmark not comparable: XLK; "
                             "price levels rescaled x0.5000 (adjusted series changed)")
    assert not needs_benchmark(e) and e.market_return == 0.0
    # a failed fetch is not "not comparable": it is retried whatever the age
    f = settled()
    apply_benchmarks(f, topix, None, today="2026-12-31")
    assert f.settle_note == "benchmark data unavailable: XLK" and needs_benchmark(f)


@pytest.mark.asyncio
async def test_not_comparable_stops_the_retry_loop(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    eid = store.add(settled(), created_at=CREATED)
    src = StaticPriceSource({"7203.T": flat(DAYS[:12]), "1306.T": flat(DAYS[:12]),
                             "XLK": flat(["2026-08-20"] + DAYS[10:12])})
    await settle_all(store, src, today="2026-09-25")
    e = store.get(eid)
    assert e.settle_note == "benchmark not comparable: XLK" and e.domain_return is None
    assert e.market_return == 0.0
    rep = await settle_all(store, src, today="2026-09-26")
    assert rep.benchmarks_backfilled == 0 and not needs_benchmark(store.get(eid))


# ── 11. the benchmark leg takes the record's direction ──────────────────────

def test_short_excess_in_rising_and_falling_benchmarks():
    days = ["2026-09-02", "2026-09-03"]
    up = [bar(days[0], 100, 101, 99, 100), bar(days[1], 100, 106, 99, 105)]
    down = [bar(days[0], 100, 101, 99, 100), bar(days[1], 100, 101, 94, 95)]
    kw = dict(ticker="AAA", direction="short", entry_date=days[0], exit_date=days[1],
              domain_benchmark="XLK")
    # a short that tracks a rising benchmark loses exactly what shorting it would
    e = settled(net_return=-0.051, **kw)
    apply_benchmarks(e, up, up, today="2026-09-04")
    assert e.excess_market == pytest.approx(-0.001) and e.excess_domain == pytest.approx(-0.001)
    # and one that tracks a falling benchmark earns what shorting it would
    e = settled(net_return=0.049, **kw)
    apply_benchmarks(e, down, down, today="2026-09-04")
    assert e.market_return == pytest.approx(-0.05)
    assert e.excess_market == pytest.approx(-0.001) and e.excess_domain == pytest.approx(-0.001)
    # a long is unchanged: net - benchmark
    e = settled(net_return=0.06, **{**kw, "direction": "long"})
    apply_benchmarks(e, up, up, today="2026-09-04")
    assert e.excess_market == pytest.approx(0.01)
