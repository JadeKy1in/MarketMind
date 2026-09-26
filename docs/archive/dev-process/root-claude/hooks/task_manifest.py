"""Task Manifest — SessionStart hook: inject workflow meta-instructions.

Injects the task classification rules and gate requirements into the AI context
so every session understands the mandatory workflow enforcement system.

Always exits 0.
"""

import json
import sys
from datetime import datetime, timezone

INJECTION = """
## Workflow Enforcement (Active This Session)

**Mandatory task declaration.** Before any code change, create `.claude/state/current_task.json`:

### Task Types (auto-detected by Stop gate)
| Type | Trigger | Required PICA Gates |
|------|---------|:---:|
| `explore` | Read-only, Q&A, no file writes | None |
| `test` | Changes ONLY in tests/ | unit + regression |
| `fix` | Existing .py modified, no new modules | unit + regression |
| `maintain` | requirements.txt, package.json, .env, settings | unit + security |
| `enhance` | New .py >50 lines, new module | unit + security + integration + regression |
| `architect` | API/schema change, critical files, cross-module | Full PICA + architecture review |

**Critical files** (auto-upgrade to architect): async_client.py, shadow_state.py, decision.py

### Declaration Format
```json
{"type": "fix", "files": ["file1.py"], "risk": "medium"}
```

### Stop Gate (Mechanical — Cannot Bypass)
When you try to end the session, `stop_gate_check.py` will:
1. Run `git diff --stat` to detect actual changes
2. Compute required gates from changed files
3. Apply `max(declared_type, actual_type)` — your declaration only UPGRADES
4. Verify PICA artifacts exist with valid content hashes
5. Missing or stale → **session end blocked** (exit 2)

**Declaring "explore" while writing code will NOT work** — the git diff cross-check catches it.

### Emergency Override
If PICA gates cannot be completed (agent unavailable, context lost):
```json
{"type": "enhance", "emergency_override": true, "reason": "agent init failed, deferring PICA-security"}
```
Override is logged. Next SessionStart will flag deferred work.

### Workflow Quick Reference
- Start: declare task in current_task.json
- Design: Skill("superpowers:brainstorming") + Skill("superpowers:writing-plans")
- Implement: Agent Team (Architect → Builder → Red Team ×2)
- Audit: PICA-Unit → PICA-Security → PICA-Integration → PICA-Regression
- Verify: Skill("superpowers:verification-before-completion")
- Commit: only after all gates pass
"""

# Escaped for JSON injection into settings.json
INJECTION_ESCAPED = json.dumps(INJECTION)


def main():
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            json.loads(stdin_data)
    except (OSError, EOFError, json.JSONDecodeError):
        pass

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"- [task_manifest] OK: workflow rules injected ({now})")
    print(INJECTION)
    sys.exit(0)


if __name__ == "__main__":
    main()
