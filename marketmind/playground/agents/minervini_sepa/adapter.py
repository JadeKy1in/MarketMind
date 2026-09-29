"""Minervini SEPA: Trend Template + VCP pivot breakouts, code first (docs/PLAYGROUND_AGENTS.md §8).

Every number and every call is code (rules.py, SPEC L3):
  universe   the bounded seed list in universe.py (~150 US large caps + 11 sector SPDRs),
             minus symbols no longer listed, minus instruments whose median 50-day dollar
             volume is under $50M;
  signal     a VCP pivot breakout on one of the last FRESH_BARS complete bars, on a bar
             where the 8-point Trend Template holds (RS rank >= 70 within the universe),
             with the last close still above the pivot;
  call       long, held HOLD bars; stop = the last contraction low capped at 8 % under
             the breakout close (ledger falsifier_rule close_below); confidence
             0.50-0.70 from the RS rank; at most MAX_CALLS a day (highest RS first);
             signal_key "<ticker>:<pivot date>" records each pivot once.
The optional LLM call (at most one per UTC day, only when a call exists and headlines
mention it) writes a one-line catalyst note from delimited, defanged headlines. The note
is stored in the signal facts; no call, number or size depends on it.

Information firewall: reads public daily bars, the public listing directory and news
titles / source names from the Playground context; nothing from the main pipeline,
shadows, the ledger or other Playground agents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from marketmind.gateway import llm_trace
from marketmind.gateway.price_history import Bar
from marketmind.pipeline.defang import defang_text
from marketmind.playground.agents import _quant as q
from marketmind.playground.agents.minervini_sepa import prompts as P
from marketmind.playground.agents.minervini_sepa import rules as R
from marketmind.playground.agents.minervini_sepa.universe import MIN_DOLLAR_VOLUME, NAMES, SEED

logger = logging.getLogger("marketmind.playground.minervini_sepa")

AGENT_ID = "minervini_sepa"
MODEL = "minervini_trend_template_vcp_v1"
LLM_TIER = "flash"
HOLD = 30                         # bars; Minervini holds leaders for weeks, the brief asks 20-40
FRESH_BARS = 3
MAX_CALLS = 3
CONF_LO, CONF_HI = 0.5, 0.7
DOLLAR_VOL_BARS = 50
MAX_HEADLINES = 3
HEADLINE_CHARS = 200
LLM_MAX_TOKENS = 400
CALL_TIMEOUT_S = 300
CHARS_PER_TOKEN = 4
INTEGRITY_HEADER_TOKENS = 160

PROMPT_VERSION = P.PROMPT_VERSION
PROMPT_FINGERPRINT = llm_trace.prompt_version(P.fingerprint_source())

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched, no LLM call."}

Llm = Callable[[str, str], Awaitable[str | None]]          # (system, user) -> reply


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


# ══════════════════════════════════════════════════════════════════════════
# Scan (code only)
# ══════════════════════════════════════════════════════════════════════════

def dollar_volume(bars: Sequence[Bar], n: int = DOLLAR_VOL_BARS) -> float | None:
    """Median close x volume of the last n bars."""
    window = bars[-n:]
    if len(window) < n:
        return None
    return statistics.median(b.close * b.volume for b in window)


def confidence(rs_rank: float) -> float:
    """RS rank 70 -> 0.50 ... 99 -> 0.70, linear."""
    x = (min(99.0, max(float(R.RS_MIN), rs_rank)) - R.RS_MIN) / (99 - R.RS_MIN)
    return round(CONF_LO + (CONF_HI - CONF_LO) * x, 4)


def scan(bars_by: dict[str, Sequence[Bar] | None], today: date) -> dict:
    """Liquidity filter, RS ranks, Trend Template and VCP breakouts over the universe."""
    need = R.MIN_BARS + FRESH_BARS
    unavailable, illiquid, liquid = {}, {}, {}
    for t, bars in bars_by.items():
        why = q.unavailable(t, bars, need, today)
        if why:
            unavailable[t] = why
            continue
        dv = dollar_volume(bars)
        if dv is None or dv < MIN_DOLLAR_VOLUME:
            illiquid[t] = dv
            continue
        liquid[t] = (bars, dv)
    # RS ranks on each of the last FRESH_BARS bars (k bars back), inside the liquid set
    ranks = [R.rs_ranks({t: R.rs_score(b, len(b) - 1 - k) for t, (b, _) in liquid.items()})
             for k in range(FRESH_BARS)]
    template_pass, candidates, near = [], [], {}
    for t, (bars, dv) in sorted(liquid.items()):
        n = len(bars)
        today_tmpl = R.template(bars, ranks[0].get(t))
        if today_tmpl["passed"]:
            template_pass.append(t)
        for k in range(FRESH_BARS):                 # latest breakout first
            i = n - 1 - k
            vcp = R.detect_vcp(bars, i)
            if not vcp.ok:
                if k == 0 and today_tmpl["passed"]:
                    near[t] = vcp.reason
                continue
            tmpl = today_tmpl if k == 0 else R.template(bars, ranks[k].get(t), i)
            if not tmpl["passed"]:
                break
            if bars[-1].close <= vcp.pivot:
                near[t] = f"breakout {bars[i].date} failed: last close back under the pivot"
                break
            candidates.append({"ticker": t, "i": i, "vcp": vcp, "template": tmpl,
                               "rs_rank": ranks[k].get(t), "dollar_volume": dv,
                               "vol_ratio": bars[i].volume / vcp.vol_avg50})
            break
    candidates.sort(key=lambda c: (-(c["rs_rank"] or 0), -c["vol_ratio"], c["ticker"]))
    return {"unavailable": unavailable, "illiquid": illiquid, "liquid": sorted(liquid),
            "template_pass": template_pass, "candidates": candidates, "near_misses": near,
            "rs_rank_today": ranks[0]}


def build_call(c: dict, bars: Sequence[Bar]) -> dict:
    t, i, vcp, tmpl = c["ticker"], c["i"], c["vcp"], c["template"]
    b = bars[i]
    stop, basis = R.stop_level(b.close, vcp.contractions[-1].low)
    text, rule = q.falsifier(t, "long", stop, 0.0, HOLD, basis=basis)
    vol_ratio = round(b.volume / vcp.vol_avg50, 3)
    depths = " → ".join(f"{x.depth:.1%}" for x in vcp.contractions)
    signal = {"as_of": bars[-1].date, "close": bars[-1].close, "breakout_date": b.date,
              "breakout_close": b.close, "breakout_volume_ratio": vol_ratio,
              "rs_rank": c["rs_rank"], "rs_universe": "scan universe (universe.py)",
              "dollar_volume_median50": round(c["dollar_volume"], 0),
              "template": {k: v for k, v in tmpl.items() if k != "passed"},
              **vcp.facts(bars), "stop_level": stop, "stop_basis": basis,
              "hold_bars": HOLD, "catalyst_note": None}
    return {
        "ticker": t, "direction": "long", "confidence": confidence(c["rs_rank"]),
        "hold_bars": HOLD, "hold_days": HOLD,
        "thesis": (f"Minervini 趋势模板 8 项全部满足（RS 排名 {c['rs_rank']:.0f}），VCP {len(vcp.contractions)} 次收缩"
                   f"（{depths}），{b.date} 收盘 {b.close:.4g} 放量 {vol_ratio:.2f}× 突破枢轴 {vcp.pivot:.4g}")[:600],
        "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
        "signal_key": f"{t}:{signal['pivot_date']}", "signal": signal,
    }


# ══════════════════════════════════════════════════════════════════════════
# Optional catalyst note (one LLM call, untrusted headlines)
# ══════════════════════════════════════════════════════════════════════════

def clean(text: str, limit: int) -> str:
    text = re.sub(r"[<>]{3,}", " ", str(text or ""))
    return defang_text(" ".join(text.split()))[:limit]


def _pattern(ticker: str) -> re.Pattern | None:
    parts = [re.escape(NAMES[ticker])] if ticker in NAMES else []
    if len(ticker) >= 2 and ticker.isalpha():
        parts.append(rf"(?-i:\b{re.escape(ticker)}\b)")         # symbols match case-sensitively
    return re.compile(r"\b(?:" + "|".join(parts) + r")", re.IGNORECASE) if parts else None


def headlines(ticker: str, news: Sequence) -> list[str]:
    """Up to MAX_HEADLINES distinct titles naming the company or symbol (title and source only)."""
    rx = _pattern(ticker)
    out, seen = [], set()
    if rx is None:
        return out
    for item in news or []:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())
        if not title or not rx.search(title):
            continue
        text = clean(title, HEADLINE_CHARS)
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        src = clean(str(item.get("source_name") or item.get("source") or "unknown"), 40)
        out.append(f"- [{src}] {text}")
        if len(out) >= MAX_HEADLINES:
            break
    return out


def catalyst_user(heads: dict[str, list[str]]) -> str:
    blocks = []
    for t, hs in heads.items():
        blocks.append(f"{t} ({NAMES.get(t, t)}):\n{P.HEADLINES_OPEN}\n" + "\n".join(hs or ["(none)"])
                      + f"\n{P.HEADLINES_CLOSE}")
    return "\n\n".join(blocks) + f"\n\nReturn the JSON object for: {', '.join(heads)}."


def parse_notes(raw: str | None, tickers: Sequence[str]) -> tuple[dict[str, str], str | None]:
    """({ticker: note}, None) or ({}, why invalid). A bare JSON object (one ``` fence allowed)."""
    text = (raw or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
    except ValueError:
        return {}, "catalyst reply is not valid JSON"
    notes = obj.get("notes") if isinstance(obj, dict) else None
    if not isinstance(notes, dict):
        return {}, "catalyst reply has no 'notes' object"
    out = {}
    for t in tickers:
        v = notes.get(t)
        if isinstance(v, str) and v.strip():
            out[t] = clean(v, P.NOTE_CHARS)
    return out, None if out else "catalyst reply has no usable note"


def _llm_state(root: Path) -> Path:
    return root / "playground" / AGENT_ID / "llm_days.json"


def llm_used_today(root: Path, today: date) -> bool:
    try:
        return json.loads(_llm_state(root).read_text(encoding="utf-8")).get("last") == today.isoformat()
    except (OSError, ValueError, AttributeError):
        return False


def mark_llm_used(root: Path, today: date) -> None:
    path = _llm_state(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"last": today.isoformat()}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("minervini_sepa: could not record the LLM day (%s)", exc)


async def _gateway_llm(system: str, user: str) -> str | None:
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_with_integrity
    token = usage_tracker.set_stage(f"playground:{AGENT_ID}")
    try:
        result = await asyncio.wait_for(chat_with_integrity(
            model=LLM_TIER, system_prompt=system, user_prompt=user,
            caller_agent=f"{AGENT_ID}:catalyst", temperature=0.2, max_tokens=LLM_MAX_TOKENS),
            timeout=CALL_TIMEOUT_S)
    except Exception as exc:                  # noqa: BLE001 - the note is optional
        logger.warning("minervini_sepa catalyst call failed: %s", exc)
        return None
    finally:
        usage_tracker.reset_stage(token)
    if not isinstance(result, dict) or result.get("error"):
        logger.warning("minervini_sepa catalyst call error: %s",
                       result.get("error") if isinstance(result, dict) else result)
        return None
    return result.get("content") or None


def token_estimate() -> int:
    """One catalyst call with MAX_CALLS tickers x MAX_HEADLINES maximum-length headlines."""
    heads = {t: [f"- [{'s' * 20}] {'h' * HEADLINE_CHARS}"] * MAX_HEADLINES
             for t in ("NVDA", "AVGO", "LLY")[:MAX_CALLS]}
    out_tokens = math.ceil((P.NOTE_CHARS + 20) * MAX_CALLS / CHARS_PER_TOKEN) + 20
    return (INTEGRITY_HEADER_TOKENS + math.ceil(len(P.CATALYST_SYSTEM) / CHARS_PER_TOKEN)
            + math.ceil(len(catalyst_user(heads)) / CHARS_PER_TOKEN) + out_tokens)


async def catalyst_notes(calls: list[dict], news: Sequence, llm: Llm, root: Path,
                         today: date) -> dict:
    """Attach catalyst notes to `calls` in place; returns what happened (for the output)."""
    heads = {c["ticker"]: headlines(c["ticker"], news) for c in calls}
    if not any(heads.values()):
        return {"called": False, "reason": "no headline mentions today's calls"}
    if llm_used_today(root, today):
        return {"called": False, "reason": "catalyst call already made today"}
    user = catalyst_user(heads)
    with llm_trace.trace() as models:
        raw = await llm(P.CATALYST_SYSTEM, user)
    mark_llm_used(root, today)
    label = llm_trace.label(models)
    notes, why = parse_notes(raw, list(heads))
    for c in calls:
        note = notes.get(c["ticker"])
        if note:
            c["signal"].update({"catalyst_note": note, "catalyst_note_source": "LLM, headlines only",
                                "llm": label, "llm_tier": LLM_TIER, "prompt_version": PROMPT_VERSION,
                                "prompt_fingerprint": PROMPT_FINGERPRINT})
    return {"called": True, "llm": label, "notes": notes, "invalid": why,
            "raw": (raw or "")[:2000], "headlines": heads}


# ══════════════════════════════════════════════════════════════════════════
# Data (network; tests inject their own)
# ══════════════════════════════════════════════════════════════════════════

async def _listed(seed: Sequence[str], root: Path) -> tuple[list[str], str]:
    """Seed symbols still in the NASDAQ Trader directory (universe.equities); the seed as
    is when the directory is unavailable."""
    from marketmind.universe.equities import load_equity_universe
    try:
        uni = await asyncio.to_thread(load_equity_universe, root / "universe")
    except Exception as exc:                  # noqa: BLE001 - degrade to the seed list
        logger.warning("minervini_sepa: listing directory failed (%s)", exc)
        uni = None
    if uni is None:
        return list(seed), "listing directory unavailable: seed list used unchecked"
    kept = [t for t in seed if t in uni]
    note = f"listing directory {uni.fetched_at.date()}{' (stale)' if uni.stale else ''}"
    dropped = sorted(set(seed) - set(kept))
    return kept, note + (f"; not listed: {', '.join(dropped)}" if dropped else "")


async def _fetch_bars(tickers: list[str]) -> tuple[dict, dict]:
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(list(tickers), years=2)
    bars = {t: (complete_bars(t, h.daily) if h is not None and h.daily else None)
            for t, h in hists.items()}
    return bars, {t: h.source for t, h in hists.items() if h is not None}


# ══════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════

async def analyze(context: dict, *, mock: bool = False, fetch=None, llm: Llm | None = None,
                  now: datetime | None = None, data_root: Path | None = None,
                  listed=None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    root = Path(data_root) if data_root is not None else data_dir()
    tickers, listing_note = await (listed or _listed)(SEED, root)
    bars_by, sources = await (fetch or _fetch_bars)(tickers)
    s = scan(bars_by, today)
    calls = [build_call(c, bars_by[c["ticker"]]) for c in s["candidates"][:MAX_CALLS]]
    news = context.get("news") if isinstance(context, dict) else None
    catalyst = {"called": False, "reason": "no call today"}
    if calls:
        catalyst = await catalyst_notes(calls, news or [], llm or _gateway_llm, root, today)
    out = {"directional_calls": calls, "as_of_run": today.isoformat(),
           "universe": {"seed": len(SEED), "scanned": len(tickers), "listing": listing_note,
                        "liquid": len(s["liquid"]), "min_dollar_volume": MIN_DOLLAR_VOLUME},
           "template_pass": s["template_pass"],
           "breakouts": [c["ticker"] for c in s["candidates"]],
           "near_misses": s["near_misses"], "unavailable": s["unavailable"],
           "illiquid": {t: (None if v is None else round(v)) for t, v in s["illiquid"].items()},
           "catalyst": catalyst, "llm_calls": int(bool(catalyst.get("called"))),
           "prompt_version": PROMPT_VERSION, "prompt_fingerprint": PROMPT_FINGERPRINT,
           "sources": sorted(set(sources.values()))}
    if not calls:
        out["no_calls_reason"] = (f"no VCP pivot breakout on a Trend Template stock in the last "
                                  f"{FRESH_BARS} bars ({len(s['template_pass'])} of {len(s['liquid'])} "
                                  "liquid instruments pass the template today)")
    return out
