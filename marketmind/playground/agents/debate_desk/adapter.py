"""Bull/bear debate desk - a multi-agent LLM Playground candidate (docs/PLAYGROUND_AGENTS.md §5).

Shape taken from TradingAgents (Xiao, Sun, Luo & Wang 2024, arXiv:2412.20138): opposing
bull and bear researchers argue from the same analyst material, then a risk manager /
facilitator records one structured decision. Cut down for a bounded daily cost:

  universe   SPY QQQ GLD TLT BTC-USD ETH-USD + the 3 Select Sector SPDR ETFs with the
             highest 20-bar return (code);
  selection  the DEFAULT_TICKERS candidates with the largest |20-bar return| scaled by
             20-bar realised volatility (code; raw |return| would pick crypto every day);
  per ticker 5 Flash calls through the gateway (chat_with_integrity): bull and bear
             openings (fact sheet only), one rebuttal each (sees the other's opening),
             then the judge, which must answer with strict JSON
             {ticker, action, confidence, hold_days, thesis, key_risk}. Anything that fails
             the schema -> no call for that ticker; nothing is invented or repaired.

L3 (docs/SPEC_v3.md §2): the fact sheet (returns, SMA50/200, ATR20, the trend state from
data/trend/<date>.json) is computed here by code; the LLMs only argue and decide. The stop
is code: 3 x Wilder ATR20 from the last complete close (agents/_quant), recorded as the
ledger falsifier_rule. The judge's confidence is recorded, then mapped linearly from
[0.5, 1] onto [0.5, 0.7] for the ledger (LLM verbalised confidence runs high).

Information firewall: the adapter reads only news titles / source names from the public
context, public daily bars, and the code-computed trend state file; never main-pipeline,
shadow or other Playground output. Headlines and every LLM argument passed on to another
role are defanged (marketmind.pipeline.defang) and fenced as untrusted data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from marketmind.gateway import llm_trace
from marketmind.gateway.price_history import Bar
from marketmind.pipeline.defang import defang_text
from marketmind.playground.agents import _quant as q
from marketmind.playground.agents.debate_desk import prompts as P
from marketmind.trend.rules import sma, wilder_atr

logger = logging.getLogger("marketmind.playground.debate_desk")

AGENT_ID = "debate_desk"
MODEL = "bull_bear_debate_v1"
LLM_TIER = "flash"                    # owner decision 2026-09-28: shadows use Flash; same here

CORE: tuple[str, ...] = ("SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD")
SECTORS: tuple[str, ...] = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
                            "XLU", "XLV", "XLY")
N_SECTORS = 3

# ── cost bounds ─────────────────────────────────────────────────────────────
CALLS_PER_TICKER = 5                  # bull, bear, bull rebuttal, bear rebuttal, judge
MAX_TICKERS = 5
MAX_CALLS_PER_RUN = MAX_TICKERS * CALLS_PER_TICKER          # 25, hard stop
DEFAULT_TICKERS = 3                   # 15 calls, ~24k tokens (token_estimate)
TOKEN_BUDGET = 40_000                 # owner target per day
MAX_HEADLINES = 3
HEADLINE_CHARS = 200
ARGUMENT_CHARS = 2000                 # an argument passed on to another role
ANALYST_MAX_TOKENS, JUDGE_MAX_TOKENS = 700, 500
CALL_TIMEOUT_S = 300
# expected reply sizes for the estimate (180 / 150 words, JSON of ~500 characters)
OUT_TOKENS_OPEN, OUT_TOKENS_REBUTTAL, OUT_TOKENS_JUDGE = 320, 270, 200
INTEGRITY_HEADER_TOKENS = 160         # chat_with_integrity's header (~120 measured, rounded up)
CHARS_PER_TOKEN = 4

# ── decision rules ──────────────────────────────────────────────────────────
MIN_BARS = 201                        # SMA200 on the last bar, ATR20
MOM_BARS = 20
HOLD_MIN, HOLD_MAX = 5, 30
CONF_LO, CONF_HI = 0.5, 0.7
ACTIONS = {"enter_long": "long", "enter_short": "short", "no_trade": None}
VERDICT_KEYS = ("ticker", "action", "confidence", "hold_days", "thesis", "key_risk")
TREND_MAX_AGE_DAYS = 3

PROMPT_VERSION = P.PROMPT_VERSION
PROMPT_FINGERPRINT = llm_trace.prompt_version(P.fingerprint_source())

KEYWORDS: dict[str, tuple[str, ...]] = {
    "SPY": (r"S&P ?500", r"\bSPY\b", r"Wall Street", r"\bstocks?\b", r"\bFed\b"),
    "QQQ": (r"Nasdaq", r"\bQQQ\b", r"tech stocks?", r"megacaps?"),
    "GLD": (r"\bgold\b", r"\bGLD\b", r"bullion"),
    "TLT": (r"Treasur(y|ies)", r"\bTLT\b", r"bond yields?", r"\byields?\b", r"\bFed\b"),
    "BTC-USD": (r"bitcoin", r"\bBTC\b", r"\bcrypto"),
    "ETH-USD": (r"\bether\b", r"ethereum", r"\bETH\b", r"\bcrypto"),
    "XLB": (r"\bmaterials\b", r"chemicals?", r"\bmining\b", r"\bXLB\b"),
    "XLC": (r"communication services", r"\bmedia\b", r"telecom", r"\bXLC\b"),
    "XLE": (r"\boil\b", r"\benergy\b", r"crude", r"OPEC", r"\bXLE\b"),
    "XLF": (r"\bbanks?\b", r"financials?", r"lenders?", r"\bXLF\b"),
    "XLI": (r"industrials?", r"manufacturing", r"aerospace", r"\bXLI\b"),
    "XLK": (r"technology", r"\bchips?\b", r"semiconductors?", r"software", r"\bXLK\b"),
    "XLP": (r"consumer staples", r"grocer", r"\bstaples\b", r"\bXLP\b"),
    "XLRE": (r"real estate", r"\bREITs?\b", r"housing", r"\bXLRE\b"),
    "XLU": (r"utilit(y|ies)", r"\bpower grid\b", r"electricity", r"\bXLU\b"),
    "XLV": (r"health ?care", r"pharma", r"biotech", r"drugmakers?", r"\bXLV\b"),
    "XLY": (r"consumer discretionary", r"retail(ers)?", r"consumer spending", r"\bXLY\b"),
}
_KEYWORD_RX = {t: re.compile("|".join(k), re.IGNORECASE) for t, k in KEYWORDS.items()}

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched, no LLM call."}

Llm = Callable[[str, str, str], Awaitable[str | None]]      # (role, system, user) -> reply


# ══════════════════════════════════════════════════════════════════════════
# Facts (code only)
# ══════════════════════════════════════════════════════════════════════════

def _pct(a: float, b: float | None) -> float | None:
    return None if b is None or b <= 0 else a / b - 1


def realised_mom(bars: Sequence[Bar], n: int = MOM_BARS) -> float | None:
    """n-bar return / (stdev of the last n daily returns x sqrt(n)): momentum in units of
    its own volatility, so a 5% move in TLT and a 5% move in ETH do not rank alike."""
    r = q.trailing(bars, n)
    window = bars[-(n + 1):]
    rets = [b.close / a.close - 1 for a, b in zip(window, window[1:]) if a.close > 0]
    if r is None or len(rets) < n:
        return None
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (len(rets) - 1))
    return None if sd <= 0 else r / (sd * math.sqrt(n))


def facts(ticker: str, bars: Sequence[Bar] | None, today: date,
          source: str | None = None) -> tuple[dict | None, str | None]:
    """(fact sheet numbers, None) or (None, why unavailable)."""
    why = q.unavailable(ticker, bars, MIN_BARS, today)
    if why:
        return None, why
    atr = wilder_atr(bars, q.ATR_PERIOD)[-1]
    if atr is None or atr <= 0:
        return None, "ATR20 not computable"
    closes = [b.close for b in bars]
    close = closes[-1]
    s50, s200 = sma(closes, 50)[-1], sma(closes, 200)[-1]
    n12 = q.momentum_bars(ticker)
    return {"ticker": ticker, "as_of": bars[-1].date, "close": close, "source": source,
            "ret_5": q.r4(q.trailing(bars, 5)), "ret_20": q.r4(q.trailing(bars, 20)),
            "ret_60": q.r4(q.trailing(bars, 60)), "ret_12m": q.r4(q.trailing(bars, n12)),
            "bars_12m": n12, "sma50": q.r4(s50), "sma200": q.r4(s200),
            "vs_sma50": q.r4(_pct(close, s50)), "vs_sma200": q.r4(_pct(close, s200)),
            "atr20": q.r4(atr), "atr_pct": q.r4(atr / close),
            "mom20_z": q.r4(realised_mom(bars))}, None


def top_sectors(bars_by: dict[str, Sequence[Bar] | None], today: date,
                n: int = N_SECTORS) -> list[str]:
    """The n sector ETFs with the highest 20-bar return (ties: alphabetical)."""
    ranked = []
    for t in SECTORS:
        bars = bars_by.get(t)
        if q.unavailable(t, bars, MOM_BARS + 1, today) is None:
            r = q.trailing(bars, MOM_BARS)
            if r is not None:
                ranked.append((-r, t))
    return [t for _, t in sorted(ranked)[:n]]


def candidates(bars_by: dict, today: date, sources: dict | None = None
               ) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    """({ticker: facts}, {ticker: why unavailable}, today's top sectors)."""
    sectors = top_sectors(bars_by, today)
    sheets, missing = {}, {}
    for t in dict.fromkeys(CORE + tuple(sectors)):
        f, why = facts(t, bars_by.get(t), today, (sources or {}).get(t))
        if f is None:
            missing[t] = why
        else:
            sheets[t] = f
    return sheets, missing, sectors


def select(sheets: dict[str, dict], n: int) -> list[str]:
    """The n candidates with the largest |volatility-scaled 20-bar momentum|."""
    ranked = sorted((-abs(s["mom20_z"]), t) for t, s in sheets.items() if s["mom20_z"] is not None)
    return [t for _, t in ranked[:max(0, n)]]


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def trend_states(folder: Path, today: date) -> tuple[dict[str, dict], str | None]:
    """The code-computed trend states (data/trend/<date>.json, docs/TREND_DESIGN.md §9)
    from the latest file at most TREND_MAX_AGE_DAYS old: ({ticker: state}, file date)."""
    from marketmind.trend.daily import load
    try:
        stem, doc = load(folder)
    except OSError:
        return {}, None
    if doc is None or stem < (today - timedelta(days=TREND_MAX_AGE_DAYS)).isoformat():
        return {}, None
    return dict(doc.get("full") or {}), stem


# ══════════════════════════════════════════════════════════════════════════
# Untrusted text
# ══════════════════════════════════════════════════════════════════════════

def clean(text: str, limit: int) -> str:
    """Untrusted text -> one prompt-safe string: no fence tokens (<<< / >>>), injection
    patterns defanged, at most `limit` characters."""
    text = re.sub(r"[<>]{3,}", " ", str(text or ""))
    return defang_text(text.strip())[:limit]


def headlines(ticker: str, news: Sequence) -> list[str]:
    """Up to MAX_HEADLINES distinct titles mentioning the instrument (title and source only)."""
    rx = _KEYWORD_RX.get(ticker)
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
        src = clean(" ".join(str(item.get("source_name") or item.get("source") or "unknown").split()), 40)
        out.append(f"- [{src}] {text}")
        if len(out) >= MAX_HEADLINES:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════
# Prompts
# ══════════════════════════════════════════════════════════════════════════

def _p(x: float | None) -> str:
    return "DATA_UNAVAILABLE" if x is None else f"{x:+.2%}"


def _n(x: float | None) -> str:
    return "DATA_UNAVAILABLE" if x is None else f"{x:.6g}"


def render_sheet(f: dict, trend: dict | None, trend_file: str | None, heads: list[str],
                 rank: int, of: int) -> str:
    unit = "UTC days" if f["bars_12m"] == 365 else "trading days"
    if trend:
        tline = f"{trend.get('state', 'DATA_UNAVAILABLE')}"
        if trend.get("entry_signal_date"):
            tline += f", entry signal {trend['entry_signal_date']}"
        if trend.get("stop_level") is not None:
            tline += f", state-machine stop {_n(trend['stop_level'])}"
        tline += f" (file {trend_file})"
    elif trend_file:
        tline = f"DATA_UNAVAILABLE (not in the trend universe; file {trend_file})"
    else:
        tline = f"DATA_UNAVAILABLE (no trend file within {TREND_MAX_AGE_DAYS} days)"
    lines = [
        f"FACT SHEET - {f['ticker']} (computed by code from complete daily bars; "
        f"last bar {f['as_of']}, source {f.get('source') or 'DATA_UNAVAILABLE'})",
        f"close: {_n(f['close'])}",
        f"returns: 5 bars {_p(f['ret_5'])} | 20 bars {_p(f['ret_20'])} | 60 bars {_p(f['ret_60'])}"
        f" | 12 months ({f['bars_12m']} {unit}) {_p(f['ret_12m'])}",
        f"SMA50: {_n(f['sma50'])} (close {_p(f['vs_sma50'])} vs SMA50) | SMA200: {_n(f['sma200'])}"
        f" (close {_p(f['vs_sma200'])} vs SMA200)",
        f"ATR20 (Wilder): {_n(f['atr20'])} ({'DATA_UNAVAILABLE' if f['atr_pct'] is None else format(f['atr_pct'], '.2%')} of close)",
        f"20-bar momentum / 20-bar volatility: {_n(f['mom20_z'])} (rank {rank} of {of} desk candidates)",
        f"trend state machine (code): {tline}",
        "",
        f"Headlines mentioning this market ({len(heads)}):",
        P.HEADLINES_OPEN,
        *(heads or ["(none)"]),
        P.HEADLINES_CLOSE,
    ]
    return "\n".join(lines)


def _fenced(label: str, text: str) -> str:
    return f"{label}:\n{P.ARGUMENT_OPEN}\n{clean(text, ARGUMENT_CHARS)}\n{P.ARGUMENT_CLOSE}"


def opening_user(sheet: str) -> str:
    return f"{sheet}\n\nWrite your opening argument."


def rebuttal_user(sheet: str, own: str, other: str) -> str:
    return "\n\n".join((sheet, _fenced("Your opening argument", own),
                        _fenced("Your opponent's opening argument", other), P.REBUTTAL_TASK))


def judge_user(sheet: str, ticker: str, bull: str, bear: str, bull_r: str, bear_r: str) -> str:
    return "\n\n".join((sheet, _fenced("Bull opening", bull), _fenced("Bear opening", bear),
                        _fenced("Bull rebuttal", bull_r), _fenced("Bear rebuttal", bear_r),
                        f"Return the JSON object for {ticker} now."))


# ══════════════════════════════════════════════════════════════════════════
# Judge verdict (strict schema)
# ══════════════════════════════════════════════════════════════════════════

def parse_verdict(raw: str | None, ticker: str) -> tuple[dict | None, str | None]:
    """(verdict, None) or (None, why invalid). A bare JSON object, optionally inside one
    ``` fence; no extraction from surrounding prose, no repair."""
    text = (raw or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
    except ValueError:
        return None, "judge reply is not valid JSON"
    if not isinstance(obj, dict):
        return None, "judge reply is not a JSON object"
    absent = [k for k in VERDICT_KEYS if k not in obj]
    if absent:
        return None, f"judge reply lacks {', '.join(absent)}"
    if str(obj["ticker"]).strip().upper() != ticker:
        return None, f"judge ticker {obj['ticker']!r} is not {ticker}"
    if obj["action"] not in ACTIONS:
        return None, f"judge action {obj['action']!r}"
    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
        return None, f"judge confidence {conf!r} not a number in 0-1"
    hold = obj["hold_days"]
    if isinstance(hold, float) and hold.is_integer():
        hold = int(hold)
    if isinstance(hold, bool) or not isinstance(hold, int) or not HOLD_MIN <= hold <= HOLD_MAX:
        return None, f"judge hold_days {obj['hold_days']!r} not an integer in {HOLD_MIN}-{HOLD_MAX}"
    texts = {}
    for k, limit in (("thesis", 300), ("key_risk", 200)):
        v = obj[k]
        if not isinstance(v, str) or not v.strip():
            return None, f"judge {k} empty"
        texts[k] = " ".join(v.split())[:limit]
    return {"ticker": ticker, "action": obj["action"], "confidence": float(conf),
            "hold_days": hold, **texts,
            "ignored_keys": sorted(set(obj) - set(VERDICT_KEYS))}, None


def ledger_confidence(judge_conf: float) -> float:
    """Judge confidence 0.5-1.0 -> ledger confidence 0.5-0.7, linear."""
    c = min(1.0, max(0.5, judge_conf))
    return round(CONF_LO + (CONF_HI - CONF_LO) * (c - 0.5) / 0.5, 4)


def build_call(f: dict, bars: Sequence[Bar], verdict: dict, week: str,
               llm_label: str | None) -> tuple[dict | None, str]:
    """(ledger call, outcome) from a valid verdict; stop, size and falsifier by code."""
    t = f["ticker"]
    direction = ACTIONS[verdict["action"]]
    if direction is None:
        return None, "judge: no_trade"
    if verdict["confidence"] < 0.5:
        return None, f"judge chose {verdict['action']} at confidence {verdict['confidence']} < 0.5"
    stop = q.atr_stop(bars, direction)
    if stop is None:
        return None, "ATR20 stop not computable"
    hold = verdict["hold_days"]
    text, rule = q.falsifier(t, direction, stop[0], stop[1], hold)
    side = "做多" if direction == "long" else "做空"
    summary = f"{verdict['thesis']} | key risk: {verdict['key_risk']}"
    signal = {k: f[k] for k in ("as_of", "close", "ret_5", "ret_20", "ret_60", "ret_12m",
                                "vs_sma50", "vs_sma200", "atr20", "mom20_z")}
    signal.update({
        "stop_level": stop[0], "stop_basis": f"close ∓ {q.STOP_ATR_MULT:g}×ATR{q.ATR_PERIOD}",
        "judge": {k: verdict[k] for k in ("action", "confidence", "hold_days", "thesis", "key_risk")},
        "reasoning_summary": summary[:520],
        "confidence_map": f"{CONF_LO}+{CONF_HI - CONF_LO:.1f}*(judge-0.5)/0.5",
        "llm": llm_label, "llm_tier": LLM_TIER,
        "prompt_version": PROMPT_VERSION, "prompt_fingerprint": PROMPT_FINGERPRINT,
    })
    return {"ticker": t, "direction": direction, "confidence": ledger_confidence(verdict["confidence"]),
            "hold_bars": hold, "hold_days": hold,
            "thesis": f"多空辩论台裁决（{side}）：{verdict['thesis']}"[:600],
            "falsifier": f"{text}；裁判列出的关键风险：{verdict['key_risk']}",
            "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{t}:{direction}:{week}", "signal": signal}, "call"


# ══════════════════════════════════════════════════════════════════════════
# Debate
# ══════════════════════════════════════════════════════════════════════════

async def debate(ticker: str, sheet: str, llm: Llm) -> dict:
    """Openings -> rebuttals -> judge. A missing reply stops the ticker (no judge call)."""
    rec: dict = {"calls": 0}
    user = opening_user(sheet)
    bull, bear = await asyncio.gather(llm("bull", P.BULL_SYSTEM, user),
                                      llm("bear", P.BEAR_SYSTEM, user))
    rec.update(calls=2, bull=bull, bear=bear)
    if not bull or not bear:
        return {**rec, "outcome": "opening argument missing"}
    bull_r, bear_r = await asyncio.gather(
        llm("bull_rebuttal", P.BULL_SYSTEM, rebuttal_user(sheet, bull, bear)),
        llm("bear_rebuttal", P.BEAR_SYSTEM, rebuttal_user(sheet, bear, bull)))
    rec.update(calls=4, bull_rebuttal=bull_r, bear_rebuttal=bear_r)
    if not bull_r or not bear_r:
        return {**rec, "outcome": "rebuttal missing"}
    raw = await llm("judge", P.JUDGE_SYSTEM, judge_user(sheet, ticker, bull, bear, bull_r, bear_r))
    verdict, why = parse_verdict(raw, ticker)
    rec.update(calls=5, judge_raw=raw, verdict=verdict)
    if verdict is None:
        rec["outcome"] = why
    return rec


async def _gateway_llm(role: str, system: str, user: str) -> str | None:
    """One Flash call through the gateway (integrity header + time anchor); None on failure."""
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_with_integrity
    token = usage_tracker.set_stage(f"playground:{AGENT_ID}")
    try:
        result = await asyncio.wait_for(chat_with_integrity(
            model=LLM_TIER, system_prompt=system, user_prompt=user,
            caller_agent=f"{AGENT_ID}:{role}", temperature=0.1 if role == "judge" else 0.4,
            max_tokens=JUDGE_MAX_TOKENS if role == "judge" else ANALYST_MAX_TOKENS),
            timeout=CALL_TIMEOUT_S)
    except Exception as exc:                       # noqa: BLE001 - one role failing ends the ticker
        logger.warning("debate_desk %s call failed: %s", role, exc)
        return None
    finally:
        usage_tracker.reset_stage(token)
    if not isinstance(result, dict) or result.get("error"):
        logger.warning("debate_desk %s call error: %s", role,
                       result.get("error") if isinstance(result, dict) else result)
        return None
    return result.get("content") or None


async def _fetch_bars(tickers: list[str]) -> tuple[dict, dict]:
    """(complete daily bars by ticker, source by ticker); two years covers SMA200 and the
    365-day crypto year. Network I/O; tests pass their own `fetch`."""
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(list(tickers), years=2)
    bars = {t: (complete_bars(t, h.daily) if h is not None and h.daily else None)
            for t, h in hists.items()}
    return bars, {t: h.source for t, h in hists.items() if h is not None}


# ══════════════════════════════════════════════════════════════════════════
# Cost estimate
# ══════════════════════════════════════════════════════════════════════════

_SAMPLE = {"ticker": "BTC-USD", "as_of": "2026-09-28", "close": 123456.78, "source": "alpaca",
           "ret_5": -0.0123, "ret_20": 0.0456, "ret_60": -0.0789, "ret_12m": 0.4321,
           "bars_12m": 365, "sma50": 118765.4321, "sma200": 101234.5678, "vs_sma50": 0.0395,
           "vs_sma200": 0.2195, "atr20": 3456.789, "atr_pct": 0.028, "mom20_z": 1.2345}


def token_estimate(n_tickers: int = DEFAULT_TICKERS) -> dict:
    """Expected tokens per day from the real prompt texts: a full fact sheet (3 headlines of
    maximum length), replies at their word limits, the gateway's integrity header.
    Characters / 4; hidden reasoning tokens (if the answering model thinks) not included."""
    def tok(s: str) -> int:
        return math.ceil(len(s) / CHARS_PER_TOKEN)
    heads = [f"- [{'s' * 20}] {'h' * HEADLINE_CHARS}"] * MAX_HEADLINES
    sheet = render_sheet(_SAMPLE, {"state": "TREND", "entry_signal_date": "2026-09-01",
                                   "stop_level": 110000.0}, "2026-09-28", heads, 1, 9)
    arg_open, arg_reb = "w" * OUT_TOKENS_OPEN * CHARS_PER_TOKEN, "w" * OUT_TOKENS_REBUTTAL * CHARS_PER_TOKEN
    hdr = INTEGRITY_HEADER_TOKENS
    opening = (hdr + tok(P.BULL_SYSTEM) + tok(opening_user(sheet)) + OUT_TOKENS_OPEN) \
        + (hdr + tok(P.BEAR_SYSTEM) + tok(opening_user(sheet)) + OUT_TOKENS_OPEN)
    rebuttal = 2 * (hdr + tok(P.BULL_SYSTEM) + tok(rebuttal_user(sheet, arg_open, arg_open))
                    + OUT_TOKENS_REBUTTAL)
    judge = hdr + tok(P.JUDGE_SYSTEM) + tok(judge_user(sheet, "BTC-USD", arg_open, arg_open,
                                                       arg_reb, arg_reb)) + OUT_TOKENS_JUDGE
    per = opening + rebuttal + judge
    n = max(0, min(n_tickers, MAX_TICKERS))
    return {"per_ticker": per, "n_tickers": n, "calls": n * CALLS_PER_TICKER, "per_day": per * n,
            "breakdown": {"openings": opening, "rebuttals": rebuttal, "judge": judge}}


# ══════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════

async def analyze(context: dict, *, mock: bool = False, fetch=None, llm: Llm | None = None,
                  now: datetime | None = None, data_root: Path | None = None,
                  max_tickers: int = DEFAULT_TICKERS) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    n = max(0, min(int(max_tickers), MAX_TICKERS))
    bars_by, sources = await (fetch or _fetch_bars)(list(CORE + SECTORS))
    sheets, missing, sectors = candidates(bars_by, today, sources)
    selected = select(sheets, n)
    trend, trend_file = trend_states(data_root or data_dir(), today)
    news = context.get("news") if isinstance(context, dict) else None

    base = llm or _gateway_llm
    log: list[dict] = []

    async def counted(role: str, system: str, user: str) -> str | None:
        entry = {"label": f"{ticker}:{role}", "response": "", "error": ""}
        log.append(entry)
        if len(log) > MAX_CALLS_PER_RUN:            # hard stop; cannot trigger at <= MAX_TICKERS
            entry["error"] = "call budget exhausted"
            return None
        reply = await base(role, system, user)
        if reply is None:
            entry["error"] = "no reply"
        else:
            entry["response"] = reply[:3000]
        return reply

    calls, debates, outcomes = [], {}, {}
    week = q.week_key(today)
    for rank, ticker in enumerate(selected, 1):
        sheet = render_sheet(sheets[ticker], trend.get(ticker), trend_file,
                             headlines(ticker, news or []), rank, len(sheets))
        with llm_trace.trace() as models:
            rec = await debate(ticker, sheet, counted)
        label = llm_trace.label(models)
        outcome = rec.get("outcome")
        if rec.get("verdict") is not None:
            call, outcome = build_call(sheets[ticker], bars_by[ticker], rec["verdict"], week, label)
            if call:
                calls.append(call)
        outcomes[ticker] = outcome
        debates[ticker] = {**{k: (v[:3000] if isinstance(v, str) else v) for k, v in rec.items()},
                           "outcome": outcome, "llm": label, "fact_sheet": sheet}

    out = {"directional_calls": calls, "as_of_run": today.isoformat(),
           "universe": list(dict.fromkeys(CORE + tuple(sectors))), "top_sectors": sectors,
           "selected": selected, "facts": sheets, "unavailable": missing,
           "trend_file": trend_file, "debates": debates, "llm_calls": len(log),
           "prompt_version": PROMPT_VERSION, "prompt_fingerprint": PROMPT_FINGERPRINT,
           "token_estimate": token_estimate(n)["per_day"],
           "_research_log": log, "_passes": 1}
    if not calls:
        out["no_calls_reason"] = ("; ".join(f"{t}: {o}" for t, o in outcomes.items())
                                  or "no candidate with usable price data")
    return out
