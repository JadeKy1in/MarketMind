"""Retirement of long-term shadows and their successors (docs/S7_DESIGN.md §一 退役 → 接任者).

Owner decision 2026-09-29:
- PROPOSED when the latest C.RETIRE_FAILED_CHALLENGERS decided challenger trials of a
  shadow all ended "failed" (an "insufficient" verdict is not a failure and breaks the
  run; "passed" / "approved" / "rejected" break it too) AND its mean excess return vs
  its domain ETF over the latest evaluation window (the last C.EVALUATION_PERIOD_DAYS
  matured decision days) is <= 0 (no rows with a domain excess -> not proposed).
- The owner approves (L1): `python -m marketmind.promotion retire {list,approve,reject}`.
  Approval retires the shadow AND starts its successor (one bundled decision).
- The successor takes the retired shadow's slot (domain, watchlist, benchmark, news
  keywords) under a new id "<old id>@<n>" and starts at probation. Its methodology is
  the one of the best same-group (else same domain benchmark) shadow by composite
  score, adapted to the slot by one LLM rewrite that must keep the 8-section template
  (trials.rewrite, the variant format check); without an eligible donor it starts
  from the retired shadow's own last methodology (no LLM call).
- Files: data/promotion/retirements.json (atomic), successor methodologies in
  data/promotion/successors/, events in data/promotion/events.jsonl. The roster reads
  approved proposals at runtime (roster.active / retired_ids / successor_entries).
- The retired shadow's ledger history stays and still counts in the DSR trials
  (ladder.trial_ids reads the ledger); it is no longer evaluated, ranked or an advisor.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from marketmind.promotion import config as C
from marketmind.shadows.v3 import roster as roster_mod
from marketmind.shadows.v3.roster import ACTIVE, RosterEntry

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
RANKED_STAGES = ("formal", "advisor", "paused")

SUCCESSOR_SYSTEM_PROMPT = """你负责把一个成绩较好的虚拟基金经理（影子）的方法论改写给另一个投资领域使用，作为一个被退役影子的接任者。
要求：
1. 输出完整的新方法论（Markdown，英文），保留原文全部 "## " 小节标题（8 段），顺序不变，不增不减。
2. 保留原方法论的决策方式（信号类型、入场 / 离场 / 持有期 / 确信度规则的思路）；把身份、标的、领域知识、基准换成"接任领域"给出的领域与观察清单，只能使用观察清单里的标的。
3. 不得加入编造的数据、价格或事实；不得取消"每天必须至少一笔决策"。
4. 只输出方法论正文，不要解释。"""


def _root(data_dir: str | Path | None) -> Path:
    return Path(data_dir) if data_dir is not None else Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load(data_dir: str | Path | None = None) -> dict:
    p = roster_mod.retirements_path(data_dir)
    if not p.exists():
        return {"proposals": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("proposals", [])
    return data


def save(data: dict, data_dir: str | Path | None = None) -> None:
    p = roster_mod.retirements_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def append_events(events: list[dict], data_dir: str | Path | None = None) -> None:
    if not events:
        return
    p = _root(data_dir) / "promotion" / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def successor_id(shadow_id: str) -> str:
    """"x" -> "x@2", "x@2" -> "x@3"."""
    base, _, n = shadow_id.partition("@")
    return f"{base}@{int(n) + 1 if n.isdigit() else 2}"


def _slug(shadow_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in shadow_id)


# ── Donor / reference shadow ────────────────────────────────────────────

def _score(state: dict, sid: str) -> float | None:
    rec = (state.get("shadows") or {}).get(sid) or {}
    sc = rec.get("score")
    if rec.get("stage") not in RANKED_STAGES or not isinstance(sc, dict):
        return None
    v = sc.get("score")
    return float(v) if isinstance(v, (int, float)) else None


def best_peer(shadow: RosterEntry, candidates: list[RosterEntry], state: dict, *,
              exclude: set[str] | frozenset = frozenset()
              ) -> tuple[RosterEntry | None, float | None, str | None]:
    """Best other long-term shadow by promotion composite score: same group first, else
    same domain (domain text or domain benchmark). Only ranked shadows (formal / advisor
    / paused) have a score. Returns (entry, score, "group" | "domain") or (None, None, None)."""
    pool = [(r, _score(state, r.shadow_id)) for r in candidates
            if r.shadow_id != shadow.shadow_id and r.shadow_id not in exclude
            and r.source_type == "shadow" and r.status == ACTIVE]
    pool = [(r, s) for r, s in pool if s is not None]
    for match, same in (("group", lambda r: r.group == shadow.group),
                        ("domain", lambda r: r.domain == shadow.domain
                         or r.domain_benchmark == shadow.domain_benchmark)):
        hits = [(r, s) for r, s in pool if same(r)]
        if hits:
            r, s = max(hits, key=lambda x: (x[1], x[0].shadow_id))
            return r, s, match
    return None, None, None


# ── Proposal conditions ─────────────────────────────────────────────────

def failed_challengers(shadow_id: str, trials: list) -> list | None:
    """The latest RETIRE_FAILED_CHALLENGERS decided challenger trials of the shadow when
    all of them ended "failed"; None otherwise. Running trials are not decided yet."""
    decided = sorted((t for t in trials if t.parent_id == shadow_id and t.kind == "challenger"
                      and t.status != "running"),
                     key=lambda t: (t.decided_at or t.ends, t.started, t.trial_id))
    last = decided[-C.RETIRE_FAILED_CHALLENGERS:]
    if len(last) < C.RETIRE_FAILED_CHALLENGERS or any(t.status != "failed" for t in last):
        return None
    return last


def window_excess(shadow_id: str, entries: list, today: str,
                  calendar: list[str] | None = None) -> dict:
    """Mean excess return vs the domain ETF of the shadow's matured records decided in
    its latest evaluation window (last EVALUATION_PERIOD_DAYS days of its matured window)."""
    from marketmind.promotion.ladder import default_calendar, shadow_stats
    cal = [d for d in (calendar or default_calendar(entries, today)) if d <= today]
    s = shadow_stats(shadow_id, entries, cal, today)
    days = s["window"][-C.EVALUATION_PERIOD_DAYS:]
    in_window = set(days)
    vals = [e.excess_domain for e in s["settled_rows"]
            if e.excess_domain is not None and (e.created_at or "")[:10] in in_window]
    return {"mean": (sum(vals) / len(vals)) if vals else None, "n": len(vals),
            "first_day": days[0] if days else None, "last_day": days[-1] if days else None}


def check(entries: list, roster_entries: list[RosterEntry], state: dict, today: str, *,
          trials: list, data_dir: str | Path | None = None,
          calendar: list[str] | None = None) -> list[dict]:
    """Write new pending proposals for shadows that meet the rule; returns their events.

    One open (pending) proposal per shadow. After an owner rejection a shadow is proposed
    again only when a newer failed challenger was decided after the rejection."""
    from marketmind.promotion.ladder import _event
    data = load(data_dir)
    props = data["proposals"]
    retired = {p["shadow_id"] for p in props if p.get("status") == APPROVED}
    recs = state.get("shadows") or {}
    events = []
    for r in roster_entries:
        sid = r.shadow_id
        stage = (recs.get(sid) or {}).get("stage")
        if r.source_type != "shadow" or sid in retired or stage in ("blocked", "retired"):
            continue
        mine = [p for p in props if p.get("shadow_id") == sid]
        if any(p.get("status") == PENDING for p in mine):
            continue
        failed = failed_challengers(sid, trials)
        if failed is None:
            continue
        last_reject = max((p.get("decided_at") or "" for p in mine
                           if p.get("status") == REJECTED), default="")
        if last_reject and (failed[-1].decided_at or "") <= last_reject:
            continue
        ex = window_excess(sid, entries, today, calendar)
        if ex["mean"] is None or ex["mean"] > 0:
            continue
        donor, donor_score, match = best_peer(r, roster_entries, state, exclude=retired)
        prop = {
            "shadow_id": sid, "status": PENDING, "proposed_at": today, "decided_at": None,
            "stage": stage,
            "reason": {"rule": f"last {C.RETIRE_FAILED_CHALLENGERS} challenger trials failed "
                               f"and mean excess vs domain ETF <= 0 over the latest "
                               f"{C.EVALUATION_PERIOD_DAYS}-day evaluation window",
                       "challengers": [t.trial_id for t in failed],
                       "challenger_p_holm": [(t.result or {}).get("p_holm") for t in failed],
                       "excess_domain_mean": ex["mean"], "excess_n": ex["n"],
                       "window": [ex["first_day"], ex["last_day"]],
                       "domain_benchmark": r.domain_benchmark},
            "successor": {"shadow_id": successor_id(sid),
                          "donor_id": donor.shadow_id if donor else None,
                          "donor_score": donor_score, "donor_match": match,
                          "method": "donor_rewrite" if donor else "own_methodology",
                          "prompt_file": None, "starts": "probation",
                          "probation_days": C.PROBATION_DAYS},
        }
        props.append(prop)
        events.append(_event(today, "retire_proposed", sid, stage, stage,
                             successor=prop["successor"]["shadow_id"],
                             donor=prop["successor"]["donor_id"],
                             challengers=prop["reason"]["challengers"],
                             excess_domain_mean=ex["mean"]))
    if events:
        save(data, data_dir)
    return events


# ── Owner decision ──────────────────────────────────────────────────────

def _pending(data: dict, shadow_id: str) -> dict:
    p = next((x for x in data["proposals"]
              if x.get("shadow_id") == shadow_id and x.get("status") == PENDING), None)
    if p is None:
        raise ValueError(f"no pending retirement proposal for {shadow_id}")
    return p


def _successor_user(slot: RosterEntry, donor: RosterEntry, donor_text: str,
                    own_text: str) -> str:
    return (f"## 接任领域\n\n"
            f"- display name: {slot.display_name} (successor)\n- group: {slot.group}\n"
            f"- domain: {slot.domain}\n- watchlist: {', '.join(slot.watchlist)}\n"
            f"- domain benchmark: {slot.domain_benchmark}\n"
            f"- news keywords: {', '.join(slot.news_keywords) or '(all news)'}\n"
            + (f"- notes: {slot.notes}\n" if slot.notes else "")
            + f"\n## 要改写的方法论（来自 {donor.display_name}，同组 / 同领域综合分最高）\n\n"
            f"{donor_text}\n\n"
            f"## 被退役影子的原方法论（仅作领域知识参考；它的做法成绩不佳，不要照搬）\n\n"
            f"{own_text}")


async def build_successor_prompt(slot: RosterEntry, donor: RosterEntry | None, *,
                                 call=None) -> tuple[str, str]:
    """(methodology, method). With a donor: one LLM rewrite of the donor's methodology for
    the slot, checked like a trial variant (same headings, 0.5-2x length) and for the
    8-section template. Without one: the retired shadow's own methodology, unchanged."""
    from marketmind.shadows.v3 import trials
    own = roster_mod.load_prompt(slot)
    if donor is None:
        return own, "own_methodology"
    donor_text = roster_mod.load_prompt(donor)
    text = await trials.rewrite(donor_text, SUCCESSOR_SYSTEM_PROMPT,
                                _successor_user(slot, donor, donor_text, own),
                                call or trials._call_llm)
    if len(trials.headings(text)) != C.SUCCESSOR_SECTIONS:
        raise ValueError(f"successor rejected: {len(trials.headings(text))} sections, "
                         f"expected {C.SUCCESSOR_SECTIONS}")
    return text, "donor_rewrite"


async def approve(shadow_id: str, *, data_dir: str | Path | None = None, call=None,
                  today: str | None = None) -> dict:
    """Owner approval: retire the shadow and start its successor. The successor's
    methodology is generated now (LLM only when a donor exists); nothing changes if that
    fails. The donor named in the proposal is used when it is still live; otherwise the
    successor falls back to the retired shadow's own methodology."""
    from marketmind.promotion.ladder import _event
    today = today or _today()
    data = load(data_dir)
    prop = _pending(data, shadow_id)
    live = {r.shadow_id: r for r in roster_mod.active(data_dir)}
    slot = roster_mod.by_id(data_dir).get(shadow_id)
    if slot is None:
        raise ValueError(f"{shadow_id} is not in the roster")
    succ = prop["successor"]
    donor = live.get(succ.get("donor_id") or "")
    if succ.get("donor_id") and donor is None:
        succ["donor_unavailable"] = succ["donor_id"]
    text, method = await build_successor_prompt(slot, donor, call=call)
    rel = f"successors/{_slug(succ['shadow_id'])}.md"
    path = roster_mod.retirements_path(data_dir).parent / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text.rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)
    succ.update(prompt_file=rel, method=method, started=today,
                donor_id=donor.shadow_id if donor else None)
    prop.update(status=APPROVED, decided_at=today)
    save(data, data_dir)
    append_events([
        _event(today, "retire", shadow_id, prop.get("stage"), "retired",
               successor=succ["shadow_id"]),
        _event(today, "successor_start", succ["shadow_id"], None, "probation",
               successor_of=shadow_id, donor=succ["donor_id"], method=method,
               prompt_file=rel),
    ], data_dir)
    return prop


def reject(shadow_id: str, *, data_dir: str | Path | None = None,
           today: str | None = None) -> dict:
    from marketmind.promotion.ladder import _event
    today = today or _today()
    data = load(data_dir)
    prop = _pending(data, shadow_id)
    prop.update(status=REJECTED, decided_at=today)
    save(data, data_dir)
    append_events([_event(today, "retire_rejected", shadow_id, prop.get("stage"),
                          prop.get("stage"))], data_dir)
    return prop


def summary(data_dir: str | Path | None = None) -> dict:
    """For the daily report / dashboard: pending proposals, retired shadows, successors."""
    try:
        props = load(data_dir)["proposals"]
    except (OSError, ValueError):
        return {"pending": [], "retired": [], "successors": [], "error": "unreadable"}
    approved = [p for p in props if p.get("status") == APPROVED]
    return {"pending": [p for p in props if p.get("status") == PENDING],
            "retired": [{"shadow_id": p["shadow_id"], "decided_at": p.get("decided_at"),
                         "successor": (p.get("successor") or {}).get("shadow_id")}
                        for p in approved],
            "successors": [p["successor"] for p in approved if p.get("successor")]}
