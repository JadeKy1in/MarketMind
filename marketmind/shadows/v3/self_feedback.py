"""Self-feedback experiment: a shadow sees its own settled record (docs/S3_DESIGN.md §8).

Owner decision 2026-09-29: shadows optimise their own strategy (SPEC_v3 §6.1), so
they may see their own past results - but that changes the methodology, so it runs
first as a controlled experiment on half of the long-term roster.

- `record_lines`: the "YOUR RECORD" block, computed by code from the shadow's OWN
  ledger rows only (settled outcomes and open positions). Never another shadow's
  rows (information isolation, SPEC §6.1); no LLM-written text (theses are left out)
  so only code-settled facts feed back (docs/S9_DESIGN.md §5).
- `arm_for`: frozen, balanced treatment / control split. Successors inherit their
  lineage's arm; temporary, event, trial and missed-path shadows are control.
- `enabled`: one switch for the whole treatment (constant + env var).
- `compare_arms`: read-only arm comparison from the ledger (per-dollar daily P&L and
  Brier, HAC t-test on the day-level difference, overall and per model).
"""
from __future__ import annotations

import os
from collections import Counter
from statistics import mean

from marketmind.shadows.v3.roster import RosterEntry, lineage_id

# ── Switch ──────────────────────────────────────────────────────────────
SELF_FEEDBACK_ENABLED = True
ENV_SWITCH = "MARKETMIND_SELF_FEEDBACK"          # "0" / "off" / "false" turns it off


def enabled() -> bool:
    """The treatment is on unless the constant or the env var switches it off."""
    env = os.getenv(ENV_SWITCH, "").strip().lower()
    return SELF_FEEDBACK_ENABLED and env not in ("0", "off", "false", "no")


# ── Assignment ──────────────────────────────────────────────────────────
# The experiment population: the 31 long-term shadows active on 2026-09-29. It is
# frozen so later roster changes (odds_analyst going live, a new shadow) never move
# an existing shadow to the other arm; shadows outside it are control.
EXPERIMENT_IDS = frozenset({
    "contrarian:consensus:fade_master", "contrarian:crash:hunter",
    "contrarian:panic:vol_surfer", "contrarian:range_bound:sideways_scout",
    "cross:china:dragon_watch", "cross:europe:euro_watch", "cross:japan:carry_watch",
    "derivatives:options:options_reader",
    "expert:agriculture:harvest_seer", "expert:bonds:yield_whisperer",
    "expert:consumer:wallet_watcher", "expert:crypto:chain_oracle",
    "expert:crypto:defi_scout", "expert:em:frontier_scout",
    "expert:energy:oil_geologist", "expert:financials:bank_examiner",
    "expert:fx:currency_dealer", "expert:gold:bullion_broker",
    "expert:healthcare:trial_reviewer", "expert:industrials:factory_floor",
    "expert:macro:cycle_reader", "expert:metals:steel_trader",
    "expert:realestate:reit_analyst", "expert:tech:silicon_oracle",
    "expert:vol:vega_trader",
    "momentum:event:news_hound", "momentum:intraday:scalper",
    "momentum:sector:rotation_engine", "momentum:weekly:trend_rider",
    "expert:short:bear_tracker", "short:squeeze:squeeze_watch",
})

# balanced_split(EXPERIMENT_IDS) - written out so the arms are reviewable and fixed
# (a test checks that the rule still yields exactly this set).
TREATMENT_IDS = frozenset({
    "contrarian:consensus:fade_master", "contrarian:panic:vol_surfer",
    "cross:china:dragon_watch", "cross:japan:carry_watch",
    "expert:agriculture:harvest_seer", "expert:consumer:wallet_watcher",
    "expert:crypto:defi_scout", "expert:energy:oil_geologist",
    "expert:fx:currency_dealer", "expert:healthcare:trial_reviewer",
    "expert:macro:cycle_reader", "expert:realestate:reit_analyst",
    "expert:vol:vega_trader",
    "momentum:event:news_hound", "momentum:sector:rotation_engine",
    "expert:short:bear_tracker",
})

TREATMENT, CONTROL = "treatment", "control"


def balanced_split(entries: list[RosterEntry]) -> frozenset[str]:
    """Treatment ids: groups in name order, each group's shadows sorted by shadow_id and
    alternated treatment / control. A group with an odd count gives its extra shadow to
    the arm that is behind (treatment first), so the arms differ by at most one overall
    and by at most one within every group."""
    groups: dict[str, list[str]] = {}
    for e in entries:
        groups.setdefault(e.group, []).append(e.shadow_id)
    treat: set[str] = set()
    odd_starts_treatment = True
    for g in sorted(groups):
        ids = sorted(groups[g])
        start = 0
        if len(ids) % 2:
            start = 0 if odd_starts_treatment else 1
            odd_starts_treatment = not odd_starts_treatment
        treat.update(i for k, i in enumerate(ids) if k % 2 == start)
    return frozenset(treat)


def arm_for(shadow_id: str, source_type: str = "shadow") -> str | None:
    """treatment / control for experiment members (successors "x@2" take x's arm);
    None for everything else (temp/event/trial/missed-path shadows, new shadows)."""
    if source_type != "shadow":
        return None
    lin = lineage_id(shadow_id)
    if lin not in EXPERIMENT_IDS:
        return None
    return TREATMENT if lin in TREATMENT_IDS else CONTROL


def is_on(entry: RosterEntry) -> bool:
    """Does this shadow get its record today (treatment arm and the switch on)?"""
    return enabled() and arm_for(entry.shadow_id, entry.source_type) == TREATMENT


# ── The block ───────────────────────────────────────────────────────────
LAST_N = 10
MIN_EVIDENCE = 10                 # below this many trades a figure is weak evidence
MAX_OPEN = 15
ERROR_CLASSES = ("win", "beta_carried", "cost_flipped", "right_but_stopped", "thesis_wrong")
BLOCK_TITLE = "## YOUR RECORD (facts computed by code)"
BLOCK_OPEN = "<<< BEGIN YOUR RECORD >>>"
BLOCK_CLOSE = "<<< END YOUR RECORD >>>"

SYSTEM_INSTRUCTIONS = """
## Your own record
The user message contains YOUR RECORD: facts about your own past trades, computed by
code from settled ledger outcomes (no one's opinion). Use it to refine your own method -
for example stop distance, holding period, and the market regimes where your method
works or fails. Small samples are weak evidence; one trade is noise. Do not chase recent
winners, do not try to win back recent losses (no revenge trading), and do not repeat a
trade only because it worked. Check your open positions before adding the same trade again.
""".strip()


def _settled(rows) -> list:
    return [e for e in rows if e.status == "settled" and e.net_return is not None]


def _weak(n: int) -> str:
    return f" (n < {MIN_EVIDENCE}: weak evidence)" if n < MIN_EVIDENCE else ""


def _pct(x, digits=1, sign=False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def _perf(rows) -> str:
    if not rows:
        return "n=0"
    hit = sum(1 for e in rows if e.net_return > 0) / len(rows)
    return (f"n={len(rows)}, hit rate {_pct(hit)}, mean net {_pct(mean(e.net_return for e in rows), 2, True)}"
            f"{_weak(len(rows))}")


def _review(e) -> dict:
    return e.review if isinstance(e.review, dict) else {}


def _ma200(e):
    return (_review(e).get("regime") or {}).get("above_ma200")


def _run_date(e) -> str:
    return (e.meta or {}).get("run_date") or (e.created_at or "")[:10]


def record_facts(own: list, baseline: list) -> dict:
    """Numbers behind the block. `own`: this shadow's ledger rows; `baseline`: its
    random-benchmark rows (source_id random:<shadow_id>)."""
    rows = _settled(own)
    rows.sort(key=lambda e: (e.exit_date or "", e.entry_id), reverse=True)
    classes = Counter(_review(e).get("error_class") for e in rows if _review(e))
    reviewed = sum(classes.values())
    return {
        "n": len(rows), "rows": rows, "baseline": _settled(baseline),
        "error_class": {c: classes.get(c, 0) for c in ERROR_CLASSES},
        "reviewed": reviewed,
        "right_but_stopped_share": classes.get("right_but_stopped", 0) / reviewed if reviewed else None,
        "above": [e for e in rows if _ma200(e) is True],
        "below": [e for e in rows if _ma200(e) is False],
        "unknown": [e for e in rows if _ma200(e) is None],
        "open": sorted((e for e in own if e.status in ("pending", "open")),
                       key=lambda e: (e.created_at or "", e.entry_id), reverse=True),
    }


def _trade_line(e) -> str:
    rv = _review(e)
    held = rv.get("bars_held")
    hold = f"hold {e.hold_bars}d" + (f", held {held}" if held is not None else "")
    return (f"- exit {(e.exit_date or '?')[:10]} | {e.ticker} {e.direction} | {hold} | "
            f"net {_pct(e.net_return, 2, True)} | exit {e.exit_reason or '?'} | "
            f"{rv.get('error_class') or 'not classified'}")


def _open_line(e) -> str:
    state = "awaiting entry" if e.status == "pending" else f"entered {(e.entry_date or '?')[:10]}"
    return f"- {e.ticker} {e.direction}, decided {_run_date(e)}, hold {e.hold_bars}d, {state}"


def record_lines(own: list, baseline: list) -> list[str]:
    """The YOUR RECORD block (title, delimiters and facts), ready for the user prompt."""
    f = record_facts(own, baseline)
    n, lines = f["n"], [BLOCK_TITLE, BLOCK_OPEN,
                        "Only your own trades; other shadows' records are never shown."]
    if not n:
        lines.append("Settled trades: none yet.")
    else:
        lines += [f"Settled trades: {_perf(f['rows'])}.",
                  f"Your random baseline (same-domain random picks, one a day): "
                  f"{_perf(f['baseline'])}.",
                  "error_class (code-classified): " + ", ".join(
                      f"{c} {f['error_class'][c]}" for c in ERROR_CLASSES)
                  + (f" (classified: {f['reviewed']})" if f["reviewed"] != n else ""),
                  f"right_but_stopped share: {_pct(f['right_but_stopped_share'])} "
                  f"(stopped out, then the target was reached within the planned hold)",
                  "By market regime at entry (instrument vs its 200-day average):",
                  f"- above MA200: {_perf(f['above'])}",
                  f"- below MA200: {_perf(f['below'])}"]
        if f["unknown"]:
            lines.append(f"- unknown (short history or not reviewed yet): {len(f['unknown'])}")
        last = f["rows"][:LAST_N]
        lines += [f"Last {len(last)} settled trades (newest first):", *map(_trade_line, last)]
    opened = f["open"]
    if opened:
        lines += [f"Open positions ({len(opened)}):", *map(_open_line, opened[:MAX_OPEN])]
        if len(opened) > MAX_OPEN:
            lines.append(f"- ... and {len(opened) - MAX_OPEN} more")
    else:
        lines.append("Open positions: none.")
    lines.append(BLOCK_CLOSE)
    return lines


def lines_for(entry: RosterEntry, shadow_rows: list, benchmark_rows: list) -> list[str]:
    """The block for `entry` from pre-loaded ledger rows, filtered to its own id only."""
    own = [e for e in shadow_rows
           if e.source_type == entry.source_type and e.source_id == entry.shadow_id]
    base = [e for e in benchmark_rows if e.source_id == f"random:{entry.shadow_id}"]
    return record_lines(own, base)


# ── Evaluation (read-only) ──────────────────────────────────────────────
MIN_TRADING_DAYS = 40             # decision days before the comparison is read


def _exposed_rows(entries) -> tuple[dict[str, list], int]:
    """Experiment rows by arm. Only rows tagged by the experiment (meta.self_feedback)
    count; treatment rows made while the switch was off are dropped (not exposed)."""
    arms: dict[str, list] = {TREATMENT: [], CONTROL: []}
    unexposed = 0
    for e in entries:
        flag = (e.meta or {}).get("self_feedback")
        arm = arm_for(e.source_id, e.source_type)
        if flag is None or arm is None:
            continue
        if arm == TREATMENT and flag != "on":
            unexposed += 1
            continue
        arms[arm].append(e)
    return arms, unexposed


def _pnl_by_exit(rows, measure: str) -> tuple[dict[str, float], float]:
    out: dict[str, float] = {}
    gross = 0.0
    for e in rows:
        if e.status != "settled" or not e.exit_date or e.pnl_usd is None:
            continue
        x = e.pnl_usd
        if measure == "excess" and e.market_return is not None:
            x -= (1.0 if e.direction == "long" else -1.0) * e.position_usd * e.market_return
        d = e.exit_date[:10]
        out[d] = out.get(d, 0.0) + x
        gross += e.position_usd * max(1, e.hold_bars)
    return out, gross


def _test(diffs: list[float], hold: int) -> dict:
    from marketmind.promotion.metrics import hac_t_test
    from marketmind.shadows.v3.trials import hac_bandwidth
    n = len(diffs)
    res = hac_t_test(diffs, hac_bandwidth(max(1, hold - 1), n))
    p = res.get("p_value")
    res["p_two_sided"] = None if p is None else min(1.0, 2 * min(p, 1.0 - p + 1e-12))
    return res


def _arm_comparison(arms: dict[str, list], calendar: list[str], measure: str) -> dict:
    t_rows, c_rows = arms[TREATMENT], arms[CONTROL]
    holds = sorted(e.hold_bars for e in t_rows + c_rows)
    hold = holds[len(holds) // 2] if holds else 1
    days = sorted({_run_date(e) for e in t_rows + c_rows})
    out = {"decision_days": len(days), "ready": len(days) >= MIN_TRADING_DAYS,
           "rows": {TREATMENT: len(t_rows), CONTROL: len(c_rows)},
           "shadows": {TREATMENT: len({e.source_id for e in t_rows}),
                       CONTROL: len({e.source_id for e in c_rows})},
           "median_hold": hold}

    # 1. per-dollar daily P&L, booked on exit dates (S7 trial convention)
    (tp, tg), (cp, cg) = _pnl_by_exit(t_rows, measure), _pnl_by_exit(c_rows, measure)
    exits = set(tp) | set(cp)
    pnl = {"measure": measure, "days": 0, "mean_diff": None, "test": None}
    if tp and cp:
        lo, hi = min(exits), max(exits)
        cal = sorted({d for d in calendar if lo <= d <= hi} | exits)
        n = len(cal)
        t_exp, c_exp = tg / n, cg / n
        t_series = [tp.get(d, 0.0) / t_exp for d in cal]
        c_series = [cp.get(d, 0.0) / c_exp for d in cal]
        diffs = [a - b for a, b in zip(t_series, c_series)]
        pnl.update(days=n, first_day=cal[0], last_day=cal[-1],
                   treatment_mean=mean(t_series), control_mean=mean(c_series),
                   mean_diff=mean(diffs), test=_test(diffs, hold))
    out["pnl_per_dollar"] = pnl

    # 2. Brier, by decision day (same day = same market): control - treatment,
    #    so a positive difference means the treatment forecasts better
    def brier_by_day(rows):
        acc: dict[str, list[float]] = {}
        for e in rows:
            if e.status == "settled" and e.brier is not None:
                acc.setdefault(_run_date(e), []).append(e.brier)
        return {d: mean(v) for d, v in acc.items()}
    tb, cb = brier_by_day(t_rows), brier_by_day(c_rows)
    common = sorted(set(tb) & set(cb))
    brier = {"days": len(common), "mean_diff": None, "test": None}
    if common:
        diffs = [cb[d] - tb[d] for d in common]
        brier.update(treatment_mean=mean(tb[d] for d in common),
                     control_mean=mean(cb[d] for d in common),
                     mean_diff=mean(diffs), test=_test(diffs, hold))
    out["brier"] = brier
    return out


def compare_arms(entries: list, *, measure: str = "net") -> dict:
    """Treatment vs control from ledger rows (read-only; pass every ledger row so the
    trading calendar is complete). `measure`: "net" (pnl_usd) or "excess" (minus the
    same capital in the market benchmark). Returns the overall comparison and one per
    model (`meta.llm`) that both arms used."""
    from marketmind.promotion.metrics import trading_calendar
    arms, unexposed = _exposed_rows(entries)
    calendar = trading_calendar([e for e in entries if e.status == "settled"])
    result = {"overall": _arm_comparison(arms, calendar, measure),
              "treatment_unexposed_rows": unexposed, "by_model": {},
              "min_trading_days": MIN_TRADING_DAYS,
              "note": "pnl mean_diff = treatment - control (per dollar of average daily "
                      "gross exposure); brier mean_diff = control - treatment; positive "
                      "favours the treatment. p_value is one-sided (treatment better), "
                      "fixed-b HAC; the owner decides any roll-out."}
    models = {m for rows in arms.values() for e in rows if (m := (e.meta or {}).get("llm"))}
    for m in sorted(models):
        sub = {a: [e for e in rows if (e.meta or {}).get("llm") == m] for a, rows in arms.items()}
        if sub[TREATMENT] and sub[CONTROL]:
            result["by_model"][m] = _arm_comparison(sub, calendar, measure)
    return result


def main(argv: list[str] | None = None) -> int:
    """python -m marketmind.shadows.v3.self_feedback [--ledger PATH] [--excess]"""
    import argparse
    import json
    from pathlib import Path

    from marketmind.ecosystem.runner import load_entries
    from marketmind.ledger.store import default_ledger_path
    p = argparse.ArgumentParser(prog="python -m marketmind.shadows.v3.self_feedback")
    p.add_argument("--ledger", default=None, help="ledger.db (default: data dir)")
    p.add_argument("--excess", action="store_true", help="compare market-excess P&L")
    args = p.parse_args(argv)
    path = Path(args.ledger) if args.ledger else default_ledger_path()
    res = compare_arms(load_entries(path), measure="excess" if args.excess else "net")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
