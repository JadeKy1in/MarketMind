"""memory_desk: an LLM Playground agent with layered memory and code-computed lessons.

Owner decision 2026-09-29 (docs/PLAYGROUND_AGENTS.md §5). Each run:
  1. code builds a fact sheet for a fixed six-instrument universe from complete daily
     bars (returns, MA50/MA200 position, ATR20, regime tags) and keeps up to 8 public
     headlines; the sheet is cached per day under <data_dir>/playground/memory_desk/facts
     so the control twin sees exactly the same facts;
  2. (memory twin only) memory.py rebuilds the working / episodic tiers from the desk's
     OWN ledger records, updates lessons by code, lets the LLM word newly activated
     lessons, retrieves at most 5 active lessons matching today's regime and passes
     them as a delimited section;
  3. one LLM call returns 1-3 calls; code validates them, caps confidence to 0.50-0.70,
     sets the stop (3 x ATR20, as agents/_quant) and the hold (5 bars).
The control twin (agents/memory_desk_control) runs step 1 and 3 with the same system
prompt and no memory section. Information firewall: only public prices / headlines
and the desk's own ledger records; never main-pipeline or shadow outputs.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from marketmind.gateway import llm_trace
from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q
from marketmind.playground.agents.memory_desk import memory as M
from marketmind.playground.agents.memory_desk import prompts as P

logger = logging.getLogger("marketmind.playground.memory_desk")

AGENT_ID = "memory_desk"
CONTROL_ID = "memory_desk_control"
UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD")
HOLD_BARS = 5
MAX_CALLS = 3
CONF_MIN, CONF_MAX = 0.50, 0.70
MIN_BARS = 201                           # MA200 plus the last close
MAX_HEADLINES = 8
NEWS_TERMS = ("s&p", "nasdaq", "stock", "equit", "fed ", "federal reserve", "treasur",
              "yield", "bond", "gold", "bitcoin", "ether", "crypto", "inflation", "rate",
              "dollar", "recession", "tariff")

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched, no LLM."}


# ── paths ───────────────────────────────────────────────────────────────────

def desk_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data")) / "playground" / AGENT_ID


def memory_path(data_dir: str | Path | None = None) -> Path:
    return desk_dir(data_dir) / "memory.json"


# ── fact sheet (code) ───────────────────────────────────────────────────────

def ticker_facts(ticker: str, bars: Sequence[Bar] | None, today: date) -> tuple[dict | None, str | None]:
    """Code-computed facts of one instrument, or (None, reason unavailable)."""
    why = q.unavailable(ticker, bars, MIN_BARS, today)
    if why:
        return None, why
    closes = [b.close for b in bars]
    c = closes[-1]
    ma50, ma200 = sum(closes[-50:]) / 50, sum(closes[-200:]) / 200
    # same regime definition as the settlement review (ledger/settlement.compute_review)
    regime = {"ret_20d": q.r4(c / closes[-21] - 1) if closes[-21] > 0 else None,
              "above_ma50": c > ma50, "above_ma200": c > ma200}
    long_stop, short_stop = q.atr_stop(bars, "long"), q.atr_stop(bars, "short")
    atr = (long_stop or short_stop or (None, None))[1]
    return {"as_of": bars[-1].date, "close": c,
            "ret_5d": q.r4(q.trailing(bars, 5)), "ret_20d": regime["ret_20d"],
            "ret_60d": q.r4(q.trailing(bars, 60)),
            "vs_ma50": q.r4(c / ma50 - 1), "vs_ma200": q.r4(c / ma200 - 1),
            "atr20": atr, "atr20_pct": q.r4(atr / c) if atr else None,
            "stop_long": long_stop[0] if long_stop else None,
            "stop_short": short_stop[0] if short_stop else None,
            "regime": regime, "tags": M.regime_tags(regime)}, None


def headlines(context: dict) -> list[str]:
    out = []
    for item in context.get("news") or []:
        title = str(item.get("title", "") if isinstance(item, dict) else item).strip()
        if title and any(t in title.lower() for t in NEWS_TERMS) and title[:140] not in out:
            out.append(title[:140])
        if len(out) >= MAX_HEADLINES:
            break
    return out


async def _fetch(tickers: list[str]) -> dict[str, list[Bar] | None]:
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(tickers, years=2)
    return {t: (complete_bars(t, h.daily) if h and h.daily else None) for t, h in hists.items()}


async def load_or_build_facts(root: Path, today: date, context: dict, fetch=None) -> dict:
    """Today's fact sheet, built once and shared by both twins (facts/<date>.json)."""
    path = root / "facts" / f"{today.isoformat()}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    histories = await (fetch or _fetch)(list(UNIVERSE))
    rows, missing = {}, {}
    for t in UNIVERSE:
        row, why = ticker_facts(t, histories.get(t), today)
        if row:
            rows[t] = row
        else:
            missing[t] = why
    facts = {"date": today.isoformat(), "tickers": rows, "unavailable": missing,
             "headlines": headlines(context)}
    if rows:
        M.save(path, facts)
    return facts


# ── prompt ──────────────────────────────────────────────────────────────────

def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def user_prompt(facts: dict, memory_text: str | None) -> str:
    lines = [f"Date: {facts['date']}", "", "## Fact sheet (code-computed, last complete daily bar)"]
    for t, f in facts["tickers"].items():
        lines.append(f"- {t} (as of {f['as_of']}): close {f['close']:.4g}; return 5d {_pct(f['ret_5d'])}, "
                     f"20d {_pct(f['ret_20d'])}, 60d {_pct(f['ret_60d'])}; vs MA50 {_pct(f['vs_ma50'])}, "
                     f"vs MA200 {_pct(f['vs_ma200'])}; ATR20 "
                     f"{'n/a' if f['atr20_pct'] is None else format(f['atr20_pct'], '.1%')} of price; "
                     f"regime {'/'.join(f['tags']) or 'n/a'}")
    for t, why in facts["unavailable"].items():
        lines.append(f"- {t}: unavailable ({why}); do not trade it")
    if facts["headlines"]:
        lines += ["", "## Public headlines"] + [f"- {h}" for h in facts["headlines"]]
    if memory_text is not None:
        lines += ["", P.MEMORY_BEGIN, memory_text, P.MEMORY_END]
    lines += ["", f"Make 1 to {MAX_CALLS} calls. Return ONLY the JSON object."]
    return "\n".join(lines)


# ── LLM (injectable; tests never reach the gateway) ─────────────────────────

async def _default_llm(system_prompt: str, user: str) -> dict:
    from marketmind.gateway.async_client import chat_flash
    return await chat_flash(system_prompt=system_prompt, user_prompt=user,
                            temperature=0.2, max_tokens=2048)


def parse_json(content: str) -> dict | None:
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
        content = content.rsplit("```", 1)[0]
    content = re.sub(r",\s*([}\]])", r"\1", content)
    for text in (content, content[content.find("{"):content.rfind("}") + 1]):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


async def _ask(llm, system_prompt: str, user: str) -> tuple[dict | None, str | None, str]:
    """(parsed JSON, models label, error)."""
    with llm_trace.trace() as calls:
        try:
            result = await llm(system_prompt, user)
        except Exception as exc:                     # a failed call is a no-call day
            logger.warning("memory_desk LLM call failed: %s", exc)
            return None, None, f"LLM call failed: {exc}"[:300]
    result = result if isinstance(result, dict) else {"content": str(result)}
    models = llm_trace.label(calls) or result.get("model")
    if result.get("error") or not result.get("content"):
        return None, models, f"LLM error: {result.get('error') or 'empty response'}"
    parsed = parse_json(result["content"])
    return parsed, models, "" if parsed is not None else "LLM output not parseable"


async def word_lessons(mem: dict, ids: list[str], llm) -> None:
    """LLM wording for newly active lessons; counts and status stay code-computed.
    On any failure the code template (memory.describe) is used."""
    todo = [mem["lessons"][i] for i in ids if i in mem["lessons"]]
    if not todo:
        return
    payload = [{"id": l["id"], "condition": l["condition"], "claim": l["claim"],
                "n": l["n"], "hit_rate": l["hit_rate"], "baseline": l["baseline"],
                "error_classes": l["error_classes"]} for l in todo]
    parsed, models, _ = await _ask(llm, P.WORDING_SYSTEM_PROMPT,
                                   json.dumps(payload, ensure_ascii=False))
    for l in todo:
        text = str((parsed or {}).get(l["id"]) or "").strip().replace("\n", " ")
        if text:
            l["wording"], l["wording_by"] = text[:120], models
            l["wording_prompt_version"] = P.WORDING_PROMPT_VERSION


# ── calls (code) ────────────────────────────────────────────────────────────

def build_calls(parsed: dict, facts: dict, *, agent_id: str, held: set[str],
                lesson_ids: set[str], models: str | None, memory_on: bool) -> tuple[list[dict], list[str]]:
    calls, skipped = [], []
    for raw in (parsed.get("calls") or [])[:MAX_CALLS * 2]:
        if not isinstance(raw, dict):
            continue
        t = str(raw.get("ticker") or "").strip().upper()
        d = {"long": "long", "bullish": "long", "short": "short",
             "bearish": "short"}.get(str(raw.get("direction") or "").strip().lower())
        f = facts["tickers"].get(t)
        if f is None or d is None:
            skipped.append(f"{t or '?'}: not in today's fact sheet or bad direction")
            continue
        if t in held or any(c["ticker"] == t for c in calls):
            skipped.append(f"{t}: already holding an unsettled {agent_id} record or duplicate")
            continue
        level = f["stop_long"] if d == "long" else f["stop_short"]
        if level is None:
            skipped.append(f"{t}: ATR20 not computable (no stop)")
            continue
        try:
            raw_conf = float(raw.get("confidence"))
        except (TypeError, ValueError):
            raw_conf = CONF_MIN
        conf = round(min(CONF_MAX, max(CONF_MIN, raw_conf)), 4)
        text, rule = q.falsifier(t, d, level, f["atr20"], HOLD_BARS)
        used = [str(x) for x in (raw.get("lessons_used") or []) if str(x) in lesson_ids]
        calls.append({
            "ticker": t, "direction": d, "confidence": conf,
            "hold_bars": HOLD_BARS, "hold_days": HOLD_BARS,
            "thesis": str(raw.get("thesis") or "")[:300],
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": agent_id,
            "signal_key": f"{facts['date']}:{t}",
            "signal": {"facts": {k: v for k, v in f.items() if not k.startswith("stop_")},
                       "raw_confidence": raw_conf, "prompt_version": P.PROMPT_VERSION,
                       "llm": models, "memory": memory_on, "lessons_used": used},
        })
        if len(calls) >= MAX_CALLS:
            break
    return calls, skipped


def _own_records(store, agent_id: str) -> list:
    sid = f"playground:{agent_id}"
    return [e for e in store.list(source_type="playground") if e.source_id == sid]


async def run_desk(context: dict, *, agent_id: str, use_memory: bool, mock: bool = False,
                   fetch=None, llm=None, now: datetime | None = None,
                   data_dir: str | Path | None = None, store=None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    root = desk_dir(data_dir)
    facts = await load_or_build_facts(root, today, context or {}, fetch)
    base = {"directional_calls": [], "as_of_run": today.isoformat(),
            "prompt_version": P.PROMPT_VERSION, "memory_enabled": use_memory,
            "unavailable": facts["unavailable"]}
    if not facts["tickers"]:
        return {**base, "no_calls_reason": "no instrument with usable price data"}
    if store is None:
        from marketmind.ledger.store import LedgerStore, default_ledger_path
        store = LedgerStore(Path(data_dir) / "ledger.db" if data_dir else default_ledger_path())
    own = _own_records(store, agent_id)
    held = {e.ticker for e in own if e.status in ("pending", "open")}
    llm = llm or _default_llm

    memory_text, retrieved, mem_stats = None, [], None
    if use_memory:
        path = memory_path(data_dir)
        mem = M.load(path)
        mem_stats = M.sync(mem, own, today)
        activated = M.update_lessons(mem, today, P.PROMPT_VERSION)
        await word_lessons(mem, activated, llm)
        retrieved = M.retrieve(mem, {t: f["tags"] for t, f in facts["tickers"].items()})
        memory_text = M.render(mem, retrieved)
        M.save(path, mem)
        mem_stats.update(lessons={s: sum(l["status"] == s for l in mem["lessons"].values())
                                  for s in ("candidate", "active")},
                         activated=activated, retrieved=[l["id"] for l in retrieved])

    prompt = user_prompt(facts, memory_text)
    parsed, models, err = await _ask(llm, P.DESK_SYSTEM_PROMPT, prompt)
    out = {**base, "llm": models, "memory": mem_stats}
    if parsed is None:
        return {**out, "no_calls_reason": err}
    calls, skipped = build_calls(parsed, facts, agent_id=agent_id, held=held,
                                 lesson_ids={l["id"] for l in retrieved}, models=models,
                                 memory_on=use_memory)
    out.update(directional_calls=calls, skipped=skipped)
    if not calls:
        out["no_calls_reason"] = str(parsed.get("no_calls_reason") or "no valid call")[:300]
    return out


async def analyze(context: dict, *, mock: bool = False, **kw) -> dict:
    return await run_desk(context, agent_id=AGENT_ID, use_memory=True, mock=mock, **kw)
