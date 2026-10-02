"""Re-register MarketMind's scheduled tasks when they are missing (docs/AUTOMATION.md).

  pythonw marketmind/scripts/ensure_tasks.py            # check; re-register + one push
  python marketmind/scripts/ensure_tasks.py --dry-run   # print what is missing only

2026-10-02: every task under \\MarketMind\\ was deleted at once (360 Total Security
suspected) and nothing ran until the owner noticed. This check starts from a shortcut
in the user's Startup folder, created by install_schedule.ps1: outside Task Scheduler,
so it is not wiped together with the tasks. At each logon it queries the four tasks;
if any is missing it runs install_schedule.ps1 (timeout, exit code checked), checks
again and sends one push through scheduled_run.push (queued when offline). Quiet and
idempotent when everything is in place.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketmind.scripts import scheduled_run as sr  # noqa: E402

FOLDER = "\\MarketMind\\"
TASKS = ("Daily", "Weekend", "Watchdog", "Dashboard")
INSTALLER = ROOT / "marketmind" / "scripts" / "install_schedule.ps1"
QUERY_TIMEOUT_S = 30
INSTALL_TIMEOUT_S = 300
# no console window flashing up when started from pythonw
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class QueryError(RuntimeError):
    """Task Scheduler could not be asked (schtasks missing, timed out)."""


def task_exists(name: str, run=subprocess.run) -> bool:
    """schtasks exits 0 when the task exists, 1 when it does not."""
    try:
        out = run(["schtasks", "/Query", "/TN", FOLDER + name], capture_output=True, text=True,
                  timeout=QUERY_TIMEOUT_S, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise QueryError(f"schtasks query of {name} failed: {type(e).__name__}") from e
    return out.returncode == 0


def missing_tasks(run=subprocess.run) -> list[str]:
    return [t for t in TASKS if not task_exists(t, run=run)]


def reinstall(run=subprocess.run) -> str | None:
    """Run install_schedule.ps1; None on success, else why it failed."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(INSTALLER)]
    try:
        out = run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S,
                  creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"install_schedule.ps1 timed out after {INSTALL_TIMEOUT_S} s"
    except OSError as e:
        return f"install_schedule.ps1 not started ({type(e).__name__}: {e})"
    if out.returncode != 0:
        tail = " ".join(((out.stderr or "") + " " + (out.stdout or "")).split())[-300:]
        return f"install_schedule.ps1 exit code {out.returncode}: {tail}"
    return None


def _log(line: str) -> None:
    """pythonw has no console: actions also go to data/logs/ensure_tasks.log."""
    print(line)
    try:
        path = sr.data_dir() / "logs" / "ensure_tasks.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {line}\n")
    except OSError as e:
        print(f"ensure_tasks log not written: {type(e).__name__}")


def ensure(dry_run: bool = False, run=subprocess.run) -> dict:
    """Check the tasks, re-register when any is missing; returns what happened."""
    try:
        missing = missing_tasks(run=run)
    except QueryError as e:
        _log(f"check skipped: {e}")
        return {"missing": None, "error": str(e)}
    if not missing:
        return {"missing": []}                                  # quiet: all four exist
    _log(f"missing tasks: {', '.join(missing)}")
    if dry_run:
        return {"missing": missing}
    error = reinstall(run=run)
    if error is None:
        try:
            still = missing_tasks(run=run)
        except QueryError as e:
            still, error = None, str(e)
        if still:
            error = f"still missing after install_schedule.ps1: {', '.join(still)}"
    names = ", ".join(missing)
    if error is None:
        _log("re-registered by install_schedule.ps1")
        title = "MarketMind: 计划任务已自动恢复"
        body = (f"任务计划程序 {FOLDER} 下缺少 {names}，已重新注册。"
                "可能是 360 等安全软件清理所致，请在其中信任 MarketMind 的计划任务。")
    else:
        _log(f"re-registration failed: {error}")
        title = "MarketMind: 计划任务缺失，自动恢复失败"
        body = (f"任务计划程序 {FOLDER} 下缺少 {names}，自动重新注册失败：{error}\n"
                "请手动运行 marketmind\\scripts\\install_schedule.ps1。")
    sr.load_user_push_env()
    sr.push(title, body[:600])
    return {"missing": missing, "error": error}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print missing tasks only")
    args = p.parse_args(argv)
    if os.name != "nt":
        print("Task Scheduler check is Windows-only")
        return 0
    result = ensure(dry_run=args.dry_run)
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
