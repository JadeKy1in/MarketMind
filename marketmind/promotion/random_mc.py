"""Monte Carlo "beats random" baseline for the probation gate (docs/S7_DESIGN.md §一).

The ledger's random-baseline shadow (`random:<sid>`) draws one $100 trade a day, so
comparing a shadow's mean with it is close to a coin flip. This gate instead builds
MC_DRAWS random portfolios per shadow, each mirroring the shadow's own settled trades:

- same number of trades, and for trade i the same entry and exit dates (so the same
  realised holding period);
- the same long/short ratio: the shadow's direction vector is randomly permuted
  across its trades in every draw (timing of direction is not given away);
- the ticker of every trade is drawn uniformly from the shadow's ticker pool: its
  roster watchlist (what the random-baseline shadow samples from, `sorted(ctx.closes)`)
  plus every ticker the random-baseline shadow has actually drawn for it (covers the
  news-driven extras some shadows get);
- net return = direction * (close(last bar <= exit) / open(first bar >= entry) - 1)
  - 2 * cost_bps / 10_000, the ledger's own cost rule (`settlement.cost_bps`, asset
  type from `recorder.classify_ticker` as for the random-baseline records).

Gate: shadow mean net return >= the MC_QUANTILE quantile of the draw means and
p = (1 + #draws with mean >= shadow mean) / (1 + valid draws) <= MC_ALPHA
(White 2000 Reality Check / Davison-Hinkley style Monte Carlo p-value).

Missing data fails closed: pool tickers without any bars are dropped and listed; a
draw that picks a ticker with a gap in that trade's window is excluded; fewer than
MC_MIN_VALID valid draws, or more than MC_MAX_POOL_MISSING of the pool without bars,
make the gate "not_evaluable". The RNG seed is sha256(shadow id + review date), so
a re-run on the same day with the same ledger gives the same answer.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Callable, Mapping

import numpy as np

from marketmind.gateway.price_history import Bar
from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C

log = logging.getLogger(__name__)

BarsFor = Callable[[list[str]], Mapping[str, "list[Bar] | None"]]
DRAW_CHUNK = 250                 # draws simulated per numpy batch (bounds memory)
FETCH_CONCURRENCY = 4            # < price_history's yfinance semaphore (5): never contended


def seed_for(shadow_id: str, today: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{shadow_id}:{today}".encode()).digest()[:8], "big")


def round_trip_cost(ticker: str) -> float:
    """2 x one-way cost as a return, exactly as settlement charges a record in `ticker`."""
    from marketmind.ledger.recorder import classify_ticker
    from marketmind.ledger.settlement import cost_bps
    return 2 * cost_bps(classify_ticker(ticker)[1], ticker) / 10_000


def _gap(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def window_return(bars: list[Bar], dates: list[str], entry: str, exit_: str,
                  max_gap: int = C.MC_MAX_GAP_DAYS) -> float | None:
    """Gross long return from the open of the first bar >= entry to the close of the
    last bar <= exit. None when the window has no bar or its first / last bar lies more
    than `max_gap` calendar days inside the window (data gap, not yet listed, stale)."""
    i0, i1 = bisect_left(dates, entry), bisect_right(dates, exit_) - 1
    if i0 >= len(dates) or i1 < i0:
        return None
    if _gap(entry, dates[i0]) > max_gap or _gap(dates[i1], exit_) > max_gap:
        return None
    o, c = bars[i0].open, bars[i1].close
    if not (o > 0 and c > 0):
        return None
    return c / o - 1


def mc_baseline(shadow_id: str, trades: list[LedgerEntry], pool: list[str],
                bars: Mapping[str, "list[Bar] | None"], today: str,
                draws: int = C.MC_DRAWS) -> dict:
    """Run the Monte Carlo gate for one shadow. `trades` are its settled records."""
    trades = [e for e in trades if e.status == "settled" and e.entry_date and e.exit_date
              and e.net_return is not None]
    pool = sorted(set(pool))
    seed = seed_for(shadow_id, today)
    out: dict = {"method": "monte_carlo", "status": "not_evaluable", "draws": draws,
                 "trades": len(trades), "pool": len(pool), "seed": seed}
    if not trades:
        return {**out, "reason": "no settled trades"}
    shadow_mean = float(np.mean([e.net_return for e in trades]))
    out["shadow_mean"] = shadow_mean
    usable = [t for t in pool if bars.get(t)]
    missing = [t for t in pool if not bars.get(t)]
    out.update(pool_usable=len(usable), missing_tickers=missing)
    if not usable or len(missing) > C.MC_MAX_POOL_MISSING * len(pool):
        return {**out, "reason": f"{len(missing)}/{len(pool)} pool tickers without bars"}

    n, k = len(trades), len(usable)
    gross = np.full((n, k), np.nan)
    for j, t in enumerate(usable):
        b = sorted(bars[t], key=lambda x: x.date)
        dates = [x.date for x in b]
        for i, e in enumerate(trades):
            r = window_return(b, dates, e.entry_date[:10], e.exit_date[:10])
            if r is not None:
                gross[i, j] = r
    cost = np.array([round_trip_cost(t) for t in usable])
    dirs = np.array([1.0 if e.direction == "long" else -1.0 for e in trades])
    rows = np.arange(n)

    rng = np.random.default_rng(seed)
    means: list[np.ndarray] = []
    for start in range(0, draws, DRAW_CHUNK):
        m = min(DRAW_CHUNK, draws - start)
        pick = rng.integers(0, k, size=(m, n))
        sign = rng.permuted(np.tile(dirs, (m, 1)), axis=1)
        vals = sign * gross[rows, pick] - cost[pick]
        ok = ~np.isnan(vals).any(axis=1)
        means.append(vals[ok].mean(axis=1))
    sims = np.concatenate(means) if means else np.array([])
    valid = int(sims.size)
    out.update(valid_draws=valid, gap_cells=int(np.isnan(gross).sum()), cells=n * k)
    if valid < C.MC_MIN_VALID:
        return {**out, "reason": f"only {valid} valid draws (< {C.MC_MIN_VALID})"}
    q = float(np.quantile(sims, C.MC_QUANTILE))
    exceed = int(np.sum(sims >= shadow_mean))
    p = (1 + exceed) / (1 + valid)
    passed = shadow_mean >= q and p <= C.MC_ALPHA
    return {**out, "status": "pass" if passed else "fail", "sim_mean": float(sims.mean()),
            "sim_sd": float(sims.std(ddof=1)) if valid > 1 else 0.0,
            "sim_quantile": q, "p_value": p}


# ── Bar loading ─────────────────────────────────────────────────────────

def _run_sync(factory):
    """Run a coroutine from sync code, also when called inside a running event loop
    (the daily pipeline's async promotion step): then in a worker thread's own loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(factory())).result()


def source_loader(source, *, today: str | None = None, live: bool = False,
                  budget_s: float = C.MC_FETCH_BUDGET_S) -> BarsFor:
    """Bars loader over a ledger `PriceSource`, cached for the loader's lifetime.

    The default `HistoryPriceSource` also shares gateway.price_history's per-process
    cache, so in the daily run most pool tickers are already loaded by settlement and
    the shadow run. Uncached tickers are fetched with at most FETCH_CONCURRENCY
    requests and a total wall-clock budget; whatever is not loaded in time counts as
    missing (the gate fails closed). `live` drops the running session's partial bar
    (settlement's rule); `today` drops bars after that date."""
    from marketmind.gateway.price_history import complete_bars
    cache: dict[str, list[Bar] | None] = {}

    async def fetch(tickers: list[str]) -> dict[str, list[Bar] | None]:
        sem = asyncio.Semaphore(FETCH_CONCURRENCY)
        deadline = time.monotonic() + budget_s

        async def one(t: str):
            async with sem:
                left = deadline - time.monotonic()
                if left <= 0:
                    return t, None
                try:
                    return t, await asyncio.wait_for(source.daily_bars(t), timeout=left)
                except Exception as exc:                  # noqa: BLE001 - reported, fails closed
                    log.warning("MC baseline: bars for %s unavailable: %s", t, exc)
                    return t, None
        return dict(await asyncio.gather(*(one(t) for t in tickers)))

    def load(tickers: list[str]) -> dict[str, list[Bar] | None]:
        need = [t for t in dict.fromkeys(tickers) if t not in cache]
        if need:
            started = time.monotonic()
            got = _run_sync(lambda: fetch(need))
            for t in need:
                b = got.get(t) or []
                if b and live:
                    b = complete_bars(t, b)
                if b and today:
                    b = [x for x in b if x.date <= today]
                cache[t] = b or None
            log.info("MC baseline: %d tickers loaded in %.1fs (%d without bars)", len(need),
                     time.monotonic() - started, sum(cache[t] is None for t in need))
        return {t: cache.get(t) for t in tickers}
    return load


def static_loader(bars: Mapping[str, "list[Bar] | None"]) -> BarsFor:
    """Loader over an in-memory {ticker: bars} map (tests, replays)."""
    return lambda tickers: {t: bars.get(t) for t in tickers}
