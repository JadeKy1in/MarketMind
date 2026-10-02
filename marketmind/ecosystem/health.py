"""Shadow-ecosystem health checks (docs/ECOSYSTEM_DESIGN.md). Pure functions, no I/O.

Rebuilt on the unified ledger from the deleted legacy detectors (collusion /
concentration, diversity, plateau, zombie, ecosystem_health). Input is the ledger
rows plus a few facts the runner loads (roster ids, retirements, trials, trend
states); output is one JSON-ready dict. Monitoring only: nothing here changes a
decision, a promotion or an alert.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import numpy as np
from scipy import stats

from marketmind.alerts.asset_groups import asset_group
from marketmind.ecosystem import config as C
from marketmind.ledger.store import LedgerEntry, is_comparison

NEW_YORK = ZoneInfo("America/New_York")
SIGN = {"long": 1, "short": -1}


# ── Population ──────────────────────────────────────────────────────────

def day_of(e: LedgerEntry) -> str:
    """The run day of a record: meta.run_date, else the New York date of created_at."""
    rd = (e.meta or {}).get("run_date")
    if rd:
        return str(rd)[:10]
    try:
        ts = datetime.fromisoformat((e.created_at or "").replace("Z", "+00:00"))
    except ValueError:
        return (e.created_at or "")[:10]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(NEW_YORK).date().isoformat()


def is_actor(e: LedgerEntry) -> bool:
    return e.source_type in C.SOURCE_TYPES and not e.source_id.startswith(C.NON_ACTOR_PREFIXES)


def is_voter(e: LedgerEntry) -> bool:
    return is_actor(e) and not e.source_id.startswith(C.NON_VOTER_PREFIXES)


@dataclass
class Facts:
    """What the runner knows besides the ledger (all optional for tests)."""
    active_ids: set[str] = field(default_factory=set)        # roster.active()
    roster_ids: set[str] = field(default_factory=set)        # roster.all_entries()
    retired: dict[str, str] = field(default_factory=dict)    # shadow id -> approval date
    successor_start: dict[str, str] = field(default_factory=dict)  # successor id -> approval date
    trial_parent: dict[str, str] | None = None                # "trial:<id>" -> parent id; None = unknown
    playground_ids: set[str] | None = None                   # "playground:<id>"; None = unknown
    trend_by_day: dict[str, dict[str, str]] = field(default_factory=dict)  # day -> ticker -> state


def full_run_days(rows: list[LedgerEntry], n_active: int) -> list[str]:
    """Days on which >= FULL_RUN_SHARE of the active long-term shadows submitted
    (weekend crypto-only runs drop out); the last LOOKBACK_RUN_DAYS of them."""
    per_day: dict[str, set[str]] = defaultdict(set)
    for e in rows:
        if e.source_type == "shadow":
            per_day[day_of(e)].add(e.source_id)
    need = max(1, math.ceil(C.FULL_RUN_SHARE * n_active)) if n_active else 1
    days = sorted(d for d, ids in per_day.items() if len(ids) >= need)
    return days[-C.LOOKBACK_RUN_DAYS:]


def family(sid: str, trial_parent: dict[str, str] | None) -> str:
    """Lineage key: a trial variant and a successor ("x@2") belong to their parent."""
    if trial_parent and sid in trial_parent:
        sid = trial_parent[sid]
    return sid.split("@", 1)[0]


# ── Statistics helpers ──────────────────────────────────────────────────

def binom_two_sided(k: int, n: int) -> float:
    """P(the dominant side has >= k of n votes) under independent 50/50 votes."""
    if n <= 0:
        return 1.0
    return float(min(1.0, 2.0 * stats.binom.sf(k - 1, n, 0.5)))


def entropy_bits(counts) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    return float(-sum(c / total * math.log2(c / total) for c in counts if c > 0))


def mann_kendall(values: list[float]) -> dict:
    """Mann-Kendall trend test (normal approximation, tie-corrected variance,
    continuity correction). tau = S / (n(n-1)/2)."""
    x = [float(v) for v in values if v is not None and np.isfinite(v)]
    n = len(x)
    if n < C.MK_MIN_POINTS:
        return {"n": n, "trend": "insufficient", "tau": None, "z": None, "p": None}
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (x[j] > x[i]) - (x[j] < x[i])
    ties = Counter(x).values()
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18.0
    if var <= 0:
        return {"n": n, "trend": "no trend", "tau": 0.0, "z": 0.0, "p": 1.0}
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    p = float(2 * stats.norm.sf(abs(z)))
    trend = "no trend" if p > C.MK_ALPHA else ("increasing" if z > 0 else "decreasing")
    return {"n": n, "trend": trend, "tau": round(s / (n * (n - 1) / 2), 4),
            "z": round(z, 4), "p": round(p, 6)}


def participation_ratio(mat: np.ndarray) -> float:
    """Eigenvalue-based effective number of independent series:
    (sum lambda)^2 / sum lambda^2 = N^2 / ||R||_F^2 for a correlation matrix R."""
    n = mat.shape[0]
    denom = float((mat ** 2).sum())
    return n * n / denom if denom > 0 else float(n)


def _clusters(ids: list[str], pairs: list[tuple[str, str]]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in pairs:
        parent[find(a)] = find(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)
    return sorted(sorted(g) for g in groups.values() if len(g) > 1)


# ── 1. Herding ──────────────────────────────────────────────────────────

def group_trend_state(states: dict[str, str] | None, group: str) -> str | None:
    """TREND if any member of the group is in TREND; CASH if every available member is
    CASH / EXIT; WATCH for anything else; None when the trend file has no member."""
    if not states:
        return None
    s = {st for t, st in states.items() if asset_group(t) == group and st and st != "UNAVAILABLE"}
    if not s:
        return None
    if "TREND" in s:
        return "TREND"
    if s <= {"CASH", "EXIT"}:
        return "CASH"
    return "WATCH"


def herding_verdict(direction: str, state: str | None) -> str:
    if state is None:
        return "unclassified"
    if (direction == "long" and state == "TREND") or (direction == "short" and state == "CASH"):
        return "market_driven"
    return "behavioural"


def check_herding(rows: list[LedgerEntry], run_days: list[str], facts: Facts) -> dict:
    votes: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    book: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    days = set(run_days)
    for e in rows:
        d = day_of(e)
        if d in days and is_voter(e):
            votes[d][asset_group(e.ticker)][e.source_id] += SIGN[e.direction]
            book[d][e.source_id] += SIGN[e.direction]

    groups = sorted({g for d in votes for g in votes[d]})
    today = run_days[-1] if run_days else None
    flags, episodes, today_rows = [], [], []
    for g in groups:
        streak: list[dict] = []
        for d in run_days:
            net = [v for v in votes[d].get(g, {}).values() if v]
            n = len(net)
            longs = sum(1 for v in net if v > 0)
            k, direction = (longs, "long") if longs >= n - longs else (n - longs, "short")
            share = k / n if n else 0.0
            state = group_trend_state(facts.trend_by_day.get(d), g)
            day_row = {"day": d, "n": n, "share": round(share, 3), "direction": direction,
                       "p": round(binom_two_sided(k, n), 6), "trend_state": state,
                       "verdict": herding_verdict(direction, state)}
            concentrated = n >= C.HERDING_MIN_VOTERS and share >= C.HERDING_SHARE
            if concentrated and streak and streak[-1]["direction"] == direction:
                streak.append(day_row)
            elif concentrated:
                if streak:
                    _close_episode(g, streak, episodes)
                streak = [day_row]
            else:
                if streak:
                    _close_episode(g, streak, episodes)
                streak = []
            if d == today and n:
                today_rows.append({"group": g, **{k2: day_row[k2] for k2 in
                                                  ("n", "share", "direction", "trend_state", "verdict")},
                                   "concentrated": concentrated})
        if streak:
            ep = _close_episode(g, streak, episodes)
            if ep and streak[-1]["day"] == today:
                flags.append(ep)
    long_share = []
    for d in run_days:
        net = [v for v in book[d].values() if v]
        long_share.append({"day": d, "n": len(net),
                           "long_share": round(sum(1 for v in net if v > 0) / len(net), 3) if net else None})
    today_rows.sort(key=lambda r: (-r["n"], r["group"]))
    return {"flags": flags, "episodes": episodes, "today": today_rows,
            "ecosystem_long_share": long_share,
            "note": "votes = each shadow's net direction per asset group per full run day; "
                    "trial variants and missed_path excluded"}


def _close_episode(group: str, streak: list[dict], episodes: list[dict]) -> dict | None:
    if len(streak) < C.HERDING_DAYS:
        return None
    joint_p = float(np.prod([r["p"] for r in streak]))
    if joint_p > C.HERDING_MAX_JOINT_P:
        return None
    verdicts = Counter(r["verdict"] for r in streak if r["verdict"] != "unclassified")
    if not verdicts:
        verdict = "unclassified"
    else:
        verdict = "market_driven" if verdicts["market_driven"] > verdicts["behavioural"] else "behavioural"
    ep = {"group": group, "direction": streak[-1]["direction"], "days": len(streak),
          "start": streak[0]["day"], "end": streak[-1]["day"],
          "min_share": min(r["share"] for r in streak), "min_voters": min(r["n"] for r in streak),
          "joint_p": joint_p, "verdict": verdict,
          "escalate": len(streak) >= C.HERDING_ESCALATE_DAYS,
          "daily": [{k: r[k] for k in ("day", "n", "share", "trend_state", "verdict")} for r in streak]}
    episodes.append(ep)
    return ep


# ── 2. Output correlation / diversity ──────────────────────────────────

def pnl_series(rows: list[LedgerEntry], calendar: list[str], today: str) -> dict[str, dict[str, float]]:
    """Per actor: {day: sum(pnl_usd on exit day) / notional} over the actor's live span
    (first decision day .. today) on the trading calendar, zero on days without exits."""
    first: dict[str, str] = {}
    pnl: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in rows:
        if not is_actor(e):
            continue
        d = day_of(e)
        first[e.source_id] = min(first.get(e.source_id, d), d)
        if e.status == "settled" and e.exit_date and e.pnl_usd is not None and e.exit_date[:10] <= today:
            pnl[e.source_id][e.exit_date[:10]] += e.pnl_usd / C.NOTIONAL_USD
    return {sid: {d: pnl[sid].get(d, 0.0) for d in calendar if start <= d <= today}
            for sid, start in first.items()}


def _pair_corr(a: dict[str, float], b: dict[str, float]) -> tuple[float | None, int]:
    common = sorted(a.keys() & b.keys())
    if len(common) < C.DUP_MIN_DAYS:
        return None, len(common)
    x = np.array([a[d] for d in common])
    y = np.array([b[d] for d in common])
    if x.std() == 0 or y.std() == 0:
        return None, len(common)
    return float(np.corrcoef(x, y)[0, 1]), len(common)


def check_pnl_diversity(series: dict[str, dict[str, float]], facts: Facts) -> dict:
    ids = sorted(s for s, m in series.items()
                 if len(m) >= C.DUP_MIN_DAYS and np.std(list(m.values())) > 0)
    n = len(ids)
    out = {"eligible": n, "actors": len(series), "n_eff": None, "mean_abs_rho": None,
           "pairs_high": [], "clusters": []}
    if n < 2:
        out["note"] = (f"needs >= 2 actors with >= {C.DUP_MIN_DAYS} days of settled P&L "
                       "and non-zero variance")
        return out
    mat = np.eye(n)
    rhos, dup = [], []
    for i, j in combinations(range(n), 2):
        rho, days = _pair_corr(series[ids[i]], series[ids[j]])
        if rho is None:
            continue
        mat[i, j] = mat[j, i] = rho
        rhos.append(abs(rho))
        if rho >= C.DUP_CORR:
            dup.append((ids[i], ids[j]))
            out["pairs_high"].append({"a": ids[i], "b": ids[j], "rho": round(rho, 3), "days": days,
                                      "expected": family(ids[i], facts.trial_parent)
                                      == family(ids[j], facts.trial_parent)})
    out["n_eff"] = round(participation_ratio(mat), 2)
    out["mean_abs_rho"] = round(float(np.mean(rhos)), 3) if rhos else None
    out["clusters"] = _label_clusters(_clusters(ids, dup), facts)
    return out


def direction_vectors(rows: list[LedgerEntry], run_days: list[str]) -> dict[str, dict[str, dict[str, int]]]:
    """Per actor, per full run day: {asset group: net direction sign}."""
    days = set(run_days)
    raw: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for e in rows:
        d = day_of(e)
        if d in days and is_actor(e):
            raw[e.source_id][d][asset_group(e.ticker)] += SIGN[e.direction]
    return {sid: {d: {g: int(np.sign(v)) for g, v in cells.items()} for d, cells in by_day.items()}
            for sid, by_day in raw.items()}


def _cosine(a: dict[str, dict[str, int]], b: dict[str, dict[str, int]], common: list[str]) -> tuple[float, int]:
    dot = na = nb = both = 0
    for d in common:
        ca, cb = a[d], b[d]
        for g in ca.keys() | cb.keys():
            x, y = ca.get(g, 0), cb.get(g, 0)
            dot += x * y
            na += x * x
            nb += y * y
            both += bool(x and y)
    return (dot / math.sqrt(na * nb) if na and nb else 0.0), both


def check_direction_diversity(vectors: dict[str, dict[str, dict[str, int]]], facts: Facts) -> dict:
    ids = sorted(s for s, v in vectors.items() if len(v) >= C.DIRECTION_MIN_DAYS)
    n = len(ids)
    out = {"eligible": n, "actors": len(vectors), "n_eff": None, "pairs_high": [], "clusters": []}
    if n < 2:
        out["note"] = f"needs >= 2 actors with >= {C.DIRECTION_MIN_DAYS} full run days of decisions"
        return out
    mat = np.eye(n)
    dup = []
    for i, j in combinations(range(n), 2):
        common = sorted(vectors[ids[i]].keys() & vectors[ids[j]].keys())
        if len(common) < C.DIRECTION_MIN_DAYS:
            continue
        cos, both = _cosine(vectors[ids[i]], vectors[ids[j]], common)
        mat[i, j] = mat[j, i] = cos
        if cos >= C.DIRECTION_DUP_COS and both >= C.DIRECTION_DUP_MIN_CELLS:
            dup.append((ids[i], ids[j]))
            out["pairs_high"].append({"a": ids[i], "b": ids[j], "cosine": round(cos, 3), "cells": both,
                                      "expected": family(ids[i], facts.trial_parent)
                                      == family(ids[j], facts.trial_parent)})
    out["n_eff"] = round(participation_ratio(mat), 2)
    out["clusters"] = _label_clusters(_clusters(ids, dup), facts)
    return out


def _label_clusters(clusters: list[list[str]], facts: Facts) -> list[dict]:
    return [{"members": c, "expected": len({family(s, facts.trial_parent) for s in c}) == 1}
            for c in clusters]


# ── 3. Source homogenisation ────────────────────────────────────────────

NEWS_NOT_RECORDED = {
    "status": "not_recorded",
    "detail": "the ledger, record meta and data/shadows/v3_runs/<day>.json do not say which "
              "headlines (or news sources) a shadow saw or cited; data/news/<day>.json keeps only "
              "the day's top-40 headlines, not each shadow's keyword-filtered set",
    "needed": "meta.news_sources: source_name of each headline in the shadow's context "
              "(shadows/v3/context.filter_news output), written at decision time; optionally a "
              "decision-level 'cites' list of headline indices",
}


def _dominant(counter: Counter) -> str | None:
    if not counter:
        return None
    top = max(counter.values())
    return sorted(k for k, v in counter.items() if v == top)[0]


def check_homogenisation(rows: list[LedgerEntry], run_days: list[str]) -> dict:
    window = set(run_days[-C.HOMOGEN_WINDOW_DAYS:])
    by_actor_group: dict[str, Counter] = defaultdict(Counter)
    by_actor_ticker: dict[str, Counter] = defaultdict(Counter)
    by_actor_llm: dict[str, Counter] = defaultdict(Counter)
    by_actor_news: dict[str, Counter] = defaultdict(Counter)     # meta.news_sources (2026-09-29+)
    for e in rows:
        if day_of(e) in window and is_voter(e):
            by_actor_group[e.source_id][asset_group(e.ticker)] += 1
            by_actor_ticker[e.source_id][e.ticker] += 1
            llm = (e.meta or {}).get("llm")      # meta.model is the tier ("flash"), not the LLM
            if llm:
                by_actor_llm[e.source_id][str(llm)] += 1
            for src in (e.meta or {}).get("news_sources") or []:
                by_actor_news[e.source_id][str(src)] += 1

    def share(per_actor: dict[str, Counter], label: str) -> dict:
        dom = Counter(d for d in (_dominant(c) for c in per_actor.values()) if d)
        n = len(per_actor)
        if not dom:
            return {"dimension": label, "actors": n, "top": None, "share": None, "flag": False}
        top, k = max(dom.items(), key=lambda kv: (kv[1], kv[0]))
        return {"dimension": label, "actors": n, "top": top, "count": k,
                "share": round(k / n, 3), "flag": n >= 2 and k / n >= C.HOMOGEN_SHARE}

    sets = [set(c) for c in by_actor_ticker.values()]
    jac = [len(a & b) / len(a | b) for a, b in combinations(sets, 2) if a | b]
    if by_actor_news:
        nsets = [set(c) for c in by_actor_news.values()]
        njac = [len(a & b) / len(a | b) for a, b in combinations(nsets, 2) if a | b]
        news = {"status": "recorded", **share(by_actor_news, "news source (meta.news_sources)"),
                "mean_source_jaccard": round(float(np.mean(njac)), 3) if njac else None}
    else:
        news = NEWS_NOT_RECORDED
    return {"window_days": len(window),
            "dominant_group": share(by_actor_group, "asset group"),
            "dominant_ticker": share(by_actor_ticker, "ticker"),
            "llm": share(by_actor_llm, "llm (meta.llm)"),
            "mean_ticker_jaccard": round(float(np.mean(jac)), 3) if jac else None,
            "news_source": news}


# ── 4. Stagnation / plateau ─────────────────────────────────────────────

def check_stagnation(rows: list[LedgerEntry]) -> dict:
    by_actor: dict[str, dict[str, list[LedgerEntry]]] = defaultdict(lambda: defaultdict(list))
    for e in rows:
        if is_voter(e):
            by_actor[e.source_id][day_of(e)].append(e)
    flags, insufficient = [], {}
    for sid in sorted(by_actor):
        days = sorted(by_actor[sid])
        if len(days) < C.REPETITION_MIN_DAYS:
            insufficient[sid] = len(days)
            continue
        recent = days[-C.PLATEAU_DAYS:]
        recs = [e for d in recent for e in by_actor[sid][d]]
        pairs = Counter((e.ticker, e.direction) for e in recs)
        (top_t, top_d), top_n = max(pairs.items(), key=lambda kv: (kv[1], kv[0]))
        rep = top_n / len(recs)
        if rep > C.REPETITION_SHARE:
            flags.append({"shadow_id": sid, "kind": "repetition", "days": len(recent),
                          "top": f"{top_t} {top_d}", "share": round(rep, 3)})
        if len(days) < C.PLATEAU_DAYS:
            insufficient[sid] = len(days)
            continue
        half = C.PLATEAU_DAYS // 2
        a = [e for d in recent[:half] for e in by_actor[sid][d]]
        b = [e for d in recent[half:] for e in by_actor[sid][d]]
        ta, tb = {e.ticker for e in a}, {e.ticker for e in b}
        jac = len(ta & tb) / len(ta | tb) if ta | tb else 1.0
        shift = abs(np.mean([e.confidence for e in a]) - np.mean([e.confidence for e in b]))
        std = float(np.std([e.confidence for e in recs]))
        if jac >= C.PLATEAU_JACCARD and shift <= C.PLATEAU_CONF_SHIFT and std <= C.PLATEAU_CONF_STD:
            flags.append({"shadow_id": sid, "kind": "plateau", "days": len(recent),
                          "ticker_jaccard": round(jac, 3), "conf_shift": round(float(shift), 4),
                          "conf_std": round(std, 4)})
    return {"flags": flags, "insufficient": insufficient,
            "note": f"plateau needs {C.PLATEAU_DAYS} decision days, repetition {C.REPETITION_MIN_DAYS}"}


# ── 5. Zombies / integrity ──────────────────────────────────────────────

def check_integrity(rows: list[LedgerEntry], run_days: list[str], facts: Facts) -> dict:
    seen: dict[str, set[str]] = defaultdict(set)
    last: dict[tuple[str, str], str] = {}
    count: Counter = Counter()
    for e in rows:
        d = day_of(e)
        seen[e.source_id].add(d)
        key = (e.source_type, e.source_id)
        last[key] = max(last.get(key, d), d)
        count[key] += 1

    zombies = []
    for sid in sorted(facts.active_ids):
        start = facts.successor_start.get(sid, "")
        days = [d for d in run_days if d > start] if start else list(run_days)
        silent = 0
        for d in reversed(days):
            if d in seen.get(sid, ()):
                break
            silent += 1
        if silent >= C.ZOMBIE_RUN_DAYS:
            zombies.append({"shadow_id": sid, "silent_run_days": silent,
                            "last_seen": max(seen[sid]) if seen.get(sid) else None})

    orphans = []
    for (stype, sid), n in sorted(count.items()):
        reason = None
        if stype == "shadow" and facts.roster_ids and sid not in facts.roster_ids:
            reason = "not in roster.all_entries()"
        elif stype == "playground" and facts.playground_ids is not None and sid not in facts.playground_ids:
            reason = "no Playground manifest"
        elif stype == "temp_shadow":
            if not sid.startswith(C.KNOWN_TEMP_PREFIXES):
                reason = "unknown temporary-shadow type"
            elif sid.startswith("trial:") and facts.trial_parent is not None and sid not in facts.trial_parent:
                reason = "trial not in trials.json"
        if reason:
            orphans.append({"source_type": stype, "source_id": sid, "records": n,
                            "last_day": last[(stype, sid)], "reason": reason})

    retired_submitting = []
    for sid, since in sorted(facts.retired.items()):
        after = sorted(d for d in seen.get(sid, ()) if since and d > since)
        if after:
            retired_submitting.append({"shadow_id": sid, "retired_on": since,
                                       "days_after": len(after), "last_day": after[-1]})
    return {"zombies": zombies, "orphans": orphans, "retired_submitting": retired_submitting,
            "active": len(facts.active_ids), "run_days_checked": len(run_days)}


# ── 6. Whole-ecosystem degradation trend ────────────────────────────────

def entropy_series(rows: list[LedgerEntry], run_days: list[str]) -> list[dict]:
    days = set(run_days)
    dirs: dict[str, Counter] = defaultdict(Counter)
    cells: dict[str, Counter] = defaultdict(Counter)
    for e in rows:
        d = day_of(e)
        if d in days and is_voter(e):
            dirs[d][e.direction] += 1
            cells[d][(asset_group(e.ticker), e.direction)] += 1
    out = []
    for d in run_days:
        n = sum(cells[d].values())
        out.append({"day": d, "records": n,
                    "direction_entropy": round(entropy_bits(dirs[d].values()), 4),
                    "spread": round(entropy_bits(cells[d].values()) / math.log2(n), 4) if n > 1 else None})
    return out


def beat_random_series(entries: list[LedgerEntry], calendar: list[str], today: str) -> list[dict]:
    """Share of shadows whose mean net return beats their own random baseline
    (benchmark `random:<shadow id>`) over rolling windows of exit dates."""
    net: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for e in entries:
        if e.status != "settled" or e.net_return is None or not e.exit_date or e.exit_date[:10] > today:
            continue
        if e.source_type in ("shadow", "playground"):
            net[e.source_id].append((e.exit_date[:10], e.net_return))
        elif e.source_type == "benchmark" and e.source_id.startswith("random:"):
            net[e.source_id].append((e.exit_date[:10], e.net_return))
    shadows = sorted(s for s in net if not s.startswith("random:") and f"random:{s}" in net)
    cal = [d for d in calendar if d <= today]
    out = []
    for end in range(len(cal) - 1, C.BEAT_WINDOW_DAYS - 2, -C.BEAT_STEP_DAYS):
        lo, hi = cal[end - C.BEAT_WINDOW_DAYS + 1], cal[end]
        beats = eligible = 0
        for s in shadows:
            a = [r for d, r in net[s] if lo <= d <= hi]
            b = [r for d, r in net[f"random:{s}"] if lo <= d <= hi]
            if len(a) >= C.BEAT_MIN_TRADES and len(b) >= C.BEAT_MIN_TRADES:
                eligible += 1
                beats += float(np.mean(a)) > float(np.mean(b))
        if eligible >= C.BEAT_MIN_ELIGIBLE:
            out.append({"window_end": hi, "eligible": eligible, "share": round(beats / eligible, 3)})
    return list(reversed(out))


def check_degradation(entries: list[LedgerEntry], rows: list[LedgerEntry], run_days: list[str],
                      calendar: list[str], today: str) -> dict:
    ent = entropy_series(rows, run_days)
    beat = beat_random_series(entries, calendar, today)
    return {"entropy": ent,
            "direction_entropy_trend": mann_kendall([r["direction_entropy"] for r in ent if r["records"]]),
            "spread_trend": mann_kendall([r["spread"] for r in ent if r["spread"] is not None]),
            "beat_random": beat,
            "beat_random_trend": mann_kendall([r["share"] for r in beat]),
            "note": "reported, not acted on; rolling windows overlap, so the Mann-Kendall p "
                    "is optimistic"}


# ── Everything ──────────────────────────────────────────────────────────

def trading_calendar(entries: list[LedgerEntry], rows: list[LedgerEntry], today: str) -> list[str]:
    """Exit dates of settled rows (any source but comparison-only baselines) plus the
    actors' decision days, <= today."""
    days = {e.exit_date[:10] for e in entries
            if e.status == "settled" and e.exit_date and not is_comparison(e)}
    days |= {day_of(e) for e in rows}
    return sorted(d for d in days if d and d <= today)


def evaluate(entries: list[LedgerEntry], today: str, facts: Facts | None = None) -> dict:
    facts = facts or Facts()
    rows = [e for e in entries if e.source_type in C.SOURCE_TYPES and day_of(e) <= today]
    actor_rows = [e for e in rows if is_actor(e)]
    n_active = sum(1 for s in facts.active_ids if not s.startswith("playground:"))
    run_days = full_run_days(rows, n_active)
    calendar = trading_calendar(entries, actor_rows, today)
    herding = check_herding(actor_rows, run_days, facts)
    pnl = check_pnl_diversity(pnl_series(actor_rows, calendar, today), facts)
    direction = check_direction_diversity(direction_vectors(actor_rows, run_days), facts)
    return {
        "date": today,
        "population": {"records": len(rows), "actor_records": len(actor_rows),
                       "actors": len({e.source_id for e in actor_rows}),
                       "full_run_days": len(run_days),
                       "first_run_day": run_days[0] if run_days else None,
                       "last_run_day": run_days[-1] if run_days else None},
        "herding": herding,
        "diversity": {"pnl": pnl, "direction": direction},
        "homogenisation": check_homogenisation(actor_rows, run_days),
        "stagnation": check_stagnation(actor_rows),
        "integrity": check_integrity(rows, run_days, facts),
        "degradation": check_degradation(entries, actor_rows, run_days, calendar, today),
    }


def summary_line(doc: dict) -> str:
    flags = doc["herding"]["flags"]
    if flags:
        parts = [f"{f['group']} {f['direction']} {f['days']}d {f['verdict']}" for f in flags[:3]]
        herd = "; ".join(parts) + (f" +{len(flags) - 3}" if len(flags) > 3 else "")
    else:
        herd = "none"
    pnl = doc["diversity"]["pnl"]
    neff = (f"{pnl['n_eff']:.1f}/{pnl['eligible']}" if pnl["n_eff"] is not None
            else f"n/a ({pnl['eligible']} eligible)")
    dup = sum(1 for c in doc["diversity"]["pnl"]["clusters"] + doc["diversity"]["direction"]["clusters"]
              if not c["expected"])
    integ = doc["integrity"]
    extra = []
    if integ["orphans"]:
        extra.append(f"orphans {len(integ['orphans'])}")
    if integ["retired_submitting"]:
        extra.append(f"retired submitting {len(integ['retired_submitting'])}")
    hom = doc["homogenisation"]
    hflags = [f"{h['top']} {h['share']:.0%}" for h in (hom["dominant_group"], hom["llm"]) if h["flag"]]
    if hflags:
        extra.append("homogenised: " + ", ".join(hflags))
    stag = doc["stagnation"]["flags"]
    if stag:
        extra.append(f"stagnant {len(stag)}")
    return (f"[ecosystem] herding: {herd}, N_eff {neff}, dup clusters {dup}, "
            f"zombies {len(integ['zombies'])}" + (", " + ", ".join(extra) if extra else ""))
