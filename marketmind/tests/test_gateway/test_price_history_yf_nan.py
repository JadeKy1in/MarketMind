"""yfinance rows with NaN O/H/L/C are dropped; NaN volume becomes 0.0 (offline)."""
import math

import pandas as pd

from marketmind.gateway import price_history as ph


def _frame(rows):
    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame([r[1:] for r in rows], index=idx,
                        columns=["Open", "High", "Low", "Close", "Volume"])


def test_rows_with_any_nan_ohlc_are_dropped():
    nan = float("nan")
    df = _frame([
        ("2026-09-21", 10.0, 11.0, 9.0, 10.5, 100.0),
        ("2026-09-22", nan, 11.0, 9.0, 10.5, 100.0),
        ("2026-09-23", 10.0, nan, 9.0, 10.5, 100.0),
        ("2026-09-24", 10.0, 11.0, nan, 10.5, 100.0),
        ("2026-09-25", 10.0, 11.0, 9.0, nan, 100.0),
        ("2026-09-26", 10.0, 11.0, 9.0, 10.8, nan),
    ])
    bars = ph._yf_bars(df)
    assert [b.date for b in bars] == ["2026-09-21", "2026-09-26"]
    assert bars[1].volume == 0.0
    assert all(math.isfinite(x) for b in bars for x in (b.open, b.high, b.low, b.close, b.volume))


def test_yf_sync_returns_none_when_every_row_is_nan(monkeypatch):
    nan = float("nan")
    df = _frame([("2026-09-25", nan, nan, nan, 10.0, 5.0)])

    class _T:
        def __init__(self, sym):
            pass

        def history(self, **kw):
            return df

    monkeypatch.setattr(ph, "yf", type("YF", (), {"Ticker": _T}))
    assert ph._yf_sync("AAPL", 1) is None
