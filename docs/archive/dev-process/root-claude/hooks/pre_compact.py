"""PreCompact Hook — save progress snapshot before context compaction.

Compaction is the #1 source of context loss in Claude Code sessions.
This hook writes a progress checkpoint to .claude/progress/ before each compaction,
ensuring no work-in-progress context is permanently lost.

Hook: PreCompact (always exit 0, non-blocking)
File written: .claude/progress/compact_snapshots.jsonl
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
SNAPSHOT_PATH = WORKSPACE / ".claude" / "progress" / "compact_snapshots.jsonl"


def main():
    timestamp = datetime.now(timezone.utc).isoformat()

    # Gather minimal snapshot: what files are modified, current git state
    import subprocess
    git_status = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(WORKSPACE), "status", "--short"],
            capture_output=True, text=True, timeout=10
        )
        git_status = result.stdout.strip()[:1000]
    except Exception:
        git_status = "unavailable"

    git_log = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(WORKSPACE), "log", "--oneline", "-3"],
            capture_output=True, text=True, timeout=10
        )
        git_log = result.stdout.strip()[:500]
    except Exception:
        git_log = "unavailable"

    # Read latest progress file for semantic task state
    task_context = ""
    progress_dir = WORKSPACE / ".claude" / "progress"
    try:
        if progress_dir.exists():
            progress_files = sorted(progress_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if progress_files:
                latest = progress_files[0]
                content = latest.read_text(encoding="utf-8", errors="replace")
                # Extract lines with [x] or [ ] task markers
                task_lines = [line.strip() for line in content.split("\n")
                              if "[" in line and ("x]" in line or " ]" in line)][-5:]
                task_context = "\n".join(task_lines)[:500]
    except Exception:
        task_context = "unavailable"

    snapshot = {
        "timestamp": timestamp,
        "modified_files": git_status,
        "recent_commits": git_log,
        "task_context": task_context,
    }

    # Append to snapshot log
    try:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SNAPSHOT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError:
        pass  # never block session for logging failure

    sys.exit(0)


if __name__ == "__main__":
    main()
