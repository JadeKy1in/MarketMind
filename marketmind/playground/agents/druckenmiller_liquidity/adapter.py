"""Druckenmiller liquidity agent: code dashboard + rule gate + sparse LLM (docs/PLAYGROUND_AGENTS.md §9).

Once per ISO week (the first run of the week; later runs return the stored result):
  1. code builds the liquidity dashboard from FRED and the trend states of SPY QQQ TLT GLD
     BTC-USD (dashboard.py);
  2. code gates: only assets whose trend agrees with the liquidity impulse are candidates;
     only candidates that were not in the gate 7 days earlier are "fresh";
  3. if there is a fresh candidate, ONE Flash call through the gateway picks at most one of
     them (strict JSON {ticker, action, confidence, hold_days 20-60, thesis}); anything
     that fails the schema -> no call. No fresh candidate -> no LLM call at all.
Stop = 3 x Wilder ATR20 from the last complete close (agents/_quant), ledger
falsifier_rule; confidence = the model's 0.5-1.0 mapped linearly onto 0.50-0.70;
signal_key "<ticker>:<ISO week>".

Information firewall: FRED series, public daily bars and the code-only trend module.
The Playground context (news, market data) is not read at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from marketmind.gateway import llm_trace
from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q
from marketmind.playground.agents.druckenmiller_liquidity import dashboard as D
from marketmind.playground.agents.druckenmiller_liquidity import prompts as P

logger = logging.getLogger("marketmind.playground.druckenmiller_liquidity")

AGENT_ID = "druckenmiller_liquidity"
MODEL = "druckenmiller_liquidity_v1"
LLM_TIER = "flash"
CONF_LO, CONF_HI = 0.5, 0.7
ACTIONS = {"enter_long": "long", "enter_short": "short", "no_trade": None}
DECISION_KEYS = ("ticker", "action", "confidence", "hold_days", "thesis")
LLM_MAX_TOKENS = 500
CALL_TIMEOUT_S = 300
CHARS_PER_TOKEN = 4
INTEGRITY_HEADER_TOKENS = 160
OUT_TOKENS = 150
KEEP_WEEKS = 60

PROMPT_VERSION = P.PROMPT_VERSION
PROMPT_FINGERPRINT = llm_trace.prompt_version(P.fingerprint_source())

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched, no LLM call."}

Llm = Callable[[str, str], Awaitable[str | None]]


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


# ══════════════════════════════════════════════════════════════════════════
# Prompt
# ══════════════════════════════════════════════════════════════════════════

def _n(x, fmt: str = "{:.4g}") -> str:
    return "DATA_UNAVAILABLE" if x is None else fmt.format(x)


def _chg(c: dict, label: str, unit: str) -> str:
    if c.get("value") is None:
        return f"{label}: DATA_UNAVAILABLE ({c.get('reason')})"
    ch = c.get("change")
    ch_s = "DATA_UNAVAILABLE" if ch is None else (f"{ch:+.2%}" if unit == "pct" else f"{ch:+.2f} pp")
    return f"{label}: {c['value']:.4g} (as of {c['as_of']}), change since {c.get('from', '?')}: {ch_s}"


def render_dashboard(ev: dict) -> str:
    d, liq = ev["dashboard"], ev["dashboard"]["liquidity"]
    if liq["impulse"] == D.UNAVAILABLE:
        liq_lines = [f"net liquidity: DATA_UNAVAILABLE ({liq.get('reason')})"]
    else:
        liq_lines = [
            f"net liquidity (Fed assets - TGA - reverse repo), week of {liq['as_of']}: "
            f"${liq['net_bn']:,.1f}B (assets ${liq['walcl_bn']:,.1f}B, TGA ${liq['tga_bn']:,.1f}B, "
            f"RRP ${liq['rrp_bn']:,.1f}B)",
            f"  4-week change: {liq['d4_bn']:+,.1f}B ({liq['d4_pct']:+.2%}); 13-week change: "
            f"{liq['d13_bn']:+,.1f}B ({liq['d13_pct']:+.2%}); impulse by rule: {liq['impulse'].upper()}",
        ]
    lines = [f"DASHBOARD (computed by code) as of {d['as_of']}", *liq_lines,
             _chg(d["dgs2"]["4w"], "2-year Treasury yield % (4 weeks)", "pp"),
             _chg(d["dgs2"]["13w"], "2-year Treasury yield % (13 weeks)", "pp"),
             _chg(d["dgs10"]["4w"], "10-year Treasury yield % (4 weeks)", "pp"),
             _chg(d["dgs10"]["13w"], "10-year Treasury yield % (13 weeks)", "pp"),
             _chg(d["usd_broad"], "broad trade-weighted dollar index (13 weeks)", "pct"),
             _chg(d["hy_oas"], "high-yield credit spread % (13 weeks)", "pp"),
             "", "Trend states (code: 12-month return > T-bill, close > SMA200, 55-day breakout, "
             "3 x ATR20 chandelier exit):"]
    for t in D.ASSETS:
        tr = ev["trends"].get(t) or {}
        if tr.get("state") == D.UNAVAILABLE or not tr:
            lines.append(f"- {t}: DATA_UNAVAILABLE ({tr.get('reason')})")
            continue
        lines.append(f"- {t}: {tr['state']}, close {_n(tr['close'])}, SMA200 {_n(tr['sma200'])}, "
                     f"12-month return {_n(tr['ret_12m'], '{:+.2%}')} vs T-bill {_n(tr['hurdle'], '{:.2%}')}"
                     + (f", in trend since {tr['entry_signal_date']}" if tr.get("entry_signal_date") else ""))
    lines += ["", "CANDIDATES that passed the rule gate this week (new since last week):"]
    lines += [f"- {c.ticker}: {c.direction} ({c.why})" for c in ev["fresh"]]
    others = [c for c in ev["candidates"] if c not in ev["fresh"]]
    if others:
        lines.append("Already in the gate last week (not offered again): "
                     + ", ".join(f"{c.ticker} {c.direction}" for c in others))
    lines.append("Standing aside by rule: " + "; ".join(f"{t}: {w}" for t, w in ev["stand_aside"].items()))
    return "\n".join(lines) + "\n\nReturn the JSON object now."


# ══════════════════════════════════════════════════════════════════════════
# Decision (strict schema)
# ══════════════════════════════════════════════════════════════════════════

def parse_decision(raw: str | None, cands: Sequence[D.Candidate]) -> tuple[dict | None, str | None]:
    """(decision, None) or (None, why invalid). A bare JSON object (one ``` fence allowed);
    no extraction from prose, no repair."""
    text = (raw or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
    except ValueError:
        return None, "reply is not valid JSON"
    if not isinstance(obj, dict):
        return None, "reply is not a JSON object"
    absent = [k for k in DECISION_KEYS if k not in obj]
    if absent:
        return None, f"reply lacks {', '.join(absent)}"
    action = obj["action"]
    if action not in ACTIONS:
        return None, f"action {action!r}"
    ticker = str(obj["ticker"]).strip().upper()
    if ACTIONS[action] is not None:
        match = [c for c in cands if c.ticker == ticker]
        if not match:
            return None, f"ticker {obj['ticker']!r} is not a gated candidate"
        if match[0].direction != ACTIONS[action]:
            return None, f"{action} does not match the gated direction {match[0].direction} of {ticker}"
    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
        return None, f"confidence {conf!r} not a number in 0-1"
    hold = obj["hold_days"]
    if isinstance(hold, float) and hold.is_integer():
        hold = int(hold)
    if isinstance(hold, bool) or not isinstance(hold, int) or not P.HOLD_MIN <= hold <= P.HOLD_MAX:
        return None, f"hold_days {obj['hold_days']!r} not an integer in {P.HOLD_MIN}-{P.HOLD_MAX}"
    thesis = obj["thesis"]
    if not isinstance(thesis, str) or not thesis.strip():
        return None, "thesis empty"
    return {"ticker": ticker, "action": action, "confidence": float(conf), "hold_days": hold,
            "thesis": " ".join(thesis.split())[:300],
            "ignored_keys": sorted(set(obj) - set(DECISION_KEYS))}, None


def ledger_confidence(model_conf: float) -> float:
    c = min(1.0, max(0.5, model_conf))
    return round(CONF_LO + (CONF_HI - CONF_LO) * (c - 0.5) / 0.5, 4)


def build_call(decision: dict, ev: dict, bars: Sequence[Bar] | None, week: str,
               llm_label: str | None) -> tuple[dict | None, str]:
    direction = ACTIONS[decision["action"]]
    if direction is None:
        return None, "model: no_trade"
    if decision["confidence"] < 0.5:
        return None, f"model chose {decision['action']} at confidence {decision['confidence']} < 0.5"
    t = decision["ticker"]
    stop = q.atr_stop(bars or [], direction)
    if stop is None:
        return None, f"{t}: ATR20 stop not computable"
    hold = decision["hold_days"]
    text, rule = q.falsifier(t, direction, stop[0], stop[1], hold)
    liq = ev["dashboard"]["liquidity"]
    signal = {"as_of": bars[-1].date, "close": bars[-1].close, "stop_level": stop[0],
              "stop_basis": f"close ∓ {q.STOP_ATR_MULT:g}×ATR{q.ATR_PERIOD}", "atr20": q.r4(stop[1]),
              "dashboard": ev["dashboard"], "trend": ev["trends"].get(t),
              "gate": [f"{c.ticker}:{c.direction}" for c in ev["candidates"]],
              "fresh": [f"{c.ticker}:{c.direction}" for c in ev["fresh"]],
              "decision": {k: decision[k] for k in ("action", "confidence", "hold_days", "thesis")},
              "confidence_map": f"{CONF_LO}+{CONF_HI - CONF_LO:.1f}*(model-0.5)/0.5",
              "llm": llm_label, "llm_tier": LLM_TIER, "prompt_version": PROMPT_VERSION,
              "prompt_fingerprint": PROMPT_FINGERPRINT}
    side = "做多" if direction == "long" else "做空"
    flip = "转为下降" if direction == "long" else "转为上升"
    return {"ticker": t, "direction": direction, "confidence": ledger_confidence(decision["confidence"]),
            "hold_bars": hold, "hold_days": hold,
            "thesis": (f"流动性框架（{side}）：净流动性 13 周 {liq.get('d13_bn', 0):+,.0f}B、"
                       f"趋势 {ev['trends'].get(t, {}).get('state')}；{decision['thesis']}")[:600],
            "falsifier": f"{text}；或净流动性 13 周变化{flip}（文字条件，不自动结算）",
            "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{t}:{week}", "signal": signal}, "call"


# ══════════════════════════════════════════════════════════════════════════
# Weekly state (LLM budget: at most one call per ISO week)
# ══════════════════════════════════════════════════════════════════════════

def _state_path(root: Path) -> Path:
    return root / "playground" / AGENT_ID / "weeks.json"


def load_weeks(root: Path) -> dict:
    try:
        doc = json.loads(_state_path(root).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_week(root: Path, week: str, record: dict) -> None:
    weeks = load_weeks(root)
    weeks[week] = record
    keep = dict(sorted(weeks.items())[-KEEP_WEEKS:])
    path = _state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("druckenmiller_liquidity: could not save weekly state (%s)", exc)


# ══════════════════════════════════════════════════════════════════════════
# Network defaults (tests inject their own)
# ══════════════════════════════════════════════════════════════════════════

async def _fetch_fred(today: date) -> dict:
    return await D.fetch_fred(D.SERIES, today)


async def _fetch_bars(tickers: list[str]) -> tuple[dict, dict, float, str]:
    from marketmind.trend.state import fetch_inputs
    return await fetch_inputs(tickers)


async def _gateway_llm(system: str, user: str) -> str | None:
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_with_integrity
    token = usage_tracker.set_stage(f"playground:{AGENT_ID}")
    try:
        result = await asyncio.wait_for(chat_with_integrity(
            model=LLM_TIER, system_prompt=system, user_prompt=user,
            caller_agent=f"{AGENT_ID}:decision", temperature=0.1, max_tokens=LLM_MAX_TOKENS),
            timeout=CALL_TIMEOUT_S)
    except Exception as exc:                    # noqa: BLE001 - no reply -> no call this week
        logger.warning("druckenmiller_liquidity call failed: %s", exc)
        return None
    finally:
        usage_tracker.reset_stage(token)
    if not isinstance(result, dict) or result.get("error"):
        logger.warning("druckenmiller_liquidity call error: %s",
                       result.get("error") if isinstance(result, dict) else result)
        return None
    return result.get("content") or None


def token_estimate() -> int:
    """One weekly call with a full dashboard, all five assets gated fresh."""
    sample = {"dashboard": {"as_of": "2026-09-28", "liquidity": {
        "impulse": "rising", "as_of": "2026-09-23", "net_bn": 5770.6, "walcl_bn": 6747.7,
        "tga_bn": 977.1, "rrp_bn": 0.0, "d4_bn": 12.3, "d13_bn": 45.6, "d4_pct": 0.0021,
        "d13_pct": 0.0079}},
        "trends": {t: {"state": "TREND", "close": 123456.78, "sma200": 101234.56, "ret_12m": 0.4321,
                       "hurdle": 0.0412, "entry_signal_date": "2026-09-01"} for t in D.ASSETS},
        "fresh": [D.Candidate(t, "long", "net liquidity rising (13w and 4w) and trend state TREND")
                  for t in D.ASSETS], "candidates": [], "stand_aside": {}}
    c = {"value": 4.123, "as_of": "2026-09-26", "change": 0.1234, "from": "2026-06-26"}
    sample["dashboard"].update({"dgs2": {"4w": c, "13w": c}, "dgs10": {"4w": c, "13w": c},
                                "usd_broad": c, "hy_oas": c})
    sample["candidates"] = sample["fresh"]
    user = render_dashboard(sample)
    return (INTEGRITY_HEADER_TOKENS + math.ceil(len(P.DECISION_SYSTEM) / CHARS_PER_TOKEN)
            + math.ceil(len(user) / CHARS_PER_TOKEN) + OUT_TOKENS)


# ══════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════

def _public(ev: dict) -> dict:
    return {"dashboard": ev["dashboard"], "trends": ev["trends"],
            "gate": [f"{c.ticker}:{c.direction}" for c in ev["candidates"]],
            "gate_prev": [f"{c.ticker}:{c.direction}" for c in ev["candidates_prev"]],
            "fresh": [f"{c.ticker}:{c.direction}" for c in ev["fresh"]],
            "stand_aside": ev["stand_aside"], "prev_as_of": ev["prev_as_of"]}


async def analyze(context: dict, *, mock: bool = False, fetch_fred=None, fetch_bars=None,
                  llm: Llm | None = None, now: datetime | None = None,
                  data_root: Path | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    week = q.week_key(today)
    root = Path(data_root) if data_root is not None else data_dir()
    stored = load_weeks(root).get(week)
    if stored is not None:
        out = dict(stored.get("output") or {})
        out["directional_calls"] = list(out.get("directional_calls") or [])
        out["llm_calls"] = 0
        out["no_calls_reason"] = out.get("no_calls_reason") or f"{week} already evaluated"
        out["note"] = f"{week} already evaluated on {stored.get('evaluated_on')}; stored result returned"
        return out

    fred = await (fetch_fred or _fetch_fred)(today)
    bars, sources, hurdle, hurdle_source = await (fetch_bars or _fetch_bars)(list(D.ASSETS))
    ev = D.evaluate(fred, bars, hurdle, today)
    out = {"directional_calls": [], "as_of_run": today.isoformat(), "week": week,
           **_public(ev), "hurdle_source": hurdle_source, "llm_calls": 0,
           "prompt_version": PROMPT_VERSION, "prompt_fingerprint": PROMPT_FINGERPRINT,
           "token_estimate_per_call": token_estimate()}
    usable = ev["dashboard"]["liquidity"]["impulse"] != D.UNAVAILABLE and \
        any(tr["state"] != D.UNAVAILABLE for tr in ev["trends"].values())
    if not ev["fresh"]:
        out["no_calls_reason"] = ("no fresh gated candidate: " + "; ".join(
            f"{t}: {w}" for t, w in ev["stand_aside"].items())
            + ("" if not ev["candidates"] else
               f"; still gated from last week: {', '.join(out['gate'])}"))
        if usable:
            save_week(root, week, {"evaluated_on": today.isoformat(), "llm_called": False, "output": out})
        return out

    user = render_dashboard(ev)
    with llm_trace.trace() as models:
        raw = await (llm or _gateway_llm)(P.DECISION_SYSTEM, user)
    label = llm_trace.label(models)
    out["llm_calls"] = 1
    decision, why = parse_decision(raw, ev["fresh"])
    out.update({"llm": label, "raw_reply": (raw or "")[:2000], "decision": decision,
                "prompt": user})
    if decision is None:
        out["no_calls_reason"] = why if raw else "no reply from the model"
    else:
        call, outcome = build_call(decision, ev, bars.get(decision["ticker"]), week, label)
        if call:
            out["directional_calls"] = [call]
        else:
            out["no_calls_reason"] = outcome
    save_week(root, week, {"evaluated_on": today.isoformat(), "llm_called": True, "output": out})
    return out
