"""Variant trials: challenger and beta as one mechanism (docs/S7_DESIGN.md §二, SPEC_v3 §6.3, C19, C30).

A trial runs a rewritten methodology for a long-term shadow side by side with
the original for TRIAL_BARS trading days (source_id trial:<id>). When every
record has settled, both sides' daily market-excess P&L per dollar of gross
exposure (booked on the exit date; fix 2026-09-29, see daily_differences) is
differenced day by day and tested one-sided with a HAC (Newey-West) t-test, i.e. a
Diebold-Mariano test, with fixed-b p-values and a bandwidth of half the sample:
lag = max(parent's median hold - 1, pairs // 2 - 1) (owner decision 2026-09-28; see
hac_bandwidth). Holm family (fix 2026-09-29): every trial whose window overlaps the
judged trial's window; Holm-adjusted p <= ALPHA passes. A parent gets at most one
new trial per REPROPOSE_GAP_DAYS trading days. Wilcoxon is reported only as a
robustness statistic. A passing trial only becomes "passed"; the owner must approve
it before the prompt file changes (SPEC L1).

The rewrite prompt also carries code-computed review facts of the parent and of the
best same-group shadow (review_sections; owner decision 2026-09-29). A running trial
stops deciding once its parent is retired (promotion/retirement.py).

CLI: python -m marketmind.shadows.v3.trials {list,propose,approve,reject}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from marketmind.shadows.v3 import roster as roster_mod
from marketmind.shadows.v3.roster import RosterEntry

logger = logging.getLogger("marketmind.shadows.v3.trials")

MAX_RUNNING = 5                  # owner decision 2026-09-28
# Owner decision 2026-09-28 (docs/S7_DESIGN.md §二 判定): the 10-day Wilcoxon at p < 0.10
# had power close to its size, so most passes were false. 40 trading days, HAC t,
# alpha 0.05 with Holm across the trials decided in the same review.
TRIAL_BARS = 40                  # trading days of decisions per trial (was 10)
# Long holds leave too few independent periods in 40 days (owner decision 2026-09-28):
# the window grows to WINDOW_PER_HOLD x the parent's median hold, capped.
WINDOW_PER_HOLD = 8
TRIAL_BARS_MAX = 120
MIN_PAIRS = 30                   # exit-date days in the paired P&L series (was 5)
ALPHA = 0.05                     # one-sided, family-wise via Holm (was p < 0.10 per trial)
SETTLE_GRACE_DAYS = 60           # give up waiting for open records after this
# Fix 2026-09-29: re-proposing after every failure made each parent a long series of
# one-trial Holm families. At most one new trial per parent in this many trading days.
REPROPOSE_GAP_DAYS = 60

SYSTEM_PROMPT = """你负责改写一个虚拟基金经理（影子）的方法论，用于对比试验。
要求：
1. 输出完整的新方法论（Markdown，英文，与原文同一语言），保留原文全部 "## " 小节标题，顺序不变，不增不减。
2. 只按"改动说明"修改；没提到的部分保持原意。改动要具体、可执行，能用上下文里给的字段检验。
3. 不得加入编造的数据、价格或事实；不得取消"每天必须至少一笔决策"。
4. 只输出方法论正文，不要解释。"""


@dataclass
class Trial:
    trial_id: str
    kind: str                     # challenger | beta
    parent_id: str
    note: str
    started: str
    ends: str
    status: str = "running"       # running | passed | failed | insufficient | approved | rejected
    result: dict = field(default_factory=dict)
    decided_at: str | None = None


def base_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "trials"


def load(folder: Path | None = None) -> list[Trial]:
    p = (folder or base_dir()) / "trials.json"
    if not p.exists():
        return []
    return [Trial(**r) for r in json.loads(p.read_text(encoding="utf-8"))]


def save(trials: list[Trial], folder: Path | None = None) -> None:
    folder = folder or base_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trials.json").write_text(
        json.dumps([asdict(t) for t in trials], ensure_ascii=False, indent=1), encoding="utf-8")


def prompt_file(trial_id: str, folder: Path | None = None) -> Path:
    return (folder or base_dir()) / trial_id / "prompt.md"


def add_trading_days(start: str, n: int) -> str:
    d = date.fromisoformat(start)
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d.isoformat()


def trading_days_between(start: str, end: str) -> int:
    """Weekdays after `start` up to and including `end` (add_trading_days' calendar)."""
    import numpy as np
    return int(np.busday_count(date.fromisoformat(start) + timedelta(days=1),
                               date.fromisoformat(end) + timedelta(days=1)))


def headings(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.startswith("## ")]


def validate_variant(original: str, variant: str) -> list[str]:
    errors = []
    if headings(original) != headings(variant):
        errors.append("section headings differ from the original")
    wo, wv = len(original.split()), len(variant.split())
    if not 0.5 * wo <= wv <= 2 * wo:
        errors.append(f"length {wv} words is outside 0.5-2x of the original ({wo})")
    return errors


def _parent_summary(store, parent_id: str) -> str:
    if store is None:
        return "（无账本数据）"
    from marketmind.ledger.scoreboard import score
    rows = [e for e in store.list(source_type="shadow") if e.source_id == parent_id]
    if not rows:
        return "（账本中还没有记录）"
    s = score(rows)
    return (f"records {s.records}, settled {s.settled}, win rate {s.win_rate}, "
            f"mean net return {s.mean_net_return}, mean excess vs domain {s.mean_excess_domain}, "
            f"mean Brier {s.mean_brier}, min-position share {s.min_position_share}")


def _promotion_state(folder: Path | None) -> dict:
    """data/promotion/state.json next to the trials folder ({} when absent / unreadable)."""
    p = (folder or base_dir()).parent / "promotion" / "state.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        logger.warning("promotion state unreadable; no reference shadow for the trial prompt")
        return {}


def review_sections(store, parent: RosterEntry, folder: Path | None = None) -> str:
    """Inheritance inputs (owner decision 2026-09-29): code-computed review facts of the
    parent's settled records, and the same facts of the best same-group shadow by
    composite score as a clearly labelled reference (its statistics, never its text).
    Each facts section is capped at review_facts.MAX_CHARS."""
    from marketmind.promotion.retirement import best_peer
    from marketmind.promotion.review_facts import format_facts, review_facts
    if store is None:
        return ""
    shadows = store.list(source_type="shadow")

    def facts(sid: str) -> str:
        return format_facts(review_facts([e for e in shadows if e.source_id == sid]))
    out = ("\n\n## 该影子复盘事实（代码计算，来自账本 review 字段）\n\n"
           + facts(parent.shadow_id))
    peer, peer_score, match = best_peer(parent, roster_mod.active(), _promotion_state(folder))
    if peer is None or match != "group":
        return out + "\n\n## 参考：同组表现最好的影子\n\n（同组还没有进入综合排名的其他影子）"
    return out + (f"\n\n## 参考：同组综合分最高的另一个影子（{peer.display_name}，综合分 "
                  f"{peer_score:.3f}）的复盘事实\n\n这是另一个影子的统计数字，不是它的方法论，"
                  f"也不是本影子的成绩；只用来说明本组里什么做法有效。\n\n"
                  + facts(peer.shadow_id))


async def _call_llm(system: str, user: str) -> str:
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_flash
    token = usage_tracker.set_stage("trial_variant")
    try:
        result = await asyncio.wait_for(chat_flash(system, user, temperature=0.3, max_tokens=8192),
                                        timeout=240)
    finally:
        usage_tracker.reset_stage(token)
    if result.get("error"):
        raise RuntimeError(f"LLM error: {result.get('error')}")
    return result.get("content") or ""


async def rewrite(original: str, system: str, user: str, call=_call_llm) -> str:
    """One LLM rewrite of a methodology, format-checked against `original` (same "## "
    headings in the same order, 0.5-2x its length). Shared by variant trials and
    retirement successors (promotion/retirement.py). Raises ValueError when rejected."""
    variant = (await call(system, user)).strip()
    variant = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", variant)
    errors = validate_variant(original, variant)
    if errors:
        raise ValueError("variant rejected: " + "; ".join(errors))
    return variant


def trial_bars_for(hold: int) -> int:
    """Trial window in trading days: 40, or 8 x the parent's median hold, at most 120."""
    return min(TRIAL_BARS_MAX, max(TRIAL_BARS, WINDOW_PER_HOLD * max(1, int(hold))))


def parent_hold(store, parent_id: str) -> int:
    """Median holding period of the parent's ledger records (1 when it has none)."""
    if store is None:
        return 1
    holds = sorted(e.hold_bars for e in store.list()
                   if e.source_type == "shadow" and e.source_id == parent_id)
    return holds[len(holds) // 2] if holds else 1


async def propose(parent_id: str, kind: str, note: str, *, store=None, call=_call_llm,
                  today: str | None = None, folder: Path | None = None) -> Trial:
    if kind not in ("challenger", "beta"):
        raise ValueError("kind must be challenger or beta")
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trials = load(folder)
    running = [t for t in trials if t.status == "running"]
    if len(running) >= MAX_RUNNING:
        raise ValueError(f"{MAX_RUNNING} trials already running")
    if any(t.parent_id == parent_id for t in running):
        raise ValueError(f"{parent_id} already has a running trial")
    recent = [t for t in trials if t.parent_id == parent_id
              and trading_days_between(t.started, today) < REPROPOSE_GAP_DAYS]
    if recent:
        raise ValueError(f"{parent_id} had a trial started on {recent[-1].started}; "
                         f"at most one per {REPROPOSE_GAP_DAYS} trading days")
    parent = roster_mod.by_id().get(parent_id)
    if parent is None or parent not in roster_mod.active():
        raise ValueError(f"{parent_id} is not an active long-term shadow")
    if not note.strip():
        raise ValueError("a change note is required")
    original = roster_mod.load_prompt(parent)
    user = (f"## 原方法论\n\n{original}\n\n## 改动说明\n\n{note}\n\n"
            f"## 该影子账本成绩\n\n{_parent_summary(store, parent_id)}"
            + review_sections(store, parent, folder))
    variant = await rewrite(original, SYSTEM_PROMPT, user, call)
    trial = Trial(uuid.uuid4().hex[:8], kind, parent_id, note.strip()[:500], today,
                  add_trading_days(today, trial_bars_for(parent_hold(store, parent_id))))
    pf = prompt_file(trial.trial_id, folder)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(variant + "\n", encoding="utf-8")
    trials.append(trial)
    save(trials, folder)
    return trial


def hac_bandwidth(overlap_lag: int, n: int) -> int:
    """Newey-West lag for the trial test: at least the holding overlap, and at least
    half the sample (fixed-b b ~ 0.5). Simulated at n=40 with overlapping fat-tailed
    P&L (2026-09-28): true-null rejections at a nominal 5% were 5.7% / 6.7% / 10% / 15%
    for holds of 1 / 5 / 10 / 20 days, against 6% / 12% / 16% / 25% with Student-t
    and lag = hold - 1. Long holds leave too few independent periods in 40 days for
    any HAC test to reach 5%."""
    return max(int(overlap_lag), n // 2 - 1, 1)


def roster_entries(folder: Path | None = None, today: str | None = None) -> list[RosterEntry]:
    """Variants that still decide today. After `ends` a trial only waits for its
    records to settle; its later decisions would not count, so it stops calling the LLM."""
    by_id = roster_mod.by_id()
    retired = roster_mod.retired_ids()      # a retired parent's trial stops calling the LLM
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for t in load(folder):
        parent = by_id.get(t.parent_id)
        pf = prompt_file(t.trial_id, folder)
        if (t.status != "running" or t.ends <= today or parent is None or not pf.exists()
                or t.parent_id in retired):
            continue
        out.append(RosterEntry(
            shadow_id=f"trial:{t.trial_id}", name=f"trial_{parent.name}_{t.trial_id[:4]}",
            display_name=f"{parent.display_name}（{t.kind} 变体）", group="trial",
            domain=parent.domain, watchlist=parent.watchlist,
            domain_benchmark=parent.domain_benchmark, news_keywords=parent.news_keywords,
            source_type="temp_shadow", prompt_text=pf.read_text(encoding="utf-8")))
    return out


def _run_date(e) -> str:
    return (e.meta or {}).get("run_date") or e.created_at[:10]


def daily_differences(store, t: Trial) -> dict:
    """Paired daily returns of a trial, aligned by exit (settlement) date.

    Rows = parent and variant records whose decision (run) date lies in
    [started, ends). Each settled record contributes its market-excess P&L,
    pnl_usd - direction * position_usd * market_return (the same capital held in the
    market benchmark over the same dates; pnl_usd when the benchmark is missing),
    booked on its exit date. Each side's series is divided by that side's average
    daily gross exposure over the paired days, sum(position_usd * hold_bars) / days,
    so it is a return per dollar deployed (fix 2026-09-29: raw P&L differences
    rewarded a variant for trading bigger or longer the market, e.g. a 5x-size copy
    of a positive-beta parent "won" in a rising market). The series runs over the
    trading calendar (exit dates of all settled ledger rows, plus both sides' own) from
    the first to the last exit of either side, days without exits count 0. Returns
    diffs (variant - parent), the HAC lag, and whether every record has settled."""
    from marketmind.promotion.metrics import trading_calendar

    def rows(source_type, source_id):
        return [e for e in store.list(source_type=source_type) if e.source_id == source_id
                and t.started <= _run_date(e) < t.ends]
    parent, variant = rows("shadow", t.parent_id), rows("temp_shadow", f"trial:{t.trial_id}")
    done = all(e.status in ("settled", "void") for e in parent + variant)

    def excess(es):
        out: dict[str, float] = {}
        gross, no_market = 0.0, 0
        for e in es:
            if e.status == "settled" and e.exit_date and e.pnl_usd is not None:
                d = e.exit_date[:10]
                sign = 1.0 if e.direction == "long" else -1.0
                if e.market_return is None:
                    no_market += 1
                    x = e.pnl_usd
                else:
                    x = e.pnl_usd - sign * e.position_usd * e.market_return
                out[d] = out.get(d, 0.0) + x
                gross += e.position_usd * max(1, e.hold_bars)
        return out, gross, no_market
    (p, p_gross, p_nm), (v, v_gross, v_nm) = excess(parent), excess(variant)
    exits = set(p) | set(v)
    holds = sorted(e.hold_bars for e in (parent or variant))
    typical = holds[len(holds) // 2] if holds else 1
    out = {"diffs": [], "days": [], "done": done, "lag": max(1, typical - 1),
           "parent_hold": typical, "parent_rows": len(parent), "variant_rows": len(variant),
           "without_market": p_nm + v_nm}
    if not exits:
        return out
    lo, hi = min(exits), max(exits)
    cal = sorted({d for d in trading_calendar(store.list(status="settled")) if lo <= d <= hi}
                 | exits)
    n = len(cal)
    p_exp, v_exp = p_gross / n, v_gross / n               # average daily gross exposure
    out.update(days=cal, parent_exposure=p_exp, variant_exposure=v_exp)
    out["diffs"] = [(v.get(d, 0.0) / v_exp if v_exp else 0.0)
                    - (p.get(d, 0.0) / p_exp if p_exp else 0.0) for d in cal]
    return out


def _wilcoxon_p(diffs: list[float]) -> float | None:
    """One-sided Wilcoxon signed-rank p (reported only, not a pass criterion)."""
    from scipy.stats import wilcoxon
    nonzero = [d for d in diffs if d != 0]
    if len(nonzero) < 2:
        return None
    try:
        return float(wilcoxon(nonzero, alternative="greater").pvalue)
    except ValueError:
        logger.warning("wilcoxon not computable", exc_info=True)
        return None


def _overlaps(a: Trial, b: Trial) -> bool:
    return a.started < b.ends and b.started < a.ends


def holm_family(t: Trial, trials: list[Trial], p_now: dict[str, float],
                untested: frozenset[str] = frozenset()) -> dict[str, float]:
    """The Holm family of trial `t` (fix 2026-09-29): every trial whose window
    [started, ends) overlaps t's, i.e. that was active at the same time. Known p-values:
    trials tested in this review (`p_now`) and earlier verdicts; trials still running
    enter with p = 1 (not yet known, so t is judged as if they will not reject).
    Trials judged without a test (insufficient data, no variation; `untested` for
    those judged in this review) are not members.
    With p = 1 for the unknown ones the adjusted p is never below the one Holm would
    give with every p known, so an early verdict cannot become too lenient later."""
    fam: dict[str, float] = {}
    for u in trials:
        if not _overlaps(t, u):
            continue
        if u.trial_id in untested:
            continue
        if u.trial_id in p_now:
            fam[u.trial_id] = p_now[u.trial_id]
        elif u.status == "running":
            fam[u.trial_id] = 1.0
        elif (u.result or {}).get("p_value") is not None and u.status != "insufficient":
            fam[u.trial_id] = float(u.result["p_value"])
    return fam


def evaluate(store, *, today: str | None = None, folder: Path | None = None) -> list[Trial]:
    """Judge running trials whose window has ended; returns the trials decided now.

    A trial is ready when its window is over and all records have settled, or the
    settlement grace period has passed. Its Holm family is `holm_family`."""
    from marketmind.promotion.metrics import hac_t_test, holm_adjust
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trials = load(folder)
    ready: list[tuple[Trial, dict]] = []
    for t in trials:
        if t.status != "running" or t.ends > today:
            continue
        paired = daily_differences(store, t)
        grace = (date.fromisoformat(today) - date.fromisoformat(t.ends)).days > SETTLE_GRACE_DAYS
        if not paired["done"] and not grace:
            continue
        diffs = paired["diffs"]
        hac = hac_t_test(diffs, hac_bandwidth(paired["lag"], len(diffs)))
        ready.append((t, {
            "test": "hac_t", "aligned_by": "exit_date", "alpha": ALPHA,
            "pairs": len(diffs), "mean_diff": (sum(diffs) / len(diffs)) if diffs else None,
            "measure": "market_excess_per_gross_dollar",
            "without_market": paired.get("without_market", 0),
            "lag": hac["lag"], "parent_hold": paired["parent_hold"],
            "t_stat": hac["t"], "se": hac["se"], "p_value": hac["p_value"],
            "inference": hac.get("inference"), "p_value_student": hac.get("p_value_student"),
            "wilcoxon_p": _wilcoxon_p(diffs),
            "first_day": paired["days"][0] if paired["days"] else None,
            "last_day": paired["days"][-1] if paired["days"] else None,
            "settled_all": paired["done"],
        }))
    tested = [(t, r) for t, r in ready if r["pairs"] >= MIN_PAIRS and r["p_value"] is not None]
    p_now = {t.trial_id: r["p_value"] for t, r in tested}
    untested = frozenset(t.trial_id for t, _ in ready) - set(p_now)
    for t, r in tested:
        fam = holm_family(t, trials, p_now, untested)
        ids = sorted(fam)
        r["p_holm"] = holm_adjust([fam[i] for i in ids])[ids.index(t.trial_id)]
        r["holm_family"], r["holm_members"] = len(ids), ids
    decided = []
    for t, r in ready:
        if r["pairs"] < MIN_PAIRS:
            t.status = "insufficient"
        elif r["p_value"] is None:
            t.status, r["note"] = "failed", "no variation in the daily P&L difference"
        else:
            t.status = "passed" if r["mean_diff"] > 0 and r["p_holm"] <= ALPHA else "failed"
        t.result = r
        t.decided_at = today
        decided.append(t)
    if decided:
        save(trials, folder)
    return decided


def resolve(trial_id: str, approve: bool, *, folder: Path | None = None,
            prompt_dir: Path | None = None) -> Trial:
    """Owner decision. Approve writes the variant over the shadow's prompt (backup kept)."""
    trials = load(folder)
    t = next((x for x in trials if x.trial_id == trial_id), None)
    if t is None:
        raise ValueError(f"no trial {trial_id}")
    if approve and t.status != "passed":
        raise ValueError(f"only a passed trial can be approved (status {t.status})")
    if t.status in ("approved", "rejected"):
        raise ValueError(f"trial already {t.status}")
    if approve:
        parent = roster_mod.by_id()[t.parent_id]
        # a retirement successor keeps its methodology in the data dir (roster.prompt_file)
        target = (parent.prompt_path if parent.prompt_file
                  else (prompt_dir or roster_mod.PROMPT_DIR) / f"{parent.name}.md")
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(target, target.with_name(f"{target.name}.{stamp}.bak"))
        target.write_text(prompt_file(t.trial_id, folder).read_text(encoding="utf-8"),
                          encoding="utf-8")
    t.status = "approved" if approve else "rejected"
    t.decided_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save(trials, folder)
    return t


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m marketmind.shadows.v3.trials")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pr = sub.add_parser("propose", help="start a beta trial for a shadow")
    pr.add_argument("shadow_id")
    pr.add_argument("--note", required=True, help="what to change in the methodology")
    for name in ("approve", "reject"):
        sub.add_parser(name).add_argument("trial_id")
    args = p.parse_args(argv)
    if args.cmd == "list":
        rows = load()
        if not rows:
            print("没有试验")
        for t in rows:
            print(f"{t.trial_id} {t.kind:10s} {t.parent_id} {t.status} {t.started}→{t.ends} {t.result}")
        return 0
    try:
        if args.cmd == "propose":
            from marketmind.config.settings import MarketMindConfig
            from marketmind.gateway.async_client import init_gateway
            from marketmind.ledger.store import LedgerStore, default_ledger_path
            cfg = MarketMindConfig()
            init_gateway(cfg.deepseek_api_key, cfg.deepseek_base_url)
            t = asyncio.run(propose(args.shadow_id, "beta", args.note,
                                    store=LedgerStore(default_ledger_path())))
            print(f"已开始 beta 试验 {t.trial_id}：{t.started} → {t.ends}")
        else:
            t = resolve(args.trial_id, approve=args.cmd == "approve")
            print(f"试验 {t.trial_id}：{t.status}" + ("（方法论已写回，请检查后提交 git）"
                                                    if t.status == "approved" else ""))
    except ValueError as e:
        print(f"拒绝：{e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
