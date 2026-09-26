"""Danger Guard — PreToolUse hook: block destructive operations.

Blocks:
  - Force push to main/master
  - rm -rf on non-temp paths
  - DROP TABLE / DROP DATABASE in sqlite3/psql
  - git reset --hard on main/master
  - settings.local.json / settings.json deletion or overwrite
  - .claude/hooks/ file deletion
  - .claude/state/ file deletion

Must complete in <50ms (PreToolUse constraint).
Uses fast string matching — no file I/O in hot path.
"""

import json
import sys

# Fast substring matches — no regex for speed
FORBIDDEN_PATTERNS = [
    # Force push to protected branches
    ("git", "push", "--force", "main"),
    ("git", "push", "--force", "master"),
    ("git", "push", "-f", "main"),
    ("git", "push", "-f", "master"),
    # Destructive git on main
    ("git", "reset", "--hard", "main"),
    ("git", "reset", "--hard", "master"),
    # Recursive delete outside temp
    ("rm", "-rf", "/"),
    ("rm", "-rf", "~"),
    # Drop database
    ("DROP", "TABLE"),
    ("DROP", "DATABASE"),
    ("TRUNCATE", "TABLE"),
]

PROTECTED_PATHS = [
    ".claude/settings.local.json",
    ".claude/settings.json",
    ".claude/hooks/",
    ".claude/state/",
    ".claude/backups/",
]


def check_protected_path(args_str):
    """Check if command targets protected filesystem paths. Returns matching path or None."""
    for path in PROTECTED_PATHS:
        if path in args_str:
            return path
    return None


def _validate_restore_source(command):
    """Extract source path from cp/mv command and verify it's a legitimate backup source."""
    parts = command.split()
    for i, part in enumerate(parts):
        if part in ("cp", "mv") and i + 1 < len(parts):
            src = parts[i + 1].strip('"').strip("'")
            if "/backups/hooks/" in src or "/.claude/hooks/" in src:
                return True
    return False


def check_forbidden(command):
    """Check entire command string for forbidden patterns."""
    cmd_upper = command.upper()
    for pattern in FORBIDDEN_PATTERNS:
        pattern_upper = tuple(p.upper() for p in pattern)
        if all(p in cmd_upper for p in pattern_upper):
            return " ".join(pattern)
    return None


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        data = json.loads(raw)
    except (OSError, EOFError, json.JSONDecodeError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Only check Bash, Write, Edit tools
    if tool_name not in ("Bash", "Write", "Edit"):
        sys.exit(0)

    command = tool_input.get("command", "")
    file_path = tool_input.get("file_path", "")

    if not command and not file_path:
        sys.exit(0)

    # Check command for forbidden patterns
    forbidden = check_forbidden(command)
    if forbidden:
        sys.stderr.write(f"BLOCKED: Forbidden pattern '{forbidden}' in command: {command[:200]}\n")
        sys.exit(2)

    # Check for protected path targeting
    targeted = check_protected_path(command + file_path)
    if targeted:
        # Write/Edit to protected paths always blocked
        if tool_name in ("Write", "Edit"):
            sys.stderr.write(f"BLOCKED: Cannot modify protected path '{targeted}' via {tool_name}\n")
            sys.exit(2)
        if tool_name == "Bash":
            # Allow cp/mv restore FROM legitimate backup/hook sources TO protected dirs
            is_restore = _validate_restore_source(command) and targeted in (
                ".claude/hooks/", ".claude/state/", ".claude/backups/"
            )
            if is_restore:
                sys.exit(0)
            # Only block destructive operations that specifically target the matched path
            if "rm " in command or "tee " in command:
                sys.stderr.write(f"BLOCKED: Cannot delete/overwrite protected path '{targeted}'\n")
                sys.exit(2)
            # Check > redirect: only block if redirect target is the protected path itself
            if ">" in command:
                import re
                for m in re.finditer(r'\d?\>\s*(\S+)', command):
                    rt = m.group(1).strip('"').strip("'")
                    if rt in ('&1', '&2', '/dev/null', '/dev/stdout', '/dev/stderr'):
                        continue
                    if any(p in rt for p in PROTECTED_PATHS):
                        sys.stderr.write(f"BLOCKED: Cannot redirect to protected path '{rt}'\n")
                        sys.exit(2)
                sys.stderr.write(f"BLOCKED: Cannot delete/overwrite protected path '{targeted}'\n")
                sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
