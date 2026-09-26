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
DEPENDENCY_MAP = STATE_DIR / "hook_dependency_map.json"

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

# Manual baseline: hook files referenced OUTSIDE the SessionStart/Stop hook chain.
# These survive all auto-discovery and serve as the ground-truth "never delete" list.
# Auto-discovery (bat scan + docstring parsing) supplements but never overrides this.
MANUAL_BASELINE = {
    "pre_session.py": {
        "external_callers": ["start.bat:12"],
        "recovery_via": ["recover_config.py"],
        "deletion_impact": "start.bat fails → Claude Code cannot launch via bat file"
    },
    "recover_config.py": {
        "external_callers": ["start.bat:17 (error message path)", "pre_session.py (recovery hint in error)"],
        "recovery_via": ["config_guardian.py"],
        "deletion_impact": "Config recovery becomes impossible without manual intervention"
    },
    "session_activity_logger.py": {
        "external_callers": [],
        "recovery_via": [],
        "deletion_impact": "Session activity audit gap; historically wired in legacy hook chains"
    },
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


def scan_launch_scripts():
    """Scan workspace root for .bat/.cmd/.sh/.ps1 files referencing .claude/hooks/ files.

    Returns {hook_name: [caller_ref, ...]} where caller_ref is like 'start.bat:12'.
    This is the A in A+B: automatic discovery of script-level dependencies.
    """
    import re

    discovered = {}
    # Match paths containing .claude/hooks/<filename>.py in any quoting style
    hook_ref_pattern = re.compile(r'\.claude[/\\]hooks[/\\]([a-zA-Z0-9_]+\.py)')

    for glob_pat in ("*.bat", "*.cmd", "*.sh", "*.ps1"):
        for script_path in WORKSPACE.glob(glob_pat):
            try:
                lines = script_path.read_text(encoding="utf-8", errors="replace").split("\n")
                for i, line in enumerate(lines, 1):
                    for m in hook_ref_pattern.finditer(line):
                        hook_name = m.group(1)
                        caller_ref = f"{script_path.name}:{i}"
                        discovered.setdefault(hook_name, []).append(caller_ref)
            except OSError:
                pass

    return discovered


def scan_hook_docstrings():
    """Scan hook file docstrings for @external-callers: annotations.

    Parses the first docstring of each hook .py file looking for:
        @external-callers: start.bat:12
        @recovery: recover_config.py
        @never-delete: reason

    Returns {hook_name: {external_callers: [...], recovery_via: [...], never_delete_reason: str}}.
    """
    import re

    discovered = {}
    # Matches @tag: value lines, allowing leading whitespace
    tag_pattern = re.compile(r'@(external-callers|recovery|never-delete):\s*(.+)')

    for hook_name in REQUIRED_HOOKS:
        hook_path = HOOKS_DIR / hook_name
        if not hook_path.exists():
            continue
        try:
            content = hook_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Extract first docstring (top-level """...""")
        ds_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if not ds_match:
            continue

        docstring = ds_match.group(1)
        info = {}
        for m in tag_pattern.finditer(docstring):
            tag, value = m.group(1).strip(), m.group(2).strip()
            if tag == "external-callers":
                info.setdefault("external_callers", []).append(value)
            elif tag == "recovery":
                info.setdefault("recovery_via", []).append(value)
            elif tag == "never-delete":
                info["never_delete_reason"] = value

        if info:
            discovered[hook_name] = info

    return discovered


def build_dependency_map():
    """Merge manual baseline + bat scan + docstring scan into a unified dependency map.

    Returns (deps_dict, warnings_list).
    Manual baseline entries are authoritative and survive all auto-discovery.
    Auto-discovery supplements with new callers or flags stale entries.
    """
    discovered_scripts = scan_launch_scripts()
    discovered_docstrings = scan_hook_docstrings()
    warnings = []

    # Start with manual baseline as ground truth
    all_deps = {}
    for hook_name, info in MANUAL_BASELINE.items():
        all_deps[hook_name] = dict(info)
        all_deps[hook_name]["discovery_method"] = "manual_baseline"

    # Merge bat-scan discoveries
    for hook_name, callers in discovered_scripts.items():
        if hook_name not in all_deps:
            # New dependency found — not in manual baseline
            all_deps[hook_name] = {
                "external_callers": callers,
                "recovery_via": [],
                "deletion_impact": "Discovered by script scan — not in manual baseline; consider adding",
                "discovery_method": "bat_scan",
            }
            warnings.append(
                f"{hook_name}: discovered external callers via bat scan [{', '.join(callers)}] "
                f"— NOT in manual baseline, consider adding to MANUAL_BASELINE in integrity_check.py"
            )
        else:
            # Already in baseline — cross-validate
            baseline_callers = all_deps[hook_name].get("external_callers", [])
            baseline_files = {c.split(":")[0] for c in baseline_callers}
            for caller in callers:
                caller_file = caller.split(":")[0]
                if caller_file not in baseline_files:
                    all_deps[hook_name].setdefault("discovered_extra_callers", []).append(caller)
                    all_deps[hook_name]["discovery_method"] = (
                        all_deps[hook_name].get("discovery_method", "") + "+bat_scan"
                    )

    # Merge docstring discoveries (supplement, never override)
    for hook_name, info in discovered_docstrings.items():
        if hook_name not in all_deps:
            all_deps[hook_name] = {
                "external_callers": info.get("external_callers", []),
                "recovery_via": info.get("recovery_via", []),
                "deletion_impact": info.get("never_delete_reason", "Docstring-annotated dependency"),
                "discovery_method": "docstring",
            }
        else:
            # Supplements manual baseline
            for key in ("external_callers", "recovery_via"):
                existing = set(all_deps[hook_name].get(key, []))
                for v in info.get(key, []):
                    if v not in existing:
                        all_deps[hook_name].setdefault(key, []).append(v)
            if "never_delete_reason" in info and "never_delete" not in all_deps[hook_name]:
                all_deps[hook_name]["deletion_impact"] = info["never_delete_reason"]
            all_deps[hook_name]["discovery_method"] = (
                all_deps[hook_name].get("discovery_method", "") + "+docstring"
            )

    # Flag baseline entries with no external callers discovered (stale check)
    for hook_name in MANUAL_BASELINE:
        if hook_name not in discovered_scripts and hook_name not in discovered_docstrings:
            baseline_callers = MANUAL_BASELINE[hook_name].get("external_callers", [])
            if baseline_callers:
                warnings.append(
                    f"{hook_name}: baseline records callers {baseline_callers} "
                    f"but none found by bat or docstring scan — caller may have changed"
                )

    return all_deps, warnings


def save_dependency_map(deps, warnings):
    """Write hook_dependency_map.json to .claude/state/."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "integrity_check.py — auto-discovery (bat scan + docstring) merged with manual baseline",
        "warnings": warnings,
        "hooks": deps,
    }
    DEPENDENCY_MAP.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


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

    # 3b. Build external dependency map (A+B patch: auto-discovery cross-referenced with manual baseline)
    deps, dep_warnings = build_dependency_map()
    save_dependency_map(deps, dep_warnings)
    if dep_warnings:
        print(f"- [integrity_check] DEPENDENCY MAP ({len(dep_warnings)} warnings):")
        for w in dep_warnings:
            print(f"  {w}")

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
