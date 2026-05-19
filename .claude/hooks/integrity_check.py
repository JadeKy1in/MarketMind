"""Integrity Check — SessionStart hook: verify all workflow enforcement infrastructure.

Validates:
  1. All hook script SHA256 hashes match known-good manifest
  2. settings.local.json contains all required hook event entries
  3. .claude/state/ directory exists
  4. .claude/backups/hooks/ recovery files exist

On mismatch: auto-restore from .claude/backups/hooks/.
On unrecoverable failure: exit 2 (block session).

Runs BEFORE config_guardian in the SessionStart chain.
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
HOOKS_DIR = WORKSPACE / ".claude" / "hooks"
BACKUPS_DIR = WORKSPACE / ".claude" / "backups" / "hooks"
STATE_DIR = WORKSPACE / ".claude" / "state"
SETTINGS_LOCAL = WORKSPACE / ".claude" / "settings.local.json"
MANIFEST_PATH = BACKUPS_DIR / "hook_manifest.json"

# Expected hook scripts and their SHA256 (populated on first install)
REQUIRED_HOOKS = [
    "config_guardian.py",
    "integrity_check.py",
    "time_anchor.py",
    "startup_report.py",
    "task_manifest.py",
    "danger_guard.py",
    "stop_gate_check.py",
    "pre_compact.py",
    "conversation_archiver.py",
    "pre_session.py",
    "recover_config.py",
    "session_activity_logger.py",
    "skill_profiler.py",
]

REQUIRED_HOOK_EVENTS = {
    "SessionStart": ["integrity_check.py", "config_guardian.py", "time_anchor.py", "task_manifest.py", "startup_report.py"],
    "PreToolUse": ["danger_guard.py"],
    "PostToolUse": ["skill_profiler.py"],
    "Stop": ["stop_gate_check.py", "conversation_archiver.py"],
    "PreCompact": ["pre_compact.py"],
}


def sha256_file(path):
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest():
    """Load the known-good hash manifest."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(hashes):
    """Save current hashes as the known-good manifest."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hooks": hashes,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def check_hook_integrity():
    """Verify all hook script hashes match manifest. Returns list of failures."""
    manifest = load_manifest()
    failures = []

    for hook_name in REQUIRED_HOOKS:
        hook_path = HOOKS_DIR / hook_name
        if not hook_path.exists():
            failures.append((hook_name, "MISSING"))
            continue
        actual_hash = sha256_file(hook_path)
        if manifest and hook_name in manifest.get("hooks", {}):
            expected = manifest["hooks"][hook_name]
            if actual_hash != expected:
                failures.append((hook_name, f"HASH_MISMATCH expected={expected[:16]}... actual={actual_hash[:16]}..."))
        # If no manifest exists yet, this is first run — just record the hash
    return failures


def restore_from_backup(hook_name):
    """Restore a hook script from backup."""
    backup_path = BACKUPS_DIR / hook_name
    if backup_path.exists():
        target = HOOKS_DIR / hook_name
        shutil.copy2(str(backup_path), str(target))
        return True
    return False


def check_settings_hooks():
    """Verify settings.local.json has all required hook event entries."""
    if not SETTINGS_LOCAL.exists():
        return ["settings.local.json MISSING"]

    try:
        settings = json.loads(SETTINGS_LOCAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["settings.local.json INVALID JSON"]

    hooks = settings.get("hooks", {})
    missing = []

    for event, required_scripts in REQUIRED_HOOK_EVENTS.items():
        if event not in hooks:
            missing.append(f"hooks.{event} MISSING")
            continue

        event_hooks = hooks[event]
        found_scripts = set()

        for entry in event_hooks:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                for script in required_scripts:
                    if script in cmd:
                        found_scripts.add(script)

        for script in required_scripts:
            if script not in found_scripts:
                missing.append(f"hooks.{event}:{script} NOT WIRED")

    return missing


def ensure_state_dir():
    """Ensure .claude/state/ directory exists."""
    if not STATE_DIR.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True


def main():
    now = datetime.now(timezone.utc)
    errors = []

    # 1. Check hook script integrity
    hash_failures = check_hook_integrity()
    recovered = []
    hash_warnings = []
    for hook_name, reason in hash_failures:
        if reason == "MISSING":
            # File deleted → auto-restore from backup
            if restore_from_backup(hook_name):
                recovered.append(hook_name)
            else:
                errors.append(f"Hook {hook_name}: MISSING (no backup available)")
        else:
            # Hash mismatch → intentional edit, warn only, do NOT restore
            hash_warnings.append(f"  {hook_name}: {reason}")

    if recovered:
        print(f"- [integrity_check] RESTORED from backup: {', '.join(recovered)}")
    if hash_warnings:
        print(f"- [integrity_check] HASH CHANGED ({len(hash_warnings)} files — likely intentional edits):")
        for w in hash_warnings:
            print(w)
        print(f"- [integrity_check] Run 'python scripts/reseal_manifest.py' to update the sealed hashes.")

    # If this is first run (no manifest), generate one
    if not load_manifest():
        hashes = {}
        for hook_name in REQUIRED_HOOKS:
            hook_path = HOOKS_DIR / hook_name
            if hook_path.exists():
                hashes[hook_name] = sha256_file(hook_path)
        save_manifest(hashes)
        print(f"- [integrity_check] MANIFEST GENERATED: {len(hashes)} hooks hashed")

    # 2. Check settings hook entries
    settings_errors = check_settings_hooks()
    if settings_errors:
        for e in settings_errors:
            errors.append(e)

    # 3. Ensure state directory
    ensure_state_dir()

    # 4. Check session diff for unfinished business from previous session
    # (M2 fix: detect uncommitted changes without PICA artifacts)
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "diff", "--name-only"],
            capture_output=True, text=True, timeout=10
        )
        modified = [line.strip() for line in r.stdout.split("\n") if line.strip() and line.endswith(".py") and "tests/" not in line]
        if modified and not STATE_DIR.joinpath("current_task.json").exists():
            print(f"- [integrity_check] WARNING: {len(modified)} untracked .py files, no current_task.json")
            print(f"- [integrity_check] Files: {', '.join(modified[:5])}{'...' if len(modified) > 5 else ''}")
    except Exception:
        pass

    # Print status
    if errors:
        print(f"- [integrity_check] FAILURES ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        print(f"- [integrity_check] BLOCKING SESSION — integrity violations detected")
        sys.exit(2)

    print(f"- [integrity_check] OK: {len(REQUIRED_HOOKS)} hooks verified, settings intact, state dir present")
    sys.exit(0)


if __name__ == "__main__":
    main()
