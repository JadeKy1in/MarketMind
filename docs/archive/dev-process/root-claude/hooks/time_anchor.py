"""Time Anchor — SessionStart hook that mechanically enforces time-awareness.

SessionStart hook that queries the OS for the real current time on every session,
computes the delta from the model training cutoff, and writes the result to
current_time.txt files. This addresses CLAUDE.md §3.2 by providing automated
enforcement rather than relying on AI memory alone.

Hook: SessionStart (always exit 0, non-blocking)
Files written: .claude/current_time.txt, ~/.claude/current_time.txt
Self-contained: only subprocess, json, sys, datetime, pathlib
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAINING_CUTOFF = datetime(2026, 1, 1, tzinfo=timezone.utc)

WORKSPACE = Path("E:/AI_Studio_Workspace")
GLOBAL_CLAUDE = Path.home() / ".claude"


# ---------------------------------------------------------------------------
# Time acquisition
# ---------------------------------------------------------------------------

def get_real_time():
    """Get real current time from the OS.

    Tries `date -u` first (Unix/Git Bash), then PowerShell.
    Falls back to Python's datetime.now() as last resort.
    Returns an ISO 8601 UTC string like '2026-05-17T14:30:00Z'.
    """
    # Strategy 1: Unix `date` (works in Git Bash on Windows)
    try:
        result = subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Strategy 2: PowerShell (native Windows)
    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                "Get-Date -AsUTC -Format 'yyyy-MM-ddTHH:mm:ssZ'",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Strategy 3: Python's own clock (fallback, warns about potential skew)
    print("- [time_anchor] WARNING: OS date query failed; using Python clock (may drift)")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def write_current_time(timestamp_str, target_dir):
    """Write current_time.txt to target_dir with timestamp, cutoff, and delta.

    Args:
        timestamp_str: ISO 8601 UTC string like '2026-05-17T14:30:00Z'
        target_dir: Path to the directory to write current_time.txt into

    Returns:
        Path to the written file
    """
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)

    delta = dt - TRAINING_CUTOFF
    months = max(0, delta.days // 30)

    content = (
        f"Session start: {timestamp_str}\n"
        f"Training cutoff: 2026-01-01 (approx)\n"
        f"Delta: ~{months} months — prefer command output for dates after Jan 2026\n"
    )

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / "current_time.txt"
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------

def format_display(timestamp_str):
    """Format a human-readable summary line for console output.

    Args:
        timestamp_str: ISO 8601 UTC string

    Returns:
        Formatted string like:
        '[time_anchor] Real time: 2026-05-17 14:30 UTC | Delta from training: ~5 months'
    """
    try:
        dt_utc = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        dt_utc = datetime.now(timezone.utc)

    delta = dt_utc - TRAINING_CUTOFF
    months = max(0, delta.days // 30)

    display_time = dt_utc.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"[time_anchor] Real time: {display_time}"
        f" | Delta from training: ~{months} months"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Run time anchor. Always exits 0 (non-blocking SessionStart hook)."""
    # Accept stdin per Claude Code hook protocol, but work without it (for testing)
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            try:
                _ = json.loads(stdin_data)
            except json.JSONDecodeError:
                pass  # stdin present but not valid JSON — ignore and proceed
    except (OSError, EOFError):
        pass  # no stdin available — testing mode

    # Get real time from the OS
    timestamp_str = get_real_time()

    # Write to workspace .claude/current_time.txt
    workspace_path = write_current_time(timestamp_str, WORKSPACE / ".claude")

    # Write to global ~/.claude/current_time.txt
    global_path = write_current_time(timestamp_str, GLOBAL_CLAUDE)

    # Print summary line
    print(f"- {format_display(timestamp_str)}")

    # Confirm file locations (trace level)
    print(f"- [time_anchor] Written: {workspace_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
