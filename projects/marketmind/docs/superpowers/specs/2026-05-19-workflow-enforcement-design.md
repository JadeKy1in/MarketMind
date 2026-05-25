# Workflow Enforcement System — Design Spec

**Status**: IMPLEMENTED
**Date**: 2026-05-19
**Red Team**: Audited — 9 findings (4C/2H/3M), all resolved

---

## Architecture

Dual-layer enforcement: **AI decides "what" (flexible), Hooks enforce "must" (mechanical).**

```
SessionStart
  ├─ integrity_check     ← SHA256 verify + auto-restore
  ├─ config_guardian     ← 5 guards (plugins, statusLine, hooks, env, enforcement)
  ├─ time_anchor         ← UTC timestamp anchor
  ├─ task_manifest       ← inject task classification rules
  └─ startup_report      ← health report

PreToolUse ← danger_guard  ← red-line blocking (<50ms)

Stop       ← stop_gate_check + conversation_archiver  ← git-diff cross-check

PreCompact ← pre_compact   ← progress snapshot
```

## Core Enforcement: Stop Gate

The Stop hook is the single unrecoverable enforcement point. Logic:

1. Run `git diff --name-status` → detect actual changes
2. Compute minimum task level from file paths (C1 fix)
3. Read AI declaration from `.claude/state/current_task.json`
4. Apply `max(declared, actual)` — declaration only UPGRADES gates
5. Missing declaration → default ARCHITECT (C2 fix)
6. Verify PICA artifacts with content hash chains (C4 fix)
7. Missing/stale → exit 2 + remediation message

## Task Types

| Type | Trigger (auto-detected) | PICA Gates |
|------|------|:---:|
| explore | Read-only, no diff | None |
| test | Only tests/ modified | unit + regression |
| fix | Existing .py modified | unit + regression |
| maintain | Config/deps modified | unit + security + regression |
| enhance | New .py >50 lines | unit + security + integration + regression |
| architect | API/schema, critical files | Full PICA + architecture review |

## Red Team Findings — Resolution Map

| # | Finding | Resolution |
|---|---------|------------|
| C1 | "explore" bypass | `git diff --name-status` cross-check at Stop |
| C2 | State file deletion | Missing file → default architect level |
| C3 | Hook removal | config_guardian Guard 5 protects all 9 hook entries |
| C4 | Timestamp forgery | PICA artifacts include `files_checked: {path: sha256}` |
| H1 | New module under-classification | New .py >50 lines auto-upgrade to enhance |
| H2 | Config/dep unmapped | `maintain` task type for config/dep changes |
| M1 | Recovery loop | `emergency_override` field in current_task.json |
| M2 | Process kill bypass | SessionStart diff check flags unfinished business |
| M3 | Worktree state confusion | `.claude/state/` per-worktree (via session ID) |

## File Manifest

| File | Event | Type | Status |
|------|-------|------|:---:|
| `integrity_check.py` | SessionStart | exit 2 block | NEW |
| `config_guardian.py` | SessionStart | non-blocking (Guard 5 added) | MODIFIED |
| `time_anchor.py` | SessionStart | non-blocking | Existing |
| `task_manifest.py` | SessionStart | non-blocking (injects rules) | NEW |
| `startup_report.py` | SessionStart | non-blocking | Existing |
| `danger_guard.py` | PreToolUse | exit 2 block | NEW |
| `stop_gate_check.py` | Stop | exit 2 block | NEW |
| `conversation_archiver.py` | Stop | non-blocking | Existing (wired) |
| `pre_compact.py` | PreCompact | non-blocking | Existing (wired) |

## Self-Protection

1. **integrity_check.py**: Verifies all 12 hook SHA256 hashes vs `.claude/backups/hooks/hook_manifest.json`. Auto-restores from backup. Blocks session on unrecoverable failure.
2. **config_guardian Guard 5**: Ensures all 9 hook entries exist in settings. Restores from hardcoded templates.
3. **danger_guard**: Blocks deletion/overwrite of `.claude/hooks/`, `.claude/state/`, `.claude/backups/`, `settings.json`.

## Emergency Override

```json
{"type": "enhance", "emergency_override": true, "reason": "agent init failed"}
```

Stop gate logs override and defers gates. Next SessionStart flags deferred work.
