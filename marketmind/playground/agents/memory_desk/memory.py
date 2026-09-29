"""Layered memory of the memory_desk Playground agent (docs/PLAYGROUND_AGENTS.md §5).

Pure code: no LLM, no network. Three tiers, after FinMem (Yu et al. 2023) and the
legacy shadow memory (working / episodic / semantic, 90-day episodic TTL):

  working    the desk's own ledger records of the last WORKING_DAYS days, any status
  episodic   the desk's own SETTLED records with the settlement's code-computed review
             facts (error_class, MFE/MAE, regime; docs/S9_DESIGN.md §3); an episode
             expires EPISODIC_TTL_DAYS after its exit and then stops counting as evidence
  semantic   lessons: structured rules computed from episodic facts only, never from
             free LLM self-critique (ExpeL, Zhao et al. 2023, extracts insights from the
             agent's own successes and failures; S9 §5 restricts that to code-settled
             outcomes)

A lesson is {condition, claim (higher | lower net hit rate than the desk's baseline),
counts, evidence ids, status candidate | active | retired, created, expires}. Every
number and every status change is computed here; an LLM may only word an active
lesson (adapter.word_lessons). Life cycle:
  candidate  >= MIN_CREATE independent trades in the condition and |hit - baseline|
             >= MIN_EDGE. The trades seen at creation are its in-sample evidence.
  active     >= MIN_SUPPORT independent supporting trades, claim-side edge >= MIN_EDGE,
             and >= MIN_OOS out-of-sample trades (settled after creation) whose hit
             rate is also on the claim side of the baseline (validate before use).
  retired    counter-evidence (the hit rate is no longer on the claim side), failed
             out-of-sample check, or TTL: LESSON_TTL_TRADING_DAYS after creation, renewed
             only by new out-of-sample supporting trades.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

MEMORY_VERSION = 1
WORKING_DAYS = 5                  # calendar days of own recent decisions (working tier)
EPISODIC_TTL_DAYS = 90            # episodic decay (FinMem-style tiers; legacy _EPISODIC_TTL_DAYS)
LESSON_TTL_TRADING_DAYS = 60      # S9 §5: lessons expire unless new evidence renews them
MIN_CREATE = 3                    # never a lesson from one or two trades (S9 §5)
MIN_SUPPORT = 5                   # owner decision 2026-09-29
MIN_EDGE = 0.10                   # minimum |hit rate - baseline| [inference, not tuned]
MIN_OOS = 2                       # out-of-sample trades needed before a lesson is used
OOS_RETIRE_N = 3                  # out-of-sample trades that can retire a lesson
MIN_BASELINE_N = 5                # fewer other trades -> baseline 0.5
MAX_RETRIEVED = 5                 # S9 §5: at most ~5 lessons per decision
INDEPENDENT_GAP_DAYS = 7          # same-ticker trades entered closer than this overlap
WINS = ("win", "beta_carried")    # net profitable (review.error_class)
LOG_CAP = 300

TAG_TEXT = {"ret20_up": "近 20 日上涨", "ret20_down": "近 20 日下跌",
            "above_ma50": "收盘在 MA50 之上", "below_ma50": "收盘在 MA50 之下",
            "above_ma200": "收盘在 MA200 之上", "below_ma200": "收盘在 MA200 之下"}


# ── tags / dates ────────────────────────────────────────────────────────────

def regime_tags(regime: dict | None) -> list[str]:
    """Structured retrieval keys from a review's (or today's) regime facts."""
    regime = regime or {}
    tags = []
    r20 = regime.get("ret_20d")
    if r20 is not None:
        tags.append("ret20_up" if r20 > 0 else "ret20_down")
    for ma in ("ma50", "ma200"):
        v = regime.get(f"above_{ma}")
        if v is not None:
            tags.append(f"above_{ma}" if v else f"below_{ma}")
    return tags


def add_trading_days(d: date, n: int) -> date:
    """d + n weekdays (exchange holidays ignored)."""
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


# ── store ───────────────────────────────────────────────────────────────────

def empty() -> dict:
    return {"v": MEMORY_VERSION, "updated": None, "working": [], "episodic": [],
            "lessons": {}, "retired": [], "log": []}


def load(path: Path) -> dict:
    try:
        mem = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    base = empty()
    base.update({k: v for k, v in mem.items() if k in base})
    return base


def save(path: Path, mem: dict) -> None:
    """Atomic write (temp file + os.replace; retried while a reader holds it on Windows)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def _log(mem: dict, today: date, event: str, lesson_id: str, reason: str = "") -> None:
    mem["log"].append({"date": today.isoformat(), "event": event, "lesson": lesson_id,
                       "reason": reason})
    del mem["log"][:-LOG_CAP]


# ── tiers from the desk's own ledger records ────────────────────────────────

def episode(e) -> dict | None:
    """Episodic entry from a settled ledger record with review facts, else None."""
    r = e.review or {}
    if e.status != "settled" or not r.get("error_class") or not e.exit_date:
        return None
    meta = e.meta or {}
    sig = meta.get("signal") or {}
    return {"id": e.entry_id, "ticker": e.ticker, "direction": e.direction,
            "confidence": e.confidence, "entry_date": e.entry_date, "exit_date": e.exit_date,
            "exit_reason": e.exit_reason, "net_return": e.net_return,
            "error_class": r["error_class"], "hit": r["error_class"] in WINS,
            "mfe": r.get("mfe"), "mae": r.get("mae"), "bars_held": r.get("bars_held"),
            "regime": r.get("regime"), "tags": regime_tags(r.get("regime")),
            "prompt_version": meta.get("prompt_version") or sig.get("prompt_version"),
            "llm": meta.get("llm") or sig.get("llm")}


def sync(mem: dict, own_entries: Iterable, today: date) -> dict:
    """Rebuild working and episodic tiers from the desk's own records (idempotent)."""
    own = list(own_entries)
    since = today - timedelta(days=WORKING_DAYS)
    mem["working"] = [
        {"date": e.created_at[:10], "ticker": e.ticker, "direction": e.direction,
         "confidence": e.confidence, "status": e.status, "net_return": e.net_return,
         "error_class": (e.review or {}).get("error_class")}
        for e in own if e.created_at and _d(e.created_at) >= since]
    eps = [ep for e in own if (ep := episode(e))]
    cutoff = today - timedelta(days=EPISODIC_TTL_DAYS)
    kept = [ep for ep in eps if _d(ep["exit_date"]) >= cutoff]
    mem["episodic"] = sorted(kept, key=lambda ep: (ep["exit_date"], ep["id"]))
    mem["updated"] = today.isoformat()
    return {"working": len(mem["working"]), "episodic": len(kept), "expired": len(eps) - len(kept)}


# ── lessons ─────────────────────────────────────────────────────────────────

def independent(episodes: Iterable[dict]) -> list[dict]:
    """One trade per entry date, and same-ticker trades whose holds overlap count once
    (the first is kept): correlated trades are not independent evidence."""
    kept, dates, last = [], set(), {}
    for ep in sorted(episodes, key=lambda ep: (ep["entry_date"] or "", ep["ticker"], ep["id"])):
        d = ep["entry_date"]
        if not d or d in dates:
            continue
        prev = last.get(ep["ticker"])
        if prev is not None and (_d(d) - prev).days < INDEPENDENT_GAP_DAYS:
            continue
        kept.append(ep)
        dates.add(d)
        last[ep["ticker"]] = _d(d)
    return kept


def conditions(ep: dict) -> list[tuple[str, dict]]:
    """(lesson id, condition) templates an episode belongs to: direction x regime tag,
    and ticker x direction. Fixed, small hypothesis set."""
    out = [(f"{ep['direction']}|{t}", {"direction": ep["direction"], "tag": t})
           for t in ep["tags"]]
    out.append((f"{ep['ticker']}|{ep['direction']}",
                {"ticker": ep["ticker"], "direction": ep["direction"]}))
    return out


def _matches(cond: dict, ep: dict) -> bool:
    if ep["direction"] != cond["direction"]:
        return False
    if "tag" in cond and cond["tag"] not in ep["tags"]:
        return False
    return "ticker" not in cond or cond["ticker"] == ep["ticker"]


def _rate(units: list[dict]) -> float | None:
    return sum(u["hit"] for u in units) / len(units) if units else None


def stats(cond: dict, episodes: list[dict], claim: str | None = None,
          in_sample: set[str] | None = None) -> dict:
    """Code-computed counts of one condition over the episodic tier."""
    inside = [ep for ep in episodes if _matches(cond, ep)]
    units = independent(inside)
    others = independent([ep for ep in episodes if not _matches(cond, ep)])
    hit = _rate(units)
    base = _rate(others) if len(others) >= MIN_BASELINE_N else 0.5
    edge = None if hit is None else hit - base
    claim = claim or ("higher" if (edge or 0) >= 0 else "lower")
    sign = 1 if claim == "higher" else -1
    support = [u for u in units if u["hit"] == (claim == "higher")]
    oos = [u for u in units if in_sample is not None and u["id"] not in in_sample]
    oos_hit = _rate(oos)
    classes: dict[str, int] = {}
    for u in units:
        classes[u["error_class"]] = classes.get(u["error_class"], 0) + 1
    return {"n": len(units), "hits": sum(u["hit"] for u in units),
            "hit_rate": None if hit is None else round(hit, 4),
            "baseline": round(base, 4), "baseline_n": len(others),
            "edge": None if edge is None else round(edge, 4),
            "claim_edge": None if edge is None else round(sign * edge, 4),
            "n_support": len(support), "n_oos": len(oos),
            "oos_hit_rate": None if oos_hit is None else round(oos_hit, 4),
            "oos_claim_edge": None if oos_hit is None else round(sign * (oos_hit - base), 4),
            "error_classes": classes, "evidence_ids": [u["id"] for u in units][-50:],
            "support_ids": [u["id"] for u in support],
            "oos_support_exits": [u["exit_date"] for u in oos if u in support]}


def update_lessons(mem: dict, today: date, prompt_version: str | None = None) -> list[str]:
    """Create, activate, demote, renew and retire lessons from the episodic tier.
    Returns the ids of lessons that became active in this call."""
    eps = mem["episodic"]
    lessons: dict = mem["lessons"]
    activated: list[str] = []
    retired_today = {r["id"] for r in mem["retired"] if r.get("retired") == today.isoformat()}

    for lid, lesson in list(lessons.items()):
        s = stats(lesson["condition"], eps, lesson["claim"], set(lesson["in_sample_ids"]))
        lesson.update({k: v for k, v in s.items() if k != "oos_support_exits"})
        renewed = max([_d(lesson["created"])] + [_d(x) for x in s["oos_support_exits"]])
        lesson["expires"] = add_trading_days(renewed, LESSON_TTL_TRADING_DAYS).isoformat()
        reason = None
        if today > _d(lesson["expires"]):
            reason = "ttl: no new supporting evidence"
        elif s["n"] and s["claim_edge"] <= 0:
            reason = f"counter-evidence: hit rate {s['hit_rate']} vs baseline {s['baseline']}"
        elif s["n_oos"] >= OOS_RETIRE_N and s["oos_claim_edge"] <= 0:
            reason = f"out-of-sample: hit rate {s['oos_hit_rate']} vs baseline {s['baseline']}"
        if reason:
            lesson.update(status="retired", retired=today.isoformat(), retire_reason=reason)
            mem["retired"].append(lesson)
            del lessons[lid]
            retired_today.add(lid)
            _log(mem, today, "retired", lid, reason)
            continue
        ready = (s["n_support"] >= MIN_SUPPORT and s["claim_edge"] >= MIN_EDGE
                 and s["n_oos"] >= MIN_OOS and s["oos_claim_edge"] > 0)
        if lesson["status"] == "candidate" and ready:
            lesson.update(status="active", activated=today.isoformat())
            activated.append(lid)
            _log(mem, today, "activated", lid)
        elif lesson["status"] == "active" and not ready:
            lesson.update(status="candidate")
            _log(mem, today, "demoted", lid, "activation criteria no longer met")

    seen: dict[str, dict] = {}
    for ep in eps:
        for lid, cond in conditions(ep):
            seen.setdefault(lid, cond)
    for lid in sorted(seen):
        if lid in lessons or lid in retired_today:
            continue
        s = stats(seen[lid], eps)
        if s["n"] >= MIN_CREATE and abs(s["edge"]) >= MIN_EDGE:
            claim = "higher" if s["edge"] > 0 else "lower"
            s = stats(seen[lid], eps, claim)
            s.pop("oos_support_exits")
            lessons[lid] = {"id": lid, "condition": seen[lid], "claim": claim,
                            "status": "candidate", "created": today.isoformat(),
                            "expires": add_trading_days(today, LESSON_TTL_TRADING_DAYS).isoformat(),
                            "in_sample_ids": list(s["evidence_ids"]),
                            "author_prompt_version": prompt_version, "wording": None,
                            "wording_by": None, **s}
            _log(mem, today, "created", lid)
    del mem["retired"][:-200]
    return activated


# ── retrieval ───────────────────────────────────────────────────────────────

def applies_to(lesson: dict, current_tags: dict[str, list[str]]) -> list[str]:
    """Tickers (with facts today) the lesson's condition matches now."""
    cond = lesson["condition"]
    if "ticker" in cond:
        return [cond["ticker"]] if cond["ticker"] in current_tags else []
    return [t for t, tags in current_tags.items() if cond["tag"] in tags]


def retrieve(mem: dict, current_tags: dict[str, list[str]],
             limit: int = MAX_RETRIEVED) -> list[dict]:
    """Active lessons whose condition matches today's regime tags, strongest first
    (|edge| x sqrt(n)), at most `limit`."""
    hits = [(lesson, applies_to(lesson, current_tags)) for lesson in mem["lessons"].values()
            if lesson["status"] == "active"]
    hits = [(lesson, t) for lesson, t in hits if t]
    hits.sort(key=lambda x: (-abs(x[0]["edge"] or 0) * math.sqrt(x[0]["n"]), x[0]["id"]))
    return [dict(lesson, applies_to=t) for lesson, t in hits[:limit]]


def describe(lesson: dict) -> str:
    """Code template wording (used when no LLM wording is available)."""
    c = lesson["condition"]
    side = "做多" if c["direction"] == "long" else "做空"
    where = TAG_TEXT.get(c.get("tag"), c.get("ticker", ""))
    more = "高于" if lesson["claim"] == "higher" else "低于"
    return f"{where}时{side}：净赚比例{more}基准"


def render(mem: dict, lessons: list[dict], recent: int = 5) -> str:
    """The memory section's body (the adapter wraps it in the delimiters)."""
    lines = ["## Working memory (own decisions, last %d days)" % WORKING_DAYS]
    for w in mem["working"][-10:] or []:
        out = (f", net {w['net_return']:+.2%} ({w['error_class']})"
               if w["net_return"] is not None else "")
        lines.append(f"- {w['date']} {w['ticker']} {w['direction']} conf {w['confidence']:.2f}: "
                     f"{w['status']}{out}")
    if not mem["working"]:
        lines.append("- none")
    lines.append("## Episodic memory (own settled trades, code-computed facts)")
    for ep in mem["episodic"][-recent:]:
        net = f"{ep['net_return']:+.2%}" if ep["net_return"] is not None else "n/a"
        lines.append(f"- {ep['ticker']} {ep['direction']} {ep['entry_date']}->{ep['exit_date']}: "
                     f"net {net}, {ep['error_class']}, MFE {ep['mfe']}, MAE {ep['mae']}, "
                     f"regime {'/'.join(ep['tags']) or 'n/a'}")
    if not mem["episodic"]:
        lines.append("- none")
    lines.append(f"## Lessons (active, matching today's regime, max {MAX_RETRIEVED})")
    for l in lessons:
        lines.append(f"- [{l['id']}] {l.get('wording') or describe(l)} | claim {l['claim']}: "
                     f"hit rate {l['hit_rate']:.0%} vs baseline {l['baseline']:.0%}, "
                     f"n={l['n']} independent, support {l['n_support']}, "
                     f"out-of-sample {l['n_oos']} at {l['oos_hit_rate']:.0%}; "
                     f"applies today to {', '.join(l['applies_to'])}")
    if not lessons:
        lines.append("- none")
    return "\n".join(lines)
