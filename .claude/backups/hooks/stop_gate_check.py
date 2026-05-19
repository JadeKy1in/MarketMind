"""Stop Gate Check — Stop hook: enforce PICA artifact requirements before session end.

This is the core enforcement point. The AI cannot end the session without passing this gate.

Logic:
  1. Run git diff --stat and --name-status
  2. If no changes → allow end (exit 0)
  3. Read .claude/state/current_task.json for AI declaration
  4. Compute actual task type from diff analysis
  5. Use max(declared_type, actual_type) — AI declaration only UPGRADES gates
  6. Verify required PICA artifacts exist with valid content hashes
  7. Missing/stale → exit 2 ("continue": true) with remediation message

Task type hierarchy (lowest → highest):
  explore < test < fix < maintain < enhance < architect
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def log(msg):
    """Write message to stderr — required for hook feedback."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


WORKSPACE = Path("E:/AI_Studio_Workspace")
STATE_DIR = WORKSPACE / ".claude" / "state"
AUDITS_DIR = WORKSPACE / ".claude" / "audits"
TASK_FILE = STATE_DIR / "current_task.json"

# Task type → numeric level (higher = more gates)
TYPE_LEVEL = {
    "explore": 0,
    "test": 1,
    "fix": 2,
    "maintain": 3,
    "enhance": 4,
    "architect": 5,
}

LEVEL_NAME = {v: k for k, v in TYPE_LEVEL.items()}

# Required PICA gates per task level
GATE_REQUIREMENTS = {
    0: [],                                          # explore
    1: ["unit", "regression"],                       # test
    2: ["unit", "regression"],                       # fix
    3: ["unit", "security", "regression"],           # maintain
    4: ["unit", "security", "integration", "regression"],  # enhance
    5: ["unit", "security", "integration", "regression", "architecture"],  # architect
}

# Critical files that auto-escalate
CRITICAL_FILES = [
    "async_client.py",
    "shadow_state.py",
    "decision.py",
]

# File patterns for task type detection
CONFIG_PATTERNS = [
    "requirements.txt", "requirements", "package.json", "package-lock.json",
    ".env", "settings.json", "settings.local.json", "setup.py", "setup.cfg",
    "pyproject.toml", "Pipfile", "Pipfile.lock",
]

API_SCHEMA_PATTERNS = [
    "schema", "migration", "api", "types.ts", "types.py",
    "__init__.py", "interface", "protocol",
]


def run_git_diff():
    """Run git diff to detect actual changes."""
    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "diff", "--name-status"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()
    except Exception:
        return ""


def run_git_diff_stat():
    """Run git diff --stat for line counts."""
    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "diff", "--stat"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()
    except Exception:
        return ""


def run_git_diff_numstat():
    """Run git diff --numstat for precise add/del counts."""
    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "diff", "--numstat"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()
    except Exception:
        return ""


def detect_actual_level(diff_output, numstat_output):
    """Determine actual minimum task level from git diff content.

    Returns (level_int, reasons_list).
    """
    if not diff_output:
        return 0, ["no changes detected"]

    reasons = []
    max_level = 0

    lines = diff_output.split("\n")
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue

        status = parts[0].strip()
        filepath = parts[1].strip()
        filename = os.path.basename(filepath)

        # New file detection
        if status.startswith("A"):
            if filepath.endswith(".py") and "tests/" not in filepath:
                # Check line count from numstat
                if numstat_output:
                    for ns_line in numstat_output.split("\n"):
                        ns_parts = ns_line.split("\t")
                        if len(ns_parts) >= 3 and ns_parts[2] == filepath:
                            try:
                                added = int(ns_parts[0]) if ns_parts[0] != "-" else 0
                                if added > 50:
                                    level = 4  # enhance
                                    reasons.append(f"New .py file >50 lines: {filename}")
                                    max_level = max(max_level, level)
                                elif added > 0:
                                    level = 3  # maintain at minimum
                                    reasons.append(f"New .py file: {filename}")
                                    max_level = max(max_level, level)
                            except ValueError:
                                pass

        # Modified file detection
        if status == "M":
            if filepath.endswith(".py"):
                if filename in CRITICAL_FILES:
                    reasons.append(f"Critical file modified: {filename}")
                    max_level = max(max_level, 5)  # architect
                elif "tests/" not in filepath:
                    # Check for API/schema patterns
                    is_api = any(p in filepath.lower() for p in API_SCHEMA_PATTERNS)
                    if is_api:
                        reasons.append(f"API/schema file modified: {filename}")
                        max_level = max(max_level, 5)  # architect
                    else:
                        reasons.append(f"Source file modified: {filename}")
                        max_level = max(max_level, 2)  # fix

            # Config/dependency files
            elif any(p in filename.lower() for p in CONFIG_PATTERNS):
                reasons.append(f"Config/dep file modified: {filename}")
                max_level = max(max_level, 3)  # maintain

            # Test files only
            elif "tests/" in filepath:
                reasons.append(f"Test file modified: {filename}")
                max_level = max(max_level, 1)  # test

    return max_level, reasons


def read_task_declaration():
    """Read the AI's task declaration."""
    if not TASK_FILE.exists():
        return None
    try:
        return json.loads(TASK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get_module_name(files):
    """Extract module name from file list for artifact path lookup."""
    if not files:
        return None
    # Use first non-test file
    for f in files:
        if "tests/" not in f:
            return os.path.splitext(os.path.basename(f))[0]
    # Fallback: first test file
    return os.path.splitext(os.path.basename(files[0]))[0]


def sha256_file(path):
    """Compute SHA256 of file."""
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_artifact_hashes_at_path(artifact_path):
    """Verify PICA artifact at the given path contains valid file content hashes."""
    if not artifact_path.exists():
        return False, "MISSING"

    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "INVALID_JSON"

    # Check artifact has files_checked with content hashes
    files_checked = artifact.get("files_checked", {})
    if not files_checked:
        return False, "NO_HASH_CHAIN"

    # Verify each file's current content matches the artifact hash
    for filepath, expected_hash in files_checked.items():
        full_path = WORKSPACE / filepath
        if not full_path.exists():
            return False, f"FILE_GONE: {filepath}"
        actual_hash = sha256_file(full_path)
        if actual_hash != expected_hash:
            return False, f"HASH_MISMATCH: {filepath}"

    return True, "OK"


def check_artifacts(level, files):
    """Check all required PICA artifacts for the given level."""
    required_gates = GATE_REQUIREMENTS.get(level, [])
    if not required_gates:
        return True, []

    module_name = get_module_name(files)
    if not module_name:
        # No files to check — try to find any recent artifact
        return True, []

    missing = []
    for gate in required_gates:
        # Find ALL matching artifacts for this gate (recursive), sorted newest first
        artifact_path = None
        try:
            all_matches = list(AUDITS_DIR.rglob(f"pica-{gate}-*.json"))
            if not all_matches:
                missing.append(f"pica-{gate} (no artifact found)")
                continue
            all_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            # Try each match (newest first) until one passes hash verification
            for candidate in all_matches:
                ok, detail = verify_artifact_hashes_at_path(candidate)
                if ok:
                    artifact_path = candidate
                    break
            if artifact_path is None:
                missing.append(f"pica-{gate} ({detail})")
        except Exception:
            missing.append(f"pica-{gate} (audit dir error)")
            continue

    return len(missing) == 0, missing


def main():
    try:
        raw = sys.stdin.read()
        if raw.strip():
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                pass
    except (OSError, EOFError):
        pass

    # Step 1: Check if any changes exist
    diff_output = run_git_diff()
    numstat_output = run_git_diff_numstat()

    if not diff_output:
        # No changes — nothing to enforce
        sys.exit(0)

    # Step 2: Detect actual task level from diff
    actual_level, reasons = detect_actual_level(diff_output, numstat_output)

    # Step 3: Read AI declaration
    declaration = read_task_declaration()
    declared_level = 0
    emergency_override = False
    override_reason = ""

    if declaration is None:
        # No declaration → default to architect (C2 fix: missing = maximum)
        declared_level = 5  # architect
        log(f"- [stop_gate] NO DECLARATION: .claude/state/current_task.json missing")
        log(f"- [stop_gate] Defaulting to ARCHITECT level — full PICA required")
        log(f"- [stop_gate] Create current_task.json with task type to reduce gate requirements")
    else:
        declared_type = declaration.get("type", "explore")
        declared_level = TYPE_LEVEL.get(declared_type, 0)
        emergency_override = declaration.get("emergency_override", False)
        override_reason = declaration.get("reason", "no reason given")

    # Step 4: Use max of declared and actual
    effective_level = max(declared_level, actual_level)
    effective_name = LEVEL_NAME.get(effective_level, "unknown")

    if declared_level < actual_level:
        log(f"- [stop_gate] UPGRADE: declared '{LEVEL_NAME.get(declared_level)}' → actual '{LEVEL_NAME.get(actual_level)}'")
        log(f"- [stop_gate] Reasons: {'; '.join(reasons)}")

    # Step 5: Emergency override
    if emergency_override:
        log(f"- [stop_gate] EMERGENCY OVERRIDE active: {override_reason}")
        # Still log what would have been required
        required_gates = GATE_REQUIREMENTS.get(effective_level, [])
        log(f"- [stop_gate] Deferred gates ({effective_name}): {', '.join(required_gates)}")
        log(f"- [stop_gate] NEXT SESSION: SessionStart will flag these as unfinished business")
        sys.exit(0)

    # Step 6: No gates needed
    if effective_level == 0:
        sys.exit(0)

    # Step 7: Extract file list
    files = []
    for line in diff_output.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append(parts[1].strip())

    # Step 8: Verify required artifacts
    required_gates = GATE_REQUIREMENTS.get(effective_level, [])
    all_ok, missing = check_artifacts(effective_level, files)

    if all_ok:
        log(f"- [stop_gate] OK: all {effective_name} gates passed ({', '.join(required_gates)})")
        sys.exit(0)
    else:
        log(f"- [stop_gate] BLOCKED: {effective_name} level requires {len(required_gates)} gates")
        log(f"- [stop_gate] Missing ({len(missing)}):")
        for m in missing:
            log(f"  - {m}")
        log(f"- [stop_gate] Remediation: run PICA gates for the missing levels")
        log(f"- [stop_gate] Or set emergency_override in current_task.json with reason")
        sys.exit(2)


if __name__ == "__main__":
    main()
