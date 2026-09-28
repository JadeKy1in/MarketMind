"""Scheduled runs (docs/AUTOMATION.md): New York clock, once per day, retries, lock."""
import json
import os
from datetime import datetime, timezone

import pytest

from marketmind.scripts import scheduled_run as sr


def utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_weekday_window_follows_new_york_daylight_saving():
    # 2026-09-28 (Mon), EDT: 12:45 UTC = 08:45 NY -> run; 11:45 UTC = 07:45 -> too early
    assert sr.plan("weekday", utc(2026, 9, 28, 12, 45))[0] is True
    assert sr.plan("weekday", utc(2026, 9, 28, 11, 45))[0] is False
    # 2026-12-01 (Tue), EST: the 12:45 UTC trigger is 07:45 NY -> skip, 13:45 runs
    assert sr.plan("weekday", utc(2026, 12, 1, 12, 45))[0] is False
    ok, key, _ = sr.plan("weekday", utc(2026, 12, 1, 13, 45))
    assert ok and key == "2026-12-01-weekday"
    # late catch-up on the same New York day still runs
    assert sr.plan("weekday", utc(2026, 9, 28, 23, 0))[0] is True


def test_weekend_slot_uses_new_york_calendar():
    assert sr.plan("weekend", utc(2026, 10, 3, 9, 0))[0] is True        # Sat
    assert sr.plan("weekday", utc(2026, 10, 3, 14, 0))[0] is False
    # Monday 02:00 UTC is still Sunday evening in New York
    assert sr.plan("weekend", utc(2026, 10, 5, 2, 0))[0] is True
    assert sr.plan("weekend", utc(2026, 10, 5, 13, 0))[0] is False


def test_should_attempt_once_per_day_with_one_retry():
    key = "2026-09-28-weekday"
    assert sr.should_attempt({"runs": {}}, key)[0]
    assert not sr.should_attempt({"runs": {key: {"status": "ok"}}}, key)[0]
    assert not sr.should_attempt({"runs": {key: {"status": "running"}}}, key)[0]
    assert sr.should_attempt({"runs": {key: {"status": "failed", "attempts": 1}}}, key)[0]
    assert not sr.should_attempt({"runs": {key: {"status": "failed", "attempts": 2}}}, key)[0]


def test_lock_blocks_live_pid_and_recovers_stale(tmp_path):
    lock = tmp_path / "run.lock"
    assert sr.acquire_lock(lock)
    assert not sr.acquire_lock(lock)                       # held by this (alive) process
    lock.write_text(json.dumps({"pid": 999999, "t": 0}), encoding="utf-8")
    assert sr.acquire_lock(lock)                           # dead pid, stale time


def test_run_records_status_and_skips_second_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, "2026-09-28-weekday", "test"))
    calls = []

    class Done:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Done()
    monkeypatch.setattr(sr.subprocess, "run", fake_run)
    assert sr.main(["--slot", "weekday"]) == 0
    state = json.loads((tmp_path / "data" / "scheduler" / "state.json").read_text("utf-8"))
    run = state["runs"]["2026-09-28-weekday"]
    assert run["status"] == "ok" and run["attempts"] == 1 and calls[0][-2:] == ["--mode", "daily"]
    assert sr.main(["--slot", "weekday"]) == 0 and len(calls) == 1
    assert not (tmp_path / "data" / "scheduler" / "run.lock").exists()


def test_failure_is_recorded_and_notified(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, "2026-10-03-weekend", "test"))

    def boom(cmd, **kw):
        raise sr.subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(sr.subprocess, "run", boom)
    sent = []
    monkeypatch.setattr(sr, "notify_failure", lambda *a: sent.append(a) or [])
    assert sr.main(["--slot", "weekend"]) == 1
    run = json.loads((tmp_path / "data" / "scheduler" / "state.json").read_text("utf-8"))["runs"]["2026-10-03-weekend"]
    assert run["status"] == "failed" and "timed out" in run["reason"] and len(sent) == 1


def test_dashboard_reads_scheduler_state(tmp_path, monkeypatch):
    from marketmind.api import whitebox
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    (tmp_path / "scheduler").mkdir()
    (tmp_path / "scheduler" / "state.json").write_text(json.dumps({"runs": {
        "2026-09-28-weekday": {"mode": "daily", "status": "ok", "started": "2026-09-28T12:45:00+00:00"},
        "2026-09-27-weekend": {"mode": "weekend", "status": "failed", "started": "2026-09-27T09:00:00+00:00",
                               "reason": "exit code 1"}}}), encoding="utf-8")
    rows = whitebox.read_scheduler()
    assert [r["key"] for r in rows] == ["2026-09-28-weekday", "2026-09-27-weekend"]


def test_crypto_shadows_for_weekend():
    from marketmind.pipeline.orchestration import crypto_shadows
    ids = {e.shadow_id for e in crypto_shadows()}
    assert ids == {"expert:crypto:chain_oracle", "expert:crypto:defi_scout"}
