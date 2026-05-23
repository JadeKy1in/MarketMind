"""SessionStart hook: prune stale git worktrees and temp files.

Runs at session start. Silent unless something is cleaned up.
"""
import shutil, os, time
from pathlib import Path

WORKTREE_DIR = Path(__file__).resolve().parent.parent / "worktrees"
MAX_AGE_HOURS = 24


def prune_worktrees():
    if not WORKTREE_DIR.exists():
        return
    now = time.time()
    cleaned = 0
    for d in WORKTREE_DIR.iterdir():
        if d.is_dir() and d.name.startswith("agent-"):
            try:
                age_hours = (now - d.stat().st_mtime) / 3600
                if age_hours > MAX_AGE_HOURS:
                    shutil.rmtree(d, ignore_errors=True)
                    cleaned += 1
            except OSError:
                pass
    if cleaned:
        print(f"[cleanup] Pruned {cleaned} stale worktree(s) older than {MAX_AGE_HOURS}h")


if __name__ == "__main__":
    prune_worktrees()
