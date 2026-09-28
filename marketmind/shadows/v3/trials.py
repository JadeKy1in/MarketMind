"""Variant trials: challenger and beta as one mechanism (docs/S7_DESIGN.md §二, SPEC_v3 §6.3, C19, C30).

A trial runs a rewritten methodology for a long-term shadow side by side with
the original for TRIAL_BARS trading days (source_id trial:<id>). When every
record has settled, both sides' daily P&L (booked on the exit date, / $10,000
notional, as in the promotion ladder) is differenced day by day and tested
one-sided with a HAC (Newey-West) t-test, lag = parent's median hold - 1 (>= 1),
i.e. a Diebold-Mariano test. Trials decided in the same review form one family:
Holm-adjusted p <= ALPHA passes. Wilcoxon is reported only as a robustness
statistic. A passing trial only becomes "passed"; the owner must approve it
before the prompt file changes (SPEC L1).

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
MIN_PAIRS = 30                   # exit-date days in the paired P&L series (was 5)
ALPHA = 0.05                     # one-sided, family-wise via Holm (was p < 0.10 per trial)
SETTLE_GRACE_DAYS = 60           # give up waiting for open records after this

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
    parent = roster_mod.by_id().get(parent_id)
    if parent is None or parent not in roster_mod.active():
        raise ValueError(f"{parent_id} is not an active long-term shadow")
    if not note.strip():
        raise ValueError("a change note is required")
    original = roster_mod.load_prompt(parent)
    user = (f"## 原方法论\n\n{original}\n\n## 改动说明\n\n{note}\n\n"
            f"## 该影子账本成绩\n\n{_parent_summary(store, parent_id)}")
    variant = (await call(SYSTEM_PROMPT, user)).strip()
    variant = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", variant)
    errors = validate_variant(original, variant)
    if errors:
        raise ValueError("variant rejected: " + "; ".join(errors))
    trial = Trial(uuid.uuid4().hex[:8], kind, parent_id, note.strip()[:500], today,
                  add_trading_days(today, TRIAL_BARS))
    pf = prompt_file(trial.trial_id, folder)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(variant + "\n", encoding="utf-8")
    trials.append(trial)
    save(trials, folder)
    return trial


def roster_entries(folder: Path | None = None, today: str | None = None) -> list[RosterEntry]:
    """Variants that still decide today. After `ends` a trial only waits for its
    records to settle; its later decisions would not count, so it stops calling the LLM."""
    by_id = roster_mod.by_id()
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for t in load(folder):
        parent = by_id.get(t.parent_id)
        pf = prompt_file(t.trial_id, folder)
        if t.status != "running" or t.ends <= today or parent is None or not pf.exists():
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
    """Paired daily P&L of a trial, aligned by exit (settlement) date.

    Rows = parent and variant records whose decision (run) date lies in
    [started, ends). Each side's settled P&L is booked on its exit date / notional
    (promotion ladder convention); the series runs over the trading calendar (exit
    dates of all settled ledger rows, plus both sides' own) from the first to the last
    exit of either side, days without exits count 0. Returns diffs (variant - parent),
    the HAC lag, and whether every record has settled."""
    from marketmind.promotion import config as PC
    from marketmind.promotion.metrics import trading_calendar

    def rows(source_type, source_id):
        return [e for e in store.list(source_type=source_type) if e.source_id == source_id
                and t.started <= _run_date(e) < t.ends]
    parent, variant = rows("shadow", t.parent_id), rows("temp_shadow", f"trial:{t.trial_id}")
    done = all(e.status in ("settled", "void") for e in parent + variant)

    def pnl(es):
        out: dict[str, float] = {}
        for e in es:
            if e.status == "settled" and e.exit_date and e.pnl_usd is not None:
                d = e.exit_date[:10]
                out[d] = out.get(d, 0.0) + e.pnl_usd / PC.NOTIONAL_USD
        return out
    p, v = pnl(parent), pnl(variant)
    exits = set(p) | set(v)
    holds = sorted(e.hold_bars for e in (parent or variant))
    typical = holds[len(holds) // 2] if holds else 1
    out = {"diffs": [], "days": [], "done": done, "lag": max(1, typical - 1),
           "parent_hold": typical, "parent_rows": len(parent), "variant_rows": len(variant)}
    if not exits:
        return out
    lo, hi = min(exits), max(exits)
    cal = sorted({d for d in trading_calendar(store.list(status="settled")) if lo <= d <= hi}
                 | exits)
    out["days"] = cal
    out["diffs"] = [v.get(d, 0.0) - p.get(d, 0.0) for d in cal]
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


def evaluate(store, *, today: str | None = None, folder: Path | None = None) -> list[Trial]:
    """Judge running trials whose window has ended; returns the trials decided now.

    Every trial ready in this call (window over and all records settled, or the
    settlement grace period passed) belongs to one Holm family."""
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
        hac = hac_t_test(diffs, paired["lag"])
        ready.append((t, {
            "test": "hac_t", "aligned_by": "exit_date", "alpha": ALPHA,
            "pairs": len(diffs), "mean_diff": (sum(diffs) / len(diffs)) if diffs else None,
            "lag": hac["lag"], "parent_hold": paired["parent_hold"],
            "t_stat": hac["t"], "se": hac["se"], "p_value": hac["p_value"],
            "wilcoxon_p": _wilcoxon_p(diffs),
            "first_day": paired["days"][0] if paired["days"] else None,
            "last_day": paired["days"][-1] if paired["days"] else None,
            "settled_all": paired["done"],
        }))
    tested = [(t, r) for t, r in ready if r["pairs"] >= MIN_PAIRS and r["p_value"] is not None]
    adjusted = holm_adjust([r["p_value"] for _, r in tested])
    for (t, r), p_holm in zip(tested, adjusted):
        r["p_holm"], r["holm_family"] = p_holm, len(tested)
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
        target = (prompt_dir or roster_mod.PROMPT_DIR) / f"{parent.name}.md"
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
