"""On-chain valuation (MVRV bands) with a Fear & Greed contrarian filter - pure code.

Evidence: Grobys, Näsman & Sandretto (2026), "Using on-chain data to predict Bitcoin
cycles", Research in International Business and Finance 89:103486: on BTC 2013-12 to
2025-04 a long/flat rule that enters when the MVRV Z-score falls below -0.2 and exits
when it reaches 5 / 6 / 7 beat buy-and-hold (Sharpe 1.28 vs 0.45 for Z). That is three
cycles and three trades per rule: weak evidence, recorded as such
(docs/PLAYGROUND_AGENTS.md §8).

Pre-registered rule (fixed before looking at our ledger; not tuned):
  metric   BTC: MVRV Z = (market cap - realized cap) / sigma(market cap), sigma over all
           days up to t (no look-ahead). Bands from the paper's moderate spec:
           entry Z < -0.2, exit Z >= 6.
           ETH: the paper's Z bands are untested for ETH (its Z never reached 6 in
           2016-2026, so the exit would never fire), so ETH uses house percentile bands of
           MVRV vs its own history up to t: entry <= 10th, exit >= 90th percentile.
  regime   replay the paper's state machine over the coin's history: enter on the entry
           band, leave on the exit band.
  zone     deep_value (entry band today) / overheated (exit band) / in_cycle (regime
           on) / out_of_cycle (regime off after an exit).
  filter   alternative.me Crypto Fear & Greed (classes: Extreme Fear <= 25, Extreme
           Greed >= 76):
             deep_value -> long unless Extreme Greed; hold 60 bars; confidence 0.60,
                           0.65 with Extreme Fear;
             in_cycle   -> long only in Extreme Fear (buy the panic inside an up-cycle);
                           hold 20 bars; confidence 0.55;
             otherwise  -> flat (no call).
  stop     close-based 3 x Wilder ATR(20) from the signal close (agents/_quant).
  cadence  at most one call per coin per ISO week (signal_key "<ticker>:<ISO week>"),
           and none while this agent still holds an unsettled record on that coin, so
           60-bar holds do not stack.
Missing, stale (MVRV > 3 days, F&G > 2 days, candles > 7 days) or short (< 4 years of
MVRV) data -> the coin is unavailable, never guessed. Zero LLM tokens.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

from marketmind.gateway import crypto_signals as cs
from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

logger = logging.getLogger("marketmind.playground.onchain_valuation")

AGENT_ID = "onchain_valuation"
MODEL = "mvrv_bands_grobys_2026_fng_contrarian"
COINS: tuple[tuple[str, str], ...] = (("BTC-USD", "btc"), ("ETH-USD", "eth"))
MIN_HISTORY_DAYS = 4 * 365
MAX_MVRV_AGE_DAYS = 3
MAX_FNG_AGE_DAYS = 2
EXTREME_FEAR, EXTREME_GREED = 25, 76
HOLD_VALUE, HOLD_DIP = 60, 20
CONF_VALUE, CONF_VALUE_FEAR, CONF_DIP = 0.60, 0.65, 0.55

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


@dataclass(frozen=True)
class Band:
    metric: str            # mvrv_z | mvrv_percentile
    entry: float           # enter below (z) / at or below (percentile)
    exit: float            # leave at or above
    basis: str


BANDS = {
    "btc": Band("mvrv_z", -0.2, 6.0, "Grobys, Näsman & Sandretto (2026) moderate spec: "
                "enter MVRV Z < -0.2, exit Z >= 6"),
    "eth": Band("mvrv_percentile", 10.0, 90.0, "house bands (paper's Z bands untested for ETH): "
                "enter MVRV <= 10th percentile of own history, exit >= 90th"),
}


def metric_series(points: Sequence[cs.MvrvPoint], band: Band) -> list[float | None]:
    if band.metric == "mvrv_z":
        return cs.expanding_mvrv_z(points)
    pct = cs.expanding_percentiles([p.mvrv for p in points])
    return [v if i + 1 >= cs.Z_MIN_DAYS else None for i, v in enumerate(pct)]


def _entry(v: float, band: Band) -> bool:
    return v < band.entry if band.metric == "mvrv_z" else v <= band.entry


def valuation(points: Sequence[cs.MvrvPoint], band: Band) -> dict:
    """Today's metric, zone and the replayed regime (entry / exit dates)."""
    values = metric_series(points, band)
    on, entered, exited = False, None, None
    for p, v in zip(points, values):
        if v is None:
            continue
        if not on and _entry(v, band):
            on, entered = True, p.date
        elif on and v >= band.exit:
            on, exited = False, p.date
    today = values[-1]
    zone = ("deep_value" if _entry(today, band) else "overheated" if today >= band.exit
            else "in_cycle" if on else "out_of_cycle")
    last = points[-1]
    return {"as_of": last.date, "mvrv": round(last.mvrv, 4),
            "mvrv_percentile": round(cs.expanding_percentiles([p.mvrv for p in points])[-1], 1)
            if band.metric == "mvrv_z" else round(today, 1),
            "mvrv_z": round(today, 3) if band.metric == "mvrv_z" else None,
            "realized_cap_usd": round(last.realized_cap), "band": band.__dict__,
            "regime_on": on, "regime_entered": entered, "regime_last_exit": exited, "zone": zone,
            "history_start": points[0].date, "history_days": len(points)}


def decide(zone: str, fng: int) -> tuple[str | None, int, float, str]:
    """(direction or None, hold bars, confidence, reason)."""
    if zone == "deep_value":
        if fng >= EXTREME_GREED:
            return None, 0, 0.0, "deep value but Extreme Greed (contrarian veto)"
        conf = CONF_VALUE_FEAR if fng <= EXTREME_FEAR else CONF_VALUE
        return "long", HOLD_VALUE, conf, "deep value band"
    if zone == "in_cycle":
        if fng <= EXTREME_FEAR:
            return "long", HOLD_DIP, CONF_DIP, "in-cycle and Extreme Fear (contrarian dip buy)"
        return None, 0, 0.0, f"in-cycle, Fear & Greed {fng} not Extreme Fear: flat"
    return None, 0, 0.0, f"{zone}: flat"


def _age(d: str, today: date) -> int:
    return (today - date.fromisoformat(d)).days


async def _default_prices(tickers: list[str]) -> dict[str, list[Bar] | None]:
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(tickers, years=1)
    return {t: (complete_bars(t, h.daily) if h else None) for t, h in hists.items()}


def _held(store, data_dir) -> set[str]:
    from marketmind.ledger.store import UNSETTLED, LedgerStore, default_ledger_path
    from marketmind.playground.ledger_bridge import source_id
    if store is None:
        store = LedgerStore(Path(data_dir) / "ledger.db" if data_dir else default_ledger_path())
    sid = source_id(AGENT_ID)
    return {e.ticker for e in store.list(status=UNSETTLED, source_type="playground")
            if e.source_id == sid}


async def analyze(context: dict, *, mock: bool = False, now: datetime | None = None,
                  data_dir: str | Path | None = None, store=None, fetch_prices=None,
                  load_mvrv=None, load_fng=None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    week = q.week_key(today)
    iso = today.isoformat()
    load_mvrv = load_mvrv or (lambda a: cs.mvrv_history(a, today=iso, data_dir=data_dir))
    load_fng = load_fng or (lambda: cs.fear_greed_history(today=iso, data_dir=data_dir))
    base = {"directional_calls": [], "as_of_run": iso, "week": week}
    try:
        fng_series = await load_fng()
        fng = fng_series.points[-1]
    except Exception as e:
        return {**base, "no_calls_reason": f"Fear & Greed unavailable ({type(e).__name__}: {e})"}
    if _age(fng.date, today) > MAX_FNG_AGE_DAYS:
        return {**base, "no_calls_reason": f"Fear & Greed stale: last value {fng.date}"}
    fng_fact = {"date": fng.date, "value": fng.value, "label": fng.label, "origin": fng_series.origin}

    signals, missing, wanted = {}, {}, {}
    for ticker, asset in COINS:
        try:
            series = await load_mvrv(asset)
        except Exception as e:
            missing[ticker] = f"MVRV unavailable ({type(e).__name__})"
            continue
        pts = series.points
        if len(pts) < MIN_HISTORY_DAYS:
            missing[ticker] = f"insufficient MVRV history: {len(pts)} < {MIN_HISTORY_DAYS} days"
            continue
        if _age(pts[-1].date, today) > MAX_MVRV_AGE_DAYS:
            missing[ticker] = f"MVRV stale: last value {pts[-1].date}"
            continue
        v = valuation(pts, BANDS[asset])
        direction, hold, conf, why = decide(v["zone"], fng.value)
        signals[ticker] = {**v, "fear_greed": fng_fact, "decision": direction or "flat",
                           "reason": why, "mvrv_origin": series.origin}
        if direction:
            wanted[ticker] = (hold, conf, why)

    calls, skipped = [], {}
    if wanted:
        try:
            held = _held(store, data_dir)
        except Exception as e:
            logger.warning("onchain_valuation: own ledger unreadable (%s); no calls", e)
            return {**base, "signals": signals, "unavailable": missing,
                    "no_calls_reason": f"own ledger unreadable ({type(e).__name__})"}
        prices = await (fetch_prices or _default_prices)(list(wanted))
        for ticker, (hold, conf, why) in wanted.items():
            if ticker in held:
                skipped[ticker] = "still holding an unsettled onchain_valuation record"
                continue
            bars = prices.get(ticker)
            bad = q.unavailable(ticker, bars, q.ATR_PERIOD + 2, today)
            stop = None if bad else q.atr_stop(bars, "long")
            if stop is None:
                missing[ticker] = bad or "ATR20 not computable (no stop)"
                continue
            s = signals[ticker]
            s.update(close=bars[-1].close, price_as_of=bars[-1].date, stop=stop[0],
                     atr20=round(stop[1], 6), hold_bars=hold)
            text, rule = q.falsifier(ticker, "long", stop[0], stop[1], hold)
            metric = (f"MVRV Z {s['mvrv_z']:+.2f}" if s["mvrv_z"] is not None
                      else f"MVRV 分位 {s['mvrv_percentile']:.0f}")
            calls.append({
                "ticker": ticker, "direction": "long", "confidence": conf,
                "hold_bars": hold, "hold_days": hold,
                "thesis": (f"链上估值：{ticker} MVRV {s['mvrv']:.2f}（{s['as_of']}，{metric}），"
                           f"区间 {s['zone']}；恐惧贪婪 {fng.value}（{fng.label}，{fng.date}）→ 做多，"
                           f"持有 {hold} 根（{why}；Grobys 等 2026，仅约 3 个周期，证据偏弱）"),
                "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
                "signal_key": f"{ticker}:{week}", "signal": s,
            })
    out = {**base, "directional_calls": calls, "signals": signals, "unavailable": missing,
           "skipped": skipped,
           "sources": {"mvrv": "Coin Metrics community CapMVRVCur / CapMrktCurUSD",
                       "fear_greed": "alternative.me Crypto Fear & Greed"}}
    if not calls:
        out["no_calls_reason"] = "; ".join(
            [f"{t}: {s['reason']}" for t, s in signals.items() if s["decision"] == "flat"]
            + [f"{t}: {r}" for t, r in {**missing, **skipped}.items()]) or "no coin with usable data"
    return out
