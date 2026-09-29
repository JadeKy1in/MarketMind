"""Feature panel for the ml_gbm Playground agent (docs/PLAYGROUND_AGENTS.md §7).

One row per (instrument, complete daily bar). Every feature of the row dated d is a
function of bars dated <= d only (the instrument's own bars, plus the latest SPY / ^VIX
bar and the other instruments' latest bars dated <= d for the market features and the
cross-sectional ranks). The label looks HORIZON bars ahead and is only used for
training rows whose label end date lies before the purge cut-off (model.py).

numpy only (pandas is not a declared runtime dependency).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

import numpy as np

from marketmind.gateway.price_history import Bar, is_crypto_ticker
from marketmind.trend.rules import wilder_atr

HORIZON = 10                      # label / holding horizon in the instrument's bars
WARMUP = 252                      # bars needed before the first feature row (ret_252)
MAX_ASOF_AGE_DAYS = 7             # an as-of value older than this counts as missing

SECTORS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
UNIVERSE: tuple[str, ...] = SECTORS + ("SPY", "QQQ", "IWM", "GLD", "TLT", "BTC-USD", "ETH-USD")
MARKET_TICKER, VIX_TICKER = "SPY", "^VIX"

RET_WINDOWS = (5, 20, 60, 120, 252)
RANKED = ("ret_20", "ret_60", "ret_120", "ret_252")
OWN_FEATURES = ([f"ret_{n}" for n in RET_WINDOWS]
                + ["vol_20", "vol_60", "dist_sma50", "dist_sma200", "dist_high55",
                   "atr_pct", "volume_z20", "cost_rt"])
XS_FEATURES = [f"rank_{f}" for f in RANKED]
MARKET_FEATURES = ["spy_ret_20", "vix"]
FEATURES: list[str] = OWN_FEATURES + XS_FEATURES + MARKET_FEATURES


def round_trip_cost(ticker: str) -> float:
    """Round-trip cost as a return fraction, from the ledger's settlement costs."""
    from marketmind.ledger.recorder import classify_ticker
    from marketmind.ledger.settlement import cost_bps
    return 2 * cost_bps(classify_ticker(ticker)[1], ticker) / 10_000


def _trailing(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) > n:
        prev = c[:-n]
        out[n:] = np.where(prev > 0, c[n:] / np.where(prev > 0, prev, 1.0) - 1, np.nan)
    return out


def _rolling(x: np.ndarray, n: int, fn) -> np.ndarray:
    """fn over the trailing window x[i-n+1 .. i] (nan until n values exist)."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = fn(w, axis=1)
    return out


def instrument_features(ticker: str, bars: Sequence[Bar]) -> dict[str, np.ndarray]:
    """Own features for every bar (row i uses bars[: i + 1]) plus the forward label."""
    c = np.array([b.close for b in bars], dtype=float)
    h = np.array([b.high for b in bars], dtype=float)
    v = np.array([b.volume or 0.0 for b in bars], dtype=float)
    n = len(c)
    annual = 365 if is_crypto_ticker(ticker) else 252
    f: dict[str, np.ndarray] = {}
    for w in RET_WINDOWS:
        f[f"ret_{w}"] = _trailing(c, w)
    logret = np.full(n, np.nan)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            logret[1:] = np.log(c[1:] / c[:-1])
    for w in (20, 60):
        f[f"vol_{w}"] = _rolling(logret, w, np.std) * math.sqrt(annual)
    for w in (50, 200):
        f[f"dist_sma{w}"] = c / _rolling(c, w, np.mean) - 1
    f["dist_high55"] = c / _rolling(h, 55, np.max) - 1
    atr = np.array([np.nan if a is None else a for a in wilder_atr(bars, 20)], dtype=float)
    f["atr_pct"] = atr / c
    logv = np.log1p(np.maximum(v, 0.0))
    mu, sd = _rolling(logv, 20, np.mean), _rolling(logv, 20, np.std)
    with np.errstate(divide="ignore", invalid="ignore"):
        f["volume_z20"] = np.where((sd > 0) & (v > 0), (logv - mu) / sd, np.nan)
    cost = round_trip_cost(ticker)
    f["cost_rt"] = np.full(n, cost)
    fwd = np.full(n, np.nan)
    if n > HORIZON:
        fwd[:-HORIZON] = c[HORIZON:] / c[:-HORIZON] - 1
    f["fwd_ret"] = fwd
    f["label"] = np.where(np.isnan(fwd), np.nan, (fwd > cost).astype(float))
    ends = np.full(n, np.datetime64("NaT"), dtype="datetime64[D]")
    dates = np.array([b.date for b in bars], dtype="datetime64[D]")
    if n > HORIZON:
        ends[:-HORIZON] = dates[HORIZON:]
    f["label_end"] = ends
    f["date"] = dates
    return f


def asof(src_dates: np.ndarray, src_vals: np.ndarray, at: np.ndarray,
         max_age: int = MAX_ASOF_AGE_DAYS) -> np.ndarray:
    """Value of the latest src bar dated <= each `at` date (nan if none or too old)."""
    out = np.full(len(at), np.nan)
    if len(src_dates) == 0:
        return out
    idx = np.searchsorted(src_dates, at, side="right") - 1
    ok = idx >= 0
    safe = np.where(ok, idx, 0)
    age = (at - src_dates[safe]).astype(int)
    ok &= age <= max_age
    out[ok] = src_vals[safe[ok]]
    return out


@dataclass
class Panel:
    tickers: list[str]
    ticker: np.ndarray            # index into tickers
    date: np.ndarray              # datetime64[D]
    X: np.ndarray                 # (rows, len(FEATURES))
    fwd_ret: np.ndarray
    label: np.ndarray             # 1 / 0 / nan (unknown yet)
    label_end: np.ndarray         # datetime64[D], NaT when unknown
    cost_rt: np.ndarray
    calendar: np.ndarray          # master calendar: SPY complete-bar dates
    features: list[str] = field(default_factory=lambda: list(FEATURES))

    def rows(self, mask: np.ndarray) -> "Panel":
        return Panel(self.tickers, self.ticker[mask], self.date[mask], self.X[mask],
                     self.fwd_ret[mask], self.label[mask], self.label_end[mask],
                     self.cost_rt[mask], self.calendar, self.features)


def build_panel(histories: dict[str, Sequence[Bar] | None],
                universe: Sequence[str] = UNIVERSE) -> Panel:
    """Stack the feature rows of every instrument with >= WARMUP + 1 bars."""
    own = {t: instrument_features(t, histories[t]) for t in universe
           if histories.get(t) and len(histories[t]) > WARMUP}
    spy = histories.get(MARKET_TICKER) or []
    calendar = np.array([b.date for b in spy], dtype="datetime64[D]")
    spy_f = own.get(MARKET_TICKER) or (instrument_features(MARKET_TICKER, spy) if spy else None)
    vix = histories.get(VIX_TICKER) or []
    vix_d = np.array([b.date for b in vix], dtype="datetime64[D]")
    vix_c = np.array([b.close for b in vix], dtype=float)
    tickers = list(own)
    blocks = []
    for k, t in enumerate(tickers):
        f = own[t]
        d = f["date"]
        cols = [f[name] for name in OWN_FEATURES]
        # cross-sectional percentile rank among instruments with a fresh value that day
        for name in RANKED:
            mine = f[name]
            others = np.vstack([asof(own[u]["date"], own[u][name], d) for u in tickers])
            valid = ~np.isnan(others)
            below = np.sum(valid & (others < mine), axis=0) + 0.5 * (np.sum(valid & (others == mine), axis=0) - 1)
            cnt = valid.sum(axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                rank = np.where((cnt > 1) & ~np.isnan(mine), below / (cnt - 1), np.nan)
            cols.append(rank)
        cols.append(asof(spy_f["date"], spy_f["ret_20"], d) if spy_f else np.full(len(d), np.nan))
        cols.append(asof(vix_d, vix_c, d))
        X = np.column_stack(cols)
        keep = np.arange(len(d)) >= WARMUP
        blocks.append((np.full(keep.sum(), k), d[keep], X[keep], f["fwd_ret"][keep],
                       f["label"][keep], f["label_end"][keep], f["cost_rt"][keep]))
    if not blocks:
        empty = np.array([], dtype="datetime64[D]")
        return Panel([], np.array([], int), empty, np.zeros((0, len(FEATURES))), np.array([]),
                     np.array([]), empty, np.array([]), calendar)
    parts = list(zip(*blocks))
    return Panel(tickers, np.concatenate(parts[0]).astype(int), np.concatenate(parts[1]),
                 np.vstack(parts[2]), np.concatenate(parts[3]), np.concatenate(parts[4]),
                 np.concatenate(parts[5]), np.concatenate(parts[6]), calendar)


def to_date(d) -> date:
    return date.fromisoformat(str(np.datetime64(d, "D")))
