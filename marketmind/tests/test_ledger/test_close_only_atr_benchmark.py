"""Close-only bars (price_history.Bar.close_only: open/high/low are copies of the close)
must not distort the ATR (l3_indicators, compute_review) or benchmark entry prices."""
from datetime import date, timedelta

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory, to_weekly
from marketmind.ledger.settlement import benchmark_return, compute_review
from marketmind.ledger.store import LedgerEntry
from marketmind.pipeline.l3_indicators import atr, compute_snapshot, true_ranges


def _days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(n, close_only_at=()):
    """Closes alternate 100 / 101 with a +-1 range: every full bar's true range is 2.
    A close-only bar (O=H=L=C, no volume) would give a true range of 1."""
    out = []
    for i, d in enumerate(_days(n)):
        c = 100.0 + (i % 2)
        if i in close_only_at:
            out.append(Bar(d, c, c, c, c, 0.0, close_only=True))
        else:
            out.append(Bar(d, c, c + 1, c - 1, c, 1000.0))
    return out


# ── l3_indicators.atr / compute_snapshot ────────────────────────────────────

def test_atr_skips_close_only_bars():
    bars = _bars(30, close_only_at={25, 27, 29})
    assert atr(bars) == pytest.approx(2.0)
    assert len(true_ranges(bars)) == 29 - 3
    # an unflagged copy of the same data is distorted: that is what the flag prevents
    raw = [Bar(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    assert atr(raw) < 2.0


def test_atr_close_only_close_still_serves_as_previous_close():
    bars = [Bar("2026-09-22", 100, 101, 99, 100, 10),
            Bar("2026-09-23", 110, 110, 110, 110, 0, close_only=True),
            Bar("2026-09-24", 111, 112, 109, 111, 10)]
    assert true_ranges(bars) == [3.0]          # max(3, |112-110|, |109-110|)


def test_atr_with_only_close_only_bars_is_zero_not_an_error():
    bars = _bars(5, close_only_at={1, 2, 3, 4})
    assert true_ranges(bars) == [] and atr(bars) == 0.0
    assert atr([]) == 0.0 and atr(bars[:1]) == 0.0


def test_compute_snapshot_atr_ignores_close_only_bars():
    daily = _bars(120, close_only_at={110, 113, 116, 119})
    snap = compute_snapshot(PriceHistory("PL=F", "test", daily, to_weekly(daily)))
    assert snap is not None and snap.atr14 == pytest.approx(2.0)


# ── settlement.compute_review ───────────────────────────────────────────────

def _settled(bars, entry_i, exit_i):
    return LedgerEntry(source_type="main", source_id="t", ticker="PL=F", direction="long",
                       hold_bars=exit_i - entry_i + 1, confidence=0.6, position_usd=1000.0,
                       falsifier="f", status="settled", entry_date=bars[entry_i].date,
                       entry_price=bars[entry_i].open, exit_date=bars[exit_i].date,
                       exit_price=bars[exit_i].close, gross_return=0.0, net_return=0.0)


def test_review_atr_skips_close_only_bars_and_reaches_further_back():
    bars = _bars(30, close_only_at={17, 18, 19})
    r = compute_review(_settled(bars, 20, 22), bars)
    # last close before entry is 101 (index 19): 2 / 101
    assert r["atr_pct"] == pytest.approx(round(2.0 / 101.0, 6))


def test_review_atr_none_when_too_few_full_bars():
    bars = _bars(30, close_only_at={10, 11, 12})
    # 15 bars before entry, 3 of them close-only: only 11 true ranges
    r = compute_review(_settled(bars, 15, 17), bars)
    assert r["atr_pct"] is None and r["mfe_atr"] is None
    # the same window without close-only bars has its 14 true ranges
    full = _bars(30)
    assert compute_review(_settled(full, 15, 17), full)["atr_pct"] == pytest.approx(
        round(2.0 / 100.0, 6))                  # last close before entry: 100 (index 14)


# ── settlement.benchmark_return ─────────────────────────────────────────────

def test_benchmark_close_only_first_bar_uses_previous_close():
    bars = [Bar("2026-09-01", 99, 101, 98, 100, 10),
            Bar("2026-09-02", 104, 104, 104, 104, 0, close_only=True),
            Bar("2026-09-03", 104, 111, 103, 110, 10),
            Bar("2026-09-04", 110, 111, 109, 110, 10)]
    # not 110 / 104 (the close-only "open"), but close-to-close from 2026-09-01
    assert benchmark_return(bars, "2026-09-02", "2026-09-03") == pytest.approx(0.10)
    # a full first bar keeps its open
    assert benchmark_return(bars, "2026-09-03", "2026-09-04") == pytest.approx(110 / 104 - 1)
    # a close-only last bar is fine: its close is real
    bars[3] = Bar("2026-09-04", 120, 120, 120, 120, 0, close_only=True)
    assert benchmark_return(bars, "2026-09-03", "2026-09-04") == pytest.approx(120 / 104 - 1)


def test_benchmark_close_only_first_bar_without_previous_bar_is_none():
    bars = [Bar("2026-09-02", 104, 104, 104, 104, 0, close_only=True),
            Bar("2026-09-03", 104, 111, 103, 110, 10)]
    assert benchmark_return(bars, "2026-09-02", "2026-09-03") is None
