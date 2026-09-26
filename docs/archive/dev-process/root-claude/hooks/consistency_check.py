"""Stop hook: quick consistency scan — catches drift before it accumulates.

Runs at session end. Silent unless anomalies found.
Must complete in <200ms.
"""
import json, os, sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
STATE = WORKSPACE / ".claude" / "state"

def check():
    issues = []

    # 1. Task file staleness (>24h old might be stale from another session)
    task_file = STATE / "current_task.json"
    if task_file.exists():
        age_h = (os.path.getmtime(task_file) - os.path.getmtime(__file__)) / 3600
        if age_h > 24:
            issues.append(f"current_task.json is {age_h:.0f}h old — may be stale")

    # 2. Preferences hash mismatch (common corruption pattern)
    pref_file = STATE / "user_preferences.json"
    hash_file = STATE / ".preferences.hash"
    if pref_file.exists() and hash_file.exists():
        import hashlib
        actual = hashlib.sha256(pref_file.read_bytes()).hexdigest()
        stored = hash_file.read_text().strip()
        if stored.startswith("sha256:"):
            stored = stored[7:]
        if actual != stored:
            issues.append("user_preferences.json hash mismatch — integrity check failed")

    # 3. Orphan backup files accumulating
    backups = list(STATE.glob("*.bak"))
    if len(backups) > 5:
        issues.append(f"{len(backups)} stale .bak files in .claude/state/")

    # 4. Hook registration vs hook files mismatch
    hooks_dir = WORKSPACE / ".claude" / "hooks"
    settings = WORKSPACE / ".claude" / "settings.local.json"
    if hooks_dir.exists() and settings.exists():
        try:
            cfg = json.loads(settings.read_text())
            registered = set()
            for trigger, entries in cfg.get("hooks", {}).items():
                for entry in entries:
                    for h in entry.get("hooks", []):
                        cmd = h.get("command", "")
                        for word in cmd.split():
                            if word.endswith(".py"):
                                registered.add(os.path.basename(word.strip('"')))
            hook_files = {f.name for f in hooks_dir.glob("*.py")
                         if f.name not in ("__init__.py",)}
            orphan = hook_files - registered
            if orphan:
                issues.append(f"Orphan hooks (not registered): {', '.join(sorted(orphan))}")
        except Exception:
            pass

    if issues:
        print("\n[consistency] Issues found:")
        for i in issues:
            print(f"  - {i}")
        # Don't block — just warn. Let stop_gate handle hard failures.
    sys.exit(0)

if __name__ == "__main__":
    check()
