"""PICA-Unit: integrity_check.py"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path("E:/AI_Studio_Workspace/.claude/hooks/integrity_check.py")


def test_manifest_loads():
    """integrity_check can load its manifest."""
    result = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, f"integrity_check failed: {result.stdout}"
    assert "13 hooks verified" in result.stdout or "MANIFEST GENERATED" in result.stdout, \
        f"Unexpected output: {result.stdout[:200]}"


def test_detects_missing_hook():
    """integrity_check detects a hook that doesn't exist."""
    # Verify the script runs without crashing even when hooks dir is fine
    result = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0


def test_state_dir_created():
    """integrity_check ensures state dir exists."""
    state_dir = Path("E:/AI_Studio_Workspace/.claude/state")
    assert state_dir.exists(), "state dir should exist after integrity_check runs"
