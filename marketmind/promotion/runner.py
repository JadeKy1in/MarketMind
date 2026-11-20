"""Daily promotion review (docs/S7_DESIGN.md §一): ledger -> state.json, events.jsonl, advisors.json.

Files under `data_dir` (default env MARKETMIND_DATA_DIR or "data"):
- promotion/state.json   each shadow's stage, gates, metrics, latest evaluation
- promotion/events.jsonl promote / pause / resume / challenge, one JSON object per line
- advisors.json          {"updated_at": ..., "advisors": [shadow ids]} read by the S8 alerts
- promotion/retirements.json  retirement proposals (promotion/retirement.py); approved
                         ones retire a shadow (stage "retired") and add its successor
                         to the evaluated roster. state.json["retirements"] mirrors
                         the pending / retired lists for the dashboard.

DSR trials (fix 2026-09-29): every promotion candidate ever in the ledger (long-term
shadows, Playground agents, challenger / beta variants; SPEC §8 "全部历史试验次数"),
reduced to an effective number by clustering on return correlation
(ladder.trial_ids, metrics.effective_trials). Event shadows and missed_path are not
candidates and no longer count. `trial_count` below is the raw candidate count.

Bars for the Monte Carlo "beats random" gate come from `price_source` (default: the
ledger's HistoryPriceSource, which shares the per-process price cache with settlement
and the shadow run); they are only loaded when a probation shadow has reached the
days gate.

Diagnostics (reporting only, no gate reads them; docs/S7_DESIGN.md §三 / §四): for every
evaluated shadow, state.json["diagnostics"][shadow] = {"factors": promotion/factors.py,
"paper_live": promotion/paper_live.py} on the same matured trades the ladder uses, and
state.json["diagnostics_meta"] says which factor source was used. `read_diagnostics`
is the dashboard's read function. A failure there never fails the promotion run.

Per-LLM-model diagnostic (owner decision 2026-11-20, docs/S7_DESIGN.md §三之二; report
only, never read by evaluate / advisors / scores): state.json["diagnostics"][shadow]
["llm_models"] splits the same matured trades by `meta.llm` model family, and
state.json["diagnostics_meta"]["llm_models"] is the cohort line over all evaluated
shadows. The families covered different calendar periods, so any difference is
confounded with the market regime.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import config as C
from marketmind.promotion import factors as factors_mod
from marketmind.promotion import paper_live as paper_live_mod
from marketmind.promotion import retirement
from marketmind.promotion.ladder import (CANDIDATE_SOURCES, _clean, advisors, default_calendar,
                                         evaluate, matured, trial_ids)
from marketmind.promotion.random_mc import source_loader
from marketmind.shadows.v3 import roster as roster_mod
from marketmind.shadows.v3.roster import ROSTER

log = logging.getLogger(__name__)

def trial_count(entries: list[LedgerEntry]) -> int:
    """Raw number of promotion candidates ever in the ledger (at least 1)."""
    return max(1, len(trial_ids(entries)))


# ── per-LLM-model diagnostic (report only) ─────────────────────────────

LLM_FLIP_MIN_DAYS = 10      # sign-flip flag needs both families >= this many decision days
_LLM_FAMILIES = (("claude", ("claude", "anthropic", "opus", "sonnet", "haiku")),
                 ("deepseek", ("deepseek",)))
LLM_REGIME_NOTE = ("model families ran over different calendar periods, so differences "
                   "are confounded with the market regime; this is not a model comparison "
                   "and no gate reads it")


def llm_family(value) -> str:
    """Model family of a `meta.llm` value: "claude", "deepseek", "other" (a named model of
    neither family), "mixed" (several families: compound "a+b" labels from
    gateway/llm_trace.label, or a list as Playground memory_desk writes) or "unknown"
    (missing / empty)."""
    parts = value if isinstance(value, (list, tuple, set)) else [value]
    names = [p.strip().lower() for v in parts if v is not None
             for p in str(v).split("+") if p.strip()]
    if not names:
        return "unknown"
    fams = {next((f for f, keys in _LLM_FAMILIES if any(k in n for k in keys)), "other")
            for n in names}
    return fams.pop() if len(fams) == 1 else "mixed"


def llm_breakdown(rows: list[LedgerEntry]) -> dict:
    """{"by_family": {family: settled, decision_days, first_day, last_day, mean_net,
    win_rate}, "sign_flip", "note"} over settled rows (the ladder's matured trades).
    `sign_flip` is set only when named families (not "unknown") with >= LLM_FLIP_MIN_DAYS
    decision days have mean net returns of opposite sign."""
    groups: dict[str, list[LedgerEntry]] = {}
    for e in rows:
        if e.net_return is not None:
            groups.setdefault(llm_family((e.meta or {}).get("llm")), []).append(e)
    by = {}
    for fam, rs in sorted(groups.items()):
        r = [e.net_return for e in rs]
        days = sorted({e.created_at[:10] for e in rs if e.created_at})
        by[fam] = {"settled": len(rs), "decision_days": len(days),
                   "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
                   "mean_net": mean(r), "win_rate": sum(1 for x in r if x > 0) / len(r)}
    big = {f: v["mean_net"] for f, v in by.items()
           if f != "unknown" and v["decision_days"] >= LLM_FLIP_MIN_DAYS}
    pos = sorted(f for f, m in big.items() if m > 0)
    neg = sorted(f for f, m in big.items() if m < 0)
    flip = {"positive": pos, "negative": neg, "min_days": LLM_FLIP_MIN_DAYS} if pos and neg else None
    return {"by_family": by, "sign_flip": flip,
            "note": LLM_REGIME_NOTE if len(by) > 1 else None}


def compute_diagnostics(entries: list[LedgerEntry], state: dict, today: str,
                        calendar: list[str], bars_for, provider) -> tuple[dict, dict]:
    """({shadow: {"factors", "paper_live", "llm_models"}}, meta) for every evaluated (not
    blocked or retired) shadow, on its matured settled trades (ladder.matured, the same
    rows as ladder.shadow_stats["settled_rows"]); meta["llm_models"] is the cohort line."""
    cal = sorted(d for d in calendar if d and d <= today)
    by_sid: dict[str, list[LedgerEntry]] = {}
    for e in entries:
        if e.source_type in CANDIDATE_SOURCES and e.created_at and e.created_at[:10] <= today:
            by_sid.setdefault(e.source_id, []).append(e)
    done_by = {}
    for sid, rec in sorted(state.get("shadows", {}).items()):
        if rec.get("stage") not in ("blocked", "retired"):
            done_by[sid] = matured(by_sid.get(sid, []), cal, today)[0]
    # one bulk load (the loader caches, misses included): a single fetch budget per run
    tickers = sorted({e.ticker for done in done_by.values() for e in done})
    bars = bars_for(tickers) if tickers else {}
    out = {}
    for sid, done in done_by.items():
        record_days = int((state["shadows"][sid].get("metrics") or {}).get("record_days") or 0)
        out[sid] = _clean({"factors": factors_mod.analyze(done, provider),
                           "paper_live": paper_live_mod.analyze(done, bars, record_days),
                           "llm_models": llm_breakdown(done)})
    cohort = llm_breakdown([e for done in done_by.values() for e in done])
    cohort["shadows_with_flip"] = sorted(s for s, v in out.items() if v["llm_models"]["sign_flip"])
    meta = _clean({**provider.meta(), "updated_at": today, "min_obs": factors_mod.MIN_OBS,
                   "llm_models": cohort})
    return out, meta


def read_diagnostics(data_dir: str | Path | None = None, shadow_id: str | None = None) -> dict:
    """Dashboard read: {"updated_at", "meta", "shadows": {shadow: {"factors", "paper_live"}}},
    or one shadow's {"factors", "paper_live"} ({} when unknown / not yet computed)."""
    root = Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data"))
    path = root / "promotion" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    diag = state.get("diagnostics") or {}
    if shadow_id is not None:
        return diag.get(shadow_id) or {}
    return {"updated_at": state.get("updated_at"), "meta": state.get("diagnostics_meta"),
            "shadows": diag}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_promotion(store: LedgerStore, *, today: str | None = None,
                  data_dir: str | Path | None = None, roster=ROSTER,
                  active_ids: set[str] | None = None, price_source=None,
                  factor_provider=None) -> dict:
    """Evaluate the ladder for `today` (UTC date by default) and persist the results."""
    live = today is None
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if price_source is None:
        from marketmind.ledger.prices import HistoryPriceSource
        price_source = HistoryPriceSource()
    bars_for = source_loader(price_source, today=today, live=live)
    root = Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data"))
    state_path = root / "promotion" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    entries = store.list()
    trials = trial_count(entries)
    # retirement overrides (promotion/retirement.py): successors join the evaluated
    # roster; approved retirements take stage "retired"
    roster = list(roster)
    known = {r.shadow_id for r in roster}
    roster += [r for r in roster_mod.successor_entries(root) if r.shadow_id not in known]
    retired = roster_mod.retired_ids(root)
    if active_ids is not None:
        active_ids = set(active_ids) - retired
    calendar = default_calendar(entries, today)
    new_state, events = evaluate(entries, roster, today, state, calendar=calendar,
                                 active_ids=active_ids, bars_for=bars_for, retired_ids=retired)
    new_state["trial_count"] = trials
    try:
        from marketmind.shadows.v3 import trials as trials_mod
        events += retirement.check(entries, roster, new_state, today,
                                   trials=trials_mod.load(root / "trials"), data_dir=root,
                                   calendar=calendar)
    except Exception:
        log.warning("retirement check failed", exc_info=True)
    try:
        provider = factor_provider or factors_mod.FactorProvider(bars_for, root / "factors")
        new_state["diagnostics"], new_state["diagnostics_meta"] = compute_diagnostics(
            entries, new_state, today, calendar, bars_for, provider)
    except Exception:
        log.warning("promotion diagnostics failed", exc_info=True)
    ret = retirement.summary(root)
    new_state["retirements"] = {"pending": [p["shadow_id"] for p in ret["pending"]],
                                "retired": [p["shadow_id"] for p in ret["retired"]]}
    _write_json(state_path, new_state)

    if events:
        events_path = root / "promotion" / "events.jsonl"
        with events_path.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    names = advisors(new_state)
    _write_json(root / "advisors.json", {"updated_at": today, "advisors": names})
    log.info("promotion %s: %d events, advisors=%s", today, len(events), names)

    shadows = new_state["shadows"]
    return {
        "date": today,
        "stages": dict(Counter(r["stage"] for r in shadows.values())),
        "probation_progress": {sid: r.get("metrics", {}).get("record_days", 0)
                               for sid, r in shadows.items() if r["stage"] == "probation"},
        "advisors": names,
        "events": events,
        "trial_count": trials,
        "retirements": ret,
        "thresholds": C.thresholds(),
    }
