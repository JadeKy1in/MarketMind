"""Scheduled-task self-check (docs/AUTOMATION.md; 2026-10-02 all MarketMind tasks were deleted)."""
from pathlib import Path

import pytest

from marketmind.scripts import ensure_tasks as et
from marketmind.scripts import scheduled_run as sr


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeWindows:
    """schtasks / powershell stand-in: `present` tasks exist; the installer adds all four."""

    def __init__(self, present=et.TASKS, install_code=0, install_adds=True):
        self.present, self.install_code, self.install_adds = set(present), install_code, install_adds
        self.installs = 0

    def __call__(self, cmd, **kw):
        assert kw.get("timeout"), "every external command needs a timeout"
        if cmd[0] == "schtasks":
            return Proc(0 if cmd[3].rsplit("\\", 1)[-1] in self.present else 1)
        self.installs += 1
        if self.install_adds and self.install_code == 0:
            self.present = set(et.TASKS)
        return Proc(self.install_code, stderr="Register-ScheduledTask : Access is denied.")


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(sr, "load_user_push_env", lambda: None)
    monkeypatch.setattr(sr, "push", lambda title, body: sent.append((title, body)) or [])
    return sent


def test_quiet_when_all_tasks_exist(pushes):
    win = FakeWindows()
    assert et.ensure(run=win) == {"missing": []}
    assert win.installs == 0 and pushes == []
    assert not (sr.data_dir() / "logs" / "ensure_tasks.log").exists()


def test_missing_tasks_are_reinstalled_and_reported_once(pushes):
    win = FakeWindows(present=())
    result = et.ensure(run=win)
    assert result == {"missing": list(et.TASKS), "error": None}
    assert win.installs == 1 and len(pushes) == 1 and "已自动恢复" in pushes[0][0]
    assert "Daily, Weekend, Watchdog, Dashboard" in pushes[0][1]
    assert "re-registered" in (sr.data_dir() / "logs" / "ensure_tasks.log").read_text("utf-8")
    assert et.ensure(run=win) == {"missing": []} and len(pushes) == 1     # idempotent


def test_failed_install_is_reported(pushes):
    win = FakeWindows(present=("Daily",), install_code=1)
    result = et.ensure(run=win)
    assert "exit code 1" in result["error"] and "Access is denied" in result["error"]
    assert len(pushes) == 1 and "自动恢复失败" in pushes[0][0]


def test_install_that_registers_nothing_is_a_failure(pushes):
    result = et.ensure(run=FakeWindows(present=("Daily",), install_adds=False))
    assert "still missing" in result["error"] and len(pushes) == 1


def test_install_timeout_is_handled(pushes):
    def run(cmd, **kw):
        if cmd[0] == "schtasks":
            return Proc(1)
        raise et.subprocess.TimeoutExpired(cmd, kw["timeout"])
    assert "timed out" in et.ensure(run=run)["error"] and len(pushes) == 1


def test_unanswered_query_never_reinstalls(pushes):
    def run(cmd, **kw):
        raise FileNotFoundError("schtasks")
    result = et.ensure(run=run)
    assert result["missing"] is None and pushes == []


def test_dry_run_only_reports(pushes):
    win = FakeWindows(present=())
    assert et.ensure(dry_run=True, run=win)["missing"] == list(et.TASKS)
    assert win.installs == 0 and pushes == []


def test_installer_creates_and_uninstaller_removes_the_startup_check():
    scripts = Path(et.__file__).parent
    install = (scripts / "install_schedule.ps1").read_text(encoding="utf-8")
    uninstall = (scripts / "uninstall_schedule.ps1").read_text(encoding="utf-8")
    assert 'GetFolderPath("Startup")' in install and "ensure_tasks.py" in install
    assert "MarketMind task check.lnk" in install and "MarketMind task check.lnk" in uninstall
    # the shortcut goes first, or a logon in between would re-register the tasks
    assert uninstall.index("Remove-Item") < uninstall.index("Unregister-ScheduledTask")
