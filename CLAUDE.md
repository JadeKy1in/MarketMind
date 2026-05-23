# Workspace-Level Development Rules

**Scope:** This file applies to ALL projects in this workspace. Project-specific rules go in `projects/<name>/CLAUDE.md`.

**Proxy Mode: [Advisor]** — set by `.claude/tools/proxy_mode.py`

---

## New Project Setup (LOCKED — must follow)

When creating a new project under `projects/`:

1. **Directory**: `projects/<project-name>/` — ALL code goes here. Never create `pipeline/`, `shadows/`, `api/` etc. at workspace root.
2. **CLAUDE.md**: Create `projects/<project-name>/CLAUDE.md` with project-specific rules. This root file covers universal rules.
3. **Git**: This entire workspace is ONE git repo. No `git init` inside project folders. No git submodules.
4. **CI**: Add a job to `.github/workflows/ci.yml` targeting the new project's test path.
5. **Module-first from day one**: New feature ≥50 lines = independent module. No appending to existing files.
6. **Shared resources**: `.claude/hooks/` (gates), User Proxy Agent (preferences), worktree cleanup — all auto-apply to new projects.
7. **Tests first**: `tests/` directory at project root, mirroring source structure 1:1.

---

## Universal Development Gates (apply to ALL projects)

| Gate | When | What |
|------|------|------|
| **PreToolUse** | Before Write/Edit `.py` | Task declaration in `current_task.json` required |
| **Pre-commit** | Before commit | 500-line ceiling per `.py` file + grandfather baseline |
| **Stop Gate** | Session end | PICA audits (unit, security, integration, regression, architecture, plan, review) |
| **Worktree Cleanup** | Session start | Auto-prune agent worktrees older than 24h |
| **CI** | On push | GitHub Actions auto-test |

---

## Module-First Principle

- New code ≥50 lines → independent module with single responsibility
- File name = what it does. No "utils" or "helpers" dumping grounds.
- Extraction is a code smell — if you're extracting, you already violated this rule.
- 500-line hard ceiling per file (grandfathered files may not grow)

---

## Development Process

```
Session Start → Flash frontload (decision points) → Sync decisions → Async agents → PICA → Commit
```

- **Frontload first**: Flash scans tasks, identifies decisions, presents to user BEFORE any code changes.
- **Sync before async**: Complete all user-interaction steps while user is present.
- **Never block on human**: If user unavailable, User Proxy Agent handles decisions per confidence tiers. All decisions logged.

---

## Active Projects

| Project | Path | Status |
|---------|------|--------|
| MarketMind | `projects/marketmind/` | Active — 1,998 tests, 0 fail |
| Singoo | `projects/singoo/` | Active — 89 tests, PoC complete |

---

## Do NOT

- Create code directories at workspace root (`pipeline/`, `shadows/`, etc.)
- `git init` inside any project folder
- Add `node_modules`, `__pycache__`, `.env` to git
- Skip the PreToolUse task declaration before editing code
- Launch async work before sync decisions are resolved
