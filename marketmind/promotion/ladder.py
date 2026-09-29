"""Promotion stage machine (docs/S7_DESIGN.md §一, SPEC_v3 §8, C03 / C04 / C20 / C30).

    probation -> formal -> advisor -> (CUSUM alarm) paused -> formal (no tenure)
    blocked: roster shadow that is not live (status != active or no prompt)

`evaluate` is pure: it takes ledger rows and the previous state and returns the
new state plus the events of this run. Re-running on the same day with the same
ledger yields the same state and no new events.

Per-shadow series:
- trading calendar = union of exit dates of settled rows across all sources (<= today)
  plus the candidates' decision days, or an explicit calendar;
- only MATURED decision cohorts are evaluated (fix 2026-09-29): a decision day counts
  once every record decided on it has settled (or MATURITY_GRACE_DAYS after its entry
  window + longest hold; still-open records are then left out and counted), and only
  the unbroken run of matured days from the first decision on (up to the "horizon").
  Evaluating whatever had settled by today favoured early exits: target hits settle
  in days, stops and expiries later;
- the daily series books each record's P&L on its decision day (cohort booking), over
  first decision .. horizon; every day in it is then complete;
- Sharpe / skew / kurtosis / MinTRL for the probation gate use per-trade net returns,
  because N_eff counts independent trades; DSR, MPPM, Calmar, Omega, PBO, CUSUM and the
  stress test use the daily return series.
- "beats random" is a Monte Carlo gate (promotion/random_mc.py), evaluated for
  probation shadows once the days gate is met; bars come from `bars_for`.
- DSR trials = effective number of promotion candidates (shadow / playground ids and
  challenger / beta variants, clustered by return correlation, metrics.effective_trials).
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from statistics import mean

import numpy as np

from marketmind.ledger.settlement import ENTRY_WINDOW_BARS
from marketmind.ledger.store import LedgerEntry
from marketmind.promotion import config as C
from marketmind.promotion import metrics as M
from marketmind.promotion.random_mc import BarsFor, mc_baseline, seed_for
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


def _terminal(e: LedgerEntry, today: str) -> bool:
    return e.status == "void" or (e.status == "settled" and bool(e.exit_date)
                                  and _day(e.exit_date) <= today)


def matured(rows: list[LedgerEntry], calendar: list[str],
            today: str) -> tuple[list[LedgerEntry], str | None, int]:
    """(settled rows of matured decision cohorts, horizon, still-open rows left out).

    Decision days are walked in order; a day is matured when all its records are
    terminal as of `today` (settled with exit <= today, or void), or when more than
    ENTRY_WINDOW_BARS + its longest hold + MATURITY_GRACE_DAYS calendar trading days
    have passed. The walk stops at the first immature day: the horizon is the last day
    of the unbroken matured run, so later early exits never enter the statistics."""
    by_day: dict[str, list[LedgerEntry]] = {}
    for e in rows:
        d = _day(e.created_at)
        if d and d <= today:
            by_day.setdefault(d, []).append(e)
    out: list[LedgerEntry] = []
    horizon, stale = None, 0
    t_idx = bisect_right(calendar, today)
    for d in sorted(by_day):
        rs = by_day[d]
        open_rows = [e for e in rs if not _terminal(e, today)]
        if open_rows:
            elapsed = t_idx - bisect_right(calendar, d)
            if elapsed < ENTRY_WINDOW_BARS + max(e.hold_bars for e in rs) + C.MATURITY_GRACE_DAYS:
                break
            stale += len(open_rows)
        horizon = d
        out += [e for e in rs if e.status == "settled" and e.net_return is not None
                and e.exit_date and _day(e.exit_date) <= today]
    return out, horizon, stale


def _cohort_mean(rows: list[LedgerEntry], calendar: list[str], today: str,
                 lo: str | None, hi: str | None) -> float | None:
    """Mean net return of matured cohorts decided in [lo, hi] (main pipeline, random shadow)."""
    if lo is None or hi is None:
        return None
    done, _, _ = matured(rows, calendar, today)
    vals = [e.net_return for e in done if lo <= _day(e.created_at) <= hi]
    return mean(vals) if vals else None


def _days_after(calendar: list[str], start: str, end: str) -> list[str]:
    return [d for d in calendar if start < d <= end]


# ── Per-shadow statistics ───────────────────────────────────────────────

def shadow_stats(sid: str, entries: list[LedgerEntry], calendar: list[str], today: str) -> dict:
    """Everything the gates and the composite score need for one shadow, from its
    matured decision cohorts (see `matured`). `tickers` = what the Monte Carlo gate
    needs bars for (the shadow's evaluated trades)."""
    rows = [e for e in entries if e.source_type in CANDIDATE_SOURCES and e.source_id == sid
            and e.created_at and _day(e.created_at) <= today]
    settled, horizon, stale = matured(rows, calendar, today)
    record_days = sorted({_day(e.created_at) for e in rows})
    first = record_days[0] if record_days else None
    window = [d for d in calendar if first and horizon and first <= d <= horizon]
    series = M.daily_series(M.cohort_pnl(settled, window), window)
    market = M.daily_series(M.cohort_market(settled, window), window)

    trade_r = np.array([e.net_return for e in settled], dtype=float)
    sr_trade = M.sharpe(trade_r)
    g3, g4 = M.skew_kurt(trade_r)
    mean_hold = mean(e.hold_bars for e in settled) if settled else 0.0

    bench = [e for e in entries if e.source_type == "benchmark"
             and e.source_id == f"random:{sid}"]
    main = [e for e in entries if e.source_type in MAIN_SOURCES]
    excess_dom = [e.excess_domain for e in settled if e.excess_domain is not None]
    briers = [e.brier for e in settled if e.brier is not None]
    return {
        "settled_rows": settled,
        "tickers": sorted({e.ticker for e in settled}),
        "records": len(rows), "record_days": len(record_days), "first_day": first,
        "horizon": horizon, "open_left_out": stale,
        "settled": len(settled), "series": series, "market": market, "window": window,
        "sharpe_trade": sr_trade, "skew": g3, "kurtosis": g4,
        "min_trl": M.min_trl(sr_trade, g3, g4, C.MINTRL_BENCHMARK_SHARPE,
                              C.MINTRL_CONFIDENCE) if trade_r.size >= 2 else math.inf,
        "n_eff": M.n_eff(len(settled), len(window), mean_hold),
        "mean_net": float(trade_r.mean()) if trade_r.size else None,
        "random_mean_net": _cohort_mean(bench, calendar, today, first, horizon),
        "main_mean_net": _cohort_mean(main, calendar, today, first, horizon),
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


def trial_ids(entries: list[LedgerEntry]) -> list[str]:
    """Every promotion candidate ever in the ledger (DSR trials, SPEC §8 "全部历史试验"):
    long-term shadows, Playground agents and challenger / beta variants (`trial:`).
    Event shadows, missed_path and benchmarks are not candidates."""
    return sorted({e.source_id for e in entries
                   if e.source_type in CANDIDATE_SOURCES
                   or (e.source_type == "temp_shadow" and e.source_id.startswith("trial:"))})


def candidate_series(entries: list[LedgerEntry], calendar: list[str], today: str,
                     known: dict[str, dict]) -> dict[str, tuple[list[str], np.ndarray]]:
    """Matured cohort series of every DSR trial; reuses the stats already computed."""
    out = {}
    for sid in trial_ids(entries):
        if sid in known:
            out[sid] = (known[sid]["window"], known[sid]["series"])
            continue
        rows = [e for e in entries if e.source_id == sid and e.created_at
                and _day(e.created_at) <= today]
        done, horizon, _ = matured(rows, calendar, today)
        first = min((_day(e.created_at) for e in rows), default=None)
        window = [d for d in calendar if first and horizon and first <= d <= horizon]
        out[sid] = (window, M.daily_series(M.cohort_pnl(done, window), window))
    return out


def probation_gates(s: dict, random_mc: dict | None = None) -> dict[str, bool]:
    """Probation -> formal: every gate must pass (S7 §一 阶段与门槛).

    beat_random: the Monte Carlo baseline (`random_mc` = mc_baseline result) passed;
    missing, not evaluated or not evaluable fails closed."""
    mn = s["mean_net"]
    return {
        "days": s["record_days"] >= C.PROBATION_DAYS,
        "min_trl": s["n_eff"] >= s["min_trl"],
        "beat_random": bool(random_mc) and random_mc.get("status") == "pass",
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

def _calibrate_cusum(sid: str, rec: dict, s: dict) -> dict:
    """Robust CUSUM parameters from the formal period (formal_since, advisor_since]:
    median / MAD center and scale, winsorised standardised values, and the alarm
    threshold h giving a geometric-equivalent in-control ARL >= CUSUM_ARL0 by a circular
    block bootstrap that re-estimates center / scale on every path (block = mean
    holding period, capped at round(n ** (1/3)) for a short reference).
    Fixed once calibrated; cleared when the advisor is paused."""
    lo, hi = rec.get("formal_since") or "", rec["advisor_since"]
    ref = np.array([x for d, x in zip(s["window"], s["series"]) if lo < d <= hi])
    out = {"ref_days": int(ref.size), "reference": [lo, hi], "h": None}
    if ref.size < C.CUSUM_MIN_REFERENCE_DAYS:
        return out
    center, scale = M.robust_center_scale(ref)
    if scale <= 0:
        return out
    holds = [e.hold_bars for e in s["settled_rows"]]
    block = max(1, min(round(mean(holds)) if holds else 1, round(ref.size ** (1 / 3))))
    h = M.calibrate_cusum_h(ref, C.CUSUM_K, C.CUSUM_ARL0, block,
                            seed=seed_for(sid, f"cusum:{hi}"))
    return {**out, "center": center, "scale": scale, "block": block, "h": h}


def _new_record(today: str) -> dict:
    return {"stage": "probation", "since": today, "formal_since": None, "advisor_since": None,
            "paused_on": None, "bottom_streak": 0}


def _event(today, kind, sid, frm, to, **detail) -> dict:
    return {"date": today, "type": kind, "shadow_id": sid, "from": frm, "to": to,
            "detail": _clean(detail)}


# Promotion candidates share one ladder (SPEC_v3 §8): long-term shadows and
# Playground agents; source ids are unique across the two ("playground:" prefix).
CANDIDATE_SOURCES = ("shadow", "playground")


def evaluate(entries: list[LedgerEntry], roster_entries: list[RosterEntry], today: str,
             state: dict | None, trial_count: int | None = None, *,
             calendar: list[str] | None = None, active_ids: set[str] | None = None,
             bars_for: BarsFor | None = None) -> tuple[dict, list[dict]]:
    """Run one day of the ladder. Returns (new_state, events).

    `active_ids` defaults to roster shadows with status active and a prompt file.
    `trial_count` overrides the DSR's effective number of trials (default: computed
    from the ledger, metrics.effective_trials over `trial_ids`).
    `bars_for(tickers) -> {ticker: bars}` feeds the Monte Carlo "beats random" gate;
    without it that gate is not evaluable and fails closed."""
    state = dict(state or {})
    prev = state.get("shadows", {})
    period = dict(state.get("period") or {"start": None, "index": 0})
    if calendar is None:
        calendar = sorted(set(M.trading_calendar(entries, until=today))
                          | {_day(e.created_at) for e in entries
                             if e.source_type in CANDIDATE_SOURCES and e.created_at})
    cal = sorted(d for d in calendar if d and d <= today)
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

    # 2. probation -> formal. The Monte Carlo baseline runs for probation shadows past
    # the days gate (the only ones it can promote); later stages keep the result from
    # their promotion day.
    need = [sid for sid, s in stats.items() if recs[sid]["stage"] == "probation"
            and s["record_days"] >= C.PROBATION_DAYS]
    bars = {}
    if need and bars_for is not None:
        bars = bars_for(sorted({t for sid in need for t in stats[sid]["tickers"]}))
    for sid, s in stats.items():
        rec = recs[sid]
        if rec["stage"] == "probation":
            if sid not in need:
                rec["random_mc"] = {"method": "monte_carlo", "status": "not_evaluated",
                                    "reason": f"record days < {C.PROBATION_DAYS}"}
            elif bars_for is None:
                rec["random_mc"] = {"method": "monte_carlo", "status": "not_evaluable",
                                    "reason": "no price source"}
            else:
                rec["random_mc"] = mc_baseline(sid, s["settled_rows"], bars, today)
        gates = probation_gates(s, rec.get("random_mc"))
        rec["probation_gates"] = gates
        if rec["stage"] == "probation" and all(gates.values()):
            rec.update(stage="formal", since=today, formal_since=today)
            events.append(_event(today, "promote", sid, "probation", "formal",
                                 n_eff=s["n_eff"], min_trl=s["min_trl"],
                                 random_p=(rec.get("random_mc") or {}).get("p_value")))

    # 3. composite score among shadows past probation (C04: nobody else is ranked)
    ranked = {sid: stats[sid] for sid, rec in recs.items()
              if rec["stage"] in ("formal", "advisor", "paused")}
    comp = composite_scores(ranked)
    tier = tiers({sid: c["score"] for sid, c in comp.items()})

    # Portfolio-level inputs: PBO over the ranked shadows on their common matured window;
    # DSR trials = effective number of candidates (only needed when a formal shadow is judged)
    pbo = None
    if len(ranked) >= 2:
        start = max(s["first_day"] for s in ranked.values())
        end = min((s["horizon"] or "") for s in ranked.values())
        common = [d for d in cal if start <= d <= end]
        cols = [np.array([dict(zip(stats[sid]["window"], stats[sid]["series"])).get(d, 0.0)
                          for d in common]) for sid in sorted(ranked)]
        pbo = M.pbo_cscv(np.column_stack(cols), C.PBO_BLOCKS) if common else None
    trials_info = {"raw": len(trial_ids(entries))}
    if trial_count is not None:
        n_trials = max(1, int(trial_count))
        trials_info["effective"] = n_trials
        trials_info["override"] = True
    elif any(recs[sid]["stage"] == "formal" for sid in ranked):
        n_trials, clusters = M.effective_trials(candidate_series(entries, cal, today, stats))
        n_trials = max(1, n_trials)
        trials_info["effective"] = n_trials
        trials_info["clusters"] = [c for c in clusters if len(c) > 1]
    else:
        n_trials = None

    for sid in ranked:
        rec, s = recs[sid], stats[sid]
        rec["score"] = comp[sid]
        rec["tier"] = tier[sid]

        # 4. advisor monitoring: robust CUSUM on cohorts decided after the promotion,
        # against the formal period (formal_since, advisor_since] only
        if rec["stage"] == "advisor" and rec["advisor_since"] and rec["advisor_since"] < today:
            cus = rec.get("cusum") or {}
            if not cus and s["horizon"] and s["horizon"] >= rec["advisor_since"]:
                cus = _calibrate_cusum(sid, rec, s)
                rec["cusum"] = cus
            live = np.array([x for d, x in zip(s["window"], s["series"]) if d > rec["advisor_since"]])
            alarm = None
            if cus.get("h") is not None and live.size:
                alarm = M.cusum_down(live, cus["center"], cus["scale"], C.CUSUM_K, cus["h"],
                                     clip=C.CUSUM_WINSOR)
            rec["cusum_alarm"] = alarm is not None
            if alarm is not None:
                rec.update(stage="paused", since=today, paused_on=today, advisor_since=None,
                           cusum=None)
                events.append(_event(today, "pause", sid, "advisor", "paused",
                                     alarm_index=alarm))
            continue

        # 5. formal -> advisor
        if rec["stage"] == "formal" and rec["formal_since"]:
            after = _days_after(cal, rec["formal_since"], today)
            # forward out-of-sample = the first matured cohorts decided after promotion
            oos_pairs = [(d, x) for d, x in zip(s["window"], s["series"])
                         if d > rec["formal_since"]][:C.FORWARD_OOS_DAYS]
            oos_days = [d for d, _ in oos_pairs]
            oos = sum(x for _, x in oos_pairs)
            stress, stress_detail = M.stress_test(s["series"], s["market"], C.STRESS_WORST_SHARE,
                                                  C.STRESS_MIN_DAYS, C.STRESS_ALPHA,
                                                  C.STRESS_MIN_WORST_DAYS)
            dsr = M.dsr(s["series"], n_trials)
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
                                            "forward_oos_days": len(oos_days),
                                            "stress": stress_detail, "pbo": pbo, "dsr": dsr,
                                            "trial_count": n_trials})
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
                                     if k not in ("series", "market", "window", "settled_rows",
                                                  "tickers")})
        rec["last_eval"] = today
        recs[sid] = _clean(rec)

    return {"updated_at": today, "period": period, "pbo": _clean(pbo),
            "dsr_trials": _clean(trials_info), "shadows": recs}, events


def advisors(state: dict) -> list[str]:
    return sorted(sid for sid, r in state.get("shadows", {}).items() if r.get("stage") == "advisor")
