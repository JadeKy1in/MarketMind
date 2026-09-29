"""Monte Carlo "beats random" baseline for the probation gate (docs/S7_DESIGN.md §一).

The ledger's random-baseline shadow (`random:<sid>`) draws one $100 trade a day, so
comparing a shadow's mean with it is close to a coin flip. This gate instead builds
MC_DRAWS random portfolios per shadow by moving the shadow's own trades in time
(fix 2026-09-29; it replaced uniform ticker draws from the watchlist pool):

- every trade keeps its ticker, direction and length in bars, so the same asset, cost,
  holding period and exactly the same long/short mix;
- each draw shifts ALL trades by one common random offset inside the evaluation
  window (first entry .. last exit of the evaluated trades), wrapping around at the
  window end; a ticker with another bar calendar (crypto) moves by the same share of
  its own window. Overlaps between trades, concentration in one ticker and
  cross-ticker timing stay those of the shadow; only the entry dates are random;
- net return = direction * (close(last bar of the moved window) / open(first bar) - 1)
  - 2 * cost_bps / 10_000, the ledger's own cost rule (`settlement.cost_bps`).

Why: drawing tickers uniformly from the watchlist compared a concentrated shadow's
mean with a diversified random mean. A zero-skill shadow that trades high-volatility
tickers, or one ticker with overlapping holds, has a much wider sampling distribution
than those random portfolios and "beat" them far more often than the nominal 5%
(simulated 2026-09-29, docs/S7_DESIGN.md implementation notes). Moving the shadow's
own trades in time keeps its risk profile exactly, so the test measures the timing of
its entries and directions, not its appetite for volatility. Ticker selection is
judged by the domain-ETF and main-pipeline gates.

Gate: shadow mean net return (ledger) >= the MC_QUANTILE quantile of the draw means
and p = (1 + #draws with mean >= shadow mean) / (1 + valid draws) <= MC_ALPHA
(White 2000 Reality Check / Davison-Hinkley style Monte Carlo p-value).

Missing data fails closed: a trade whose ticker has no bars, or with a gap at its
entry / exit (more than MC_MAX_GAP_DAYS calendar days), is unpriced; more than
MC_MAX_UNPRICED_SHARE of the trades unpriced, an evaluation window shorter than
MC_MIN_WINDOW_DAYS (too few distinct shifts), or fewer than MC_MIN_VALID finite draws
make the gate "not_evaluable". The RNG seed is sha256(shadow id + review date), so a
re-run on the same day gives the same answer.
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


def _locate(dates: list[str], entry: str, exit_: str,
            max_gap: int = C.MC_MAX_GAP_DAYS) -> tuple[int, int] | None:
    """(index of the first bar >= entry, index of the last bar <= exit), or None when
    the window has no bar or its first / last bar lies more than `max_gap` calendar
    days inside the window (data gap, not yet listed, stale)."""
    i0, i1 = bisect_left(dates, entry), bisect_right(dates, exit_) - 1
    if i0 >= len(dates) or i1 < i0:
        return None
    if _gap(entry, dates[i0]) > max_gap or _gap(dates[i1], exit_) > max_gap:
        return None
    return i0, i1


def window_return(bars: list[Bar], dates: list[str], entry: str, exit_: str,
                  max_gap: int = C.MC_MAX_GAP_DAYS) -> float | None:
    """Gross long return from the open of the first bar >= entry to the close of the
    last bar <= exit; None on a data gap (see `_locate`)."""
    loc = _locate(dates, entry, exit_, max_gap)
    if loc is None:
        return None
    o, c = bars[loc[0]].open, bars[loc[1]].close
    if not (o > 0 and c > 0):
        return None
    return c / o - 1


def mc_baseline(shadow_id: str, trades: list[LedgerEntry],
                bars: Mapping[str, "list[Bar] | None"], today: str,
                draws: int = C.MC_DRAWS) -> dict:
    """Run the Monte Carlo gate for one shadow. `trades` are its evaluated settled
    records (matured decision cohorts); `bars` should hold every ticker they traded."""
    trades = [e for e in trades if e.status == "settled" and e.entry_date and e.exit_date
              and e.net_return is not None]
    seed = seed_for(shadow_id, today)
    tickers = sorted({e.ticker for e in trades})
    out: dict = {"method": "monte_carlo_time_shift", "status": "not_evaluable",
                 "draws": draws, "trades": len(trades), "tickers": len(tickers), "seed": seed}
    if not trades:
        return {**out, "reason": "no settled trades"}
    lo = min(e.entry_date[:10] for e in trades)
    hi = max(e.exit_date[:10] for e in trades)
    window: dict[str, tuple[list[str], np.ndarray, np.ndarray]] = {}
    for t in tickers:
        w = sorted((x for x in (bars.get(t) or []) if lo <= x.date <= hi), key=lambda x: x.date)
        if w:
            window[t] = ([x.date for x in w], np.array([x.open for x in w], dtype=float),
                         np.array([x.close for x in w], dtype=float))
    rows = []                                        # (ticker, start, length, sign, cost, net)
    for e in trades:
        loc = (_locate(window[e.ticker][0], e.entry_date[:10], e.exit_date[:10])
               if e.ticker in window else None)
        if loc is not None:
            rows.append((e.ticker, loc[0], loc[1] - loc[0] + 1,
                         1.0 if e.direction == "long" else -1.0, round_trip_cost(e.ticker),
                         float(e.net_return)))
    unpriced = len(trades) - len(rows)
    out.update(missing_tickers=[t for t in tickers if t not in window], unpriced_trades=unpriced)
    if not rows or unpriced > C.MC_MAX_UNPRICED_SHARE * len(trades):
        return {**out, "reason": f"{unpriced}/{len(trades)} trades without usable bars"}
    ref_days = len({d for dates, _, _ in window.values() for d in dates})
    out["window_days"] = ref_days
    if ref_days < C.MC_MIN_WINDOW_DAYS:
        return {**out, "reason": f"evaluation window {ref_days} < {C.MC_MIN_WINDOW_DAYS} days"}
    shadow_mean = float(np.mean([r[5] for r in rows]))
    out["shadow_mean"] = shadow_mean

    # one common shift per draw: 1 .. ref_days - 1 days, as a share of each ticker's window
    rng = np.random.default_rng(seed)
    frac = rng.integers(1, ref_days, size=draws) / ref_days
    total = np.zeros(draws)
    with np.errstate(divide="ignore", invalid="ignore"):
        for ticker, start, length, sign, cost, _ in rows:
            _, o, c = window[ticker]
            shift = np.floor(frac * o.size + 1e-9).astype(int)
            s0 = (start + shift) % (o.size - length + 1)
            gross = np.where(o[s0] > 0, c[s0 + length - 1] / o[s0] - 1, np.nan)
            total += sign * gross - cost
    sims = total[np.isfinite(total)] / len(rows)
    valid = int(sims.size)
    out["valid_draws"] = valid
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
