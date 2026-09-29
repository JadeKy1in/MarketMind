"""Entry point for Windows Task Scheduler (docs/AUTOMATION.md).

  python marketmind/scripts/scheduled_run.py --slot weekday   # full pre-open run
  python marketmind/scripts/scheduled_run.py --slot weekend   # settle + crypto shadows

Several triggers may fire per day (US daylight saving moves the open by one hour,
and missed triggers catch up at wake-up); this script decides from the New York
clock whether to run and makes sure each slot runs at most once per day:
- weekday: Mon-Fri, not before 08:25 New York time (after the 08:30 data
  releases when started on schedule at 08:45). A late catch-up run still counts:
  every decision fills at the next open after it is made.
- weekend: Sat-Sun.
A failed attempt may be retried once by a later trigger. A record still marked
running whose lock is gone, whose process is dead, or which outlived its timeout
(a crash, or the machine slept mid-run) is closed as failed and reported, so the
retry is not blocked. Skipped triggers of an eligible day are recorded, and the
state file is written atomically with a last-good copy. Each run has a hard
timeout, its own log file, and a status record the dashboard reads; failures are
pushed through the configured channels (marketmind/alerts/notify.py). Exit code 3
from app.py means "finished, some steps failed": status "degraded", done for the
day (no retry), steps taken from the last "[degraded]" log line, one short push.
Pushes that fail (offline) wait in data/scheduler/push_queue.json for the next
invocation of this script or of watchdog.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

NEW_YORK = ZoneInfo("America/New_York")
WEEKDAY_EARLIEST = dtime(8, 25)
US_OPEN = dtime(9, 30)
MODES = {"weekday": "daily", "weekend": "weekend"}
TIMEOUT_S = {"weekday": 3600, "weekend": 1800}
MAX_ATTEMPTS = 2
LOCK_STALE_S = 3 * 3600


def data_dir() -> Path:
    return ROOT / os.getenv("MARKETMIND_DATA_DIR", "data")


def plan(slot: str, now: datetime) -> tuple[bool, str, str]:
    """(run?, day key, reason) for a trigger firing at `now` (aware datetime)."""
    ny = now.astimezone(NEW_YORK)
    key = f"{ny.date().isoformat()}-{slot}"
    weekend = ny.weekday() >= 5
    if slot == "weekday":
        if weekend:
            return False, key, "weekend in New York"
        if ny.time() < WEEKDAY_EARLIEST:
            return False, key, f"too early ({ny:%H:%M} New York)"
        if ny.time() >= US_OPEN:
            return True, key, f"late run ({ny:%H:%M} New York, after the open)"
        return True, key, "pre-open run"
    if slot == "weekend":
        return (True, key, "weekend run") if weekend else (False, key, "weekday in New York")
    raise ValueError(f"unknown slot {slot}")


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def load_state(path: Path) -> dict:
    """The run record; falls back to the last good copy when the main file is
    missing or unreadable, so a damaged file never causes a second run of a day."""
    for candidate in (path, _backup_path(path)):
        try:
            state = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(state, dict) and isinstance(state.get("runs"), dict):
            return state
    return {"runs": {}}


def _replace(tmp: Path, target: Path) -> None:
    # a reader (the dashboard) holding the target open makes os.replace fail on Windows
    for attempt in range(10):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def save_state(path: Path, state: dict) -> None:
    """Atomic write (temp file in the same folder, then os.replace), mirrored to
    state.json.bak as the last good copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=1)
    for target in (path, _backup_path(path)):
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        _replace(tmp, target)


MAX_SKIPS = 10


def record_skip(path: Path, key: str, now: datetime, reason: str) -> None:
    """Keep the last few skipped triggers of a day so the dashboard can show them."""
    state = load_state(path)
    rec = state["runs"].setdefault(key, {})
    rec["skips"] = (rec.get("skips", []) + [{"t": now.isoformat(timespec="seconds"),
                                              "reason": reason}])[-MAX_SKIPS:]
    save_state(path, state)


def should_attempt(state: dict, key: str) -> tuple[bool, str]:
    run = state.get("runs", {}).get(key)
    if not run or not run.get("status"):
        return True, "first attempt"
    if run.get("status") == "ok":
        return False, "already succeeded today"
    if run.get("status") == "degraded":
        return False, "already finished today (degraded)"
    if run.get("status") == "running":
        return False, "a run is in progress"
    if run.get("attempts", 0) >= MAX_ATTEMPTS:
        return False, f"gave up after {MAX_ATTEMPTS} attempts"
    return True, "retry after failure"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True,
                             text=True, timeout=30)
        return re.search(rf"\b{pid}\b", out.stdout) is not None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_lock(lock: Path) -> dict | None:
    """The lock's {pid, t}, {} when unreadable, None when there is no lock."""
    if not lock.exists():
        return None
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def lock_held(lock: Path) -> bool:
    """True while a live process holds a lock that is not stale."""
    info = read_lock(lock)
    if info is None:
        return False
    try:
        pid, t = int(info.get("pid", 0)), float(info.get("t", 0))
    except (TypeError, ValueError):
        return False
    return time.time() - t < LOCK_STALE_S and _pid_alive(pid)


def acquire_lock(lock: Path) -> bool:
    if lock_held(lock):
        return False
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "t": time.time()}), encoding="utf-8")
    return True


def stale_run_reason(rec: dict, lock: Path, now: datetime, timeout_s: int) -> str | None:
    """Why a record still marked "running" cannot belong to a live attempt
    (the process crashed, or the machine slept mid-run), or None if it may be live."""
    info = read_lock(lock)
    if info is None:
        return "previous attempt stopped without finishing (run lock missing)"
    try:
        pid = int(info.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0
    if not _pid_alive(pid):
        return f"previous attempt stopped without finishing (process {pid} not running)"
    try:
        started = datetime.fromisoformat(rec["started"])
    except (KeyError, TypeError, ValueError):
        return "previous attempt has no valid start time"
    if (now - started).total_seconds() > timeout_s + 600:
        return f"previous attempt still marked running {int((now - started).total_seconds() // 60)} minutes after start"
    return None


PUSH_VARS = ("SERVERCHAN_SENDKEY", "PUSHPLUS_TOKEN", "WECOM_WEBHOOK_KEY", "FEISHU_WEBHOOK_TOKEN",
             "FEISHU_WEBHOOK_SECRET",
             # LLM provider switch (docs/LLM_PROVIDER.md)
             "MARKETMIND_LLM", "MARKETMIND_CLAUDE_PRO_MODEL", "MARKETMIND_CLAUDE_FLASH_MODEL")


def load_user_push_env() -> None:
    """Task Scheduler may start us with an environment captured before the owner
    saved a push key or switched the LLM provider (setx / switch_llm.ps1); read
    missing ones from the user's registry settings."""
    if os.name != "nt":
        return
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
    except OSError:
        return
    for name in PUSH_VARS:
        if os.environ.get(name):
            continue
        try:
            value = winreg.QueryValueEx(key, name)[0]
        except OSError:
            continue
        if value:
            os.environ[name] = str(value)
    # the Claude CLI lives in the user's npm folder, which a scheduled task's PATH may lack
    if not os.environ.get("MARKETMIND_CLAUDE_BIN"):
        import shutil
        candidate = Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"
        if not shutil.which("claude") and candidate.exists():
            os.environ["MARKETMIND_CLAUDE_BIN"] = str(candidate)


QUEUE_MAX = 20
QUEUE_MAX_AGE_S = 3 * 86400
QUEUE_LOCK_STALE_S = 600


def queue_path() -> Path:
    return data_dir() / "scheduler" / "push_queue.json"


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    _replace(tmp, path)


def load_queue(path: Path) -> list[dict]:
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _prune_queue(items: list[dict], now: float) -> list[dict]:
    """Drop entries older than three days, keep the newest QUEUE_MAX."""
    fresh = [i for i in items if isinstance(i.get("t"), (int, float))
             and now - i["t"] <= QUEUE_MAX_AGE_S]
    return fresh[-QUEUE_MAX:]


def enqueue_push(title: str, body: str, now: float | None = None) -> None:
    """Keep an undelivered push for the next scheduled_run / watchdog invocation."""
    now = time.time() if now is None else now
    path = queue_path()
    items = load_queue(path) + [{"id": uuid.uuid4().hex, "t": now, "title": title, "body": body}]
    _write_json(path, _prune_queue(items, now))


def _send(title: str, body: str) -> list[dict]:
    from marketmind.alerts.notify import send
    return asyncio.run(send(title, body))


def _delivered(results: list[dict]) -> bool:
    return any(r.get("ok") for r in results)


def push(title: str, body: str) -> list[dict]:
    """Send through the configured channels; if every channel failed (offline),
    queue the message for a later retry. With no channel configured nothing is
    queued (it could never be delivered)."""
    try:
        results = _send(title, body)
    except Exception as e:                       # never mask the caller's own failure
        print(f"notification not sent: {type(e).__name__}")
        results = [{"channel": "?", "ok": False, "status": 0}]
    if results and not _delivered(results):
        try:
            enqueue_push(title, body)
            print("notification queued for retry")
        except OSError as e:
            print(f"notification could not be queued: {type(e).__name__}")
    return results


def flush_push_queue(now: float | None = None) -> int:
    """Retry queued pushes, oldest first; stops at the first failure (still offline).
    One process at a time (push_queue.lock) so a message is not sent twice.
    Returns the number delivered."""
    now = time.time() if now is None else now
    path = queue_path()
    if not load_queue(path):
        return 0
    lock = path.with_name("push_queue.lock")
    try:
        if lock.exists() and now - lock.stat().st_mtime > QUEUE_LOCK_STALE_S:
            lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return 0                                 # another process is flushing
    sent: set[str] = set()
    try:
        os.close(fd)
        load_user_push_env()
        for item in _prune_queue(load_queue(path), now):
            try:
                ok = _delivered(_send(str(item.get("title", "")), str(item.get("body", ""))))
            except Exception as e:
                print(f"queued notification not sent: {type(e).__name__}")
                ok = False
            if not ok:
                break
            sent.add(item.get("id"))
        # re-read: another process may have queued a message meanwhile
        _write_json(path, _prune_queue([i for i in load_queue(path) if i.get("id") not in sent], now))
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    if sent:
        print(f"delivered {len(sent)} queued notification(s)")
    return len(sent)


def notify_failure(slot: str, key: str, log_path: Path, reason: str) -> list[dict]:
    from marketmind.notification.log_redaction import redact
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
    except OSError:
        tail = []
    body = f"{key}（{slot}）自动运行失败：{reason}\n日志：{log_path}\n\n" + redact("\n".join(tail))
    return push("MarketMind 自动运行失败", body[:1800])


EXIT_DEGRADED = 3
DEGRADED_PREFIX = "[degraded]"


def degraded_detail(log_path: Path, start: int = 0) -> str:
    """Text after the last "[degraded]" line this attempt wrote (from byte `start`)."""
    try:
        with log_path.open("rb") as f:
            f.seek(start)
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        line = line.strip()
        if line.startswith(DEGRADED_PREFIX):
            return line[len(DEGRADED_PREFIX):].strip(" :")[:500]
    return ""


def split_steps(detail: str) -> list[str]:
    return [s.strip() for s in re.split(r"[,;，；]", detail) if s.strip()]


def notify_degraded(slot: str, key: str, log_path: Path, detail: str) -> list[dict]:
    from marketmind.notification.log_redaction import redact
    body = f"{key}（{slot}）已完成，但部分步骤失败：{redact(detail) or '未列出'}\n日志：{log_path}"
    return push("MarketMind 自动运行部分失败", body[:600])


def recover_stale_run(slot: str, key: str, state_path: Path, reason: str) -> dict:
    """Close a "running" record left by a crashed attempt as failed and report it,
    so a later trigger may retry (still bounded by MAX_ATTEMPTS)."""
    state = load_state(state_path)
    rec = state["runs"][key]
    rec.update(status="failed", reason=reason,
               ended=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    save_state(state_path, state)
    log_path = Path(rec.get("log") or data_dir() / "logs" / "scheduled" / f"{key}.log")
    rec["notified"] = notify_failure(slot, key, log_path, reason)
    save_state(state_path, state)
    return state


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slot", choices=sorted(MODES), required=True)
    p.add_argument("--dry-run", action="store_true", help="print the decision only")
    args = p.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    if not args.dry_run:
        load_user_push_env()                     # failure pushes and the run need the keys
        flush_push_queue()
    run, key, reason = plan(args.slot, now)
    sched = data_dir() / "scheduler"
    state_path = sched / "state.json"
    lock = sched / "run.lock"
    state = load_state(state_path)
    if run:
        prev = state["runs"].get(key, {})
        stale = (stale_run_reason(prev, lock, now, TIMEOUT_S[args.slot])
                 if prev.get("status") == "running" else None)
        if stale:
            print(f"{key}: {stale}")
            if args.dry_run:
                state = {"runs": {**state["runs"], key: {**prev, "status": "failed"}}}
            else:
                state = recover_stale_run(args.slot, key, state_path, stale)
    ok, why = should_attempt(state, key) if run else (False, reason)
    print(f"{now.isoformat(timespec='seconds')} {key}: {'run' if ok else 'skip'} ({why})")
    if args.dry_run:
        return 0
    if not ok:
        if run:                                  # an eligible day: show the skip on the dashboard
            record_skip(state_path, key, now, why)
        return 0
    if not acquire_lock(lock):
        print("another scheduled run holds the lock; skipping")
        record_skip(state_path, key, now, "another run holds the lock")
        return 0
    try:
        return _run_locked(args.slot, key, now, state_path)
    finally:                                     # released only after the final state write
        try:
            lock.unlink()
        except OSError:
            pass


def _run_locked(slot: str, key: str, now: datetime, state_path: Path) -> int:
    state = load_state(state_path)               # re-check: another trigger may have finished
    ok, why = should_attempt(state, key)
    if not ok:
        print(f"{key}: skip ({why})")
        record_skip(state_path, key, now, why)
        return 0
    log_dir = data_dir() / "logs" / "scheduled"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{key}.log"
    log_start = log_path.stat().st_size if log_path.exists() else 0
    rec = state["runs"].setdefault(key, {})
    for stale in ("degraded", "degraded_steps"):
        rec.pop(stale, None)
    rec.update(status="running", started=now.isoformat(timespec="seconds"),
               mode=MODES[slot], log=str(log_path), attempts=rec.get("attempts", 0) + 1)
    save_state(state_path, state)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(ROOT / "marketmind" / "app.py"), "--mode", MODES[slot]]
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n===== {now.isoformat(timespec='seconds')} attempt {rec['attempts']}: "
                      f"{' '.join(cmd[1:])}\n")
            log.flush()
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S[slot])
        code, failure = proc.returncode, (None if proc.returncode == 0 else f"exit code {proc.returncode}")
    except subprocess.TimeoutExpired:
        code, failure = -1, f"timed out after {TIMEOUT_S[slot] // 60} minutes"
    except Exception as e:
        code, failure = -1, f"{type(e).__name__}: {e}"

    status = "ok" if failure is None else "failed"
    if code == EXIT_DEGRADED:                    # finished, some steps failed: done for the day
        status, failure = "degraded", None
        detail = degraded_detail(log_path, log_start)
        rec.update(degraded=detail, degraded_steps=split_steps(detail))
    rec.update(status=status, exit_code=code, reason=failure,
               ended=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if status == "degraded":
        rec["reason"] = f"degraded: {rec['degraded'] or 'steps not listed'}"   # shown on the dashboard
        rec["notified"] = notify_degraded(slot, key, log_path, rec["degraded"])
    elif failure:
        rec["notified"] = notify_failure(slot, key, log_path, failure)
    state = load_state(state_path)               # merge: the other slot may have written meanwhile
    latest = state["runs"].get(key, {})
    for field in ("skips", "watchdog_notified"):  # written by other triggers / the watchdog
        if latest.get(field):
            rec[field] = latest[field]
    state["runs"][key] = rec
    state["runs"] = dict(sorted(state["runs"].items())[-60:])     # keep about two months
    save_state(state_path, state)
    print(f"{key}: {rec['status']}" + (f" ({rec['reason']})" if rec.get("reason") else ""))
    return 0 if failure is None else 1


if __name__ == "__main__":
    sys.exit(main())
