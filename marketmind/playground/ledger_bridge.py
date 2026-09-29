"""Playground → unified ledger (SPEC_v3 §7, §8; docs/S8_DESIGN.md "Playground 接回").

Playground agents are promotion candidates: their directional calls go into the
same ledger as shadows (source_type "playground", source_id "playground:<agent>")
and are judged by the same ladder. Unlike long-term shadows they are not forced
to trade every day. Each agent with at least one call that day also gets a
same-domain random benchmark (manifest `domain_universe`), like shadows do.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from marketmind.gateway.price_history import complete_bars
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.playground.ledger_bridge")

DEFAULT_HOLD = 10
MIN_POSITION, MAX_POSITION = 100.0, 1000.0
DIRECTIONS = {"bullish": "long", "long": "long", "buy": "long",
              "bearish": "short", "short": "short", "sell": "short"}


def source_id(agent_id: str) -> str:
    return f"playground:{agent_id}"


def _position(conf: float) -> float:
    """$100 at 0.5 confidence up to $1,000 at 1.0 (same scale as shadows)."""
    return round(MIN_POSITION + (MAX_POSITION - MIN_POSITION) * max(0.0, conf - 0.5) / 0.5, 2)


def parse_call(call: dict, tradable) -> tuple[dict | None, str | None]:
    """(normalised call, reason dropped)."""
    if not isinstance(call, dict):
        return None, "not an object"
    ticker = str(call.get("ticker") or "").strip().upper().lstrip("$")
    direction = DIRECTIONS.get(str(call.get("direction") or "").strip().lower())
    try:
        conf = float(call.get("confidence"))
    except (TypeError, ValueError):
        return None, f"{ticker}: confidence missing"
    if not ticker or not tradable(ticker):
        return None, f"{ticker or '?'}: not a tradable instrument"
    if direction is None:
        return None, f"{ticker}: direction {call.get('direction')!r}"
    if not 0.0 <= conf <= 1.0:
        return None, f"{ticker}: confidence {conf} outside 0-1"
    try:
        hold = int(call.get("hold_days") or DEFAULT_HOLD)
    except (TypeError, ValueError):
        hold = DEFAULT_HOLD
    thesis = str(call.get("thesis") or "")[:600]
    return {"ticker": ticker, "direction": direction, "confidence": conf,
            "hold": max(1, min(hold, 60)), "thesis": thesis,
            "falsifier": str(call.get("falsifier") or "").strip()
            or f"{max(1, min(hold, 60))} 个交易日内走势与判断相反（净收益为负）",
            "model": call.get("mental_model_used")}, None


async def record_run(store: LedgerStore, result, manifests: dict, *, today: str | None = None,
                     tradable=None, histories_fn=None) -> dict:
    """Write each agent's calls for today once; returns {agent_id: [entry ids]} and drops."""
    from marketmind.ledger.recorder import classify_ticker
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if tradable is None:
        from marketmind.markets import is_shadow_tradable as tradable
    if histories_fn is None:
        from marketmind.gateway.price_history import get_price_histories as histories_fn
    done = {e.source_id for e in store.list(source_type="playground")
            if (e.meta or {}).get("run_date") == today}
    out: dict[str, list[str]] = {}
    dropped: list[str] = []
    for decision in getattr(result, "decisions", []):
        sid = source_id(decision.agent_id)
        if sid in done or decision.metadata.get("mock_mode"):
            continue
        calls = []
        for c in decision.directional_calls:
            parsed, why = parse_call(c, tradable)
            if parsed:
                calls.append(parsed)
            else:
                dropped.append(f"{decision.agent_id}: {why}")
        if not calls:
            continue
        manifest = manifests.get(decision.agent_id)
        universe = list(getattr(manifest, "domain_universe", None) or [])
        bench_ticker = random.Random(f"{today}:{sid}").choice(universe) if universe else None
        wanted = sorted({c["ticker"] for c in calls} | ({bench_ticker} if bench_ticker else set()))
        histories = await histories_fn(wanted)
        quotes = {}
        for t in wanted:
            h = histories.get(t)
            # the running session is a partial bar; settlement compares the snapshot
            # with the completed bar of that date (adjustment factor)
            daily = complete_bars(t, h.daily) if h is not None and h.daily else []
            if daily:
                quotes[t] = (daily[-1].close, daily[-1].date, h.source)
        snapshot_id = store.save_snapshot(quotes) if quotes else None
        domain_bench = getattr(manifest, "domain_benchmark", None) or "SPY"
        ids = []
        for c in calls:
            if c["ticker"] not in quotes:
                dropped.append(f"{decision.agent_id}: {c['ticker']} has no price data")
                continue
            layer, asset_type = classify_ticker(c["ticker"])
            ids.append(store.add(LedgerEntry(
                source_type="playground", source_id=sid, ticker=c["ticker"],
                direction=c["direction"], hold_bars=c["hold"], confidence=c["confidence"],
                position_usd=_position(c["confidence"]), falsifier=c["falsifier"],
                thesis=c["thesis"], layer=layer, asset_type=asset_type, entry_rule="next_open",
                domain_benchmark=domain_bench, snapshot_id=snapshot_id,
                meta={"run_date": today, "agent": decision.agent_id, "model": c["model"],
                      "run_id": decision.run_id})))
        if ids and bench_ticker in quotes:
            rng = random.Random(f"{today}:{sid}:dir")
            store.add(LedgerEntry(
                source_type="benchmark", source_id=f"random:{sid}", ticker=bench_ticker,
                direction=rng.choice(["long", "short"]), hold_bars=DEFAULT_HOLD, confidence=0.5,
                position_usd=MIN_POSITION, falsifier="random benchmark (no thesis)",
                thesis="same-domain random pick", entry_rule="next_open",
                domain_benchmark=domain_bench, snapshot_id=snapshot_id,
                meta={"benchmark": "random_same_domain", "run_date": today}))
        out[decision.agent_id] = ids
    return {"recorded": out, "dropped": dropped}
