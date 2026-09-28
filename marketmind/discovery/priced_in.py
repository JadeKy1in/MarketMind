"""Pure-code "already priced in?" check per anomaly x proxy (docs/S10_DESIGN.md §2).

From the anomaly's latest observation date (the base = the proxy's last complete
daily close on or before that date) to the proxy's latest complete close:
- move_atr    = (last close - base close) / ATR14 at the base date;
- excess      = for single stocks with a sector ETF mapping, the stock's return minus
                the ETF's, converted to ATR multiples of the stock (ETFs / crypto: none);
- volume_ratio = mean volume of the bars after the base / mean of the 20 bars up to
                and including the base;
- agree       = the measured move has the sign of the implied direction.
Buckets (thresholds configurable): agree and >= 2 ATR -> priced_in; agree and
0.5-2 ATR -> partial; < 0.5 ATR or the opposite direction -> not_priced.

Approximation: the base is the *observation* date, not the publication time
(weekly FRED / SOMA / EIA data are published one to five days later), so any move
between observation and publication counts as already taken. That errs towards
"priced in", i.e. towards fewer candidates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from marketmind.gateway.price_history import Bar
from marketmind.pipeline.l3_indicators import atr

PRICED_IN = "priced_in"
PARTIAL = "partial"
NOT_PRICED = "not_priced"
UNAVAILABLE = "unavailable"

# Single stock -> sector ETF for excess returns. Empty in v1: every registry proxy
# is an ETF or a crypto pair, which get no excess (S10 §2 "keep simple").
SECTOR_ETF: dict[str, str] = {}


@dataclass(frozen=True)
class PricedInConfig:
    atr_n: int = 14
    priced_atr: float = 2.0
    partial_atr: float = 0.5
    volume_lookback: int = 20

    def to_dict(self) -> dict:
        return asdict(self)


def _base_index(bars: list[Bar], since: str) -> int | None:
    idx = None
    for i, b in enumerate(bars):
        if b.date <= since:
            idx = i
        else:
            break
    return idx


def _ret(bars: list[Bar], since: str) -> float | None:
    i = _base_index(bars, since)
    if i is None or not bars[i].close:
        return None
    return bars[-1].close / bars[i].close - 1


def bucket_for(measure: float, implied: int, cfg: PricedInConfig) -> tuple[bool, str]:
    agree = implied != 0 and measure != 0 and (measure > 0) == (implied > 0)
    if not agree:
        return False, NOT_PRICED
    m = abs(measure)
    if m >= cfg.priced_atr:
        return True, PRICED_IN
    if m >= cfg.partial_atr:
        return True, PARTIAL
    return True, NOT_PRICED


def assess(ticker: str, bars: list[Bar] | None, since: str, implied: int,
           cfg: PricedInConfig | None = None, sector_bars: list[Bar] | None = None,
           sector_etf: str | None = None) -> dict:
    """One anomaly x proxy row. `bars` are complete daily bars, oldest first."""
    cfg = cfg or PricedInConfig()
    row = {"ticker": ticker, "implied_direction": implied, "since": since,
           "base_date": None, "base_close": None, "last_date": None, "last_close": None,
           "bars_since": None, "return_pct": None, "atr14": None, "move_atr": None,
           "sector_etf": None, "excess_pct": None, "excess_atr": None,
           "volume_ratio": None, "agree": None, "bucket": UNAVAILABLE, "reason": ""}
    if not bars:
        row["reason"] = "no price history"
        return row
    i = _base_index(bars, since)
    if i is None:
        row["reason"] = f"no bar on or before {since}"
        return row
    if i < cfg.atr_n:
        row["reason"] = f"fewer than {cfg.atr_n + 1} bars up to {since} for ATR{cfg.atr_n}"
        return row
    base, last = bars[i], bars[-1]
    a = atr(bars[:i + 1], cfg.atr_n)
    if a <= 0 or not base.close:
        row["reason"] = "zero ATR or close at the base date"
        return row
    after = bars[i + 1:]
    row.update(base_date=base.date, base_close=base.close, last_date=last.date,
               last_close=last.close, bars_since=len(after),
               return_pct=round((last.close / base.close - 1) * 100, 3),
               atr14=round(a, 6), move_atr=round((last.close - base.close) / a, 3))
    prior_vol = [b.volume for b in bars[max(0, i + 1 - cfg.volume_lookback):i + 1]]
    if after and prior_vol and sum(prior_vol) > 0:
        row["volume_ratio"] = round((sum(b.volume for b in after) / len(after))
                                    / (sum(prior_vol) / len(prior_vol)), 3)
    measure = row["move_atr"]
    if sector_etf:
        row["sector_etf"] = sector_etf
        etf_ret = _ret(sector_bars or [], since)
        if etf_ret is None:
            row["reason"] = f"sector ETF {sector_etf} unavailable: excess not computed"
        else:
            excess = (last.close / base.close - 1) - etf_ret
            row["excess_pct"] = round(excess * 100, 3)
            row["excess_atr"] = round(excess * base.close / a, 3)
            measure = row["excess_atr"]
    row["agree"], row["bucket"] = bucket_for(measure, implied, cfg)
    return row
