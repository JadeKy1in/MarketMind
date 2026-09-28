"""Promotion stage machine (docs/S7_DESIGN.md §一, SPEC_v3 §8, C03 / C04 / C20 / C30).

    probation -> formal -> advisor -> (CUSUM alarm) paused -> formal (no tenure)
    blocked: roster shadow that is not live (status != active or no prompt)

`evaluate` is pure: it takes ledger rows and the previous state and returns the
new state plus the events of this run. Re-running on the same day with the same
ledger yields the same state and no new events.

Per-shadow series:
- trading calendar = union of exit dates of settled rows across all sources (<= today),
  or an explicit calendar;
- a shadow's daily window runs from its first decision date to today;
- Sharpe / skew / kurtosis / MinTRL for the probation gate use per-trade net returns,
  because N_eff counts independent trades; DSR, MPPM, Calmar, Omega, PBO, CUSUM and the
  stress test use the daily return series.
"""
from __future__ import annotations

import math
from statistics import mean

import numpy as np

from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C
from marketmind.promotion import metrics as M
from marketmind.shadows.v3.roster import ACTIVE, RosterEntry

MAIN_SOURCES = ("main", "main_forced")


def _day(ts: str | None) -> str | None:
    return ts[:10] if ts else None


def _clean(v):
    """JSON-safe numbers: non-finite floats become 'inf' / '-inf' / None."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return round(v, 8)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _settled_mean(rows: list[LedgerEntry], lo: str | None, hi: str | None) -> float | None:
    vals = [e.net_return for e in rows
            if e.status == "settled" and e.net_return is not None and e.exit_date
            and (lo is None or _day(e.exit_date) >= lo) and (hi is None or _day(e.exit_date) <= hi)]
    return mean(vals) if vals else None


def _days_after(calendar: list[str], start: str, end: str) -> list[str]:
    return [d for d in calendar if start < d <= end]


# ── Per-shadow statistics ───────────────────────────────────────────────

def shadow_stats(sid: str, entries: list[LedgerEntry], calendar: list[str], today: str) -> dict:
    """Everything the gates and the composite score need for one shadow."""
    rows = [e for e in entries if e.source_type == "shadow" and e.source_id == sid
            and e.created_at and _day(e.created_at) <= today]
    settled = [e for e in rows if e.status == "settled" and e.exit_date
               and _day(e.exit_date) <= today and e.net_return is not None]
    record_days = sorted({_day(e.created_at) for e in rows})
    first = record_days[0] if record_days else None
    window = [d for d in calendar if first and first <= d <= today]
    series = M.daily_series(M.daily_pnl(settled), window)
    market = M.daily_series(M.daily_market(settled), window)

    trade_r = np.array([e.net_return for e in settled], dtype=float)
    sr_trade = M.sharpe(trade_r)
    g3, g4 = M.skew_kurt(trade_r)
    mean_hold = mean(e.hold_bars for e in settled) if settled else 0.0
    exits = sorted(_day(e.exit_date) for e in settled)
    lo, hi = (exits[0], exits[-1]) if exits else (None, None)

    bench = [e for e in entries if e.source_type == "benchmark"
             and e.source_id == f"random:{sid}"]
    main = [e for e in entries if e.source_type in MAIN_SOURCES]
    excess_dom = [e.excess_domain for e in settled if e.excess_domain is not None]
    briers = [e.brier for e in settled if e.brier is not None]
    return {
        "records": len(rows), "record_days": len(record_days), "first_day": first,
        "settled": len(settled), "series": series, "market": market, "window": window,
        "sharpe_trade": sr_trade, "skew": g3, "kurtosis": g4,
        "min_trl": M.min_trl(sr_trade, g3, g4, C.MINTRL_BENCHMARK_SHARPE,
                              C.MINTRL_CONFIDENCE) if trade_r.size >= 2 else math.inf,
        "n_eff": M.n_eff(len(settled), len(window), mean_hold),
        "mean_net": float(trade_r.mean()) if trade_r.size else None,
        "random_mean_net": _settled_mean(bench, lo, hi),
        "main_mean_net": _settled_mean(main, lo, hi),
        "mean_excess_domain": mean(excess_dom) if excess_dom else None,
        "mean_brier": mean(briers) if briers else None,
        "win_rate": float(np.mean(trade_r > 0)) if trade_r.size else 0.0,
        "min_position_share": (sum(1 for e in rows if e.position_usd <= C.MIN_POSITION_USD)
                               / len(rows)) if rows else 0.0,
        "sharpe_daily": M.sharpe(series),
        "mppm": M.mppm(series, C.MPPM_RHO), "calmar": M.calmar(series),
        "omega": M.omega(series, C.OMEGA_THRESHOLD),
        "max_drawdown": M.max_drawdown(series),
    }


def probation_gates(s: dict) -> dict[str, bool]:
    """Probation -> formal: every gate must pass (S7 §一 阶段与门槛)."""
    mn = s["mean_net"]
    return {
        "days": s["record_days"] >= C.PROBATION_DAYS,
        "min_trl": s["n_eff"] >= s["min_trl"],
        "beat_random": mn is not None and s["random_mean_net"] is not None
                       and mn > s["random_mean_net"],
        "beat_domain": s["mean_excess_domain"] is not None and s["mean_excess_domain"] > 0,
        "beat_main": mn is not None and s["main_mean_net"] is not None
                     and mn > s["main_mean_net"],
    }


# ── Composite score ─────────────────────────────────────────────────────

def composite_scores(stats_by_id: dict[str, dict]) -> dict[str, dict]:
    """Percentile-rank each component among the given (formal) shadows, weight, shrink
    toward the group mean with n / (n + k), then apply the minimum-position haircut."""
    ids = sorted(stats_by_id)
    if not ids:
        return {}
    raw = {sid: 0.0 for sid in ids}
    for comp, w in C.SCORE_WEIGHTS.items():
        for sid, p in zip(ids, M.percentile_ranks([stats_by_id[s][comp] for s in ids])):
            raw[sid] += w * p
    prior = mean(raw.values())
    out = {}
    for sid in ids:
        s = stats_by_id[sid]
        shrunk = M.shrink(raw[sid], s["settled"], prior, C.SHRINKAGE_K)
        haircut = s["min_position_share"] > C.MIN_POSITION_SHARE_LIMIT
        out[sid] = {"raw": raw[sid], "shrunk": shrunk, "haircut": haircut,
                    "score": shrunk * (C.MIN_POSITION_HAIRCUT if haircut else 1.0)}
    return out


def tiers(scores: dict[str, float]) -> dict[str, int | None]:
    """Tier1 = top 20%, Tier2 = top 50% (ceil, so one shadow alone is Tier1)."""
    order = sorted(scores, key=lambda s: (-scores[s], s))
    n = len(order)
    t1, t2 = math.ceil(C.TIER1_TOP_SHARE * n), math.ceil(C.TIER2_TOP_SHARE * n)
    return {sid: (1 if i < t1 else 2 if i < t2 else None) for i, sid in enumerate(order)}


def bottom(scores: dict[str, float]) -> set[str]:
    """Bottom 20% (floor, so fewer than 5 ranked shadows have no bottom group)."""
    order = sorted(scores, key=lambda s: (scores[s], s))
    return set(order[:math.floor(C.BOTTOM_SHARE * len(order))])


# ── Stage machine ───────────────────────────────────────────────────────

def _new_record(today: str) -> dict:
    return {"stage": "probation", "since": today, "formal_since": None, "advisor_since": None,
            "paused_on": None, "bottom_streak": 0}


def _event(today, kind, sid, frm, to, **detail) -> dict:
    return {"date": today, "type": kind, "shadow_id": sid, "from": frm, "to": to,
            "detail": _clean(detail)}


def evaluate(entries: list[LedgerEntry], roster_entries: list[RosterEntry], today: str,
             state: dict | None, trial_count: int, *, calendar: list[str] | None = None,
             active_ids: set[str] | None = None) -> tuple[dict, list[dict]]:
    """Run one day of the ladder. Returns (new_state, events).

    `active_ids` defaults to roster shadows with status active and a prompt file.
    `trial_count` is the number of trials for the DSR (see runner)."""
    state = dict(state or {})
    prev = state.get("shadows", {})
    period = dict(state.get("period") or {"start": None, "index": 0})
    cal = sorted(d for d in (calendar if calendar is not None
                             else M.trading_calendar(entries, until=today)) if d <= today)
    if active_ids is None:
        active_ids = {r.shadow_id for r in roster_entries
                      if r.status == ACTIVE and r.prompt_path.exists()}
    events: list[dict] = []
    recs: dict[str, dict] = {}
    stats: dict[str, dict] = {}

    for r in roster_entries:
        rec = {**_new_record(today), **prev.get(r.shadow_id, {})}
        if r.shadow_id not in active_ids:
            if rec["stage"] != "blocked":
                rec["resume_stage"] = rec["stage"]
                rec["stage"] = "blocked"
            recs[r.shadow_id] = rec
            continue
        if rec["stage"] == "blocked":
            rec["stage"] = rec.pop("resume_stage", None) or "probation"
        recs[r.shadow_id] = rec
        stats[r.shadow_id] = shadow_stats(r.shadow_id, entries, cal, today)

    # 1. paused -> formal on the next evaluation day (no tenure)
    for sid, rec in recs.items():
        if rec["stage"] == "paused" and rec["paused_on"] and rec["paused_on"] < today:
            rec.update(stage="formal", since=today, formal_since=today, advisor_since=None)
            events.append(_event(today, "resume", sid, "paused", "formal"))

    # 2. probation -> formal
    for sid, s in stats.items():
        rec = recs[sid]
        gates = probation_gates(s)
        rec["probation_gates"] = gates
        if rec["stage"] == "probation" and all(gates.values()):
            rec.update(stage="formal", since=today, formal_since=today)
            events.append(_event(today, "promote", sid, "probation", "formal",
                                 n_eff=s["n_eff"], min_trl=s["min_trl"]))

    # 3. composite score among shadows past probation (C04: nobody else is ranked)
    ranked = {sid: stats[sid] for sid, rec in recs.items()
              if rec["stage"] in ("formal", "advisor", "paused")}
    comp = composite_scores(ranked)
    tier = tiers({sid: c["score"] for sid, c in comp.items()})

    # Portfolio-level inputs: PBO over the ranked shadows, Sharpe variance over all live ones
    pbo = None
    if len(ranked) >= 2:
        start = max(s["first_day"] for s in ranked.values())
        common = [d for d in cal if start <= d <= today]
        cols = [M.daily_series(M.daily_pnl([e for e in entries if e.source_type == "shadow"
                                            and e.source_id == sid]), common)
                for sid in sorted(ranked)]
        pbo = M.pbo_cscv(np.column_stack(cols), C.PBO_BLOCKS)
    sharpes = [s["sharpe_daily"] for s in stats.values() if s["series"].size >= 2]
    sr_var = float(np.var(sharpes, ddof=1)) if len(sharpes) >= 2 else None

    for sid in ranked:
        rec, s = recs[sid], stats[sid]
        rec["score"] = comp[sid]
        rec["tier"] = tier[sid]

        # 4. advisor monitoring: CUSUM on days since promotion vs. pre-advisor reference
        if rec["stage"] == "advisor" and rec["advisor_since"] and rec["advisor_since"] < today:
            ref = np.array([x for d, x in zip(s["window"], s["series"]) if d <= rec["advisor_since"]])
            live = np.array([x for d, x in zip(s["window"], s["series"]) if d > rec["advisor_since"]])
            alarm = None
            if ref.size >= C.CUSUM_MIN_REFERENCE_DAYS and live.size:
                alarm = M.cusum_down(live, float(ref.mean()), float(ref.std(ddof=1)),
                                     C.CUSUM_K, C.CUSUM_H)
            rec["cusum_alarm"] = alarm is not None
            if alarm is not None:
                rec.update(stage="paused", since=today, paused_on=today, advisor_since=None)
                events.append(_event(today, "pause", sid, "advisor", "paused",
                                     alarm_index=alarm))
            continue

        # 5. formal -> advisor
        if rec["stage"] == "formal" and rec["formal_since"]:
            after = _days_after(cal, rec["formal_since"], today)
            oos_days = after[:C.FORWARD_OOS_DAYS]
            by_day = dict(zip(s["window"], s["series"]))
            oos = sum(by_day.get(d, 0.0) for d in oos_days)
            stress, stress_detail = M.stress_test(s["series"], s["market"], C.STRESS_WORST_SHARE,
                                                  C.STRESS_MULTIPLE, C.STRESS_MIN_DAYS)
            dsr = M.dsr(s["series"], trial_count, sr_var)
            gates = {
                "formal_days": len(after) >= C.ADVISOR_MIN_FORMAL_DAYS,
                "tier": tier[sid] in (1, 2),
                "stress": bool(stress),
                "forward_oos": len(oos_days) >= C.FORWARD_OOS_DAYS and oos > 0,
                "pbo": pbo is not None and pbo < C.PBO_MAX,
                "dsr": dsr >= C.DSR_MIN,
                "brier": s["mean_brier"] is not None and s["mean_brier"] < C.BRIER_MAX,
            }
            rec["advisor_gates"] = gates
            rec["advisor_inputs"] = _clean({"formal_days": len(after), "forward_oos": oos,
                                            "stress": stress_detail, "pbo": pbo, "dsr": dsr,
                                            "trial_count": trial_count})
            if all(gates.values()):
                rec.update(stage="advisor", since=today, advisor_since=today)
                events.append(_event(today, "promote", sid, "formal", "advisor",
                                     tier=tier[sid], dsr=dsr, pbo=pbo))

    for sid, rec in recs.items():
        if sid not in ranked:
            rec["score"], rec["tier"] = None, None

    # 6. evaluation periods (C30): bottom 20% for 3 consecutive periods -> challenger
    if period["start"] is None:
        period["start"] = today
    elif len(_days_after(cal, period["start"], today)) >= C.EVALUATION_PERIOD_DAYS:
        period["index"] += 1
        period["start"] = today
        low = bottom({sid: c["score"] for sid, c in comp.items()})
        for sid, rec in recs.items():
            rec["bottom_streak"] = rec.get("bottom_streak", 0) + 1 if sid in low else 0
            if rec["bottom_streak"] >= C.BOTTOM_PERIODS_FOR_CHALLENGE:
                events.append(_event(today, "challenge", sid, rec["stage"], rec["stage"],
                                     periods=rec["bottom_streak"]))
                rec["bottom_streak"] = 0

    for sid, rec in recs.items():
        s = stats.get(sid)
        if s is not None:
            rec["metrics"] = _clean({k: v for k, v in s.items()
                                     if k not in ("series", "market", "window")})
        rec["last_eval"] = today
        recs[sid] = _clean(rec)

    return {"updated_at": today, "period": period, "pbo": _clean(pbo),
            "shadows": recs}, events


def advisors(state: dict) -> list[str]:
    return sorted(sid for sid, r in state.get("shadows", {}).items() if r.get("stage") == "advisor")
