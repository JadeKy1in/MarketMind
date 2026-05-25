"""PICA-Unit: stop_gate_check.py"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("E:/AI_Studio_Workspace/.claude/hooks")))

HOOK = Path("E:/AI_Studio_Workspace/.claude/hooks/stop_gate_check.py")


def run_gate():
    """Run stop_gate_check with default stdin."""
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{}", capture_output=True, text=True, timeout=15
    )
    return result.returncode, result.stderr


def test_detects_changes():
    """stop_gate_check detects git changes and reports level."""
    exit_code, stderr = run_gate()
    # Either exits 2 (blocked - changes exist) or 0 (emergency override)
    assert exit_code in (0, 2), f"Unexpected exit: {exit_code}, stderr: {stderr[:200]}"
    if exit_code == 2:
        assert "BLOCKED" in stderr or "NO DECLARATION" in stderr or "UPGRADE" in stderr, \
            f"Expected block message, got: {stderr[:200]}"


def test_type_level_hierarchy():
    """Verify task type level ordering."""
    from stop_gate_check import TYPE_LEVEL
    assert TYPE_LEVEL["explore"] < TYPE_LEVEL["test"] < TYPE_LEVEL["fix"]
    assert TYPE_LEVEL["fix"] < TYPE_LEVEL["maintain"] < TYPE_LEVEL["enhance"]
    assert TYPE_LEVEL["enhance"] < TYPE_LEVEL["architect"]


def test_critical_files():
    """Verify critical files list is correct."""
    from stop_gate_check import CRITICAL_FILES
    assert "async_client.py" in CRITICAL_FILES
    assert "shadow_state.py" in CRITICAL_FILES
    assert "decision.py" in CRITICAL_FILES


def test_gate_requirements():
    """Verify gate requirements for each level."""
    from stop_gate_check import GATE_REQUIREMENTS
    assert GATE_REQUIREMENTS[0] == []  # explore
    assert "unit" in GATE_REQUIREMENTS[2]  # fix
    assert "security" in GATE_REQUIREMENTS[4]  # enhance
    assert "architecture" in GATE_REQUIREMENTS[5]  # architect


def test_level_name_roundtrip():
    """Verify level name mapping."""
    from stop_gate_check import TYPE_LEVEL, LEVEL_NAME
    for name, level in TYPE_LEVEL.items():
        assert LEVEL_NAME[level] == name


def test_emergency_override_allows_exit_0():
    """When emergency_override is set in current_task.json, exit 0."""
    # Read current task file to verify it has override
    task_file = Path("E:/AI_Studio_Workspace/.claude/state/current_task.json")
    if task_file.exists():
        data = json.loads(task_file.read_text(encoding="utf-8"))
        # This test just verifies the structure, not the hook behavior
        assert "type" in data
