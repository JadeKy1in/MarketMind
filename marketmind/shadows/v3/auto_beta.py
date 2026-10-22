"""Automatic beta trials on the weekend run (docs/S9_DESIGN.md 第 1 步, owner decision 2026-10-22).

Once per weekend (ISO week; the weekend run runs on Saturday and Sunday), code picks the
worst long-term shadows by ledger facts and starts a beta trial for each through
trials.propose (same rewrite prompt with code-computed review facts, same limits:
MAX_RUNNING concurrent trials, REPROPOSE_GAP_DAYS per parent).

Selection (pure code):
- active long-term shadows (retired ones are not active), no running trial, no trial
  started within REPROPOSE_GAP_DAYS trading days;
- at least MIN_SETTLED settled rows over at least MIN_DAYS distinct decision days;
- mean excess return < 0 (excess vs the domain benchmark, else vs the market, else net);
- ranked by that mean excess ascending, ties by mean Brier descending;
- at most PER_RUN new trials per weekend and never more than MAX_RUNNING running.

The change note is written by code from the parent's own facts (mean excess, Brier,
win rate, most frequent error_class). A trial that passes is only "passed"; approval
stays with the owner (`python -m marketmind.shadows.v3.trials approve <id>`);
notify_passed pushes the request to WeChat.

Switch: MARKETMIND_AUTO_BETA ("0" / "off" / "false" / "no" turns it off; default on).
Idempotent: data/trials/auto_beta.json records each finished week; a rerun of the same
week (the 14:00 retry, Sunday's run, a resumed attempt) proposes nothing. A week whose
LLM rewrite failed is not marked, so the next weekend run retries it.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean

from marketmind.shadows.v3 import roster as roster_mod
from marketmind.shadows.v3 import trials as trials_mod

logger = logging.getLogger("marketmind.shadows.v3.auto_beta")

ENV_SWITCH = "MARKETMIND_AUTO_BETA"
MIN_SETTLED = 10
MIN_DAYS = 5
PER_RUN = 2

CLASS_HINTS = {
    "thesis_wrong": "最常见的结果是论点本身错了（thesis_wrong）：提高入场论点的证据要求，删掉证据不足时的入场理由。",
    "right_but_stopped": "最常见的结果是止损后原持有期内又到了目标（right_but_stopped）：止损过紧，按 ATR 放宽止损或缩短持有期。",
    "cost_flipped": "最常见的结果是毛赚、扣成本后亏（cost_flipped）：目标太近，提高最低目标距离或减少低波动标的。",
    "beta_carried": "最常见的结果是赚了但没跑赢市场基准（beta_carried）：选股没有超额，要求相对基准的理由。",
    "win": "多数记录净赚，但平均超额为负：亏损单的幅度太大，收紧最大亏损或减少逆势单。",
}


def enabled() -> bool:
    return os.getenv(ENV_SWITCH, "").strip().lower() not in ("0", "off", "false", "no")


def week_key(today: str) -> str:
    y, w, _ = date.fromisoformat(today).isocalendar()
    return f"{y}-W{w:02d}"


def _marker_path(folder: Path | None) -> Path:
    return (folder or trials_mod.base_dir()) / "auto_beta.json"


def _load_marker(folder: Path | None) -> dict:
    p = _marker_path(folder)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        logger.warning("auto-beta marker %s unreadable; treated as empty", p)
        return {}


def _excess(e) -> float | None:
    for v in (e.excess_domain, e.excess_market, e.net_return):
        if v is not None:
            return float(v)
    return None


def shadow_facts(rows) -> dict:
    settled = [e for e in rows if e.status == "settled" and e.net_return is not None]
    days = {(e.meta or {}).get("run_date") or e.created_at[:10] for e in settled}
    ex = [x for x in (_excess(e) for e in settled) if x is not None]
    briers = [e.brier for e in settled if e.brier is not None and not e.confidence_is_default]
    classes: dict[str, int] = {}
    for e in settled:
        c = (e.review or {}).get("error_class") if isinstance(e.review, dict) else None
        if c:
            classes[c] = classes.get(c, 0) + 1
    return {"settled": len(settled), "days": len(days),
            "mean_excess": mean(ex) if ex else None,
            "mean_brier": mean(briers) if briers else None,
            "win_rate": (sum(1 for e in settled if e.net_return > 0) / len(settled)) if settled else None,
            "top_class": max(sorted(classes), key=classes.get) if classes else None}


def candidates(store, *, today: str, folder: Path | None = None) -> list[dict]:
    """Eligible parents, worst first (no LLM, no writes)."""
    existing = trials_mod.load(folder)
    busy = {t.parent_id for t in existing if t.status == "running"}
    recent = {t.parent_id for t in existing
              if trials_mod.trading_days_between(t.started, today) < trials_mod.REPROPOSE_GAP_DAYS}
    by_src: dict[str, list] = {}
    for e in store.list(source_type="shadow"):
        by_src.setdefault(e.source_id, []).append(e)
    out = []
    for r in roster_mod.active():
        if r.shadow_id in busy or r.shadow_id in recent:
            continue
        f = shadow_facts(by_src.get(r.shadow_id, []))
        if f["settled"] < MIN_SETTLED or f["days"] < MIN_DAYS:
            continue
        if f["mean_excess"] is None or f["mean_excess"] >= 0:
            continue
        out.append({"shadow_id": r.shadow_id, **f})
    out.sort(key=lambda c: (c["mean_excess"], -(c["mean_brier"] or 0.0), c["shadow_id"]))
    return out


def change_note(c: dict) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v * 100:.2f}%"
    brier = "n/a" if c["mean_brier"] is None else f"{c['mean_brier']:.3f}"
    note = (f"[auto beta {c.get('week', '')}] 代码事实：{c['settled']} 条已结算、{c['days']} 个决策日，"
            f"平均超额收益 {pct(c['mean_excess'])}，胜率 {pct(c['win_rate'])}，平均 Brier {brier}。")
    return note + CLASS_HINTS.get(c.get("top_class"), "针对最弱的指标修改方法论。")


async def run(store, *, today: str | None = None, folder: Path | None = None,
              call=None, dry_run: bool = False) -> dict:
    """Propose this weekend's beta trials. Returns {status, week, proposed, skipped, errors}."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week = week_key(today)
    res = {"week": week, "proposed": [], "errors": [], "candidates": []}
    if not enabled():
        return {**res, "status": "disabled"}
    marker = _load_marker(folder)
    if week in marker and not dry_run:
        return {**res, "status": "already_done", "proposed": marker[week].get("proposed", [])}
    running = sum(1 for t in trials_mod.load(folder) if t.status == "running")
    slots = max(0, min(PER_RUN, trials_mod.MAX_RUNNING - running))
    cands = candidates(store, today=today, folder=folder)
    res["candidates"] = [c["shadow_id"] for c in cands]
    res["slots"] = slots
    if dry_run:
        return {**res, "status": "dry_run", "would_propose": res["candidates"][:slots],
                "facts": cands[:max(slots, 5)]}
    for c in cands:
        if len(res["proposed"]) >= slots:
            break
        try:
            kw = {"store": store, "today": today, "folder": folder}
            if call is not None:
                kw["call"] = call
            t = await trials_mod.propose(c["shadow_id"], "beta", change_note({**c, "week": week}), **kw)
            res["proposed"].append({"trial_id": t.trial_id, "parent_id": t.parent_id})
        except ValueError as e:          # refused by a limit or the format check
            logger.info("auto beta for %s not started: %s", c["shadow_id"], e)
            res["errors"].append({"shadow_id": c["shadow_id"], "error": str(e)[:200]})
        except Exception as e:           # LLM / network: retried next weekend run
            logger.warning("auto beta for %s failed", c["shadow_id"], exc_info=True)
            res["errors"].append({"shadow_id": c["shadow_id"], "error": type(e).__name__,
                                  "transient": True})
    if any(e.get("transient") for e in res["errors"]):
        return {**res, "status": "retry"}
    marker[week] = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "proposed": res["proposed"]}
    p = _marker_path(folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(sorted(marker.items())[-26:]), ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return {**res, "status": "done"}


def approval_message(t) -> tuple[str, str]:
    r = t.result or {}
    title = f"MarketMind 试验通过，待批准 {t.trial_id}"
    body = (f"{t.kind} 试验 {t.trial_id}（{t.parent_id}）判定通过：配对天数 {r.get('pairs')}，"
            f"日均差 {r.get('mean_diff')}，Holm 调整后 p = {r.get('p_holm')}。\n\n"
            f"改动说明：{t.note}\n\n"
            f"变体方法论：data/trials/{t.trial_id}/prompt.md\n\n"
            f"批准（写回方法论）：`python -m marketmind.shadows.v3.trials approve {t.trial_id}`\n\n"
            f"驳回：`python -m marketmind.shadows.v3.trials reject {t.trial_id}`\n\n"
            "系统不会自动采用，需要所有人批准。")
    return title, body


async def notify_passed(decided, send=None, enqueue=None) -> list[str]:
    """Push one approval request per newly passed trial; a push no channel delivered
    goes to the scheduler's retry queue. Returns the notified trial ids."""
    if send is None:
        from marketmind.alerts.notify import send
    out = []
    for t in decided:
        if t.status != "passed":
            continue
        title, body = approval_message(t)
        try:
            sent = await send(title, body)
        except Exception:
            logger.warning("approval push for %s failed", t.trial_id, exc_info=True)
            sent = [{"ok": False}]
        if sent and not any(r.get("ok") for r in sent):   # no channel configured: nothing to retry
            try:
                if enqueue is None:
                    from marketmind.scripts.scheduled_run import enqueue_push as enqueue
                enqueue(title, body)
            except OSError as e:
                logger.warning("approval push for %s not queued: %s", t.trial_id, type(e).__name__)
        out.append(t.trial_id)
    return out
