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
A failed attempt may be retried once by a later trigger. Each run has a hard
timeout, its own log file, and a status record the dashboard reads; failures are
pushed through the configured channels (marketmind/alerts/notify.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

NEW_YORK = ZoneInfo("America/New_York")
WEEKDAY_EARLIEST = dtime(8, 25)
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
        return True, key, "pre-open run"
    if slot == "weekend":
        return (True, key, "weekend run") if weekend else (False, key, "weekday in New York")
    raise ValueError(f"unknown slot {slot}")


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"runs": {}}


def should_attempt(state: dict, key: str) -> tuple[bool, str]:
    run = state.get("runs", {}).get(key)
    if not run:
        return True, "first attempt"
    if run.get("status") == "ok":
        return False, "already succeeded today"
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
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(lock: Path) -> bool:
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        fresh = time.time() - info.get("t", 0) < LOCK_STALE_S
        if fresh and _pid_alive(int(info.get("pid", 0))):
            return False
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "t": time.time()}), encoding="utf-8")
    return True


PUSH_VARS = ("SERVERCHAN_SENDKEY", "PUSHPLUS_TOKEN", "WECOM_WEBHOOK_KEY", "FEISHU_WEBHOOK_TOKEN",
             "FEISHU_WEBHOOK_SECRET")


def load_user_push_env() -> None:
    """Task Scheduler may start us with an environment captured before the owner
    saved a push key (setx); read missing ones from the user's registry settings."""
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


def notify_failure(slot: str, key: str, log_path: Path, reason: str) -> list[dict]:
    from marketmind.alerts.notify import send
    from marketmind.notification.log_redaction import redact
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
    except OSError:
        tail = []
    body = f"{key}（{slot}）自动运行失败：{reason}\n日志：{log_path}\n\n" + redact("\n".join(tail))
    try:
        return asyncio.run(send("MarketMind 自动运行失败", body[:1800]))
    except Exception as e:                       # never mask the original failure
        print(f"failure notification not sent: {type(e).__name__}")
        return []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slot", choices=sorted(MODES), required=True)
    p.add_argument("--dry-run", action="store_true", help="print the decision only")
    args = p.parse_args(argv)

    now = datetime.now(timezone.utc)
    run, key, reason = plan(args.slot, now)
    sched = data_dir() / "scheduler"
    state_path = sched / "state.json"
    state = load_state(state_path)
    ok, why = should_attempt(state, key) if run else (False, reason)
    print(f"{now.isoformat(timespec='seconds')} {key}: {'run' if ok else 'skip'} ({why})")
    if not ok or args.dry_run:
        return 0
    lock = sched / "run.lock"
    if not acquire_lock(lock):
        print("another scheduled run holds the lock; skipping")
        return 0

    log_dir = data_dir() / "logs" / "scheduled"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{key}.log"
    rec = state.setdefault("runs", {}).setdefault(key, {"attempts": 0})
    rec.update(status="running", started=now.isoformat(timespec="seconds"),
               mode=MODES[args.slot], log=str(log_path), attempts=rec.get("attempts", 0) + 1)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    load_user_push_env()                         # alerts and failure pushes need the keys
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(ROOT / "marketmind" / "app.py"), "--mode", MODES[args.slot]]
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n===== {now.isoformat(timespec='seconds')} attempt {rec['attempts']}: "
                      f"{' '.join(cmd[1:])}\n")
            log.flush()
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S[args.slot])
        code, failure = proc.returncode, (None if proc.returncode == 0 else f"exit code {proc.returncode}")
    except subprocess.TimeoutExpired:
        code, failure = -1, f"timed out after {TIMEOUT_S[args.slot] // 60} minutes"
    except Exception as e:
        code, failure = -1, f"{type(e).__name__}: {e}"
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    rec.update(status="ok" if failure is None else "failed", exit_code=code, reason=failure,
               ended=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if failure:
        rec["notified"] = notify_failure(args.slot, key, log_path, failure)
    state = load_state(state_path) | {"runs": {**load_state(state_path).get("runs", {}), key: rec}}
    runs = dict(sorted(state["runs"].items())[-60:])          # keep about two months
    state_path.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{key}: {rec['status']}" + (f" ({failure})" if failure else ""))
    return 0 if failure is None else 1


if __name__ == "__main__":
    sys.exit(main())
