"""Classic machine-learning Playground agent (docs/PLAYGROUND_AGENTS.md §7) - pure code.

A gradient-boosted tree classifier (sklearn HistGradientBoostingClassifier) predicts,
per instrument, the probability that the next 10-bar close-to-close return beats the
ledger's round-trip cost. Tree ensembles on a panel of price-based predictors follow
Gu, Kelly & Xiu (2020); the purged walk-forward training follows Lopez de Prado (2018).
Features: features.py. Training / cache: model.py. Out-of-sample report: backtest.py.

Daily rule: among instruments with a fresh complete bar, long the (at most) MAX_CALLS
highest calibrated probabilities at or above THRESHOLD; hold 10 bars; close-based stop
at 3 x ATR20 (agents/_quant); confidence = calibrated probability clipped to 0.50-0.70;
signal_key = ticker:ISO-week, so each instrument is recorded at most once a week.
Zero LLM tokens.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q
from marketmind.playground.agents.ml_gbm import features as F
from marketmind.playground.agents.ml_gbm import model as M

AGENT_ID = "ml_gbm"
MODEL = "hist_gbm_walk_forward_v1"
UNIVERSE = F.UNIVERSE
THRESHOLD = 0.55
MAX_CALLS = 2
HOLD = F.HORIZON
CONF_MIN, CONF_MAX = 0.5, 0.7
HISTORY_YEARS = 10

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


async def fetch_histories(tickers: Sequence[str]) -> tuple[dict, dict]:
    """(complete daily bars by ticker, source by ticker). Network I/O; not used by tests."""
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(list(tickers), years=HISTORY_YEARS)
    bars = {t: (complete_bars(t, h.daily) if h else None) for t, h in hists.items()}
    return bars, {t: h.source for t, h in hists.items() if h}


def confidence(p: float) -> float:
    return round(min(CONF_MAX, max(CONF_MIN, p)), 4)


def score_latest(panel: F.Panel, bundle: dict, histories: dict, fresh: set[str]) -> dict[str, dict]:
    """Model scores on each fresh instrument's latest complete bar."""
    out = {}
    for k, t in enumerate(panel.tickers):
        if t not in fresh:
            continue
        idx = np.flatnonzero(panel.ticker == k)
        if not len(idx):
            continue
        i = idx[np.argmax(panel.date[idx])]
        if str(panel.date[i]) != histories[t][-1].date:
            continue
        raw, cal = M.predict(bundle, panel.X[i:i + 1])
        out[t] = {"as_of": str(panel.date[i]), "close": histories[t][-1].close,
                  "p_raw": round(float(raw[0]), 4), "p_calibrated": round(float(cal[0]), 4),
                  "x": {f: (None if np.isnan(v) else round(float(v), 4))
                        for f, v in zip(panel.features, panel.X[i])}}
    return out


def build_calls(scores: dict[str, dict], bundle: dict, histories: dict,
                week: str) -> tuple[list[dict], dict]:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1]["p_calibrated"])
    calls, missing = [], {}
    tops = M.top_features(bundle)
    model_facts = {k: bundle.get(k) for k in ("version", "asof", "row_cutoff", "label_cutoff",
                                              "train_first", "train_last", "n_fit", "n_calib",
                                              "base_rate")}
    for rank, (t, s) in enumerate(ranked, 1):
        if len(calls) >= MAX_CALLS or s["p_calibrated"] < THRESHOLD:
            break
        stop = q.atr_stop(histories[t], "long")
        if stop is None:
            missing[t] = "ATR20 not computable (no stop)"
            continue
        text, rule = q.falsifier(t, "long", stop[0], stop[1], HOLD)
        signal = {"as_of": s["as_of"], "close": s["close"], "p_raw": s["p_raw"],
                  "p_calibrated": s["p_calibrated"], "threshold": THRESHOLD, "rank": rank,
                  "stop": stop[0], "atr20": q.r4(stop[1]), "model": model_facts,
                  "top_features": [{"feature": f, "importance": imp, "value": s["x"].get(f)}
                                   for f, imp in tops]}
        calls.append({
            "ticker": t, "direction": "long", "confidence": confidence(s["p_calibrated"]),
            "hold_bars": HOLD, "hold_days": HOLD,
            "thesis": (f"梯度提升树（walk-forward，训练截止 {model_facts['row_cutoff']}）估计 {t} "
                       f"未来 {HOLD} 根 K 线净收益为正的校准概率 {s['p_calibrated']:.1%}"
                       f"（阈值 {THRESHOLD:.0%}，全体第 {rank}）→ 做多"),
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{t}:{week}", "signal": signal,
        })
    return calls, missing


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None, data_dir=None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    fetch = fetch or fetch_histories
    histories, sources = await fetch(list(UNIVERSE) + [F.VIX_TICKER])
    missing: dict[str, str] = {}
    fresh: set[str] = set()
    for t in UNIVERSE:
        why = q.unavailable(t, histories.get(t), F.WARMUP + 1, today)
        if why:
            missing[t] = why
        else:
            fresh.add(t)
    base = {"directional_calls": [], "as_of_run": today.isoformat(), "unavailable": missing}
    if F.MARKET_TICKER not in fresh:
        return {**base, "no_calls_reason": "SPY history unavailable: no trading calendar"}
    panel = F.build_panel(histories)
    bundle, retrained = M.get_model(panel, today, data_dir)
    if bundle is None:
        return {**base, "no_calls_reason": "not enough purged training rows to fit the model"}
    scores = score_latest(panel, bundle, histories, fresh)
    calls, no_stop = build_calls(scores, bundle, histories, q.week_key(today))
    missing.update(no_stop)
    out = {**base, "directional_calls": calls, "retrained": retrained,
           "model": {k: bundle.get(k) for k in ("version", "asof", "week", "row_cutoff",
                                                "label_cutoff", "n_fit", "n_calib", "base_rate")},
           "vix_available": bool(histories.get(F.VIX_TICKER)),
           "scores": {t: s["p_calibrated"] for t, s in scores.items()},
           "sources": {t: sources.get(t) for t in scores}}
    if not calls:
        out["no_calls_reason"] = f"no instrument with calibrated probability >= {THRESHOLD}"
    return out
