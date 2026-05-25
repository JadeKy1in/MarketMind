"""Skill Profiler — PostToolUse hook: track skill invocations for dead-weight analysis.

Logs every Skill tool invocation to .claude/logs/skill_usage.jsonl.
Fields: timestamp, skill_name, plugin, session_id

Performance: exits <1ms for non-Skill calls (fast string check before JSON parse).
Always exits 0 — non-blocking, fire-and-forget.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
LOG_PATH = WORKSPACE / ".claude" / "logs" / "skill_usage.jsonl"
SESSION_ID_PATH = WORKSPACE / ".claude" / "state" / "skill_profiler_session_id"


def get_session_id():
    """Get or create a stable session ID. First call writes, subsequent calls read."""
    try:
        if SESSION_ID_PATH.exists():
            return SESSION_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        pass

    sid = str(uuid.uuid4())
    try:
        SESSION_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_ID_PATH.write_text(sid, encoding="utf-8")
    except OSError:
        pass
    return sid


def extract_plugin(skill_name):
    """Extract plugin name from skill name (text before first colon).

    Returns "unknown" if there is no colon in the name.
    """
    if ":" in skill_name:
        return skill_name.split(":", 1)[0]
    return "unknown"


def main():
    # Read stdin — PostToolUse passes JSON with tool_name, tool_input, tool_response
    try:
        raw = sys.stdin.read()
    except (OSError, EOFError):
        sys.exit(0)

    if not raw.strip():
        sys.exit(0)

    # Fast pre-check: if "Skill" not in raw, skip parse entirely
    if '"Skill"' not in raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Only track Skill invocations
    if tool_name != "Skill":
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if not skill_name:
        sys.exit(0)

    plugin = extract_plugin(skill_name)
    session_id = get_session_id()
    timestamp = datetime.now(timezone.utc).isoformat()

    entry = {
        "timestamp": timestamp,
        "skill_name": skill_name,
        "plugin": plugin,
        "session_id": session_id,
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # never block session for logging failure

    sys.exit(0)


if __name__ == "__main__":
    main()
