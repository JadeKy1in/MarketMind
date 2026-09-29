"""Scheduled runs (docs/AUTOMATION.md): New York clock, once per day, retries, lock."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from marketmind.scripts import scheduled_run as sr

_REAL_LOAD_USER_PUSH_ENV = sr.load_user_push_env


@pytest.fixture(autouse=True)
def _no_real_push(monkeypatch):
    """Never read the owner's push keys or reach a push channel from a test."""
    monkeypatch.setattr(sr, "load_user_push_env", lambda: None)

    def refuse(title, body):
        raise AssertionError("a test tried to send a real notification")
    monkeypatch.setattr(sr, "_send", refuse)


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


def _setup_running(tmp_path, monkeypatch, started, lock_pid, key="2026-09-28-weekday"):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, key, "test"))
    sched = tmp_path / "data" / "scheduler"
    sr.save_state(sched / "state.json", {"runs": {key: {
        "status": "running", "attempts": 1, "mode": "daily", "started": started.isoformat(),
        "log": str(tmp_path / "old.log")}}})
    if lock_pid is not None:
        (sched / "run.lock").write_text(json.dumps({"pid": lock_pid, "t": started.timestamp()}),
                                        encoding="utf-8")
    calls, sent = [], []

    class Done:
        returncode = 0
    monkeypatch.setattr(sr.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    monkeypatch.setattr(sr, "notify_failure", lambda *a: sent.append(a) or [])
    return sched / "state.json", calls, sent


def test_stale_running_with_dead_pid_is_failed_notified_and_retried(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    state_path, calls, sent = _setup_running(tmp_path, monkeypatch, now, lock_pid=424242)
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: pid == os.getpid())
    assert sr.main(["--slot", "weekday"]) == 0
    run = json.loads(state_path.read_text("utf-8"))["runs"]["2026-09-28-weekday"]
    assert len(sent) == 1 and "424242 not running" in sent[0][3]
    assert len(calls) == 1 and run["status"] == "ok" and run["attempts"] == 2


def test_stale_running_with_missing_lock_is_retried(tmp_path, monkeypatch):
    state_path, calls, sent = _setup_running(tmp_path, monkeypatch, datetime.now(timezone.utc),
                                             lock_pid=None)
    assert sr.main(["--slot", "weekday"]) == 0
    assert len(sent) == 1 and "lock missing" in sent[0][3] and len(calls) == 1


def test_running_past_timeout_is_failed_but_attempts_are_bounded(tmp_path, monkeypatch):
    started = datetime.now(timezone.utc) - timedelta(seconds=sr.TIMEOUT_S["weekday"] + 700)
    state_path, calls, sent = _setup_running(tmp_path, monkeypatch, started, lock_pid=os.getpid())
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(sr, "LOCK_STALE_S", 60)             # the old lock has expired too
    state = sr.load_state(state_path)
    state["runs"]["2026-09-28-weekday"]["attempts"] = sr.MAX_ATTEMPTS
    sr.save_state(state_path, state)
    assert sr.main(["--slot", "weekday"]) == 0
    run = json.loads(state_path.read_text("utf-8"))["runs"]["2026-09-28-weekday"]
    assert run["status"] == "failed" and "minutes after start" in run["reason"]
    assert len(sent) == 1 and calls == []                  # gave up: no third attempt
    assert run["skips"][-1]["reason"].startswith("gave up")


def test_genuinely_running_attempt_is_still_skipped(tmp_path, monkeypatch):
    state_path, calls, sent = _setup_running(tmp_path, monkeypatch, datetime.now(timezone.utc),
                                             lock_pid=os.getpid())
    monkeypatch.setattr(sr, "_pid_alive", lambda pid: True)
    assert sr.main(["--slot", "weekday"]) == 0
    run = json.loads(state_path.read_text("utf-8"))["runs"]["2026-09-28-weekday"]
    assert calls == [] and sent == [] and run["status"] == "running"
    assert run["skips"][0]["reason"] == "a run is in progress"


def test_dry_run_does_not_touch_a_stale_record(tmp_path, monkeypatch):
    state_path, calls, sent = _setup_running(tmp_path, monkeypatch, datetime.now(timezone.utc),
                                             lock_pid=None)
    before = state_path.read_text("utf-8")
    assert sr.main(["--slot", "weekday", "--dry-run"]) == 0
    assert state_path.read_text("utf-8") == before and sent == [] and calls == []


def test_state_writes_are_atomic_and_keep_a_backup(tmp_path):
    path = tmp_path / "state.json"
    sr.save_state(path, {"runs": {"2026-09-28-weekday": {"status": "ok", "attempts": 1}}})
    assert (tmp_path / "state.json.bak").exists()
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
    path.write_text('{"runs": {"2026-09-28-wee', encoding="utf-8")      # truncated
    assert not sr.should_attempt(sr.load_state(path), "2026-09-28-weekday")[0]
    path.unlink()
    assert sr.load_state(path)["runs"]["2026-09-28-weekday"]["status"] == "ok"
    (tmp_path / "state.json.bak").write_text("[]", encoding="utf-8")
    assert sr.load_state(path) == {"runs": {}}


def test_corrupt_state_does_not_rerun_a_finished_day(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, "2026-09-28-weekday", "test"))
    calls = []

    class Done:
        returncode = 0
    monkeypatch.setattr(sr.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    assert sr.main(["--slot", "weekday"]) == 0 and len(calls) == 1
    state_path = tmp_path / "data" / "scheduler" / "state.json"
    state_path.write_bytes(state_path.read_bytes()[:20])
    assert sr.main(["--slot", "weekday"]) == 0 and len(calls) == 1


def test_skips_are_recorded_and_capped(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    now = datetime.now(timezone.utc)
    for i in range(sr.MAX_SKIPS + 5):
        sr.record_skip(path, "2026-09-28-weekday", now, f"reason {i}")
    rec = sr.load_state(path)["runs"]["2026-09-28-weekday"]
    assert len(rec["skips"]) == sr.MAX_SKIPS and rec["skips"][-1]["reason"] == f"reason {sr.MAX_SKIPS + 4}"
    assert sr.should_attempt({"runs": {"2026-09-28-weekday": rec}}, "2026-09-28-weekday") == (True, "first attempt")


def test_lock_holder_skip_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, "2026-09-28-weekday", "test"))
    monkeypatch.setattr(sr, "acquire_lock", lambda lock: False)
    assert sr.main(["--slot", "weekday"]) == 0
    rec = sr.load_state(tmp_path / "data" / "scheduler" / "state.json")["runs"]["2026-09-28-weekday"]
    assert "status" not in rec and rec["skips"][0]["reason"] == "another run holds the lock"


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


def test_push_keys_loaded_from_user_environment(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows registry only")
    import winreg

    class FakeKey:
        pass
    monkeypatch.delenv("SERVERCHAN_SENDKEY", raising=False)
    monkeypatch.setattr(winreg, "OpenKey", lambda *a: FakeKey())

    def query(key, name):
        if name == "SERVERCHAN_SENDKEY":
            return ("SCTtest", 1)
        raise OSError
    monkeypatch.setattr(winreg, "QueryValueEx", query)
    _REAL_LOAD_USER_PUSH_ENV()
    assert os.environ["SERVERCHAN_SENDKEY"] == "SCTtest"


# ── push queue ─────────────────────────────────────────────────────────

def _queue_env(tmp_path, monkeypatch, outcomes):
    """outcomes: list of results per _send call (a list of dicts, or an exception)."""
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    sent = []

    def fake_send(title, body):
        sent.append(title)
        out = outcomes.pop(0) if outcomes else [{"channel": "serverchan", "ok": True, "status": 200}]
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(sr, "_send", fake_send)
    return sent


OFFLINE = [{"channel": "serverchan", "ok": False, "status": 0}]
DELIVERED = [{"channel": "serverchan", "ok": True, "status": 200}]


def test_failed_push_is_queued_and_delivered_next_time(tmp_path, monkeypatch):
    sent = _queue_env(tmp_path, monkeypatch, [OFFLINE, ConnectionError("offline")])
    sr.push("t1", "b1")
    sr.push("t2", "b2")
    q = sr.load_queue(sr.queue_path())
    assert [i["title"] for i in q] == ["t1", "t2"]
    assert [p.name for p in sr.queue_path().parent.iterdir() if p.suffix == ".tmp"] == []
    assert sr.flush_push_queue() == 2 and sent == ["t1", "t2", "t1", "t2"]
    assert sr.load_queue(sr.queue_path()) == []
    assert not sr.queue_path().with_name("push_queue.lock").exists()


def test_push_without_channels_or_with_one_channel_ok_is_not_queued(tmp_path, monkeypatch):
    _queue_env(tmp_path, monkeypatch, [[], OFFLINE + DELIVERED])
    sr.push("no channel", "b")
    sr.push("partly delivered", "b")
    assert sr.load_queue(sr.queue_path()) == []


def test_flush_stops_at_first_failure_and_keeps_order(tmp_path, monkeypatch):
    sent = _queue_env(tmp_path, monkeypatch, [DELIVERED, OFFLINE])
    now = time.time()
    for i in range(3):
        sr.enqueue_push(f"t{i}", "b", now=now + i)
    assert sr.flush_push_queue(now=now + 10) == 1 and sent == ["t0", "t1"]
    assert [i["title"] for i in sr.load_queue(sr.queue_path())] == ["t1", "t2"]


def test_queue_is_capped_and_old_entries_dropped(tmp_path, monkeypatch):
    sent = _queue_env(tmp_path, monkeypatch, [])
    now = time.time()
    sr.enqueue_push("old", "b", now=now - sr.QUEUE_MAX_AGE_S - 60)
    for i in range(sr.QUEUE_MAX + 5):
        sr.enqueue_push(f"t{i}", "b", now=now)
    q = sr.load_queue(sr.queue_path())
    assert len(q) == sr.QUEUE_MAX and q[0]["title"] == "t5"
    # entries that age out while queued are dropped at flush, not sent
    assert sr.flush_push_queue(now=now + sr.QUEUE_MAX_AGE_S + 60) == 0 and sent == []
    assert sr.load_queue(sr.queue_path()) == []


def test_flush_skips_while_another_process_flushes(tmp_path, monkeypatch):
    sent = _queue_env(tmp_path, monkeypatch, [])
    sr.enqueue_push("t", "b")
    lock = sr.queue_path().with_name("push_queue.lock")
    lock.write_text("", encoding="utf-8")
    assert sr.flush_push_queue() == 0 and sent == []
    os.utime(lock, (time.time() - sr.QUEUE_LOCK_STALE_S - 5,) * 2)     # stale lock
    assert sr.flush_push_queue() == 1 and sent == ["t"]


def test_scheduled_run_retries_the_queue_first(tmp_path, monkeypatch):
    sent = _queue_env(tmp_path, monkeypatch, [])
    sr.enqueue_push("queued", "b")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (False, "2026-10-03-weekday", "weekend in New York"))
    assert sr.main(["--slot", "weekday"]) == 0 and sent == ["queued"]
    assert sr.main(["--slot", "weekday", "--dry-run"]) == 0 and sent == ["queued"]


# ── degraded exit code ─────────────────────────────────────────────────

def _degraded_env(tmp_path, monkeypatch, key="2026-09-28-weekday", lines=(), code=3):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "plan", lambda slot, now: (True, key, "test"))
    calls, pushed = [], []

    class Done:
        returncode = code

    def fake_run(cmd, stdout=None, **kw):
        calls.append(cmd)
        for line in lines:
            stdout.write(line + "\n")
        return Done()
    monkeypatch.setattr(sr.subprocess, "run", fake_run)
    monkeypatch.setattr(sr, "push", lambda title, body: pushed.append((title, body)) or [])
    return tmp_path / "data" / "scheduler" / "state.json", calls, pushed


def test_exit_code_3_is_degraded_done_for_the_day(tmp_path, monkeypatch):
    state_path, calls, pushed = _degraded_env(tmp_path, monkeypatch, lines=[
        "[degraded] old line", "step output", "[degraded] news, evidence; alerts", "done"])
    assert sr.main(["--slot", "weekday"]) == 0
    run = sr.load_state(state_path)["runs"]["2026-09-28-weekday"]
    assert run["status"] == "degraded" and run["exit_code"] == 3
    assert run["degraded_steps"] == ["news", "evidence", "alerts"]
    assert run["reason"] == "degraded: news, evidence; alerts"
    assert len(pushed) == 1 and "news, evidence; alerts" in pushed[0][1]
    assert sr.main(["--slot", "weekday"]) == 0 and len(calls) == 1       # no retry
    assert sr.load_state(state_path)["runs"]["2026-09-28-weekday"]["skips"][-1]["reason"] \
        == "already finished today (degraded)"


def test_degraded_line_is_read_from_this_attempt_only(tmp_path, monkeypatch):
    state_path, calls, pushed = _degraded_env(tmp_path, monkeypatch, lines=["no marker"])
    log = tmp_path / "data" / "logs" / "scheduled" / "2026-09-28-weekday.log"
    log.parent.mkdir(parents=True)
    log.write_text("[degraded] from an earlier attempt\n", encoding="utf-8")
    assert sr.main(["--slot", "weekday"]) == 0
    run = sr.load_state(state_path)["runs"]["2026-09-28-weekday"]
    assert run["status"] == "degraded" and run["degraded_steps"] == []
    assert len(pushed) == 1


def test_other_nonzero_exit_is_still_a_failure(tmp_path, monkeypatch):
    state_path, calls, pushed = _degraded_env(tmp_path, monkeypatch, code=2,
                                              lines=["[degraded] news"])
    monkeypatch.setattr(sr, "notify_failure", lambda *a: pushed.append(a) or [])
    assert sr.main(["--slot", "weekday"]) == 1
    run = sr.load_state(state_path)["runs"]["2026-09-28-weekday"]
    assert run["status"] == "failed" and "degraded_steps" not in run and len(pushed) == 1


# ── the three weekday triggers (15:45 / 16:45 / 17:45 Riyadh) ──────────

def _trigger_day(tmp_path, monkeypatch, codes):
    """Run main() at the three weekday trigger times; `codes` are the app exit codes
    of the attempts actually started."""
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setenv("MARKETMIND_DATA_DIR", "data")
    monkeypatch.setattr(sr, "notify_failure", lambda *a: [])
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class Done:
            returncode = codes[len(calls) - 1]
        return Done()
    monkeypatch.setattr(sr.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize("day,first_attempt_utc", [
    ((2026, 9, 29), 12),       # US daylight time: 15:45 Riyadh = 08:45 New York
    ((2026, 12, 1), 13),       # US standard time: 15:45 Riyadh = 07:45 New York (too early)
])
def test_later_trigger_retries_a_failed_run_in_both_dst_regimes(tmp_path, monkeypatch, day,
                                                                 first_attempt_utc):
    calls = _trigger_day(tmp_path, monkeypatch, codes=[1, 0])
    key = f"{day[0]}-{day[1]:02d}-{day[2]:02d}-weekday"
    for hour in (12, 13, 14):                    # 15:45, 16:45, 17:45 Riyadh (UTC+3)
        now = utc(*day, hour, 45)
        run, k, _ = sr.plan("weekday", now)
        assert k == key and run is (hour >= first_attempt_utc)
        assert sr.main(["--slot", "weekday"], now=now) in (0, 1)
    rec = sr.load_state(tmp_path / "data" / "scheduler" / "state.json")["runs"][key]
    assert len(calls) == 2 and rec["status"] == "ok" and rec["attempts"] == 2
    if first_attempt_utc == 12:                  # daylight: the 17:45 trigger found it done
        assert rec["skips"][-1]["reason"] == "already succeeded today"
    else:                                        # standard: 15:45 was too early (not an attempt)
        assert "skips" not in rec


def test_17_45_trigger_is_a_late_catch_up_for_the_same_new_york_day():
    for day in ((2026, 9, 29), (2026, 12, 1)):
        run, key, reason = sr.plan("weekday", utc(*day, 14, 45))
        assert run and key.startswith(f"{day[0]}-{day[1]:02d}-{day[2]:02d}")
    assert "late run (10:45" in sr.plan("weekday", utc(2026, 9, 29, 14, 45))[2]
    assert "late run (09:45" in sr.plan("weekday", utc(2026, 12, 1, 14, 45))[2]


def test_at_most_two_attempts_even_with_three_triggers(tmp_path, monkeypatch):
    calls = _trigger_day(tmp_path, monkeypatch, codes=[1, 1])
    for hour in (12, 13, 14):
        sr.main(["--slot", "weekday"], now=utc(2026, 9, 29, hour, 45))
    rec = sr.load_state(tmp_path / "data" / "scheduler" / "state.json")["runs"]["2026-09-29-weekday"]
    assert len(calls) == 2 and rec["status"] == "failed" and rec["attempts"] == 2
    assert rec["skips"][-1]["reason"].startswith("gave up")


def test_second_weekend_trigger_retries_a_failed_weekend_run(tmp_path, monkeypatch):
    calls = _trigger_day(tmp_path, monkeypatch, codes=[1, 0])
    for hour in (9, 11):                         # Saturday 12:00 and 14:00 Riyadh
        sr.main(["--slot", "weekend"], now=utc(2026, 10, 3, hour, 0))
    rec = sr.load_state(tmp_path / "data" / "scheduler" / "state.json")["runs"]["2026-10-03-weekend"]
    assert len(calls) == 2 and rec["status"] == "ok" and calls[0][-1] == "weekend"
