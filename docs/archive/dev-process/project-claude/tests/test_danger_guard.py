"""PICA-Unit: danger_guard.py"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path("E:/AI_Studio_Workspace/.claude/hooks/danger_guard.py")


def run_guard(tool_name, command="", file_path=""):
    """Run danger_guard with simulated PreToolUse input."""
    stdin = json.dumps({
        "tool_name": tool_name,
        "tool_input": {"command": command, "file_path": file_path},
    })
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin, capture_output=True, text=True, timeout=5
    )
    return result.returncode


def test_blocks_force_push_main():
    assert run_guard("Bash", "git push --force main") == 2


def test_blocks_force_push_master():
    assert run_guard("Bash", "git push --force master") == 2


def test_blocks_rm_rf_root():
    assert run_guard("Bash", "rm -rf /") == 2


def test_blocks_drop_table():
    assert run_guard("Bash", "DROP TABLE users;") == 2


def test_allows_normal_git():
    assert run_guard("Bash", "git status") == 0


def test_allows_normal_python():
    assert run_guard("Bash", "python script.py") == 0


def test_allows_non_bash_write_edit():
    assert run_guard("Read", "", "some_file.md") == 0


def test_blocks_write_to_protected_path():
    assert run_guard("Write", "", ".claude/hooks/evil.py") == 2


def test_allows_cp_restore_to_hooks():
    """Allow cp operations that restore files to protected dirs."""
    assert run_guard("Bash", "cp E:/AI_Studio_Workspace/.claude/hooks/config_guardian.py /tmp/") == 0


def test_empty_stdin_ok():
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="", capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
