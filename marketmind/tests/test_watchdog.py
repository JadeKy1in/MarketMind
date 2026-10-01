"""Missed-run watchdog (docs/AUTOMATION.md): fake clock, fake notifier; it starts a run
only to catch up today's interrupted or failed one."""
import json
import os
from datetime import date, datetime, timezone

import pytest

from marketmind.scripts import scheduled_run as sr
from marketmind.scripts import watchdog as wd


def utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "load_user_push_env", lambda: None)
    monkeypatch.setattr(sr, "online", lambda *a, **k: True)       # never probe the network
    pushed, started = [], []
    monkeypatch.setattr(sr, "_send", lambda title, body: pushed.append(body) or
                        [{"channel": "serverchan", "ok": True, "status": 200}])
    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **kw: started.append(a))
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: pid == os.getpid())
    state_path = tmp_path / "data" / "scheduler" / "state.json"

    def write(runs):
        sr.save_state(state_path, {"runs": runs})
    return state_path, write, pushed, started


def test_due_keys_pick_the_latest_days_whose_window_has_passed():
    # Tue 2026-09-29 18:00 Riyadh = 11:00 New York: today's window is still open
    assert wd.due_keys(utc(2026, 9, 29, 15, 0)) == [
        ("weekday", "2026-09-28-weekday", date(2026, 9, 28)),
        ("weekend", "2026-09-27-weekend", date(2026, 9, 27))]
    # 20:00 Riyadh = 13:00 New York: today counts
    assert wd.due_keys(utc(2026, 9, 29, 17, 0))[0][1] == "2026-09-29-weekday"
    # Monday morning Riyadh (Sunday night New York): Friday and Sunday
    keys = [k for _, k, _ in wd.due_keys(utc(2026, 10, 5, 5, 0))]
    assert keys == ["2026-10-02-weekday", "2026-10-04-weekend"]
    # US standard time: 12:30 New York = 17:30 UTC
    assert wd.due_keys(utc(2026, 12, 1, 17, 29))[0][1] == "2026-11-30-weekday"
    assert wd.due_keys(utc(2026, 12, 1, 17, 31))[0][1] == "2026-12-01-weekday"


def test_missing_failed_and_given_up_days_are_reported_once(env):
    state_path, write, pushed, started = env
    write({"2026-09-29-weekday": {"skips": [{"t": "x", "reason": "another run holds the lock"}]},
           "2026-09-27-weekend": {"status": "failed", "attempts": 2, "reason": "exit code 1"}})
    now = utc(2026, 9, 29, 20, 0)
    assert wd.main([], now=now) == 0
    assert pushed == [
        "MarketMind: 2026-09-29 daily run did not complete: no run was started "
        "(last skipped trigger: another run holds the lock)",
        "MarketMind: 2026-09-27 weekend run did not complete: gave up after 2 attempts (exit code 1)"]
    runs = sr.load_state(state_path)["runs"]
    assert runs["2026-09-29-weekday"]["watchdog_notified"]["reason"].startswith("no run")
    assert "status" not in runs["2026-09-29-weekday"]          # the watchdog does not run anything
    assert wd.main([], now=utc(2026, 9, 29, 22, 0)) == 0 and len(pushed) == 2   # once per key
    assert started == []


def test_missing_record_is_reported(env):
    state_path, write, pushed, _ = env
    write({"2026-09-28-weekday": {"status": "ok"}, "2026-09-27-weekend": {"status": "ok"}})
    wd.main([], now=utc(2026, 9, 29, 20, 0))
    assert pushed == ["MarketMind: 2026-09-29 daily run did not complete: no run was started"]


def test_completed_degraded_and_live_runs_are_not_reported(env):
    state_path, write, pushed, _ = env
    now = utc(2026, 9, 29, 20, 0)
    write({"2026-09-29-weekday": {"status": "running", "started": now.isoformat(), "attempts": 1},
           "2026-09-27-weekend": {"status": "degraded"}})
    (state_path.parent / "run.lock").write_text(json.dumps({"pid": os.getpid(), "t": 0}),
                                                encoding="utf-8")
    wd.main([], now=now)
    assert pushed == []
    assert "watchdog_notified" not in sr.load_state(state_path)["runs"]["2026-09-29-weekday"]


def test_retryable_failure_and_dead_running_record_are_reported(env):
    state_path, write, pushed, _ = env
    now = utc(2026, 9, 30, 5, 0)        # 01:00 New York next day: too late to catch up 09-29
    write({"2026-09-29-weekday": {"status": "failed", "attempts": 1, "reason": "timed out after 60 minutes"},
           "2026-09-27-weekend": {"status": "running", "started": "2026-09-27T09:00:00+00:00"}})
    wd.main([], now=now)                                        # no run.lock: the run is gone
    assert pushed[0].endswith("failed (timed out after 60 minutes)")
    assert "run lock missing" in pushed[1]


def test_fresh_install_and_dry_run_push_nothing(env):
    state_path, write, pushed, _ = env
    assert wd.main([], now=utc(2026, 9, 29, 20, 0)) == 0 and pushed == []   # no state yet
    write({"2026-09-28-weekday": {"status": "ok"}})
    before = state_path.read_text("utf-8")
    found = wd.check(utc(2026, 9, 29, 20, 0), dry_run=True)
    # the 09-27 weekend predates the first recorded run (09-28): not checked
    assert [f["key"] for f in found] == ["2026-09-29-weekday"]
    assert pushed == [] and state_path.read_text("utf-8") == before


def test_days_before_the_first_recorded_run_are_not_reported(env):
    state_path, write, pushed, _ = env
    # only a watchdog note on an earlier day: it does not count as installed
    write({"2026-09-26-weekend": {"watchdog_notified": {"t": "x", "reason": "r", "sent": []}},
           "2026-09-29-weekday": {"status": "ok"}})
    wd.main([], now=utc(2026, 9, 30, 20, 0))
    assert pushed == ["MarketMind: 2026-09-30 daily run did not complete: no run was started"]
    runs = sr.load_state(state_path)["runs"]
    assert "2026-09-27-weekend" not in runs


def test_offline_watchdog_push_is_queued_and_not_repeated(env, monkeypatch):
    state_path, write, pushed, _ = env
    write({"2026-09-28-weekday": {"status": "ok"}, "2026-09-27-weekend": {"status": "ok"}})
    monkeypatch.setattr(sr, "_send", lambda title, body: pushed.append(body) or
                        [{"channel": "serverchan", "ok": False, "status": 0}])
    wd.main([], now=utc(2026, 9, 29, 20, 0))
    assert len(sr.load_queue(sr.queue_path())) == 1
    # next invocation: the queue is retried (still offline), the key is not pushed again
    wd.main([], now=utc(2026, 9, 29, 21, 0))
    assert len(pushed) == 2 and len(sr.load_queue(sr.queue_path())) == 1


def test_run_finishing_after_the_watchdog_keeps_its_note(tmp_path, monkeypatch, env):
    state_path, write, pushed, _ = env
    key = "2026-09-29-weekday"
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, key, "test"))

    class Done:
        returncode = 0

    def run_and_watchdog(cmd, **kw):                            # watchdog fires mid-run
        state = sr.load_state(state_path)
        state["runs"][key]["watchdog_notified"] = {"t": "x", "reason": "r", "sent": []}
        sr.save_state(state_path, state)
        return Done()
    monkeypatch.setattr(sr.subprocess, "run", run_and_watchdog)
    assert sr.main(["--slot", "weekday"]) == 0
    rec = sr.load_state(state_path)["runs"][key]
    assert rec["status"] == "ok" and rec["watchdog_notified"]["reason"] == "r"


class _Done:
    returncode = 0


def test_interrupted_run_today_is_caught_up_not_reported(env, monkeypatch):
    """2026-09-30: a restart at 12:44 New York killed the run after the last trigger."""
    state_path, write, pushed, started = env
    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **kw: started.append(a) or _Done())
    write({"2026-09-29-weekday": {"status": "ok"},
           "2026-09-30-weekday": {"status": "running", "attempts": 1,
                                  "started": "2026-09-30T16:39:15+00:00"}})   # no run.lock: dead
    assert wd.main([], now=utc(2026, 9, 30, 17, 0)) == 0      # 13:00 New York, after logon
    rec = sr.load_state(state_path)["runs"]["2026-09-30-weekday"]
    assert len(started) == 1 and rec["status"] == "ok" and rec["attempts"] == 2
    assert "watchdog_notified" not in rec                      # caught up: nothing to report
    assert not any("did not complete" in p for p in pushed)


def test_no_catch_up_when_given_up_finished_too_early_or_dry_run(env, monkeypatch):
    state_path, write, pushed, started = env
    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **kw: started.append(a) or _Done())
    write({"2026-09-29-weekday": {"status": "failed", "attempts": 2, "reason": "x"}})
    wd.main([], now=utc(2026, 9, 29, 20, 0))                   # gave up: report only
    write({"2026-09-30-weekday": {"status": "ok"}})
    wd.main([], now=utc(2026, 9, 30, 20, 0))                   # already done
    write({"2026-10-01-weekday": {"status": "failed", "attempts": 1, "reason": "x"}})
    wd.main([], now=utc(2026, 10, 1, 11, 0))                   # 07:00 New York: too early
    wd.main(["--dry-run"], now=utc(2026, 10, 1, 17, 0))        # dry run never starts
    assert started == []
    assert wd.catch_up_slot(utc(2026, 10, 1, 17, 0)) == "weekday"
