"""Missed-run watchdog (docs/AUTOMATION.md).

  python marketmind/scripts/watchdog.py            # check and push
  python marketmind/scripts/watchdog.py --dry-run  # print the decision only

Task Scheduler starts it at logon and on wake from sleep. It looks at the most
recent New York weekday, and the most recent weekend day, whose run window has
passed (12:30 New York on that date: the last trigger plus the run timeout). If
that day's record in data/scheduler/state.json is missing, failed, given up, or
still marked running although the run is gone, it pushes one notification
"MarketMind: <date> daily run did not complete: <reason>" and records
`watchdog_notified` on that day, so each missed day is reported at most once.
Days before the first day any trigger fired (automation not installed yet) are
not checked.
Missed starts are caught up by the regular triggers. A run that was interrupted
after the day's last trigger (on 2026-09-30 a restart killed it at 12:44 New York and
no trigger was left) is caught up here: before checking, if today's slot is still
runnable (scheduled_run.plan) and its record is a dead "running" or a failure with an
attempt left, the watchdog runs scheduled_run for that slot in this process (its lock,
attempt limit and network check apply). It also retries pushes queued while offline.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketmind.scripts import scheduled_run as sr  # noqa: E402

DEADLINE_NY = dtime(12, 30)
LABELS = {"weekday": "daily", "weekend": "weekend"}


def due_keys(now: datetime) -> list[tuple[str, str, date]]:
    """(slot, key, New York date) of the latest weekday and weekend day whose
    run window has passed at `now`."""
    ny = now.astimezone(sr.NEW_YORK)
    last = ny.date() if ny.time() >= DEADLINE_NY else ny.date() - timedelta(days=1)
    weekday, weekend = last, last
    while weekday.weekday() >= 5:
        weekday -= timedelta(days=1)
    while weekend.weekday() < 5:
        weekend -= timedelta(days=1)
    return [("weekday", f"{weekday.isoformat()}-weekday", weekday),
            ("weekend", f"{weekend.isoformat()}-weekend", weekend)]


def missed_reason(rec: dict, slot: str, lock: Path, now: datetime) -> str | None:
    """Why the day's run did not complete, or None if it did (or may still be running)."""
    status = rec.get("status")
    if not status:
        skips = rec.get("skips") or []
        last = f" (last skipped trigger: {skips[-1].get('reason')})" if skips else ""
        return "no run was started" + last
    if status in ("ok", "degraded"):
        return None
    if status == "running":
        return sr.stale_run_reason(rec, lock, now, sr.TIMEOUT_S[slot])
    if status == "failed":
        why = rec.get("reason") or "unknown error"
        attempts = rec.get("attempts", 0)
        if attempts >= sr.MAX_ATTEMPTS:
            return f"gave up after {attempts} attempts ({why})"
        return f"failed ({why})"
    return f"unexpected status {status!r}"


def first_day(runs: dict) -> date | None:
    """Earliest New York date on which a run was recorded or a trigger fired;
    records the watchdog itself created do not count."""
    days = [date.fromisoformat(key[:10]) for key, rec in runs.items()
            if rec.get("status") or rec.get("skips")]
    return min(days) if days else None


def check(now: datetime, dry_run: bool = False) -> list[dict]:
    """Push one notification per missed day not yet reported; returns what was found."""
    sched = sr.data_dir() / "scheduler"
    state_path, lock = sched / "state.json", sched / "run.lock"
    state = sr.load_state(state_path)
    if not state["runs"]:
        print("no scheduled run recorded yet; nothing to check")
        return []
    found, first = [], first_day(state["runs"])
    for slot, key, day in due_keys(now):
        if first is None or day < first:
            continue                                    # before automation was installed
        rec = state["runs"].get(key, {})
        if rec.get("watchdog_notified"):
            continue
        reason = missed_reason(rec, slot, lock, now)
        if reason is None:
            print(f"{key}: completed or in progress")
            continue
        title = f"MarketMind: {day.isoformat()} {LABELS[slot]} run did not complete"
        print(f"{title}: {reason}")
        found.append({"key": key, "reason": reason})
        if dry_run:
            continue
        results = sr.push(title, f"{title}: {reason}")
        state = sr.load_state(state_path)        # re-read: a run may have written meanwhile
        state["runs"].setdefault(key, {})["watchdog_notified"] = {
            "t": now.isoformat(timespec="seconds"), "reason": reason, "sent": results}
        sr.save_state(state_path, state)
    return found


def catch_up_slot(now: datetime) -> str | None:
    """Today's slot whose run was interrupted or failed and may be retried now."""
    sched = sr.data_dir() / "scheduler"
    state = sr.load_state(sched / "state.json")
    for slot in sr.MODES:
        run, key, _ = sr.plan(slot, now)
        if not run:
            continue
        rec = state["runs"].get(key, {})
        if rec.get("status") == "running" and sr.stale_run_reason(
                rec, sched / "run.lock", now, sr.TIMEOUT_S[slot]):
            return slot
        if rec.get("status") == "failed" and rec.get("attempts", 0) < sr.MAX_ATTEMPTS:
            return slot
    return None


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print the decision only")
    args = p.parse_args(argv)
    fixed_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if not args.dry_run:
        sr.load_user_push_env()
        sr.flush_push_queue()
    slot = catch_up_slot(now)
    if slot:
        print(f"catch-up: today's {LABELS[slot]} run was interrupted or failed")
        if args.dry_run:
            sr.main(["--slot", slot, "--dry-run"], now=now)
        else:
            sr.main(["--slot", slot], now=now)
            if not fixed_clock:                     # the run took a while
                now = datetime.now(timezone.utc)
    check(now, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
